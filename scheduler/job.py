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
    if not light:
        # Step 3: Noise vs Signal HMM 국면 판별
        print('\n[Step 3] Noise vs Signal 국면 판별...')
        try:
            start_date = str(datetime.date.today() - datetime.timedelta(days=365 * 18 + 30))

            # 3a: 데이터 수집
            shiller = fetch_shiller()
            fred = fetch_fred_regime()
            # Step 3에서 수집한 FRED 데이터를 캐시에 저장 (Step 7에서 재사용)
            # 컬럼명을 Step 7 형식(FRED_MAP의 value)으로 변환하여 저장
            if 'hy_spread' in fred:                          # BAMLH0A0HYM2 → HY_OAS
                hy_df = fred['hy_spread'].copy()             # DataFrame 복사
                hy_df.columns = ['HY_OAS']                   # 컬럼명 변환: hy_spread → HY_OAS
                fred_cache['HY_OAS'] = hy_df                 # Step 7 형식으로 캐시 저장
            if 'tips_rate' in fred:                          # DFII10 → DFII10
                tips_df = fred['tips_rate'].copy()           # DataFrame 복사
                tips_df.columns = ['DFII10']                 # 컬럼명 변환: tips_rate → DFII10
                fred_cache['DFII10'] = tips_df               # Step 7 형식으로 캐시 저장
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

            # 3f: 신규 날짜만 백필 (기존 히스토리 보존)
            if should_retrain:
                print('[Step 3f] Noise Regime 백필...')
                backfill_records = backfill_noise_regime(bundle, model_bundle, days=60)  # 최근 60 영업일 계산
                existing = fetch_noise_regime_all()                                      # 기존 DB 날짜 조회
                existing_dates = {r['date'] for r in existing}                           # 기존 날짜 set 변환
                new_records = [r for r in backfill_records if r['date'] not in existing_dates]  # 신규 날짜만 필터
                print(f'[Step 3f] 전체 {len(backfill_records)}건 중 신규 {len(new_records)}건 백필')
                for rec in new_records:                                                  # 신규 레코드만 저장
                    upsert_noise_regime(rec)
                print(f'[Step 3f] 백필 완료: {len(new_records)}건 DB 저장')
        except Exception as e:
            print(f'[Step 3] Noise HMM 실패, 건너뜀: {e}')    # 실패해도 다음 Step 계속 진행

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
        try:
            sector_macro = fetch_sector_macro()
            macro_records = to_sector_macro_records(sector_macro)
            upsert_sector_macro(macro_records)

            macro_start = str(sector_macro.index[0].date())
            sector_ret, holding_ret = fetch_sector_etf_returns(macro_start)
            cycle_result = run_sector_cycle(sector_macro, sector_ret, holding_ret)
            upsert_sector_cycle(cycle_result)
        except Exception as e:
            print(f'[Step 6] 섹터 경기국면 실패, 건너뜀: {e}')  # 실패해도 다음 Step 계속 진행

        # Step 7: XGBoost 폭락/급등 전조 탐지
        print('\n[Step 7] 폭락/급등 전조 탐지...')
        try:
            raw = fetch_crash_surge_raw(fred_cache=fred_cache)  # Step 3 캐시 재사용
            save_fred_cache(raw['fred'])                      # 경량 파이프라인용 파일 캐시 저장
            features = compute_features(raw['spy'], raw['fred'], raw['cboe'],
                                                  raw['yahoo_macro'])
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

            # Step 7b: 신규 날짜만 백필 (기존 히스토리 보존, redeploy 시에도 과거 점수 유지)
            if cs_should_retrain:
                print('\n[Step 7b] 신규 날짜 점수 백필...')
                backfill_records = backfill_crash_surge(datasets['df_full'], cs_model)  # 전체 기간 점수 계산
                # DB에서 기존 날짜 목록 조회
                existing = fetch_crash_surge_all()                                      # 기존 DB 레코드 전체 조회
                existing_dates = {r['date'] for r in existing}                          # 기존 날짜를 set으로 변환
                # 기존에 없는 날짜만 필터링
                new_records = [r for r in backfill_records if r['date'] not in existing_dates]  # 신규 날짜만 추출
                print(f'[Step 7b] 전체 {len(backfill_records)}건 중 신규 {len(new_records)}건 백필')
                for rec in new_records:                                                 # 신규 레코드만 DB 저장
                    upsert_crash_surge(rec)
                print(f'[Step 7b] 백필 완료: {len(new_records)}건 DB 저장')
        except Exception as e:
            print(f'[Step 7] 폭락/급등 전조 실패, 건너뜀: {e}')  # 실패해도 파이프라인 완료 처리

    elapsed = (datetime.datetime.now() - start).seconds  # 소요 시간 계산
    print(f'\n{"="*50}')
    print(f'[Pipeline-{mode}] 완료 (소요: {elapsed}초)')
    print(f'{"="*50}\n')
