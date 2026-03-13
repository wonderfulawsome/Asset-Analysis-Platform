"""XGBoost 3클래스 폭락/급등 전조 분류기

노트북 XGBoost_CrashSurge.ipynb Cell 4~6 로직을 production 코드로 변환.
Optuna 50-trial 최적화 + Platt Scaling (surge) + Percentile Rank 점수화.
"""

import datetime
import os
import warnings
from collections import Counter
from typing import Optional

import joblib
import numpy as np
from scipy.special import logit as scipy_logit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
import optuna

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

from collector.crash_surge_data import ALL_FEATURES

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
MODEL_PATH = os.path.join(MODEL_DIR, 'crash_surge_xgb.pkl')

DECAY = 0.9995


# ── 등급 ──

def grade(score: float) -> str:
    """0~100 percentile rank -> 등급."""
    if score < 50:
        return '낮음'
    elif score < 70:
        return '보통'
    elif score < 85:
        return '주의'
    elif score < 95:
        return '경고'
    else:
        return '위험'


# ── 내부 헬퍼 ──

def _make_decay_weights(n: int) -> np.ndarray:
    """지수 감쇠 가중치: 최근 데이터에 높은 가중치."""
    return DECAY ** np.arange(n - 1, -1, -1)


def _calc_sample_weight_balanced(y: np.ndarray) -> np.ndarray:
    """sklearn balanced class weight -> sample weight."""
    counts = Counter(y)
    n = len(y)
    n_classes = len(counts)
    class_w = {c: n / (n_classes * cnt) for c, cnt in counts.items()}
    return np.array([class_w[yi] for yi in y])


def _fit_platt(raw_proba: np.ndarray, y_true_binary: np.ndarray) -> LogisticRegression:
    """Platt Scaling: raw probability -> calibrated probability via sigmoid."""
    raw_clipped = np.clip(raw_proba, 1e-6, 1 - 1e-6)
    logits = scipy_logit(raw_clipped).reshape(-1, 1)
    lr = LogisticRegression(C=1e10, solver='lbfgs', max_iter=1000)
    lr.fit(logits, y_true_binary)
    return lr


def _apply_platt(lr: LogisticRegression, raw_proba: np.ndarray) -> np.ndarray:
    """Platt 보정 적용."""
    raw_clipped = np.clip(raw_proba, 1e-6, 1 - 1e-6)
    logits = scipy_logit(raw_clipped).reshape(-1, 1)
    return lr.predict_proba(logits)[:, 1]


# ── 학습 ──

def train_crash_surge(
    X_train: np.ndarray, y_train: np.ndarray,
    X_calib: np.ndarray, y_calib: np.ndarray,
    X_test: np.ndarray, y_test: np.ndarray,
    X_dev: np.ndarray, y_dev: np.ndarray,
    X_full: np.ndarray,
    n_trials: int = 50,
) -> dict:
    """XGBoost 학습 + Platt 캘리브레이션 + 모델 번들 저장."""

    tscv = TimeSeriesSplit(n_splits=5)

    def objective(trial):
        params = {
            'n_estimators': trial.suggest_int('n_estimators', 200, 1000),
            'learning_rate': trial.suggest_float('learning_rate', 0.005, 0.1, log=True),
            'max_depth': trial.suggest_int('max_depth', 3, 7),
            'subsample': trial.suggest_float('subsample', 0.5, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
            'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
            'gamma': trial.suggest_float('gamma', 0.0, 0.5),
            'reg_alpha': trial.suggest_float('reg_alpha', 1e-4, 10.0, log=True),
            'reg_lambda': trial.suggest_float('reg_lambda', 1e-4, 10.0, log=True),
        }

        fold_scores = []
        for train_idx, val_idx in tscv.split(X_dev):
            X_tr, X_vl = X_dev[train_idx], X_dev[val_idx]
            y_tr, y_vl = y_dev[train_idx], y_dev[val_idx]

            sc = StandardScaler()
            X_tr_s = sc.fit_transform(X_tr)
            X_vl_s = sc.transform(X_vl)

            class_sw = _calc_sample_weight_balanced(y_tr)
            decay_sw = _make_decay_weights(len(y_tr))
            sw = class_sw * decay_sw

            model = XGBClassifier(
                objective='multi:softprob', num_class=3, eval_metric='mlogloss',
                random_state=42, verbosity=0, use_label_encoder=False, **params,
            )
            model.fit(X_tr_s, y_tr, sample_weight=sw)
            y_pred = model.predict(X_vl_s)
            fold_scores.append(f1_score(y_vl, y_pred, average='macro'))

        return np.mean(fold_scores)

    # Optuna
    print(f'  [CrashSurge] Optuna {n_trials} trials 시작...')
    study = optuna.create_study(direction='maximize', study_name='crash_surge_xgb')
    study.optimize(objective, n_trials=n_trials)
    best = study.best_params
    print(f'  [CrashSurge] 최적 macro F1: {study.best_value:.4f}')

    # 최종 모델 학습
    scaler_final = StandardScaler()
    X_train_s = scaler_final.fit_transform(X_train)

    class_sw = _calc_sample_weight_balanced(y_train)
    decay_sw = _make_decay_weights(len(y_train))
    sw = class_sw * decay_sw

    model_final = XGBClassifier(
        objective='multi:softprob', num_class=3, eval_metric='mlogloss',
        random_state=42, verbosity=0, use_label_encoder=False, **best,
    )
    model_final.fit(X_train_s, y_train, sample_weight=sw)

    # Platt Scaling 캘리브레이션
    X_calib_s = scaler_final.transform(X_calib)
    calib_proba = model_final.predict_proba(X_calib_s)

    platt_surge = _fit_platt(calib_proba[:, 2], (y_calib == 2).astype(int))
    platt_surge_w = platt_surge.coef_[0][0]
    print(f'  [CrashSurge] Platt surge w={platt_surge_w:.4f}')

    # 홀드아웃 테스트
    X_test_s = scaler_final.transform(X_test)
    y_pred_test = model_final.predict(X_test_s)
    macro_f1 = f1_score(y_test, y_pred_test, average='macro')
    print(f'  [CrashSurge] Holdout macro F1: {macro_f1:.4f}')

    # 전체 추론 → percentile 기준값 저장
    X_full_s = scaler_final.transform(X_full)
    proba_full = model_final.predict_proba(X_full_s)

    crash_rank_values = proba_full[:, 1] * 100  # raw crash %
    surge_rank_values = _apply_platt(platt_surge, proba_full[:, 2]) * 100  # Platt surge %

    bundle = {
        'model': model_final,
        'scaler': scaler_final,
        'platt_surge': platt_surge,
        'best_params': best,
        'macro_f1': macro_f1,
        'crash_rank_values': crash_rank_values,
        'surge_rank_values': surge_rank_values,
        'train_month': datetime.date.today().strftime('%Y-%m'),
    }

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(bundle, MODEL_PATH)
    print(f'  [CrashSurge] 모델 저장 완료: {MODEL_PATH}')

    return bundle


# ── 모델 로드 ──

def load_model() -> Optional[dict]:
    """저장된 모델 번들 로드. 없으면 None."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        bundle = joblib.load(MODEL_PATH)
        print(f'  [CrashSurge] 모델 로드 (학습 월: {bundle.get("train_month", "?")})')
        return bundle
    except Exception as e:
        print(f'  [CrashSurge] 모델 로드 실패: {e}')
        return None


# ── 추론 ──

def predict_crash_surge(X_today: np.ndarray, model_bundle: dict) -> dict:
    """오늘의 44피처 벡터로 crash/surge 점수 예측.

    Args:
        X_today: shape (1, 44) numpy array (raw features, not scaled)
        model_bundle: train_crash_surge() 반환값

    Returns:
        dict with date, crash_score, crash_grade, surge_score, surge_grade,
             crash_raw, surge_raw, macro_f1
    """
    model = model_bundle['model']
    scaler = model_bundle['scaler']
    platt_surge = model_bundle['platt_surge']
    crash_rank_values = model_bundle['crash_rank_values']
    surge_rank_values = model_bundle['surge_rank_values']

    # Scale + predict
    X_scaled = scaler.transform(X_today)
    proba = model.predict_proba(X_scaled)[0]

    crash_raw = proba[1] * 100
    surge_calibrated = float(_apply_platt(platt_surge, np.array([proba[2]]))[0]) * 100

    # Percentile rank vs historical distribution
    crash_pctl = float((crash_rank_values < crash_raw).mean()) * 100
    surge_pctl = float((surge_rank_values < surge_calibrated).mean()) * 100

    result = {
        'date': str(datetime.date.today()),
        'crash_score': float(round(crash_pctl, 1)),           # numpy float32 → Python float 변환
        'crash_grade': grade(crash_pctl),
        'surge_score': float(round(surge_pctl, 1)),           # numpy float32 → Python float 변환
        'surge_grade': grade(surge_pctl),
        'net_score': float(round(surge_pctl - crash_pctl, 1)),  # 순방향 점수 (양수=급등 우세, 음수=폭락 우세)
        'crash_raw': float(round(crash_raw, 2)),              # numpy float32 → Python float 변환
        'surge_raw': float(round(surge_calibrated, 2)),       # numpy float32 → Python float 변환
        'macro_f1': float(round(model_bundle['macro_f1'], 4)),  # numpy float32 → Python float 변환
    }

    # 현재 피처값 저장 (46개 피처 모두)
    result['feature_values'] = {
        ALL_FEATURES[i]: round(float(X_today[0][i]), 4)
        for i in range(len(ALL_FEATURES))
    }

    # SHAP 값 계산 (lazy import — 서버 시작 시 필수 아님)
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_scaled)

        def _top_shap(sv, n=10):
            pairs = [(ALL_FEATURES[i], float(sv[i])) for i in range(len(ALL_FEATURES))]  # numpy → float 변환
            pairs.sort(key=lambda x: abs(x[1]), reverse=True)  # 절대값 기준 정렬
            return [{'name': p[0], 'value': float(round(p[1], 4))} for p in pairs[:n]]  # round 후 float 보장

        # shap 버전에 따라 반환 형태가 다름:
        #   구버전: list of arrays [class0(1,F), class1(1,F), class2(1,F)]
        #   신버전: single array (1, F) — Explanation 객체로 반환되기도 함
        if isinstance(shap_vals, list) and len(shap_vals) == 3:
            # 구버전: 클래스별 배열 리스트
            crash_sv = shap_vals[1][0]
            surge_sv = shap_vals[2][0]
        elif isinstance(shap_vals, np.ndarray) and shap_vals.ndim == 3:
            # (1, F, n_classes) 또는 (n_classes, 1, F)
            if shap_vals.shape[0] == 1:
                crash_sv = shap_vals[0, :, 1]
                surge_sv = shap_vals[0, :, 2]
            else:
                crash_sv = shap_vals[1, 0, :]
                surge_sv = shap_vals[2, 0, :]
        elif isinstance(shap_vals, np.ndarray) and shap_vals.ndim == 2:
            # (1, F) — 단일 출력, 클래스 구분 불가 → 동일 값 사용
            crash_sv = shap_vals[0]
            surge_sv = shap_vals[0]
        else:
            # shap.Explanation 객체 등
            sv_arr = np.array(shap_vals.values) if hasattr(shap_vals, 'values') else np.array(shap_vals)
            if sv_arr.ndim == 3 and sv_arr.shape[0] == 1:
                crash_sv = sv_arr[0, :, 1]
                surge_sv = sv_arr[0, :, 2]
            elif sv_arr.ndim == 3:
                crash_sv = sv_arr[1, 0, :]
                surge_sv = sv_arr[2, 0, :]
            else:
                crash_sv = sv_arr.flatten()[:len(ALL_FEATURES)]
                surge_sv = crash_sv

        result['shap_values'] = {
            'crash': _top_shap(crash_sv),
            'surge': _top_shap(surge_sv),
        }

        imp = model.feature_importances_                      # XGBoost feature importance (float32 배열)
        imp_pairs = sorted(zip(ALL_FEATURES, imp), key=lambda x: x[1], reverse=True)[:10]  # 상위 10개
        result['feature_importance'] = [{'name': n, 'value': float(round(float(v), 4))} for n, v in imp_pairs]  # float32 → float 변환
    except Exception as e:
        print(f'  [CrashSurge] SHAP 계산 실패: {e}')
        result['shap_values'] = None
        result['feature_importance'] = None

    print(f'  [CrashSurge] {result["date"]} → '
          f'crash={result["crash_score"]}({result["crash_grade"]}) '
          f'surge={result["surge_score"]}({result["surge_grade"]})')

    return result


def backfill_crash_surge(df_full, model_bundle: dict) -> list[dict]:
    """전체 기간 crash/surge 점수를 일괄 계산하여 DB upsert용 레코드 리스트 반환.

    Args:
        df_full: prepare_datasets()['df_full'] — 날짜 인덱스 + ALL_FEATURES 컬럼
        model_bundle: train_crash_surge() 반환값

    Returns:
        list[dict] — date, crash_score, crash_grade, surge_score, surge_grade, net_score
    """
    model = model_bundle['model']                       # XGBoost 모델
    scaler = model_bundle['scaler']                     # StandardScaler
    platt_surge = model_bundle['platt_surge']            # Platt 캘리브레이터
    crash_rank_values = model_bundle['crash_rank_values']  # 전체 기간 crash raw 분포
    surge_rank_values = model_bundle['surge_rank_values']  # 전체 기간 surge raw 분포

    # 전체 피처를 스케일링 + 추론
    X_all = df_full[ALL_FEATURES].values                 # (N, 46) 피처 행렬
    X_scaled = scaler.transform(X_all)                   # 표준화
    proba_all = model.predict_proba(X_scaled)            # (N, 3) 확률 행렬

    # crash/surge raw 점수 계산
    crash_raw_all = proba_all[:, 1] * 100                # crash raw %
    surge_cal_all = _apply_platt(platt_surge, proba_all[:, 2]) * 100  # Platt 보정 surge %

    # percentile rank 계산 (벡터화)
    crash_pctl_all = np.array([                          # 각 날짜의 crash percentile
        float((crash_rank_values < v).mean()) * 100
        for v in crash_raw_all
    ])
    surge_pctl_all = np.array([                          # 각 날짜의 surge percentile
        float((surge_rank_values < v).mean()) * 100
        for v in surge_cal_all
    ])

    # 레코드 리스트 생성
    records = []                                         # 결과를 담을 리스트
    dates = df_full.index                                # 날짜 인덱스
    for i in range(len(dates)):                          # 전체 기간 순회
        crash_s = round(crash_pctl_all[i], 1)            # crash percentile 반올림
        surge_s = round(surge_pctl_all[i], 1)            # surge percentile 반올림
        records.append({
            'date': str(dates[i].date()),                # 날짜 문자열
            'crash_score': crash_s,                      # 폭락 점수
            'crash_grade': grade(crash_s),               # 폭락 등급
            'surge_score': surge_s,                      # 급등 점수
            'surge_grade': grade(surge_s),               # 급등 등급
            'net_score': round(surge_s - crash_s, 1),    # 순방향 점수 (급등-폭락)
        })

    print(f'  [CrashSurge] 백필 완료: {len(records)}건 ({records[0]["date"]} ~ {records[-1]["date"]})')
    return records
