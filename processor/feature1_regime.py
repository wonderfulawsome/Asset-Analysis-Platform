"""Noise vs Signal HMM — 4-state 시장 소음 국면 판별기

노트북 HMM.ipynb Cell 10~14 로직을 production 코드로 변환.
GaussianHMM(4 states) + RobustScaler + noise_score v2 가중치 기반 국면 매핑.
"""

import datetime
import os
import warnings
from typing import Optional

import joblib
import numpy as np
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings('ignore')

N_STATES = 4
PHASE_NAMES = {
    0: '펀더멘털 반영',
    1: '펀더멘털 약반영',
    2: '센티멘트 약반영',
    3: '센티멘트 지배',
}
PHASE_EMOJIS = {0: '🧠', 1: '⚖️', 2: '🌊', 3: '🔥'}

FEATURE_NAMES = [
    'fundamental_gap', 'erp_zscore', 'residual_corr',
    'dispersion', 'amihud', 'vix_term', 'hy_spread',
    'realized_vol',
]

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
MODEL_PATH = os.path.join(MODEL_DIR, 'noise_hmm.pkl')


def compute_noise_score(means: np.ndarray) -> np.ndarray:
    """noise_score v2: 상관 기반 가중치.

    피처 순서: fundamental_gap, erp_zscore, residual_corr,
              dispersion, amihud, vix_term, hy_spread, realized_vol
    """
    return (
        0.5 * np.abs(means[:, 0])   # fundamental_gap
      + 0.3 * np.abs(means[:, 1])   # erp_zscore
      + 1.0 * means[:, 2]           # residual_corr
      # dispersion 제거 (가중치 0)
      + 0.5 * means[:, 4]           # amihud
      + 2.0 * means[:, 5]           # vix_term
      + 1.5 * means[:, 6]           # hy_spread
      + 2.0 * means[:, 7]           # realized_vol
    )


def train_hmm(features_df) -> dict:
    """4-state GaussianHMM 학습 → 모델 번들 저장 및 반환.

    Args:
        features_df: pd.DataFrame with FEATURE_NAMES columns (윈저라이징 적용 완료)

    Returns:
        dict with model, scaler, state_to_phase, phase_order, train_month
    """
    X = features_df[FEATURE_NAMES].values
    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    for cov_type in ('full', 'diag'):
        try:
            model = GaussianHMM(
                n_components=N_STATES,
                covariance_type=cov_type,
                n_iter=200,
                random_state=42,
            )
            model.fit(X_scaled)
            print(f'[NoiseHMM] 학습 완료 (cov: {cov_type}, 데이터: {len(X_scaled)}개월)')
            break
        except (ValueError, np.linalg.LinAlgError):
            if cov_type == 'diag':
                raise

    # noise_score 기반 상태 → 국면 매핑
    noise_scores = compute_noise_score(model.means_)
    sorted_states = np.argsort(noise_scores)
    state_to_phase = {int(sid): rank for rank, sid in enumerate(sorted_states)}

    # phase_order: phase_order[phase_rank] = hmm_state_id
    phase_order = [int(sid) for sid in sorted_states]

    bundle = {
        'model': model,
        'scaler': scaler,
        'state_to_phase': state_to_phase,
        'phase_order': phase_order,
        'train_month': datetime.date.today().strftime('%Y-%m'),
    }

    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(bundle, MODEL_PATH)
    print(f'[NoiseHMM] 모델 저장: {MODEL_PATH}')

    return bundle


def load_model() -> Optional[dict]:
    """저장된 모델 번들 로드. 없으면 None."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        bundle = joblib.load(MODEL_PATH)
        print(f'[NoiseHMM] 모델 로드 (학습 월: {bundle.get("train_month", "?")})')
        return bundle
    except Exception as e:
        print(f'[NoiseHMM] 모델 로드 실패: {e}')
        return None


def predict_regime(daily_features: np.ndarray, model_bundle: dict) -> dict:
    """오늘의 8피처 벡터로 국면 예측.

    Args:
        daily_features: shape (1, 8) numpy array
        model_bundle: train_hmm() 반환값

    Returns:
        {date, regime_id, regime_name, regime_emoji, noise_score, probabilities}
    """
    model = model_bundle['model']
    scaler = model_bundle['scaler']
    state_to_phase = model_bundle['state_to_phase']

    daily_scaled = scaler.transform(daily_features)
    proba_raw = model.predict_proba(daily_scaled)[0]  # shape (4,)

    # HMM state 확률 → phase 확률로 변환
    proba_by_phase = {}
    for state_id, prob in enumerate(proba_raw):
        phase_id = state_to_phase[state_id]
        proba_by_phase[phase_id] = proba_by_phase.get(phase_id, 0.0) + float(prob)

    pred_phase = max(proba_by_phase, key=proba_by_phase.get)

    # noise_score 계산 (오늘 피처 기준)
    ns = float(compute_noise_score(daily_scaled)[0])

    today_str = str(datetime.date.today())
    proba_dict = {PHASE_NAMES[ph]: round(proba_by_phase.get(ph, 0.0), 4) for ph in range(N_STATES)}

    # 피처별 noise_score 기여도 계산
    noise_weights = [0.5, 0.3, 1.0, 0.0, 0.5, 2.0, 1.5, 2.0]
    contributions = []
    for i, fname in enumerate(FEATURE_NAMES):
        w = noise_weights[i]
        sv = float(daily_scaled[0][i])
        contrib = w * abs(sv) if i in (0, 1) else w * sv
        contributions.append({
            'name': fname, 'weight': w,
            'value': round(float(daily_features[0][i]), 4),
            'contribution': round(contrib, 4),
        })
    contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)

    feature_values = {fname: round(float(daily_features[0][i]), 4)
                      for i, fname in enumerate(FEATURE_NAMES)}

    result = {
        'date': today_str,
        'regime_id': pred_phase,
        'regime_name': PHASE_NAMES[pred_phase],
        'regime_emoji': PHASE_EMOJIS[pred_phase],
        'noise_score': round(ns, 4),
        'probabilities': proba_dict,
        'feature_contributions': contributions,
        'feature_values': feature_values,
    }

    print(f'[NoiseHMM] {today_str} → {PHASE_EMOJIS[pred_phase]} {PHASE_NAMES[pred_phase]} '
          f'({proba_by_phase[pred_phase]*100:.0f}%)')

    return result
