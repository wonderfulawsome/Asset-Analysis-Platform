# ============================================================
# ML_07_Feature3CrashSurge — XGBoost 3클래스 폭락/급등 분류기 빈칸 연습
# 원본: processor/feature3_crash_surge.py
# 총 빈칸: 55개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

import datetime
import ___                                              # Q1: 파일 경로 처리 모듈
import warnings
from collections import ___                              # Q2: 요소별 개수를 세는 클래스
from typing import Optional

import ___                                              # Q3: 모델 직렬화/역직렬화 라이브러리
import numpy as np
from scipy.special import logit as ___                   # Q4: 로짓 함수의 별칭
from sklearn.linear_model import ___                     # Q5: 로지스틱 회귀 클래스
from sklearn.metrics import ___                          # Q6: F1 점수 평가 함수
from sklearn.model_selection import ___                  # Q7: 시계열 교차검증 분할기
from sklearn.preprocessing import ___                    # Q8: 표준 정규화 스케일러
from xgboost import ___                                  # Q9: XGBoost 분류기 클래스
import ___                                              # Q10: 하이퍼파라미터 최적화 라이브러리

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.___)         # Q11: 경고 수준 로깅 상수

from collector.crash_surge_data import ___                # Q12: 전체 피처 이름 리스트 상수

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
MODEL_PATH = os.path.join(MODEL_DIR, '___')              # Q13: 모델 저장 파일명 (pkl 확장자)

DECAY = ___                                              # Q14: 지수 감쇠 가중치 계수 (1에 가까운 소수)


def grade(score: float) -> str:
    """0~100 percentile rank → 등급."""
    if score < ___:                                      # Q15: 낮음 등급 상한 경계값
        return '낮음'
    elif score < ___:                                    # Q16: 보통 등급 상한 경계값
        return '보통'
    elif score < ___:                                    # Q17: 주의 등급 상한 경계값
        return '주의'
    elif score < ___:                                    # Q18: 경고 등급 상한 경계값
        return '경고'
    else:
        return '___'                                     # Q19: 최고 위험 등급명


def _make_decay_weights(n: int) -> np.ndarray:
    """지수 감쇠 가중치: 최근 데이터에 높은 가중치."""
    return DECAY ** np.___(n - 1, -1, -1)                # Q20: 역순 정수 배열을 생성하는 numpy 함수


def _calc_sample_weight_balanced(y: np.ndarray) -> np.ndarray:
    """sklearn balanced class weight → sample weight."""
    counts = ___(y)                                      # Q21: 각 클래스별 개수를 세는 함수
    n = ___(y)                                           # Q22: 전체 샘플 수를 구하는 내장 함수
    n_classes = len(counts)
    class_w = {c: n / (n_classes * cnt) for c, cnt in counts.___()}  # Q23: 딕셔너리의 키-값 쌍을 순회하는 메서드
    return np.array([class_w[yi] for yi in y])


def _fit_platt(raw_proba, y_true_binary) -> LogisticRegression:
    """Platt Scaling: raw probability → calibrated probability."""
    raw_clipped = np.___(raw_proba, 1e-6, 1 - 1e-6)     # Q24: 값을 범위 내로 제한하는 numpy 함수
    logits = scipy_logit(raw_clipped).reshape(-1, ___)   # Q25: 2D 배열로 만들기 위한 열 수
    lr = LogisticRegression(C=___, solver='lbfgs', max_iter=1000)  # Q26: 정규화 거의 없는 큰 C 값
    lr.___(logits, y_true_binary)                        # Q27: 모델을 학습시키는 메서드
    return lr


def train_crash_surge(X_train, y_train, X_calib, y_calib,
                      X_test, y_test, X_dev, y_dev,
                      X_full, n_trials: int = ___) -> dict:  # Q28: Optuna 기본 시행 횟수
    """XGBoost 학습 + Platt 캘리브레이션 + 모델 저장."""

    tscv = TimeSeriesSplit(n_splits=___)                  # Q29: 시계열 교차검증 분할 수

    def objective(trial):
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 200, ___),  # Q30: 트리 개수 상한값
            'learning_rate': trial.suggest_float('learning_rate', 0.005, 0.1, log=___),  # Q31: 로그 스케일 탐색 여부
            'max_depth': trial.suggest_int('max_depth', ___, ___),       # Q32~Q33: 트리 최소/최대 깊이
            'subsample': trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
        }

        fold_scores = []
        for train_idx, val_idx in tscv.___(X_dev):       # Q34: 교차검증 인덱스를 생성하는 메서드
            X_tr, X_vl = X_dev[train_idx], X_dev[val_idx]
            y_tr, y_vl = y_dev[train_idx], y_dev[val_idx]

            sc = StandardScaler()
            X_tr_s = sc.fit_transform(X_tr)
            X_vl_s = sc.___(X_vl)                        # Q35: 학습된 스케일러로 변환만 수행하는 메서드

            class_sw = _calc_sample_weight_balanced(y_tr)
            decay_sw = _make_decay_weights(len(y_tr))
            sw = class_sw * ___                          # Q36: 시간 감쇠 가중치 변수

            model = XGBClassifier(
                objective='___', num_class=___, eval_metric='mlogloss',  # Q37~Q38: 다중 클래스 목적함수 문자열, 클래스 수
                random_state=42, verbosity=0, **params,
            )
            model.fit(X_tr_s, y_tr, sample_weight=___)   # Q39: 샘플 가중치 변수
            y_pred = model.___(X_vl_s)                   # Q40: 클래스 레이블을 예측하는 메서드
            fold_scores.append(f1_score(y_vl, y_pred, average='___'))  # Q41: 다중 클래스 F1 평균 방식

        return np.mean(fold_scores)

    # Optuna 최적화
    study = optuna.create_study(direction='___')          # Q42: 최적화 방향 (최대화/최소화)
    study.___(objective, n_trials=n_trials)               # Q43: 최적화를 실행하는 메서드
    best = study.___                                     # Q44: 최적 하이퍼파라미터를 가져오는 속성

    # 최종 모델 학습 + Platt Scaling
    scaler_final = StandardScaler()
    X_train_s = scaler_final.fit_transform(X_train)
    # ... 모델 학습, Platt 캘리브레이션 ...

    bundle = {
        'model': None,  # model_final
        'scaler': scaler_final,
        'train_month': datetime.date.today().strftime('___'),  # Q45: 연-월 형식의 날짜 포맷 문자열
    }
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(bundle, MODEL_PATH)
    return bundle


def load_model() -> Optional[dict]:
    """저장된 모델 번들 로드."""
    if not os.path.exists(___):                          # Q46: 모델 파일 경로 상수
        return None
    try:
        return joblib.load(MODEL_PATH)
    except Exception:
        return None


def predict_crash_surge(X_today: np.ndarray, model_bundle: dict) -> dict:
    """오늘의 44피처 벡터로 crash/surge 점수 예측."""
    model = model_bundle['___']                          # Q47: 학습된 XGBoost 모델 키
    scaler = model_bundle['___']                         # Q48: 표준 스케일러 키
    platt_surge = model_bundle['___']                    # Q49: 급등 Platt 캘리브레이터 키
    crash_rank_values = model_bundle['crash_rank_values']
    surge_rank_values = model_bundle['surge_rank_values']

    # Scale + predict
    X_scaled = scaler.___(X_today)                       # Q50: 학습된 스케일러로 변환만 수행하는 메서드
    proba = model.predict_proba(X_scaled)[___]           # Q51: 첫 번째 샘플의 인덱스

    crash_raw = proba[___] * 100                         # Q52: 폭락 클래스의 확률 인덱스

    # Percentile rank
    crash_pctl = float((crash_rank_values < crash_raw).___()) * 100  # Q53: 불리언 배열의 비율을 구하는 메서드

    result = {
        'date': str(datetime.date.today()),
        'crash_score': float(round(crash_pctl, 1)),
        'crash_grade': ___(crash_pctl),                  # Q54: 점수를 등급으로 변환하는 함수
        'net_score': float(round(0 - crash_pctl, 1)),    # 임시 계산
    }
    return result


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | import ___                    | os                     |
# | Q2 | from collections import ___   | Counter                |
# | Q3 | import ___                    | joblib                 |
# | Q4 | as ___                        | scipy_logit            |
# | Q5 | import ___                    | LogisticRegression     |
# | Q6 | import ___                    | f1_score               |
# | Q7 | import ___                    | TimeSeriesSplit        |
# | Q8 | import ___                    | StandardScaler         |
# | Q9 | import ___                    | XGBClassifier          |
# | Q10| import ___                    | optuna                 |
# | Q11| .___                          | WARNING                |
# | Q12| import ___                    | ALL_FEATURES           |
# | Q13| '___'                         | crash_surge_xgb.pkl    |
# | Q14| DECAY = ___                   | 0.9995                 |
# | Q15| < ___                         | 50                     |
# | Q16| < ___                         | 70                     |
# | Q17| < ___                         | 85                     |
# | Q18| < ___                         | 95                     |
# | Q19| '___'                         | 위험                   |
# | Q20| np.___                        | arange                 |
# | Q21| ___(y)                        | Counter                |
# | Q22| ___(y)                        | len                    |
# | Q23| .___()                        | items                  |
# | Q24| np.___                        | clip                   |
# | Q25| reshape(-1, ___)              | 1                      |
# | Q26| C=___                         | 1e10                   |
# | Q27| lr.___                        | fit                    |
# | Q28| n_trials: int = ___           | 50                     |
# | Q29| n_splits=___                  | 5                      |
# | Q30| 200, ___                      | 1000                   |
# | Q31| log=___                       | True                   |
# | Q32| ___                           | 3                      |
# | Q33| ___                           | 7                      |
# | Q34| tscv.___                      | split                  |
# | Q35| sc.___                        | transform              |
# | Q36| class_sw * ___                | decay_sw               |
# | Q37| '___'                         | multi:softprob         |
# | Q38| num_class=___                 | 3                      |
# | Q39| sample_weight=___             | sw                     |
# | Q40| model.___                     | predict                |
# | Q41| average='___'                 | macro                  |
# | Q42| direction='___'               | maximize               |
# | Q43| study.___                     | optimize               |
# | Q44| study.___                     | best_params            |
# | Q45| strftime('___')               | %Y-%m                  |
# | Q46| exists(___)                   | MODEL_PATH             |
# | Q47| ['___']                       | model                  |
# | Q48| ['___']                       | scaler                 |
# | Q49| ['___']                       | platt_surge            |
# | Q50| scaler.___                    | transform              |
# | Q51| [___]                         | 0                      |
# | Q52| proba[___]                    | 1                      |
# | Q53| .___()                        | mean                   |
# | Q54| ___(crash_pctl)               | grade                  |
# ============================================================
