import datetime
import traceback
from collector.market_data import fetch_macro, to_macro_records
from collector.fear_greed import fetch_fear_greed, fetch_putcall_ratio
from collector.index_price import fetch_index_prices
from collector.sector_macro import fetch_sector_macro, to_sector_macro_records
from collector.sector_etf import fetch_sector_etf_returns
from collector.noise_regime_data import (
    fetch_shiller, fetch_fred_regime, fetch_sector_stocks,
    fetch_amihud_stocks, compute_monthly_features, compute_daily_features,
    fetch_noise_regime_light,
)
from database.repositories import (upsert_macro, upsert_noise_regime, upsert_fear_greed,
                                   upsert_index_prices, upsert_sector_macro, upsert_sector_cycle,
                                   upsert_crash_surge, fetch_crash_surge_all, fetch_noise_regime_all)
from processor.feature1_regime import train_hmm, load_model, predict_regime, backfill_noise_regime
from processor.feature2_sector_cycle import run_sector_cycle
from collector.crash_surge_data import (
    fetch_crash_surge_raw, fetch_crash_surge_light,
    compute_features, compute_labels, prepare_datasets, ALL_FEATURES,
    save_fred_cache,                                         # FRED 파일 캐시 저장 함수
)
from processor.feature3_crash_surge import (
    train_crash_surge, load_model as load_crash_surge_model, predict_crash_surge,
    backfill_crash_surge,
)
from processor.feature4_chart_predict import run_chart_predict_all
from database.repositories import upsert_chart_predict
from collector.real_estate_trade import fetch_trades, fetch_rents
from collector.real_estate_population import (
    fetch_population, fetch_household_by_size, fetch_all_sgg_codes,
)
from collector.real_estate_geocode import batch_geocode
from processor.feature5_real_estate import build_mapping, compute_region_summary
from processor.feature6_buy_signal import compute_buy_signal
from collector.ecos_macro import fetch_macro_rate_kr as ecos_fetch_macro_rate_kr
from collector.kosis_migration import fetch_kosis_migration
from database.repositories import (
    upsert_re_trades, upsert_re_rents, upsert_mois_population, upsert_mois_household,
    upsert_stdg_admm_mapping, upsert_geo_stdg, upsert_region_summary, fetch_geo_stdg,
    upsert_buy_signal, fetch_region_timeseries,
    upsert_macro_rate_kr, fetch_macro_rate_kr as repo_fetch_macro_rate_kr,
    upsert_region_migration, fetch_region_migration,
)


# ── 부동산 API 응답(camelCase) → DB 스키마(snake_case) 변환 헬퍼 ────────────────

def _re_norm_trades(items: list[dict], sgg_cd: str, deal_ym: str) -> list[dict]:
    # [입력 출처] fetch_trades(sgg_cd, re_ym) — 국토부 매매 API (camelCase, 값은 str)
    #
    # [출력 행선지] upsert_re_trades() → real_estate_trade_raw 테이블
    #               + compute_region_summary(trades=...) → 법정동 집계용
    #
    # [출력 예시] result[0] = {
    #   "sgg_cd": "11680", "deal_ym": "202603", "apt_nm": "한라비발디",
    #   "apt_seq": "11680-4474", "umd_nm": "도곡동", "umd_cd": "11800",
    #   "stdg_cd": "1168011800", "deal_amount": 235000,
    #   "exclu_use_ar": 84.8861, "floor": 6, "build_year": 2016,
    #   "deal_date": "2026-03-28", "dealing_gbn": "중개거래",
    #   "road_nm": "남부순환로365길"}
    #
    # 국토부 API가 같은 (apt_seq, deal_date, floor, exclu_use_ar) 조합을 2건 이상
    # 반환하는 경우가 있어 upsert 전 dedupe. 테이블 UNIQUE 제약과 동일 키.
    result = []
    seen_trade: set[tuple] = set()
    for it in items:
        y = it.get("dealYear", "")
        m = it.get("dealMonth", "").zfill(2)
        d = it.get("dealDay", "").zfill(2)
        deal_date = f"{y}-{m}-{d}" if y and m and d else None
        umd_cd = (it.get("umdCd") or "").zfill(5)
        exclu = float(it.get("excluUseAr") or 0)
        floor = int(it.get("floor") or 0)
        apt_seq = it.get("aptSeq")
        key = (apt_seq, deal_date, floor, exclu)
        if key in seen_trade:
            continue
        seen_trade.add(key)
        result.append({
            "sgg_cd": sgg_cd,
            "deal_ym": deal_ym,
            "apt_nm": it.get("aptNm"),
            "apt_seq": apt_seq,
            "umd_nm": it.get("umdNm"),
            "umd_cd": umd_cd,
            "stdg_cd": sgg_cd.zfill(5) + umd_cd,
            "deal_amount": int(str(it.get("dealAmount", "0") or "0").replace(",", "")),
            "exclu_use_ar": exclu,
            "floor": floor,
            "build_year": int(it.get("buildYear")) if it.get("buildYear") else None,
            "deal_date": deal_date,
            "dealing_gbn": it.get("dealingGbn"),
            "road_nm": it.get("roadNm"),
        })
    return result


def _re_norm_rents(items: list[dict], sgg_cd: str, deal_ym: str) -> list[dict]:
    # [입력 출처] fetch_rents(sgg_cd, re_ym) — 국토부 전월세 API
    #              (매매와 달리 road 관련 필드만 소문자 roadnm/roadnmcd …)
    #
    # [출력 행선지] upsert_re_rents() → real_estate_rent_raw 테이블
    #               + compute_region_summary(rents=...) → 시군구 전/월세 집계용
    #
    # [출력 예시] result[0] = {
    #   "sgg_cd": "11680", "deal_ym": "202603", "apt_nm": "래미안대치팰리스",
    #   "apt_seq": "11680-4394", "umd_nm": "대치동",
    #   "deposit": 130000, "monthly_rent": 0,    # monthly_rent=0 → 전세
    #   "exclu_use_ar": 59.99, "floor": 3,
    #   "deal_date": "2026-03-21", "contract_type": None,
    #   "road_nm": "삼성로51길 37"}
    #
    # trades 와 동일하게 테이블 UNIQUE 제약 동일 키로 dedupe
    # (apt_seq, deal_date, floor, exclu_use_ar, deposit, monthly_rent) 중복 제거
    result = []
    seen_rent: set[tuple] = set()
    for it in items:
        y = it.get("dealYear", "")
        m = it.get("dealMonth", "").zfill(2)
        d = it.get("dealDay", "").zfill(2)
        deal_date = f"{y}-{m}-{d}" if y and m and d else None
        deposit = int(str(it.get("deposit", "0") or "0").replace(",", ""))
        monthly_rent = int(str(it.get("monthlyRent", "0") or "0").replace(",", ""))
        exclu = float(it.get("excluUseAr") or 0)
        floor = int(it.get("floor") or 0)
        apt_seq = it.get("aptSeq")
        key = (apt_seq, deal_date, floor, exclu, deposit, monthly_rent)
        if key in seen_rent:
            continue
        seen_rent.add(key)
        result.append({
            "sgg_cd": sgg_cd,
            "deal_ym": deal_ym,
            "apt_nm": it.get("aptNm"),
            "apt_seq": apt_seq,
            "umd_nm": it.get("umdNm"),
            "deposit": deposit,
            "monthly_rent": monthly_rent,
            "exclu_use_ar": exclu,
            "floor": floor,
            "deal_date": deal_date,
            "contract_type": it.get("contractType"),
            # 전월세 API는 roadNm 대신 소문자 roadnm 사용
            "road_nm": it.get("roadnm") or it.get("roadNm"),
        })
    return result


def _re_norm_population(items: list[dict], stats_ym: str) -> list[dict]:
    # [입력 출처] fetch_population(sgg_cd_10, re_ym) — 행안부 인구통계 API lv=3
    #              (시군구 10자리 → 법정동별 집계, admmCd는 None)
    #
    # [출력 행선지] upsert_mois_population() → mois_population 테이블
    #               + compute_region_summary(population=...) → 법정동 인구 컬럼
    #
    # [출력 예시] result[0] = {
    #   "stats_ym": "202603", "stdg_cd": "1168010100", "stdg_nm": "역삼동",
    #   "sgg_nm": "강남구", "tot_nmpr_cnt": 70093, "hh_cnt": 39424,
    #   "hh_nmpr": 1.78, "male_nmpr_cnt": 33465, "feml_nmpr_cnt": 36628,
    #   "male_feml_rate": 0.91}
    result = []
    seen_pop: set[tuple] = set()         # 같은 (stats_ym, stdg_cd) batch 중복 방지 (UNIQUE 충돌 → ON CONFLICT 21000)
    for it in items:
        stdg_cd = it.get("stdgCd")
        if not stdg_cd:
            continue
        key = (stats_ym, stdg_cd)
        if key in seen_pop:
            continue
        seen_pop.add(key)
        result.append({
            "stats_ym": stats_ym,
            "stdg_cd": stdg_cd,
            "stdg_nm": it.get("stdgNm"),
            "sgg_nm": it.get("sggNm"),
            "tot_nmpr_cnt": int(str(it.get("totNmprCnt", "0") or "0").replace(",", "")),
            "hh_cnt": int(str(it.get("hhCnt", "0") or "0").replace(",", "")),
            "hh_nmpr": float(it.get("hhNmpr") or 0),
            "male_nmpr_cnt": int(str(it.get("maleNmprCnt", "0") or "0").replace(",", "")),
            "feml_nmpr_cnt": int(str(it.get("femlNmprCnt", "0") or "0").replace(",", "")),
            "male_feml_rate": float(it.get("maleFemlRate") or 0),
        })
    return result


def _re_norm_household(items: list[dict], stats_ym: str) -> list[dict]:
    # [입력 출처] fetch_household_by_size(admm_cd, re_ym) — 행안부 세대원수 API lv=3
    #              (행정동 10자리 단위 호출 — mapping.admm_cd를 순회)
    #
    # [출력 행선지] upsert_mois_household() → mois_household_by_size 테이블
    #               + compute_region_summary(household=...) → solo_rate 가중합
    #
    # [출력 예시] result[0] = {
    #   "stats_ym": "202603", "admm_cd": "1168051000", "dong_nm": "신사동",
    #   "sgg_nm": "강남구", "tot_hh_cnt": 6534,
    #   "hh_1": 2466, "hh_2": 1505, "hh_3": 1226, "hh_4": 1001,
    #   "hh_5": 242, "hh_6": 63, "hh_7plus": 31,    # = 16+13+2+0
    #   "solo_rate": 0.3773}                         # = 2466 / 6534
    #
    # MOIS API가 같은 admm_cd를 여러 건 반환하거나 호출자가 여러 번 누적할 때
    # 중복 발생 → 테이블 UNIQUE (stats_ym, admm_cd) 충돌. 함수 내에서 dedupe.
    result = []
    seen_hh: set[tuple] = set()
    for it in items:
        admm_cd = it.get("admmCd")
        if not admm_cd:
            continue
        key = (stats_ym, admm_cd)
        if key in seen_hh:
            continue
        seen_hh.add(key)
        tot = int(str(it.get("totHhCnt", "0") or "0").replace(",", ""))
        hh_1 = int(str(it.get("hhNmprCnt1", "0") or "0").replace(",", ""))
        # hhNmprCnt7~10 합산 → hh_7plus
        hh_7plus = sum(int(str(it.get(f"hhNmprCnt{i}", "0") or "0").replace(",", "")) for i in range(7, 11))
        result.append({
            "stats_ym": stats_ym,
            "admm_cd": admm_cd,
            "dong_nm": it.get("dongNm"),
            "sgg_nm": it.get("sggNm"),
            "tot_hh_cnt": tot,
            "hh_1": hh_1,
            "hh_2": int(str(it.get("hhNmprCnt2", "0") or "0").replace(",", "")),
            "hh_3": int(str(it.get("hhNmprCnt3", "0") or "0").replace(",", "")),
            "hh_4": int(str(it.get("hhNmprCnt4", "0") or "0").replace(",", "")),
            "hh_5": int(str(it.get("hhNmprCnt5", "0") or "0").replace(",", "")),
            "hh_6": int(str(it.get("hhNmprCnt6", "0") or "0").replace(",", "")),
            "hh_7plus": hh_7plus,
            "solo_rate": (hh_1 / tot) if tot > 0 else None,
        })
    return result


def _re_norm_mapping(pairs: list[dict]) -> list[dict]:
    # [입력 출처] build_mapping(sgg_cd_10, re_ym) — processor/feature5_real_estate
    #              (내부에서 fetch_mapping_pairs(stdgCd, ym)를 읍면동마다 호출해 dedupe)
    #
    # [출력 행선지] upsert_stdg_admm_mapping() → stdg_admm_mapping 테이블
    #               + compute_region_summary(mapping=...) → 행정동→법정동 join 키
    #               + batch_geocode(f"{ctpv_nm} {sgg_nm} {stdg_nm}") → 지오코딩 주소 조합
    #
    # [출력 예시] return[0] = {
    #   "ref_ym": "202603", "stdg_cd": "1168010100", "stdg_nm": "역삼동",
    #   "admm_cd": "1168053000", "admm_nm": "역삼1동",
    #   "ctpv_nm": "서울특별시", "sgg_nm": "강남구"}
    # build_mapping 이 내부 dedupe 한다고 주석에 나와있으나, 호출자 누적 단계에서
     # 중복이 새로 생길 수 있으므로 안전망으로 (ref_ym, stdg_cd, admm_cd) 기준 dedupe.
    seen_map: set[tuple] = set()
    out = []
    for p in pairs:
        stdg = p.get("stdgCd")
        admm = p.get("admmCd")
        if not stdg or not admm:
            continue
        key = (p.get("ref_ym"), stdg, admm)
        if key in seen_map:
            continue
        seen_map.add(key)
        out.append({
            "ref_ym": p.get("ref_ym"),
            "stdg_cd": stdg,
            "stdg_nm": p.get("stdgNm"),
            "admm_cd": admm,
            "admm_nm": p.get("admmNm"),
            "ctpv_nm": p.get("ctpvNm"),
            "sgg_nm": p.get("sggNm"),
        })
    return out


def run_pipeline(light: bool = False) -> None:
    """파이프라인 실행.
    light=False: 전체 파이프라인 (100년치 수집 + 모델 학습)
    light=True:  경량 파이프라인 (최근 데이터만 갱신, 30분 주기용)
    """
    start = datetime.datetime.now()  # 시작 시간 기록
    mode = '경량' if light else '전체'  # 실행 모드 표시
    print(f'\n{"="*50}')
    print(f'[Pipeline-{mode}] 시작: {start.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*50}')

    # Step 1: 거시 지표 수집 (경량: 최근 60일, 전체: 100년)
    print('\n[Step 1] 거시 지표 수집...')
    df = fetch_macro(days=60 if light else 0)  # 경량 모드면 60일치만 수집

    # Step 2: macro_raw 저장
    print('\n[Step 2] macro_raw DB 저장...')
    records = to_macro_records(df)  # DataFrame → dict 리스트 변환
    upsert_macro(records)  # Supabase에 upsert

    # FRED 캐시: Step 3에서 수집한 데이터를 Step 7에서 재사용 (중복 호출 방지)
    fred_cache = {}                                          # FRED 시리즈 공유 캐시

    # 경량 모드가 아닐 때만 무거운 작업 실행
    noise_bundle = None                                      # 백필에서 재사용할 변수
    noise_model_bundle = None
    noise_should_retrain = False

    if not light:
        # Step 3: Noise vs Signal HMM 국면 판별 (모델 학습 + 오늘 예측)
        print('\n[Step 3] Noise vs Signal 국면 판별...')
        try:
            start_date = str(datetime.date.today() - datetime.timedelta(days=365 * 18 + 30))

            # 3a: 데이터 수집 (FRED 실패 시 캐시 fallback)
            shiller = fetch_shiller()
            try:
                fred = fetch_fred_regime()
                # Step 3에서 수집한 FRED 데이터를 캐시에 저장 (Step 7에서 재사용)
                if 'hy_spread' in fred:
                    hy_df = fred['hy_spread'].copy()
                    hy_df.columns = ['HY_OAS']
                    fred_cache['HY_OAS'] = hy_df
                if 'tips_rate' in fred:
                    tips_df = fred['tips_rate'].copy()
                    tips_df.columns = ['DFII10']
                    fred_cache['DFII10'] = tips_df
            except Exception as fred_err:
                print(f'[Step 3] FRED API 실패, 캐시 fallback 시도: {fred_err}')
                from collector.crash_surge_data import _load_fred_cache
                cached = _load_fred_cache()
                if cached:
                    fred = {}
                    if 'HY_OAS' in cached:
                        hy = cached['HY_OAS']
                        hy.columns = ['hy_spread']
                        fred['hy_spread'] = hy
                    if 'DFII10' in cached:
                        tips = cached['DFII10']
                        tips.columns = ['tips_rate']
                        fred['tips_rate'] = tips
                    print('[Step 3] FRED 캐시 fallback 성공')
                else:
                    raise RuntimeError('FRED API 실패 + 캐시 없음') from fred_err
            stock_prices = fetch_sector_stocks(start_date)
            amihud_data = fetch_amihud_stocks(start_date)

            # 3b: 월별 피처 계산
            noise_bundle = compute_monthly_features(shiller, fred, stock_prices, amihud_data)

            # 3c: 모델 학습 또는 로드
            noise_model_bundle = load_model()
            current_month = datetime.date.today().strftime('%Y-%m')
            noise_should_retrain = (noise_model_bundle is None or
                                    noise_model_bundle.get('train_month') != current_month)
            if noise_should_retrain:
                print('[Step 3] 모델 재학습...')
                noise_model_bundle = train_hmm(noise_bundle['features'], monthly_bundle=noise_bundle)
            else:
                print(f'[Step 3] 기존 모델 사용 (학습 월: {noise_model_bundle["train_month"]})')

            # 3d: 일별 피처 계산 + 예측
            daily_feat = compute_daily_features(noise_bundle)
            result = predict_regime(daily_feat, noise_model_bundle)

            # 3e: DB 저장
            upsert_noise_regime(result)
        except Exception as e:
            print(f'[Step 3] Noise HMM 실패, 건너뜀: {e}')
            traceback.print_exc()

        # Step 3f: 백필 (모델 학습/예측과 분리 — 백필 실패해도 모델+오늘 예측은 보존)
        if noise_should_retrain and noise_bundle is not None and noise_model_bundle is not None:
            try:
                print('[Step 3f] Noise Regime 백필...')
                existing = fetch_noise_regime_all()
                existing_dates = {r['date'] for r in existing}

                backfill_days = 50
                print(f'[Step 3f] 백필 범위: {backfill_days}일 (기존 {len(existing_dates)}건)')
                backfill_records = backfill_noise_regime(noise_bundle, noise_model_bundle, days=backfill_days)
                new_records = [r for r in backfill_records if r['date'] not in existing_dates]
                print(f'[Step 3f] 전체 {len(backfill_records)}건 중 신규 {len(new_records)}건 백필')
                for rec in new_records:
                    upsert_noise_regime(rec)
                print(f'[Step 3f] 백필 완료: {len(new_records)}건 DB 저장')
            except Exception as e:
                print(f'[Step 3f] Noise Regime 백필 실패, 건너뜀: {e}')
                traceback.print_exc()

    # Step 4: Fear & Greed + PUT/CALL Ratio 수집 및 저장 (항상 실행)
    print('\n[Step 4] Fear & Greed 수집...')
    fear_greed = fetch_fear_greed()  # CNN Fear & Greed 웹 스크래핑
    upsert_fear_greed(fear_greed)

    # PUT/CALL Ratio 수집 후 macro_raw 최신 레코드에 추가 저장
    print('[Step 4] PUT/CALL Ratio 수집...')
    pcr = fetch_putcall_ratio()  # CBOE Put/Call Ratio 스크래핑
    if pcr is not None:
        # 오늘 날짜 기준으로 putcall_ratio 컬럼 upsert
        upsert_macro([{'date': fear_greed['date'], 'putcall_ratio': pcr}])

    # Step 5: ETF 가격 수집 및 저장 (항상 실행)
    print('\n[Step 5] ETF 가격 수집...')
    index_prices = fetch_index_prices()  # 31개 ETF 종가/등락률 수집
    # non_zero: 31개 ETF 종가/등락률 데이터를 반복하고 0이 아닌 데이터 정의
    non_zero = [r for r in index_prices if r['change_pct'] != 0]
    if not non_zero and index_prices:
        print('[Step 5] 모든 change_pct가 0 → stale 데이터, upsert 건너뜀')
    else:
        # 0이 아닌 index_prices를 DB에 저장
        upsert_index_prices(index_prices)

    # Step 5b: 경량 모드 crash/surge 실시간 예측 (기존 모델 사용, 학습 없음)
    if light:
        print('\n[Step 5b] 폭락/급등 실시간 예측...')
        try:
            cs_model = load_crash_surge_model()  # 저장된 모델 로드
            if cs_model is not None:
                raw_light = fetch_crash_surge_light()  # 최근 데이터 경량 수집 (SPY/Cboe/PutCall 실시간 포함)
                features_light = compute_features(raw_light['spy'], raw_light['fred'],
                                                  raw_light['cboe'],
                                                  raw_light['yahoo_macro'])  # 44 피처 계산
                # Core 피처 NaN 제거, Aux fillna(0) 처리
                from collector.crash_surge_data import CORE_FEATURES, AUX_FEATURES
                import numpy as np
                feat_row = features_light[ALL_FEATURES].copy()  # 피처만 추출
                feat_row = feat_row.ffill()  # FRED/Yahoo 결측 → 직전 값으로 채움
                feat_row = feat_row.dropna(subset=CORE_FEATURES)  # Core NaN 제거
                feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)  # Aux 결측 대체
                feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)  # inf 제거
                if len(feat_row) > 0:
                    latest_row = feat_row.iloc[[-1]].values  # 최신 1행 추출
                    cs_result = predict_crash_surge(latest_row, cs_model)  # 예측 실행
                    upsert_crash_surge(cs_result)  # DB 저장
                else:
                    print('  [CrashSurge-Light] 유효한 피처 행 없음, 건너뜀')
            else:
                print('  [CrashSurge-Light] 저장된 모델 없음, 건너뜀 (전체 파이프라인에서 학습 필요)')
        except Exception as e:
            print(f'  [CrashSurge-Light] 실시간 예측 실패: {e}')
            traceback.print_exc()

        # Step 5d: ERP (Fed Model) 일일 갱신 — DB 가드 (오늘 row 있으면 skip)
        print('\n[Step 5d] ERP 시그널 갱신...')
        try:
            from collector.valuation_signal import fetch_valuation_signal_today, backfill_valuation_signal
            from database.repositories import (
                fetch_valuation_signal_latest, upsert_valuation_signal, upsert_valuation_signal_bulk,
            )
            import datetime as _dt
            latest = fetch_valuation_signal_latest()
            today_str = _dt.date.today().isoformat()
            if not latest or latest.get('date') != today_str:
                # 처음이면 30일 backfill, 이후엔 오늘 1행만
                if not latest:
                    rows = backfill_valuation_signal(days=60)
                    if rows:
                        upsert_valuation_signal_bulk(rows)
                rec = fetch_valuation_signal_today()
                if rec:
                    # 미리 baseline 스냅샷 + LLM 해설 산출 → DB 적재
                    # endpoint 는 select 만 하면 즉시 응답 가능
                    try:
                        from collector.valuation_signal import get_baselines as _get_b
                        from api.routers.macro import (
                            build_baseline_snapshot as _build_snap,
                            build_valuation_interpretation as _build_interp,
                        )
                        _baselines = _get_b()
                        rec['baseline_snapshot'] = _build_snap(_baselines)
                        rec['interpretation'] = _build_interp(rec, _baselines)
                    except Exception as _ee:
                        print(f'  [ERP] enrich 실패 (raw 만 저장): {_ee}')
                    upsert_valuation_signal(rec)
                    print(f'  [ERP] {rec["date"]} ERP={rec["erp"]:+.4f} ({rec["label"]})')
            else:
                print('  [ERP] 오늘 이미 갱신됨, 건너뜀')
        except Exception as e:
            print(f'  [ERP] 실패: {e}')
            traceback.print_exc()

        # Step 5c: 경량 모드 Noise HMM 실시간 예측 (기존 모델 사용, 학습 없음)
        print('\n[Step 5c] Noise HMM 실시간 예측...')
        try:
            noise_model = load_model()                   # 저장된 Noise HMM 모델 로드
            if noise_model is not None and noise_model.get('last_monthly_values'):  # 모델 + 캐시값 존재 확인
                daily_feat = fetch_noise_regime_light(noise_model)  # 실시간 4피처 + 캐시 4피처 → 8피처 벡터
                noise_result = predict_regime(daily_feat, noise_model)  # 국면 예측 실행
                upsert_noise_regime(noise_result)        # DB 저장
            else:
                print('  [NoiseHMM-Light] 저장된 모델 또는 캐시값 없음, 건너뜀 (전체 파이프라인에서 학습 필요)')
        except Exception as e:
            print(f'  [NoiseHMM-Light] 실시간 예측 실패: {e}')
            traceback.print_exc()

    # 경량 모드가 아닐 때만 무거운 작업 실행
    if not light:
        # Step 6: 섹터 경기국면 분석 (FRED 매크로 + 섹터 ETF + XGBoost)
        print('\n[Step 6] 섹터 경기국면 분석...')
        cycle_result = None
        try:
            sector_macro = fetch_sector_macro()
            macro_records = to_sector_macro_records(sector_macro)
            upsert_sector_macro(macro_records)

            macro_start = str(sector_macro.index[0].date())
            sector_ret, holding_ret = fetch_sector_etf_returns(macro_start)
            cycle_result = run_sector_cycle(sector_macro, sector_ret, holding_ret)
            upsert_sector_cycle(cycle_result)
        except Exception as e:
            print(f'[Step 6] 섹터 경기국면 실패, 건너뜀: {e}')
            traceback.print_exc()

        # Step 6b: 섹터 펀더멘털 갭 — yfinance ETF 가격 + holdings 가중 EPS 로
        # log(P).diff(12) - log(E).diff(12) 시계열 산출 (28점/ETF). idempotent.
        print('\n[Step 6b] 섹터 펀더멘털 갭 산출...')
        try:
            from processor.sector_fundamental_gap import backfill_all as fg_backfill_all
            fg_backfill_all()
        except Exception as e:
            print(f'[Step 6b] 섹터 펀더멘털 갭 실패, 건너뜀: {e}')
            traceback.print_exc()

        # Step 7: XGBoost 폭락/급등 전조 탐지 (모델 학습 + 오늘 예측)
        print('\n[Step 7] 폭락/급등 전조 탐지...')
        cs_datasets = None
        cs_model = None
        cs_should_retrain = False
        try:
            raw = fetch_crash_surge_raw(fred_cache=fred_cache)  # Step 3 캐시 재사용
            save_fred_cache(raw['fred'])                      # 경량 파이프라인용 파일 캐시 저장
            features = compute_features(raw['spy'], raw['fred'], raw['cboe'],
                                                  raw['yahoo_macro'])
            labels = compute_labels(raw['spy']['Close'])
            cs_datasets = prepare_datasets(features, labels, raw['spy']['Close'])

            cs_model = load_crash_surge_model()
            current_month = datetime.date.today().strftime('%Y-%m')
            cs_should_retrain = (cs_model is None or
                                 cs_model.get('train_month') != current_month)
            if cs_should_retrain:
                try:
                    print('[Step 7] 모델 재학습 (Optuna 50 trials)...')
                    X_tr, y_tr = cs_datasets['train']
                    X_cal, y_cal = cs_datasets['calib']
                    X_te, y_te = cs_datasets['test']
                    X_dev, y_dev = cs_datasets['dev']
                    X_full = cs_datasets['df_full'][ALL_FEATURES].values
                    cs_model = train_crash_surge(X_tr, y_tr, X_cal, y_cal, X_te, y_te,
                                                 X_dev, y_dev, X_full, n_trials=50)
                except Exception as e:
                    print(f'[Step 7] 모델 재학습 실패, 기존 모델로 예측 계속: {e}')
                    traceback.print_exc()
                    cs_model = load_crash_surge_model()  # 기존 모델 다시 로드
            else:
                print(f'[Step 7] 기존 모델 사용 (학습 월: {cs_model["train_month"]})')

            # 예측은 재학습 성패와 무관하게 실행
            if cs_model is not None:
                latest_row = cs_datasets['df_full'][ALL_FEATURES].iloc[[-1]].values
                cs_result = predict_crash_surge(latest_row, cs_model)
                upsert_crash_surge(cs_result)
            else:
                print('[Step 7] 사용 가능한 모델 없음, 예측 건너뜀')
        except Exception as e:
            print(f'[Step 7] 폭락/급등 전조 실패, 경량 fallback 시도: {e}')
            traceback.print_exc()
            # Fallback: 경량 수집으로 예측 시도
            try:
                fallback_model = load_crash_surge_model()
                if fallback_model is not None:
                    import numpy as np
                    from collector.crash_surge_data import CORE_FEATURES, AUX_FEATURES
                    raw_light = fetch_crash_surge_light()
                    features_light = compute_features(raw_light['spy'], raw_light['fred'],
                                                      raw_light['cboe'], raw_light['yahoo_macro'])
                    feat_row = features_light[ALL_FEATURES].copy()
                    feat_row = feat_row.ffill()
                    feat_row = feat_row.dropna(subset=CORE_FEATURES)
                    feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)
                    feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)
                    if len(feat_row) > 0:
                        latest_row = feat_row.iloc[[-1]].values
                        cs_result = predict_crash_surge(latest_row, fallback_model)
                        upsert_crash_surge(cs_result)
                        print('[Step 7-fallback] 경량 수집으로 예측 성공')
                    else:
                        print('[Step 7-fallback] 유효한 피처 행 없음')
            except Exception as e2:
                print(f'[Step 7-fallback] 경량 fallback도 실패: {e2}')

        # Step 7b: 백필 (모델 학습/예측과 분리)
        if cs_should_retrain and cs_datasets is not None and cs_model is not None:
            try:
                print('\n[Step 7b] 신규 날짜 점수 백필...')
                backfill_records = backfill_crash_surge(cs_datasets['df_full'], cs_model)
                existing = fetch_crash_surge_all()
                existing_dates = {r['date'] for r in existing}
                new_records = [r for r in backfill_records if r['date'] not in existing_dates]
                print(f'[Step 7b] 전체 {len(backfill_records)}건 중 신규 {len(new_records)}건 백필')
                for rec in new_records:
                    upsert_crash_surge(rec)
                print(f'[Step 7b] 백필 완료: {len(new_records)}건 DB 저장')
            except Exception as e:
                print(f'[Step 7b] 폭락/급등 백필 실패, 건너뜀: {e}')
                traceback.print_exc()

        # Step 8: 앙상블 ETF 30일 가격 예측 (16 tickers) — 추론 모드 (.pkl load)
        # 학습은 매월 1일 train_chart_pipeline 가 별도 담당 (api/app.py Stage 3)
        # .pkl 없으면 run_chart_predict_single 가 자동으로 fallback 1회 학습
        print('\n[Step 8] ETF 앙상블 예측 (추론 모드)...')
        try:
            predict_results = run_chart_predict_all(train=False)
            for rec in predict_results:
                upsert_chart_predict(rec)
            print(f'[Step 8] {len(predict_results)}건 예측 완료')
        except Exception as e:
            print(f'[Step 8] 앙상블 예측 실패, 건너뜀: {e}')
            traceback.print_exc()

        # Step 8b: ECOS 거시지표 (기준금리·주담대 금리·잔액) — 24개월
        # 부동산 수집보다 먼저 호출해 buy_signal 계산 시 이용 가능하게.
        print('\n[Step 8b] ECOS 거시지표 수집...')
        try:
            ecos_rows = ecos_fetch_macro_rate_kr(months=24)
            upsert_macro_rate_kr(ecos_rows)
            print(f'[Step 8b] {len(ecos_rows)}개월 ECOS 저장')
        except Exception as e:
            print(f'[Step 8b] ECOS 실패, 건너뜀: {e}')
            traceback.print_exc()

        # Step 9: 부동산 월별 수집 (매매·전월세·인구·세대원수·매핑·지역집계)
        print('\n[Step 9] 부동산 데이터 수집...')
        try:
            # 기준월 = 전월 — MOIS 인구통계가 당월엔 미집계(1~2개월 lag)라
            # 당월로 호출하면 resultCode=10 INVALID_REQUEST_PARAMETER 반환됨.
            _today = datetime.date.today()
            re_ym = (_today.replace(day=1) - datetime.timedelta(days=1)).strftime('%Y%m')
            # 전국 시군구 코드 동적 조회 (MOIS lv=1→lv=2) — 신규 시군구 자동 반영
            re_sgg_codes = fetch_all_sgg_codes(re_ym)
            # KOSIS 인구이동 — 시군구별로 한 번에 (셀 한도 안 넘게 묶음)
            try:
                kosis_rows = fetch_kosis_migration(re_sgg_codes, months=24)
                upsert_region_migration(kosis_rows)
                print(f'  KOSIS 인구이동 {len(kosis_rows)}건 저장')
            except Exception as e_k:
                print(f'  KOSIS 실패, 건너뜀: {e_k}')

            # ECOS 시계열 한 번 읽어 두고 buy_signal 계산 시 매번 재사용
            rate_ts = repo_fetch_macro_rate_kr(months=24)
            print(f'  [Step 9] 전국 {len(re_sgg_codes)}개 시군구 대상')

            for sgg_cd in re_sgg_codes:
                print(f'  [Step 9] sgg_cd={sgg_cd}...')
                try:
                    raw_trades = fetch_trades(sgg_cd, re_ym)
                    trades = _re_norm_trades(raw_trades, sgg_cd, re_ym)
                    upsert_re_trades(trades)

                    raw_rents = fetch_rents(sgg_cd, re_ym)
                    rents = _re_norm_rents(raw_rents, sgg_cd, re_ym)
                    upsert_re_rents(rents)

                    # 행안부 API는 시군구도 10자리 코드로 호출 (뒷 5자리 0 패딩)
                    sgg_cd_10 = sgg_cd + "00000"
                    raw_pop = fetch_population(sgg_cd_10, re_ym)
                    population = _re_norm_population(raw_pop, re_ym)
                    upsert_mois_population(population)

                    raw_mapping = build_mapping(sgg_cd_10, re_ym)
                    mapping = _re_norm_mapping(raw_mapping)
                    upsert_stdg_admm_mapping(mapping)

                    # MOIS API가 상위 admm_cd 호출 시 하위 admm_cd까지 섞어 반환 →
                    # 누적 후 (stats_ym, admm_cd) 중복 제거 (테이블 UNIQUE 키와 동일)
                    hh_seen: set[tuple] = set()
                    household: list[dict] = []
                    admm_cds = list({m["admm_cd"] for m in mapping if m.get("admm_cd")})
                    for admm_cd in admm_cds:
                        raw_hh = fetch_household_by_size(admm_cd, re_ym)
                        for row in _re_norm_household(raw_hh, re_ym):
                            k = (row["stats_ym"], row["admm_cd"])
                            if k in hh_seen:
                                continue
                            hh_seen.add(k)
                            household.append(row)
                    upsert_mois_household(household)

                    summary = compute_region_summary(
                        trades=trades, rents=rents,
                        population=population, mapping=mapping,
                        household=household or None,
                        sgg_cd=sgg_cd, stats_ym=re_ym,
                    )
                    upsert_region_summary(summary)

                    # 매수 시그널 — region_summary 시계열 + ECOS 금리 + KOSIS 이동
                    ts = fetch_region_timeseries(sgg_cd)
                    flow_ts = fetch_region_migration(sgg_cd)
                    signal_rec = compute_buy_signal(ts, rate_ts=rate_ts, flow_ts=flow_ts)
                    if signal_rec:
                        signal_rec['sgg_cd'] = sgg_cd
                        upsert_buy_signal(signal_rec)

                    # 신규 법정동만 지오코딩 — (ctpv_nm, sgg_nm, stdg_nm) 조합으로 검색
                    existing_geo = {g["stdg_cd"] for g in fetch_geo_stdg(sgg_cd)}
                    seen_stdg: set[str] = set()
                    uniq_new: list[dict] = []
                    for m in mapping:
                        if m.get("stdg_cd") not in existing_geo and m["stdg_cd"] not in seen_stdg:
                            seen_stdg.add(m["stdg_cd"])
                            uniq_new.append(m)
                    if uniq_new:
                        addresses = [
                            f'{m.get("ctpv_nm", "")} {m.get("sgg_nm", "")} {m.get("stdg_nm", "")}'.strip()
                            for m in uniq_new
                        ]
                        geo_results = batch_geocode(addresses)
                        geo_records = [
                            {"stdg_cd": m["stdg_cd"], "stdg_nm": m.get("stdg_nm"),
                             "sgg_nm": m.get("sgg_nm"), "lat": geo["lat"], "lng": geo["lng"]}
                            for m, geo in zip(uniq_new, geo_results) if geo
                        ]
                        if geo_records:
                            upsert_geo_stdg(geo_records)
                            print(f'    지오코딩 {len(geo_records)}건 저장')
                except Exception as e_sgg:
                    print(f'  [Step 9] sgg_cd={sgg_cd} 실패, 건너뜀: {e_sgg}')
                    traceback.print_exc()

            print(f'[Step 9] 완료 ({len(re_sgg_codes)}개 시군구)')
        except Exception as e:
            print(f'[Step 9] 부동산 수집 실패, 건너뜀: {e}')
            traceback.print_exc()

    elapsed = (datetime.datetime.now() - start).seconds  # 소요 시간 계산
    print(f'\n{"="*50}')
    print(f'[Pipeline-{mode}] 완료 (소요: {elapsed}초)')
    print(f'{"="*50}\n')
