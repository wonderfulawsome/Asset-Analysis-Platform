# ============================================================
# BE_10_Scheduler — 파이프라인 스케줄러 빈칸 연습
# 원본: scheduler/job.py
# 총 빈칸: 50개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

import ___                                              # Q1: 날짜/시간 처리 표준 라이브러리
# Q2~Q7: 수집 모듈 임포트
from collector.market_data import ___, ___               # Q2~Q3: 거시 데이터 수집 함수와 레코드 변환 함수
from collector.fear_greed import ___, ___                # Q4~Q5: 공포탐욕지수 수집 함수와 풋콜비율 수집 함수
from collector.index_price import ___                    # Q6: ETF/인덱스 가격 수집 함수
from collector.sector_macro import fetch_sector_macro, ___  # Q7: 섹터 매크로 데이터를 DB 레코드로 변환하는 함수
from collector.sector_etf import ___                     # Q8: 섹터 ETF 수익률 수집 함수
from collector.noise_regime_data import (
    fetch_shiller, fetch_fred_regime, fetch_sector_stocks,
    fetch_amihud_stocks, compute_monthly_features, ___,  # Q9: 일별 피처 계산 함수
    fetch_noise_regime_light,
)
# Q10~Q13: DB 저장 함수 임포트
from database.repositories import (
    upsert_macro, ___, upsert_fear_greed,                # Q10: 노이즈 국면 결과를 DB에 저장하는 함수
    upsert_index_prices, ___, upsert_sector_cycle,       # Q11: 섹터 매크로 데이터를 DB에 저장하는 함수
    ___                                                  # Q12: 폭락/급등 전조 데이터를 DB에 저장하는 함수
)
# Q13~Q14: 프로세서 임포트
from processor.feature1_regime import ___, load_model, predict_regime  # Q13: HMM 모델 학습 함수
from processor.feature2_sector_cycle import ___          # Q14: 섹터 경기국면 분석 실행 함수
from collector.crash_surge_data import (
    fetch_crash_surge_raw, fetch_crash_surge_light,
    compute_features, compute_labels, ___, ALL_FEATURES, # Q15: 학습용 데이터셋 준비 함수
)
from processor.feature3_crash_surge import (
    train_crash_surge, load_model as load_crash_surge_model, ___,  # Q16: 폭락/급등 예측 함수
    backfill_crash_surge,
)


def run_pipeline(light: bool = ___) -> None:             # Q17: 기본값은 전체 파이프라인 실행(불리언)
    """파이프라인 실행.
    light=False: 전체 파이프라인 (100년치 수집 + 모델 학습)
    light=True:  경량 파이프라인 (최근 데이터만 갱신, 30분 주기용)
    """
    start = datetime.datetime.___()                      # Q18: 현재 시각을 반환하는 메서드
    mode = '경량' if ___ else '전체'                      # Q19: 경량 모드 여부를 나타내는 매개변수

    # Step 1: 거시 지표 수집 (경량: 최근 60일, 전체: 100년)
    print('\n[Step 1] 거시 지표 수집...')
    df = fetch_macro(days=___ if light else ___)          # Q20~Q21: 경량 모드 최근 일수와 전체 모드 전체기간(0=무제한) 값

    # Step 2: macro_raw 저장
    records = ___(df)                                    # Q22: DataFrame을 DB 저장용 레코드 리스트로 변환하는 함수
    ___(records)                                         # Q23: 거시 지표 레코드를 DB에 upsert하는 함수

    # 경량 모드가 아닐 때만 무거운 작업 실행
    if not ___:                                          # Q24: 경량 모드 여부를 나타내는 매개변수
        # Step 3: Noise vs Signal HMM 국면 판별
        try:
            start_date = str(datetime.date.today() - datetime.timedelta(days=365 * ___ + 30))  # Q25: 데이터 수집 기간(년 수, 약 18년치)

            # 3a: 데이터 수집
            shiller = ___()                              # Q26: Shiller CAPE 데이터 수집 함수
            fred = ___()                                 # Q27: FRED 국면 데이터 수집 함수
            stock_prices = fetch_sector_stocks(___)      # Q28: 데이터 수집 시작일 변수
            amihud_data = fetch_amihud_stocks(start_date)

            # 3b: 월별 피처 계산
            bundle = ___(shiller, fred, stock_prices, amihud_data)  # Q29: 월별 피처를 계산하는 함수

            # 3c: 모델 학습 또는 로드
            model_bundle = ___()                         # Q30: 저장된 모델을 불러오는 함수
            current_month = datetime.date.today().strftime('___')  # Q31: 연-월 형식의 날짜 포맷 문자열
            should_retrain = (model_bundle is ___ or     # Q32: 모델이 존재하지 않음을 나타내는 값
                              model_bundle.get('___') != current_month)  # Q33: 모델 학습 시점(월)을 저장하는 키
            if should_retrain:
                model_bundle = train_hmm(bundle['___'], monthly_bundle=bundle)  # Q34: 번들에서 피처 데이터를 꺼내는 키

            # 3d: 일별 피처 계산 + 예측
            daily_feat = compute_daily_features(___)     # Q35: 수집된 데이터 묶음 변수
            result = predict_regime(daily_feat, ___)     # Q36: 학습된 모델 번들 변수

            # 3e: DB 저장
            upsert_noise_regime(___)                     # Q37: 국면 예측 결과 변수
        except Exception as e:
            print(f'[Step 3] Noise HMM 실패, 건너뜀: {e}')

    # Step 4: Fear & Greed + PUT/CALL Ratio (항상 실행)
    fear_greed = ___()                                   # Q38: 공포탐욕지수를 수집하는 함수
    upsert_fear_greed(___)                               # Q39: 수집된 공포탐욕 데이터 변수
    pcr = ___()                                          # Q40: 풋콜비율을 수집하는 함수
    if pcr is not None:
        upsert_macro([{'date': fear_greed['___'], 'putcall_ratio': pcr}])  # Q41: 날짜 필드의 키 이름

    # Step 5: ETF 가격 수집 (항상 실행)
    index_prices = ___()                                 # Q42: ETF/인덱스 가격을 수집하는 함수
    upsert_index_prices(___)                             # Q43: 수집된 인덱스 가격 데이터 변수

    # Step 5b: 경량 모드 crash/surge 실시간 예측
    if light:
        try:
            cs_model = ___()                             # Q44: 폭락/급등 예측 모델을 불러오는 함수
            if cs_model is not None:
                raw_light = fetch_crash_surge_light()
                features_light = compute_features(
                    raw_light['spy'], raw_light['___'],  # Q45: FRED 경제 데이터 키
                    raw_light['cboe'], raw_light['___']) # Q46: Yahoo 거시 데이터 키
                # 피처 NaN 처리 후 예측
        except Exception as e:
            print(f'  [CrashSurge-Light] 실시간 예측 실패: {e}')

    # 경량 모드가 아닐 때 Step 6, 7 실행
    if not light:
        # Step 6: 섹터 경기국면 분석
        try:
            sector_macro = fetch_sector_macro()
            macro_records = to_sector_macro_records(___)  # Q47: 섹터 매크로 DataFrame 변수
            upsert_sector_macro(macro_records)
            macro_start = str(sector_macro.index[0].date())
            sector_ret, holding_ret = ___(macro_start)   # Q48: 섹터 ETF 수익률을 수집하는 함수
            cycle_result = run_sector_cycle(sector_macro, sector_ret, ___)  # Q49: 보유 종목 수익률 변수
            upsert_sector_cycle(___)                     # Q50: 섹터 경기국면 분석 결과 변수
        except Exception as e:
            print(f'[Step 6] 섹터 경기국면 실패, 건너뜀: {e}')

    elapsed = (datetime.datetime.now() - start).___      # Q51: timedelta에서 경과 초를 가져오는 속성
    print(f'[Pipeline-{mode}] 완료 (소요: {elapsed}초)')


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | datetime               |
# | Q2 | import ___                    | fetch_macro            |
# | Q3 | import ___                    | to_macro_records       |
# | Q4 | import ___                    | fetch_fear_greed       |
# | Q5 | import ___                    | fetch_putcall_ratio    |
# | Q6 | import ___                    | fetch_index_prices     |
# | Q7 | import ___                    | to_sector_macro_records|
# | Q8 | import ___                    | fetch_sector_etf_returns|
# | Q9 | import ___                    | compute_daily_features |
# | Q10| import ___                    | upsert_noise_regime    |
# | Q11| import ___                    | upsert_sector_macro    |
# | Q12| import ___                    | upsert_crash_surge     |
# | Q13| import ___                    | train_hmm              |
# | Q14| import ___                    | run_sector_cycle       |
# | Q15| import ___                    | prepare_datasets       |
# | Q16| import ___                    | predict_crash_surge    |
# | Q17| light: bool = ___            | False                  |
# | Q18| datetime.datetime.___()      | now                    |
# | Q19| if ___                        | light                  |
# | Q20| days=___                      | 60                     |
# | Q21| else ___                      | 0                      |
# | Q22| ___(df)                       | to_macro_records       |
# | Q23| ___(records)                  | upsert_macro           |
# | Q24| not ___                       | light                  |
# | Q25| 365 * ___                     | 18                     |
# | Q26| ___()                         | fetch_shiller          |
# | Q27| ___()                         | fetch_fred_regime      |
# | Q28| (___) 인자                    | start_date             |
# | Q29| ___(...) 함수                 | compute_monthly_features|
# | Q30| ___()                         | load_model             |
# | Q31| strftime('___')               | %Y-%m                  |
# | Q32| is ___                        | None                   |
# | Q33| .get('___')                   | train_month            |
# | Q34| bundle['___']                 | features               |
# | Q35| (___) 인자                    | bundle                 |
# | Q36| (daily_feat, ___) 인자        | model_bundle           |
# | Q37| (___) 인자                    | result                 |
# | Q38| ___()                         | fetch_fear_greed       |
# | Q39| (___) 인자                    | fear_greed             |
# | Q40| ___()                         | fetch_putcall_ratio    |
# | Q41| fear_greed['___']             | date                   |
# | Q42| ___()                         | fetch_index_prices     |
# | Q43| (___) 인자                    | index_prices           |
# | Q44| ___()                         | load_crash_surge_model |
# | Q45| raw_light['___']              | fred                   |
# | Q46| raw_light['___']              | yahoo_macro            |
# | Q47| (___) 인자                    | sector_macro           |
# | Q48| ___(macro_start)              | fetch_sector_etf_returns|
# | Q49| (..., ___)                    | holding_ret            |
# | Q50| (___) 인자                    | cycle_result           |
# | Q51| .___                          | seconds                |
# ============================================================
