import datetime
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
                                   upsert_crash_surge)
from processor.feature1_regime import train_hmm, load_model, predict_regime
from processor.feature2_sector_cycle import run_sector_cycle
from collector.crash_surge_data import (
    fetch_crash_surge_raw, fetch_crash_surge_light,
    compute_features, compute_labels, prepare_datasets, ALL_FEATURES,
)
from processor.feature3_crash_surge import (
    train_crash_surge, load_model as load_crash_surge_model, predict_crash_surge,
    backfill_crash_surge,
)


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

    # 경량 모드가 아닐 때만 무거운 작업 실행
    if not light:
        # Step 3: Noise vs Signal HMM 국면 판별
        print('\n[Step 3] Noise vs Signal 국면 판별...')
        start_date = str(datetime.date.today() - datetime.timedelta(days=365 * 18 + 30))

        # 3a: 데이터 수집
        shiller = fetch_shiller()
        fred = fetch_fred_regime()
        stock_prices = fetch_sector_stocks(start_date)
        amihud_data = fetch_amihud_stocks(start_date)

        # 3b: 월별 피처 계산
        bundle = compute_monthly_features(shiller, fred, stock_prices, amihud_data)

        # 3c: 모델 학습 또는 로드
        model_bundle = load_model()
        current_month = datetime.date.today().strftime('%Y-%m')
        should_retrain = (model_bundle is None or
                          model_bundle.get('train_month') != current_month)
        if should_retrain:
            print('[Step 3] 모델 재학습...')
            model_bundle = train_hmm(bundle['features'], monthly_bundle=bundle)
        else:
            print(f'[Step 3] 기존 모델 사용 (학습 월: {model_bundle["train_month"]})')

        # 3d: 일별 피처 계산 + 예측
        daily_feat = compute_daily_features(bundle)
        result = predict_regime(daily_feat, model_bundle)

        # 3e: DB 저장
        upsert_noise_regime(result)

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
    upsert_index_prices(index_prices)

    # Step 5b: 경량 모드 crash/surge 실시간 예측 (기존 모델 사용, 학습 없음)
    if light:
        print('\n[Step 5b] 폭락/급등 실시간 예측...')
        try:
            cs_model = load_crash_surge_model()  # 저장된 모델 로드
            if cs_model is not None:
                raw_light = fetch_crash_surge_light()  # 최근 데이터 경량 수집 (SPY/Cboe/PutCall 실시간 포함)
                features_light = compute_features(raw_light['spy'], raw_light['fred'],
                                                  raw_light['cboe'], raw_light['putcall'])  # 46 피처 계산
                # Core 피처 NaN 제거, Aux fillna(0) 처리
                from collector.crash_surge_data import CORE_FEATURES, AUX_FEATURES
                import numpy as np
                feat_row = features_light[ALL_FEATURES].copy()  # 피처만 추출
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

    # 경량 모드가 아닐 때만 무거운 작업 실행
    if not light:
        # Step 6: 섹터 경기국면 분석 (FRED 매크로 + 섹터 ETF + XGBoost)
        print('\n[Step 6] 섹터 경기국면 분석...')
        sector_macro = fetch_sector_macro()
        macro_records = to_sector_macro_records(sector_macro)
        upsert_sector_macro(macro_records)

        macro_start = str(sector_macro.index[0].date())
        sector_ret, holding_ret = fetch_sector_etf_returns(macro_start)
        cycle_result = run_sector_cycle(sector_macro, sector_ret, holding_ret)
        upsert_sector_cycle(cycle_result)

        # Step 7: XGBoost 폭락/급등 전조 탐지
        print('\n[Step 7] 폭락/급등 전조 탐지...')
        raw = fetch_crash_surge_raw()
        features = compute_features(raw['spy'], raw['fred'], raw['cboe'], raw['putcall'])
        labels = compute_labels(raw['spy']['Close'])
        datasets = prepare_datasets(features, labels, raw['spy']['Close'])

        cs_model = load_crash_surge_model()
        current_month = datetime.date.today().strftime('%Y-%m')
        cs_should_retrain = (cs_model is None or
                             cs_model.get('train_month') != current_month)
        if cs_should_retrain:
            print('[Step 7] 모델 재학습 (Optuna 50 trials)...')
            X_tr, y_tr = datasets['train']
            X_cal, y_cal = datasets['calib']
            X_te, y_te = datasets['test']
            X_dev, y_dev = datasets['dev']
            X_full = datasets['df_full'][ALL_FEATURES].values
            cs_model = train_crash_surge(X_tr, y_tr, X_cal, y_cal, X_te, y_te,
                                         X_dev, y_dev, X_full, n_trials=50)
        else:
            print(f'[Step 7] 기존 모델 사용 (학습 월: {cs_model["train_month"]})')

        latest_row = datasets['df_full'][ALL_FEATURES].iloc[[-1]].values
        cs_result = predict_crash_surge(latest_row, cs_model)
        upsert_crash_surge(cs_result)

        # Step 7b: 전체 기간 crash/surge 점수 백필 (모델 학습/재학습 시에만)
        if cs_should_retrain:
            print('\n[Step 7b] 전체 기간 점수 백필...')
            backfill_records = backfill_crash_surge(datasets['df_full'], cs_model)
            # 100건씩 나눠서 upsert (Supabase 요청 크기 제한 대비)
            batch_size = 100
            for i in range(0, len(backfill_records), batch_size):
                batch = backfill_records[i:i + batch_size]
                for rec in batch:
                    upsert_crash_surge(rec)
            print(f'[Step 7b] 백필 완료: {len(backfill_records)}건 DB 저장')

    elapsed = (datetime.datetime.now() - start).seconds  # 소요 시간 계산
    print(f'\n{"="*50}')
    print(f'[Pipeline-{mode}] 완료 (소요: {elapsed}초)')
    print(f'{"="*50}\n')
