# ============================================================
# ML_05_Feature1Regime — Noise HMM 4-state 국면 판별기 빈칸 연습
# 원본: processor/feature1_regime.py
# 총 빈칸: 55개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

import datetime
import ___                                              # Q1: 파일 경로 처리 모듈
import warnings
from typing import ___                                   # Q2: None을 허용하는 타입 힌트

import ___                                              # Q3: 모델 직렬화/역직렬화 라이브러리
import numpy as np
from hmmlearn.hmm import ___                             # Q4: 가우시안 분포 기반 HMM 클래스
from sklearn.preprocessing import ___                    # Q5: 이상치에 강건한 스케일러

warnings.filterwarnings('ignore')

N_STATES = ___                                           # Q6: HMM 은닉 상태 수 (국면 개수)
PHASE_NAMES = {
    0: '___',                                            # Q7: 기초여건이 시장에 온전히 반영되는 국면
    1: '___',                                            # Q8: 기초여건이 시장에 부분 반영되는 국면
    2: '___',                                            # Q9: 투자심리가 시장에 부분 영향을 미치는 국면
    3: '___',                                            # Q10: 투자심리가 시장을 완전히 좌우하는 국면
}

FEATURE_NAMES = [
    'fundamental_gap', '___', 'residual_corr',           # Q11: 주식위험프리미엄 Z점수 피처명
    'dispersion', '___', '___', '___',                   # Q12~Q14: 비유동성 지표, VIX 기간구조, 하이일드 스프레드 피처명
    '___',                                               # Q15: 실현 변동성 피처명
]

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(___)), 'models')  # Q16: 현재 스크립트의 파일 경로를 나타내는 내장 변수
MODEL_PATH = os.path.join(MODEL_DIR, '___')              # Q17: 노이즈 HMM 모델 저장 파일명 (.pkl)


def compute_noise_score(means: np.ndarray) -> np.ndarray:
    """noise_score v2: 상관 기반 가중치."""
    return (
        ___ * np.abs(means[:, 0])                        # Q18: fundamental_gap 가중치 (0보다 크고 1 이하)
      + ___ * np.abs(means[:, 1])                        # Q19: erp_zscore 가중치 (0보다 크고 0.5 이하)
      + ___ * means[:, 2]                                # Q20: residual_corr 가중치 (정수)
      # dispersion 제거 (가중치 0)
      + 0.5 * means[:, ___]                              # Q21: amihud 다음 피처(vix_term)의 인덱스
      + ___ * means[:, 5]                                # Q22: hy_spread 가중치 (정수)
      + ___ * means[:, 6]                                # Q23: realized_vol 이전 피처의 가중치 (1과 2 사이)
      + 2.0 * means[:, ___]                              # Q24: 마지막 피처(realized_vol)의 인덱스
    )


def train_hmm(features_df, monthly_bundle: dict = None) -> dict:
    """4-state GaussianHMM 학습 → 모델 번들 저장 및 반환."""
    X = features_df[___].values                          # Q25: 8개 피처명 리스트 상수
    scaler = ___()                                       # Q26: 이상치에 강건한 스케일러 클래스 인스턴스 생성
    X_scaled = scaler.___(X)                             # Q27: 학습과 변환을 한번에 수행하는 메서드

    for cov_type in ('___', '___'):                       # Q28~Q29: 완전 공분산 → 대각 공분산 순서로 시도하는 공분산 타입
        try:
            model = GaussianHMM(
                n_components=___,                        # Q30: 은닉 상태 수 상수
                covariance_type=cov_type,
                n_iter=___,                              # Q31: EM 알고리즘 최대 반복 횟수
                random_state=42,
            )
            model.___(X_scaled)                          # Q32: 모델 학습 메서드
            break
        except (ValueError, np.linalg.LinAlgError):
            if cov_type == 'diag':
                raise

    # noise_score 기반 상태 → 국면 매핑
    noise_scores = compute_noise_score(model.___)        # Q33: HMM 각 상태의 평균 벡터 속성
    sorted_states = np.___(noise_scores)                 # Q34: 오름차순 정렬된 인덱스를 반환하는 함수
    state_to_phase = {int(sid): rank for rank, sid in enumerate(___)}  # Q35: 정렬된 상태 배열

    # 경량 파이프라인용 월별 피처 캐시값 추출
    last_monthly = {}
    if monthly_bundle is not None:
        feat_df = monthly_bundle['___']                  # Q36: 월별 피처 데이터프레임 키 이름
        last_monthly = {
            'fundamental_gap': float(feat_df['fundamental_gap'].iloc[___]),  # Q37: 가장 마지막 행의 인덱스
            'erp_zscore':      float(feat_df['erp_zscore'].iloc[-1]),
            'vix_term':        float(feat_df['vix_term'].iloc[-1]),
            'hy_spread':       float(feat_df['hy_spread'].iloc[-1]),
        }

    bundle = {
        '___': model,                                    # Q38: 학습된 HMM 모델 객체의 딕셔너리 키
        '___': scaler,                                   # Q39: 스케일러 객체의 딕셔너리 키
        'state_to_phase': state_to_phase,
        'train_month': datetime.date.today().strftime('___'),  # Q40: 연-월 형식의 날짜 포맷 문자열
        'last_monthly_values': last_monthly,
    }

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.___(bundle, MODEL_PATH)                       # Q41: 객체를 파일로 저장하는 메서드
    return bundle


def load_model() -> Optional[dict]:
    """저장된 모델 번들 로드. 없으면 None."""
    if not os.path.___(MODEL_PATH):                      # Q42: 파일 존재 여부를 확인하는 메서드
        return None
    try:
        bundle = joblib.___(MODEL_PATH)                  # Q43: 파일에서 객체를 불러오는 메서드
        return bundle
    except Exception:
        return None


def predict_regime(daily_features: np.ndarray, model_bundle: dict) -> dict:
    """오늘의 8피처 벡터로 국면 예측."""
    model = model_bundle['model']
    scaler = model_bundle['___']                         # Q44: 스케일러 객체의 딕셔너리 키
    state_to_phase = model_bundle['state_to_phase']

    daily_scaled = scaler.___(daily_features)            # Q45: 학습된 파라미터로 변환만 수행하는 메서드
    proba_raw = model.___(daily_scaled)[0]               # Q46: 각 상태의 사후 확률을 반환하는 메서드

    # HMM state 확률 → phase 확률로 변환
    proba_by_phase = {}
    for state_id, prob in ___(proba_raw):                # Q47: 인덱스와 값을 함께 순회하는 내장 함수
        phase_id = state_to_phase[state_id]
        proba_by_phase[phase_id] = proba_by_phase.get(phase_id, 0.0) + float(prob)

    pred_phase = ___(proba_by_phase, key=proba_by_phase.get)  # Q48: 최대값의 키를 반환하는 내장 함수

    # noise_score 계산
    ns = float(compute_noise_score(daily_scaled)[___])   # Q49: 첫 번째 원소의 인덱스

    today_str = str(datetime.date.___())                 # Q50: 오늘 날짜를 반환하는 메서드
    proba_dict = {PHASE_NAMES[ph]: round(proba_by_phase.get(ph, 0.0), 4) for ph in range(___)}  # Q51: 전체 국면 수 상수

    result = {
        'date': today_str,
        '___': pred_phase,                               # Q52: 예측된 국면 ID의 딕셔너리 키
        '___': PHASE_NAMES[pred_phase],                  # Q53: 예측된 국면 이름의 딕셔너리 키
        'noise_score': round(ns, 4),
        '___': proba_dict,                               # Q54: 국면별 확률 딕셔너리의 키
    }
    return result


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | os                     |
# | Q2 | from typing import ___        | Optional               |
# | Q3 | import ___                    | joblib                 |
# | Q4 | import ___                    | GaussianHMM            |
# | Q5 | import ___                    | RobustScaler           |
# | Q6 | N_STATES = ___                | 4                      |
# | Q7 | 0: '___'                      | 펀더멘털 반영           |
# | Q8 | 1: '___'                      | 펀더멘털 약반영         |
# | Q9 | 2: '___'                      | 센티멘트 약반영         |
# | Q10| 3: '___'                      | 센티멘트 지배           |
# | Q11| '___'                         | erp_zscore             |
# | Q12| '___'                         | amihud                 |
# | Q13| '___'                         | vix_term               |
# | Q14| '___'                         | hy_spread              |
# | Q15| '___'                         | realized_vol           |
# | Q16| ___                           | __file__               |
# | Q17| '___'                         | noise_hmm.pkl          |
# | Q18| ___                           | 0.5                    |
# | Q19| ___                           | 0.3                    |
# | Q20| ___                           | 1.0                    |
# | Q21| means[:, ___]                 | 4                      |
# | Q22| ___                           | 2.0                    |
# | Q23| ___                           | 1.5                    |
# | Q24| means[:, ___]                 | 7                      |
# | Q25| features_df[___]              | FEATURE_NAMES          |
# | Q26| ___()                         | RobustScaler           |
# | Q27| scaler.___                    | fit_transform          |
# | Q28| '___'                         | full                   |
# | Q29| '___'                         | diag                   |
# | Q30| n_components=___              | N_STATES               |
# | Q31| n_iter=___                    | 200                    |
# | Q32| model.___                     | fit                    |
# | Q33| model.___                     | means_                 |
# | Q34| np.___                        | argsort                |
# | Q35| enumerate(___)                | sorted_states          |
# | Q36| monthly_bundle['___']         | features               |
# | Q37| .iloc[___]                    | -1                     |
# | Q38| '___': model                  | model                  |
# | Q39| '___': scaler                 | scaler                 |
# | Q40| strftime('___')               | %Y-%m                  |
# | Q41| joblib.___                    | dump                   |
# | Q42| os.path.___                   | exists                 |
# | Q43| joblib.___                    | load                   |
# | Q44| ['___']                       | scaler                 |
# | Q45| scaler.___                    | transform              |
# | Q46| model.___                     | predict_proba          |
# | Q47| ___(proba_raw)                | enumerate              |
# | Q48| ___(proba_by_phase, ...)      | max                    |
# | Q49| [___]                         | 0                      |
# | Q50| date.___()                    | today                  |
# | Q51| range(___)                    | N_STATES               |
# | Q52| '___': pred_phase             | regime_id              |
# | Q53| '___': PHASE_NAMES[...]       | regime_name            |
# | Q54| '___': proba_dict             | probabilities          |
# ============================================================
