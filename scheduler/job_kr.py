"""한국 시장 일일 데이터 파이프라인.

매일 16:00 KST (UTC 07:00) 1회 실행 — KR 장 마감(15:30) 후 30분 뒤.

- macro_raw (region='kr'): KOSPI close/return/RSI/vol20 + VKOSPI + KR 10Y
- index_price_raw (region='kr'): KODEX 200, TIGER 200, KOSDAQ150 등 + KODEX/TIGER 섹터 ETF

향후 추가 (Stage 3+):
- noise_regime / sector_cycle / valuation_signal — KR 모델 학습 후 적재
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

        # 5) KODEX/TIGER 10종 섹터 ETF — index_price_raw 에 90일치 일별 적재
        # 1주/1개월 모멘텀 계산을 위해 최소 21일 누적 필요 → days=90 + 모든 일자 적재.
        try:
            by_ticker = fetch_sector_etf_prices_kr(days=90)
            sector_rows = []
            for ticker, df in by_ticker.items():
                if df is None or df.empty or len(df) < 2:
                    continue
                # 모든 일자 적재 (i=0 은 prev 없으니 change_pct=0)
                for i in range(len(df)):
                    cur = df.iloc[i]
                    close = float(cur['종가'])
                    if i == 0:
                        change_pct = 0.0
                    else:
                        prev = df.iloc[i - 1]
                        prev_close = float(prev['종가'])
                        change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
                    sector_rows.append({
                        'date': df.index[i].strftime('%Y-%m-%d'),
                        'ticker': ticker,
                        'close': close,
                        'change_pct': change_pct,
                    })
            if sector_rows:
                # 청크 분할 (Supabase 단일 upsert 한도 ~500 안전)
                CHUNK = 200
                for i in range(0, len(sector_rows), CHUNK):
                    upsert_index_prices(sector_rows[i:i + CHUNK], region='kr')
                print(f'[KR-Pipeline] sector ETF {len(sector_rows)}건 적재 (90일×10종)')
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

        # 10) 무거운 화면 응답 사전 계산 — 사용자 클릭 시 app_cache select 만 수행.
        # AI 요약은 LLM quota 에 의존하므로, 실패해도 sector valuation/momentum cache 를 막지 않게
        # non-LLM cache 와 분리한다.
        try:
            from api.routers.market_summary import precompute_ai_summary
            for _lang in ('ko', 'en'):
                ok = precompute_ai_summary(_lang, 'kr')
                print(f"[KR-Pipeline] ai-summary kr/{_lang} {'OK' if ok else 'FAIL'}")
        except Exception as e:
            print(f'[KR-Pipeline] ai-summary precompute 실패: {e}')
            traceback.print_exc()

        try:
            from api.routers.sector_cycle import precompute_valuation, precompute_momentum
            ok_val = precompute_valuation('kr')
            ok_mom = precompute_momentum('kr')
            print(f"[KR-Pipeline] sector valuation cache kr {'OK' if ok_val else 'FAIL'}")
            print(f"[KR-Pipeline] sector momentum cache kr {'OK' if ok_mom else 'FAIL'}")
        except Exception as e:
            print(f'[KR-Pipeline] sector app_cache precompute 실패: {e}')
            traceback.print_exc()

        # 11) 5탭 AI 해설 미리 생성 — fundamental/signal/sector/sector-mom × ko/en × region=kr.
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

        # 12) AI 차트 유사 패턴 매칭용 KR ETF close 시계열 적재 (chart_close_cache).
        # 매일 1회 pykrx → DB upsert. 사용자 클릭 시 응답 ~200ms.
        try:
            print('[KR-Pipeline] AI 차트 유사 패턴용 close 시계열 적재 (KR 12개)...')
            from processor.feature_chart_similarity import precompute_chart_closes
            from api.routers.chart import CHART_TICKERS_KR as _CHART_KR
            result = precompute_chart_closes(list(_CHART_KR))
            print(f"[KR-Pipeline] chart_close_cache OK={len(result['ok'])} FAIL={len(result['fail'])} rows={result['total_rows']}")
            if result['fail']:
                print(f"[KR-Pipeline] 실패 ticker: {result['fail']}")
        except Exception as e:
            print(f'[KR-Pipeline] chart_close_cache precompute 실패: {e}')
            traceback.print_exc()

        # 13) 시장 요약 (4 fetch 합본) + 이상도 10년 시계열 (페이지네이션 3 RTT 합본)
        # — endpoint 의 multiple round-trip 을 1 RTT cache hit 으로 단축.
        try:
            from api.routers.market_summary import precompute_market_summary_today
            ok = precompute_market_summary_today('kr')
            print(f"[KR-Pipeline] market-summary today kr {'OK' if ok else 'FAIL'}")
        except Exception as e:
            print(f'[KR-Pipeline] market-summary today precompute 실패: {e}')
            traceback.print_exc()

        # KR anomaly_daily 1행 적재 — KR noise_regime 가 252거래일(약 1년) 이상 누적되면
        # compute_today_anomaly 가 d2/percentile 산출. 그전엔 None 반환 → DB 무변경(자연 noop).
        try:
            from processor.feature_anomaly import compute_today_anomaly
            from database.repositories import upsert_anomaly_daily
            out = compute_today_anomaly(region='kr')
            if out:
                upsert_anomaly_daily(out, region='kr')
                print(f"[KR-Pipeline] anomaly_daily kr today OK (d2={out.get('d2'):.2f})")
            else:
                print('[KR-Pipeline] anomaly_daily kr today: 데이터 누적 부족(252거래일 미만) — skip')
        except Exception as e:
            print(f'[KR-Pipeline] anomaly today 실패: {e}')
            traceback.print_exc()

        try:
            from api.routers.anomaly import precompute_anomaly_history
            ok = precompute_anomaly_history(region='kr', days=2520)
            print(f"[KR-Pipeline] anomaly history kr/2520 {'OK' if ok else 'FAIL/EMPTY'}")
        except Exception as e:
            print(f'[KR-Pipeline] anomaly history precompute 실패: {e}')
            traceback.print_exc()

        # 14) AI 차트 유사 패턴 매칭 *결과 통째* 적재 (chart_similarity_cache).
        # 12 ticker × 2 mode = 24 entry. 사용자 클릭 시 numpy 슬라이딩 CPU 0 → DB select 1회.
        try:
            print('[KR-Pipeline] AI 차트 유사 패턴 매칭 결과 적재 (KR 12 × 2 mode)...')
            from processor.feature_chart_similarity import precompute_chart_similarity
            from api.routers.chart import CHART_TICKERS_KR as _CHART_KR
            result = precompute_chart_similarity(list(_CHART_KR))
            print(f"[KR-Pipeline] chart_similarity_cache OK={len(result['ok'])} FAIL={len(result['fail'])}")
            if result['fail']:
                print(f"[KR-Pipeline] 실패: {result['fail']}")
        except Exception as e:
            print(f'[KR-Pipeline] chart_similarity_cache precompute 실패: {e}')
            traceback.print_exc()

        # 15) AI 차트 OHLC (캔들) 적재 — 12 ticker × 3 interval (1d/1wk/1mo) = 36 entry.
        # endpoint 매 클릭 시 외부 pykrx/yfinance 호출 1~3s → DB select 1회로 단축.
        try:
            print('[KR-Pipeline] AI 차트 OHLC 캔들 적재 (KR 12 × 3 interval)...')
            from api.routers.chart import precompute_chart_ohlc, CHART_TICKERS_KR as _CHART_KR
            result = precompute_chart_ohlc(list(_CHART_KR))
            print(f"[KR-Pipeline] chart_ohlc_cache OK={len(result['ok'])} FAIL={len(result['fail'])}")
            if result['fail']:
                print(f"[KR-Pipeline] 실패: {result['fail']}")
        except Exception as e:
            print(f'[KR-Pipeline] chart_ohlc_cache precompute 실패: {e}')
            traceback.print_exc()

        # 17) 탭별 한 줄 해설 (룰베이스) 적재.
        # 8개 탭(차트/시황/펀더/이탈도/사이클/밸류/모멘텀/시장밸류) × region 단일 app_cache 1행.
        # endpoint 호출 시 8 RTT (rule 마다 DB select) → 1 RTT (cache select) 로 단축.
        try:
            from processor.tab_headline import precompute_tab_headlines
            ok = precompute_tab_headlines('kr')
            print(f"[KR-Pipeline] tab_headlines kr {'OK' if ok else 'FAIL/EMPTY'}")
        except Exception as e:
            print(f'[KR-Pipeline] tab_headlines precompute 실패: {e}')
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
