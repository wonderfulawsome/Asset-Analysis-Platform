"""한국 시장 일일 데이터 파이프라인.

매일 16:00 KST (UTC 07:00) 1회 실행 — KR 장 마감(15:30) 후 30분 뒤.

- macro_raw (region='kr'): KOSPI close/return/RSI/vol20 + VKOSPI + KR 10Y
- index_price_raw (region='kr'): KODEX 200, TIGER 200, KOSDAQ150 등 + KODEX/TIGER 섹터 ETF

향후 추가 (Stage 3+):
- noise_regime / crash_surge / sector_cycle / valuation_signal — KR 모델 학습 후 적재
- 합성 한국 F&G — fear_greed_raw 에 region='kr' 적재
"""

from __future__ import annotations

import traceback


def run_kr_pipeline() -> None:
    """KR 일일 파이프라인 — 외부에서 1회 호출 (스케줄러 또는 수동)."""
    print('\n[KR-Pipeline] 시작 ============================')
    try:
        from collector.market_data_kr import (
            compute_kr_macro_history, fetch_kr_index_prices_today,
        )
        from collector.sector_etf_kr import (
            fetch_sector_etf_prices_kr, SECTOR_ETF_KR,
        )
        from collector.valuation_signal_kr import fetch_valuation_signal_today_kr
        from database.repositories import (
            upsert_macro, upsert_index_prices, upsert_valuation_signal,
            upsert_noise_regime,
        )

        # 1) macro_raw — 최근 5일치 (오늘 + 며칠 buffer)
        try:
            records = compute_kr_macro_history(days=5)
            if records:
                upsert_macro(records, region='kr')
                print(f'[KR-Pipeline] macro {len(records)}건 적재')
            else:
                print('[KR-Pipeline] macro 데이터 없음')
        except Exception as e:
            print(f'[KR-Pipeline] macro 실패: {e}')
            traceback.print_exc()

        # 2) index_price_raw — KOSPI200/KOSDAQ150 ETF
        try:
            rows = fetch_kr_index_prices_today()
            if rows:
                upsert_index_prices(rows, region='kr')
                print(f'[KR-Pipeline] index {len(rows)}건 적재')
        except Exception as e:
            print(f'[KR-Pipeline] index 실패: {e}')
            traceback.print_exc()

        # 3) valuation_signal — KOSPI ERP + VKOSPI + DD60 composite z
        try:
            v = fetch_valuation_signal_today_kr()
            if v:
                upsert_valuation_signal(v, region='kr')
                print(f"[KR-Pipeline] valuation_signal {v['date']} z={v['z_comp']:+.2f} ({v['label']}) 적재")
        except Exception as e:
            print(f'[KR-Pipeline] valuation_signal 실패: {e}')
            traceback.print_exc()

        # 4) KR HMM 추론 — 학습된 모델 있으면 오늘자 noise_regime 1행 생성
        try:
            from processor.feature1_regime import load_model, backfill_noise_regime
            from collector.noise_regime_data_kr import fetch_all_kr
            kr_model = load_model(region='kr')
            if kr_model is not None:
                # 작은 bundle 로 fetch (3년이면 충분, 비용 절약)
                kr_bundle = fetch_all_kr(years=3)
                if kr_bundle and 'features' in kr_bundle:
                    # 최근 3일만 추론 (오늘 + buffer)
                    recs = backfill_noise_regime(kr_bundle, kr_model, days=3, region='kr')
                    for rec in recs:
                        upsert_noise_regime(rec, region='kr')
                    print(f'[KR-Pipeline] noise_regime {len(recs)}건 적재')
            else:
                print('[KR-Pipeline] noise_hmm_kr.pkl 없음 — 학습 먼저 (python -m scripts.train_kr_hmm)')
        except Exception as e:
            print(f'[KR-Pipeline] noise_regime 실패: {e}')
            traceback.print_exc()

        # 5) KODEX/TIGER 10종 섹터 ETF — index_price_raw 에 같이 적재
        try:
            by_ticker = fetch_sector_etf_prices_kr(days=10)
            sector_rows = []
            for ticker, df in by_ticker.items():
                if df is None or df.empty or len(df) < 2:
                    continue
                last = df.iloc[-1]
                prev = df.iloc[-2]
                close = float(last['종가'])
                change_pct = round((close - float(prev['종가'])) / float(prev['종가']) * 100, 2)
                sector_rows.append({
                    'date': df.index[-1].strftime('%Y-%m-%d'),
                    'ticker': ticker,
                    'close': close,
                    'change_pct': change_pct,
                })
            if sector_rows:
                upsert_index_prices(sector_rows, region='kr')
                print(f'[KR-Pipeline] sector ETF {len(sector_rows)}건 적재')
        except Exception as e:
            print(f'[KR-Pipeline] sector ETF 실패: {e}')
            traceback.print_exc()

    except Exception as e:
        print(f'[KR-Pipeline] 전체 실패: {e}')
        traceback.print_exc()
    finally:
        print('[KR-Pipeline] 종료 ============================')


if __name__ == '__main__':
    # 수동 실행: python -m scheduler.job_kr
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    run_kr_pipeline()
