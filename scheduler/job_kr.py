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
            upsert_noise_regime, upsert_crash_surge,
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

        # 6) 홈 화면 AI 헤드라인 — KR × (ko, en) 미리 생성 후 ai_headline_cache 적재
        # endpoint /api/market-summary/home-headline 는 DB 조회만 하면 되어 즉시 응답.
        try:
            from api.routers.market_summary import precompute_home_headline
            for _lang in ('ko', 'en'):
                ok = precompute_home_headline(_lang, 'kr')
                print(f"[KR-Pipeline] home-headline kr/{_lang} {'OK' if ok else 'FAIL'}")
        except Exception as e:
            print(f'[KR-Pipeline] home-headline 실패: {e}')
            traceback.print_exc()

        # 8) KR Sector Cycle (5번째 탭 거시경제) — 매크로 12종 + HMM 4-state 경기국면.
        # 매크로 데이터가 월별이라 매일 적재해도 같은 결과지만, idempotent 하니 무해.
        # 부분 실패 (ECOS 일부 코드 무효 등) 도 sector_macro_kr 안에서 graceful.
        try:
            from collector.sector_macro_kr import (
                fetch_sector_macro_kr, to_sector_macro_kr_records,
            )
            from collector.sector_etf_kr import fetch_sector_etf_returns_kr
            from processor.feature2_sector_cycle import run_sector_cycle
            from database.repositories import upsert_sector_macro, upsert_sector_cycle

            macro_kr = fetch_sector_macro_kr(months=240)
            if macro_kr is not None and not macro_kr.empty:
                # macro 적재 — 청크 분할
                recs = to_sector_macro_kr_records(macro_kr)
                CHUNK = 200
                for i in range(0, len(recs), CHUNK):
                    upsert_sector_macro(recs[i:i + CHUNK], region='kr')
                print(f"[KR-Pipeline] sector_macro {len(recs)}건 적재")

                macro_start = str(macro_kr.index[0].date())
                sector_ret, holding_ret = fetch_sector_etf_returns_kr(macro_start)
                if not sector_ret.empty:
                    cycle_kr = run_sector_cycle(macro_kr, sector_ret, holding_ret, region='kr')
                    upsert_sector_cycle(cycle_kr, region='kr')
                    print(f"[KR-Pipeline] sector_cycle {cycle_kr['date']} "
                          f"{cycle_kr['phase_emoji']} {cycle_kr['phase_name']} 적재")
                else:
                    print('[KR-Pipeline] sector_ret 빈 DF — sector_cycle 건너뜀')
            else:
                print('[KR-Pipeline] sector_macro 빈 DF — sector_cycle 건너뜀')
        except Exception as e:
            print(f'[KR-Pipeline] sector_cycle 실패: {e}')
            traceback.print_exc()

        # 9) KR Sector Valuation — 10 ETF PER/PBR 1차 fallback (KOSPI 시장 평균 동일 적용)
        try:
            from collector.sector_etf_kr import fetch_sector_etf_per_pbr_kr
            from database.repositories import upsert_sector_valuation
            val_rows = fetch_sector_etf_per_pbr_kr()
            if val_rows:
                upsert_sector_valuation(val_rows, region='kr')
                print(f"[KR-Pipeline] sector_valuation {len(val_rows)}건 적재 (1차 fallback)")
            else:
                print('[KR-Pipeline] sector_valuation 0건 — KOSPI PER/PBR fetch 실패')
        except Exception as e:
            print(f'[KR-Pipeline] sector_valuation 실패: {e}')
            traceback.print_exc()

        # 7) KR Crash/Surge — 학습된 모델 있으면 오늘자 1행 적재 (신호탭)
        # KRX/VKOSPI 일부 fetch 실패로 NaN 발생 시: ffill+bfill 후 NaN 컬럼만 0 fallback.
        # 그래도 안 되면 가장 최근 NaN 없는 행으로 후퇴 적재 (날짜는 그 행 기준).
        try:
            from processor.feature3_crash_surge import load_crash_surge_model, predict_crash_surge
            from collector.crash_surge_data_kr import (
                fetch_crash_surge_light_kr, compute_features_kr,
            )
            cs_model = load_crash_surge_model(region='kr')
            if cs_model is not None:
                raw = fetch_crash_surge_light_kr(lookback_days=300)
                feat_df = compute_features_kr(raw)
                if feat_df is not None and not feat_df.empty:
                    # 1차: ffill + bfill 로 결측 채움
                    filled = feat_df.ffill().bfill()
                    last_row = filled.tail(1)
                    nan_cols = last_row.columns[last_row.isna().any()].tolist()
                    if nan_cols:
                        # 일부 컬럼 전체 NaN → 0 fallback (학습 분포 약간 왜곡되지만 적재 가능)
                        print(f'[KR-Pipeline] crash_surge 잔여 NaN 컬럼 {len(nan_cols)}개 → 0 fallback: {nan_cols}')
                        last_row = last_row.fillna(0)
                    # 적재 — date 는 feat_df 의 마지막 인덱스 (가장 최근 거래일)
                    last_date = last_row.index[-1].strftime('%Y-%m-%d')
                    result = predict_crash_surge(last_row.values, cs_model)
                    result['date'] = last_date
                    upsert_crash_surge(result, region='kr')
                    print(f"[KR-Pipeline] crash_surge {last_date} "
                          f"crash={result['crash_score']:.1f}({result['crash_grade']}) "
                          f"surge={result['surge_score']:.1f}({result['surge_grade']}) 적재"
                          f"{' (NaN ' + str(len(nan_cols)) + '개 fallback)' if nan_cols else ''}")
                else:
                    print('[KR-Pipeline] crash_surge 피처 빈 DF — 건너뜀')
            else:
                print('[KR-Pipeline] crash_surge_xgb_kr.pkl 없음 — 학습 먼저 '
                      '(python -m scripts.train_kr_crash_surge)')
        except Exception as e:
            print(f'[KR-Pipeline] crash_surge 실패: {e}')
            traceback.print_exc()

        # 10) 5탭 AI 해설 미리 생성 — fundamental/signal/sector/sector-mom × ko/en × region=kr.
        # endpoint /api/market-summary/ai-explain 가 DB 즉시 응답 → 사용자 첫 진입 빠름.
        # sector-val 은 region='us' 통일이라 KR 파이프라인 제외. sector-mom 은 region 분리 — KR 도 적재.
        try:
            from api.routers.market_summary import precompute_ai_explain
            for _tab in ('fundamental', 'signal', 'sector', 'sector-mom'):
                for _lang in ('ko', 'en'):
                    ok = precompute_ai_explain(_tab, _lang, 'kr')
                    print(f"[KR-Pipeline] ai-explain {_tab}/{_lang}/kr {'OK' if ok else 'SKIP'}")
        except Exception as e:
            print(f'[KR-Pipeline] ai-explain precompute 실패: {e}')
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
