"""Noise vs Signal HMM — 4-state 시장 소음 국면 판별기

노트북 HMM.ipynb Cell 10~14 로직을 production 코드로 변환.
GaussianHMM(4 states) + RobustScaler + noise_score v2 가중치 기반 국면 매핑.

DB 저장 부호 (옛 컨벤션 유지):
    + 양수 = 감정적 (주가가 펀더멘털과 괴리)
    - 음수 = 이성적 (주가가 펀더멘털 반영)
표시 단에서는 repositories.py 의 _flip_noise_record() 가 부호를 뒤집어 사용자에게는
"양수 = 이성, 음수 = 감정" 으로 보이도록 매핑한다 (2026-04-30 도입).
"""

import datetime
import os
import warnings
from itertools import combinations
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings('ignore')

N_STATES = 4
PHASE_NAMES = {
    0: '펀더멘털-주가 일치',
    1: '펀더멘털-주가 일치',
    2: '펀더멘털-주가 불일치',
    3: '펀더멘털-주가 불일치',
}
PHASE_EMOJIS = {0: '🧠', 1: '⚖️', 2: '🌊', 3: '🔥'}


def score_to_regime_name(noise_score: float) -> tuple:
    """noise_score → (regime_id, regime_name) — 옛(저장용) 부호 컨벤션 기준
    score < 0  → 일치 (주가가 펀더멘털 반영)
    score >= 0 → 불일치 (주가가 펀더멘털과 괴리)
    """
    if noise_score < 0:
        return 0, '펀더멘털-주가 일치'
    return 2, '펀더멘털-주가 불일치'


FEATURE_NAMES = [
    'fundamental_gap', 'erp_zscore', 'residual_corr',
    'dispersion', 'amihud', 'vix_term', 'hy_spread',
    'realized_vol',
]

# KR 6-feature: PER 시계열 부재(fundamental_gap=0 평탄) + VKOSPI 단일값(vix_term=1.0 평탄)
# 으로 두 피처가 학습 데이터에서 정보 없는 평탄 시리즈가 됨 → 제외.
# vix_term 가중치 2.0 → realized_vol 흡수, fundamental_gap 0.5 → erp_zscore(abs) 흡수.
FEATURE_NAMES_KR = [
    'erp_zscore', 'residual_corr', 'dispersion',
    'amihud', 'hy_spread', 'realized_vol',
]

# noise_score 가중치 — 양수 = 감정성 (옛 컨벤션, DB 저장용 / repo 단에서 부호 반전)
# abs() 적용 피처: |값|이 클수록 감정성 ↑ (양/음 모두 비정상)
# 직접 적용: 부호가 의미 있는 피처 (corr/amihud/vix/hy/rv)
NOISE_WEIGHTS_US = [
    ('fundamental_gap', 0.5, True),   # abs
    ('erp_zscore',      0.3, True),   # abs
    ('residual_corr',   1.0, False),
    ('dispersion',      0.0, False),
    ('amihud',          0.5, False),
    ('vix_term',        2.0, False),
    ('hy_spread',       1.5, False),
    ('realized_vol',    2.0, False),
]
NOISE_WEIGHTS_KR = [
    ('erp_zscore',      0.5, True),   # 0.3 → 0.5 (fundamental_gap 0.5 흡수)
    ('residual_corr',   1.0, False),
    ('dispersion',      0.0, False),
    ('amihud',          0.5, False),
    ('hy_spread',       1.5, False),
    ('realized_vol',    4.0, False),  # 2.0 → 4.0 (vix_term 2.0 흡수)
]

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models')
# 하위호환 — region 미지정 시 기존 'noise_hmm.pkl' 그대로 사용 (US default).
# region='kr' 은 _kr.pkl 로 분리.
MODEL_PATH = os.path.join(MODEL_DIR, 'noise_hmm.pkl')


def _model_path(region: str = 'us') -> str:
    """region 별 모델 파일 경로. US 는 기존 파일 (하위호환), KR 은 _kr.pkl."""
    if region == 'kr':
        return os.path.join(MODEL_DIR, 'noise_hmm_kr.pkl')
    return MODEL_PATH


def _feature_names(region: str = 'us') -> list[str]:
    return FEATURE_NAMES_KR if region == 'kr' else FEATURE_NAMES


def _noise_weights(region: str = 'us') -> list:
    """region 별 noise_score 가중치 spec — list[(name, weight, use_abs)]."""
    return NOISE_WEIGHTS_KR if region == 'kr' else NOISE_WEIGHTS_US


def _weights_for_features(feat_names: list[str]) -> list:
    """주어진 feature_names 와 동일 순서·길이의 가중치 spec 반환.

    구버전 모델 (feature_names 추정) 호환 — feat_names 길이로 region 결정.
    """
    if len(feat_names) == len(FEATURE_NAMES_KR):
        return NOISE_WEIGHTS_KR
    return NOISE_WEIGHTS_US


def compute_noise_score(means: np.ndarray, region: str = 'us') -> np.ndarray:
    """noise_score v2: 가중치 합 — 양수 = 감정성 (옛 컨벤션, DB 저장용).

    means.shape = (n_samples, n_features). n_features 는 region 따라 8(US) / 6(KR).
    표시 단(_flip_noise_record)에서 부호 반전되어 "양수=이성"으로 클라이언트에 노출.
    """
    weights = _noise_weights(region)
    score = np.zeros(means.shape[0])
    for i, (_name, w, use_abs) in enumerate(weights):
        if w == 0:
            continue
        col = np.abs(means[:, i]) if use_abs else means[:, i]
        score = score + w * col
    return score


def train_hmm(features_df, monthly_bundle: dict = None, region: str = 'us') -> dict:
    """4-state GaussianHMM 학습 → 모델 번들 저장 및 반환.

    Args:
        features_df: pd.DataFrame with FEATURE_NAMES columns (윈저라이징 적용 완료)
        monthly_bundle: compute_monthly_features() 반환값 (경량 파이프라인용 캐시 데이터 포함)
        region: 'us' 또는 'kr' — 모델 파일 분리 (noise_hmm.pkl ↔ noise_hmm_kr.pkl)

    Returns:
        dict with model, scaler, state_to_phase, phase_order, train_month, region,
             feature_names, last_monthly_values, winsor_bounds, amihud_q01, amihud_q99
    """
    feat_names = _feature_names(region)
    # KR 은 fundamental_gap·vix_term 제외 6피처. compute_monthly_features_kr 가
    # 8 컬럼을 만들어도 여기서 region 의 subset 만 학습에 사용.
    X = features_df[feat_names].values
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
            print(f'[NoiseHMM-{region}] 학습 완료 (cov: {cov_type}, '
                  f'{len(feat_names)}피처 × {len(X_scaled)}개월)')
            break
        except (ValueError, np.linalg.LinAlgError):
            if cov_type == 'diag':
                raise

    # noise_score 기반 상태 → 국면 매핑
    noise_scores = compute_noise_score(model.means_, region=region)
    sorted_states = np.argsort(noise_scores)
    state_to_phase = {int(sid): rank for rank, sid in enumerate(sorted_states)}

    # phase_order: phase_order[phase_rank] = hmm_state_id
    phase_order = [int(sid) for sid in sorted_states]

    # ── 경량 파이프라인용 월별 피처 캐시값 추출 ──
    last_monthly = {}                                    # 월별 4피처 최신값 저장용
    winsor_bounds = {}                                   # 윈저라이징 범위 저장용
    amihud_q01 = 0.0                                     # Amihud 하한 기본값
    amihud_q99 = 0.0                                     # Amihud 상한 기본값
    if monthly_bundle is not None:                       # compute_monthly_features 결과가 있으면
        feat_df = monthly_bundle['features']             # 월별 피처 DataFrame
        # 학습에 쓰인 피처만 last_monthly 에 저장 (region 별 6 또는 8개)
        for fname in feat_names:
            if fname in feat_df.columns:
                last_monthly[fname] = float(feat_df[fname].iloc[-1])
        winsor_bounds = monthly_bundle.get('winsor_bounds', {})  # 윈저라이징 범위
        amihud_q01 = monthly_bundle.get('amihud_q01', 0.0)      # Amihud 윈저 하한
        amihud_q99 = monthly_bundle.get('amihud_q99', 0.0)      # Amihud 윈저 상한

    bundle = {
        'model': model,
        'scaler': scaler,
        'state_to_phase': state_to_phase,
        'phase_order': phase_order,
        'train_month': datetime.date.today().strftime('%Y-%m'),
        'region': region,
        'feature_names': feat_names,                     # 추론 시 동일 컬럼·순서 보장용
        'last_monthly_values': last_monthly,
        'winsor_bounds': winsor_bounds,
        'amihud_q01': amihud_q01,
        'amihud_q99': amihud_q99,
    }

    os.makedirs(MODEL_DIR, exist_ok=True)
    path = _model_path(region)
    joblib.dump(bundle, path)
    print(f'[NoiseHMM-{region}] 모델 저장: {path}')

    return bundle


def load_model(region: str = 'us') -> Optional[dict]:
    """저장된 모델 번들 로드. 없으면 None. 구버전 호환 — feature_names 없으면 8-feature US 추정."""
    path = _model_path(region)
    if not os.path.exists(path):
        return None
    try:
        bundle = joblib.load(path)
        # 구버전 (feature_names 없음) → 학습된 모델의 차원으로 역추정
        if 'feature_names' not in bundle:
            try:
                n_feat = bundle['model'].means_.shape[1]
            except Exception:
                n_feat = 8
            if n_feat == 6:
                bundle['feature_names'] = list(FEATURE_NAMES_KR)
            else:
                bundle['feature_names'] = list(FEATURE_NAMES)
            print(f'[NoiseHMM-{region}] 구버전 모델 — feature_names 추정: {n_feat} 피처')
        print(f'[NoiseHMM-{region}] 모델 로드 (학습 월: {bundle.get("train_month", "?")}, '
              f'{len(bundle["feature_names"])} 피처)')
        return bundle
    except Exception as e:
        print(f'[NoiseHMM-{region}] 모델 로드 실패: {e}')
        return None


def predict_regime(daily_features: np.ndarray, model_bundle: dict) -> dict:
    """오늘의 피처 벡터로 국면 예측. 차원은 model_bundle['feature_names'] 길이와 일치.

    Args:
        daily_features: shape (1, n_features) numpy array — n_features = US 8 / KR 6
        model_bundle: train_hmm() 반환값

    Returns:
        {date, regime_id, regime_name, regime_emoji, noise_score, probabilities}
    """
    model = model_bundle['model']
    scaler = model_bundle['scaler']
    state_to_phase = model_bundle['state_to_phase']
    region = model_bundle.get('region', 'us')
    feat_names = model_bundle.get('feature_names') or _feature_names(region)
    weights_spec = _weights_for_features(feat_names)

    daily_scaled = scaler.transform(daily_features)
    proba_raw = model.predict_proba(daily_scaled)[0]  # shape (4,)

    # HMM state 확률 → phase 확률로 변환
    proba_by_phase = {}
    for state_id, prob in enumerate(proba_raw):
        phase_id = state_to_phase[state_id]
        proba_by_phase[phase_id] = proba_by_phase.get(phase_id, 0.0) + float(prob)

    # HMM이 예측한 국면 (이모지용)
    hmm_phase = max(proba_by_phase, key=proba_by_phase.get)

    # noise_score 계산 → score 기반 레짐 이름 결정
    ns = float(compute_noise_score(daily_scaled, region=region)[0])
    pred_phase, pred_name = score_to_regime_name(ns)

    today_str = str(datetime.date.today())
    # HMM 4-state 확률을 2-레짐(일치/불일치)으로 합산
    p_match = sum(proba_by_phase.get(ph, 0.0) for ph in (0, 1))
    p_mismatch = sum(proba_by_phase.get(ph, 0.0) for ph in (2, 3))
    proba_dict = {
        '펀더멘털-주가 일치': round(p_match, 4),
        '펀더멘털-주가 불일치': round(p_mismatch, 4),
    }

    # 피처별 noise_score 기여도 (DB 저장용 옛 컨벤션 — repo 단에서 부호 반전)
    contributions = []
    for i, (fname, w, use_abs) in enumerate(weights_spec):
        sv = float(daily_scaled[0][i])
        contrib = w * abs(sv) if use_abs else w * sv
        contributions.append({
            'name': fname, 'weight': w,
            'value': round(float(daily_features[0][i]), 4),
            'contribution': round(contrib, 4),
        })
    contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)

    feature_values = {fname: round(float(daily_features[0][i]), 4)
                      for i, fname in enumerate(feat_names)}

    result = {
        'date': today_str,
        'regime_id': pred_phase,
        'regime_name': pred_name,
        'regime_emoji': PHASE_EMOJIS[hmm_phase],
        'noise_score': round(ns, 4),
        'probabilities': proba_dict,
        'feature_contributions': contributions,
        'feature_values': feature_values,
    }

    region_tag = model_bundle.get('region', 'us')
    print(f'[NoiseHMM-{region_tag}] {today_str} → {PHASE_EMOJIS[hmm_phase]} {pred_name} (score: {ns:.2f})')

    return result


def backfill_noise_regime(bundle: dict, model_bundle: dict, days: int = 60,
                          region: str = 'us') -> list[dict]:
    """과거 N일간의 noise regime 결과를 일괄 계산하여 반환합니다.

    bundle 내 일별 시계열(residuals, stock_returns, amihud_frames,
    fred_raw/macro_raw, spy_ret)을 각 날짜별 20일 윈도우로 슬라이딩하며
    8피처를 계산 → HMM 예측.

    Args:
        bundle: compute_monthly_features[_kr]() 반환값 (일별 시계열 포함)
        model_bundle: train_hmm() 반환값
        days: 백필할 최근 일수 (기본 60일)
        region: 'us' 또는 'kr' — 종목 리스트와 raw 데이터 키 분기

    Returns:
        list[dict]: 날짜별 regime 결과 리스트
    """
    if region == 'kr':
        from collector.noise_regime_data_kr import (
            SECTOR_STOCKS_KR as SECTOR_STOCKS,
            ALL_STOCKS_KR as ALL_STOCKS,
        )
    else:
        from collector.noise_regime_data import SECTOR_STOCKS, ALL_STOCKS

    features_monthly = bundle['features']
    residuals = bundle['residuals']
    stock_returns = bundle['stock_returns']
    amihud_frames = bundle['amihud_frames']
    # KR bundle 은 'macro_raw' 키, US 는 'fred_raw' — 둘 다 호환되게
    raw_dict = bundle.get('macro_raw') or bundle.get('fred_raw') or {}
    spy_ret = bundle['spy_ret']
    amihud_q01 = bundle['amihud_q01']
    amihud_q99 = bundle['amihud_q99']

    model = model_bundle['model']                  # 학습된 HMM 모델
    scaler = model_bundle['scaler']                # RobustScaler
    state_to_phase = model_bundle['state_to_phase']  # HMM state → phase 매핑
    feat_names = model_bundle.get('feature_names') or _feature_names(region)
    weights_spec = _weights_for_features(feat_names)

    # 기준 날짜 인덱스: SPY 수익률의 최근 N일 (영업일 기준)
    spy_dates = spy_ret.dropna().index[-days:]     # 최근 N 영업일

    # 월별 피처(fundamental_gap, erp_zscore)를 일별로 forward-fill — KR 은 fundamental_gap 미사용
    fg_monthly = features_monthly['fundamental_gap'] if 'fundamental_gap' in features_monthly.columns else None
    ez_monthly = features_monthly['erp_zscore']       # 월별 ERP Z-score

    # ⑥ vix_term 일별 시계열 (US: VIX/VIX3M, KR: VKOSPI/VKOSPI 60D)
    # 빈 Series 도 DatetimeIndex 보장 — RangeIndex 와 Timestamp 비교 시 TypeError 회피
    _empty_dt = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    if region == 'kr':
        vk = raw_dict.get('vkospi')
        if vk is not None and not vk.empty:
            vk_series = vk['vkospi'].dropna()
            vk_60d = vk_series.rolling(60, min_periods=20).mean()
            vix_term_daily = (vk_series / vk_60d).replace([np.inf, -np.inf], np.nan).dropna()
        else:
            vix_term_daily = _empty_dt
        vix_daily = vix_term_daily
        vix3m_daily = pd.Series(1.0, index=vix_term_daily.index) if len(vix_term_daily) > 0 else _empty_dt
    else:
        vix_daily = raw_dict['vix']['vix'].dropna() if 'vix' in raw_dict else _empty_dt
        vix3m_daily = raw_dict['vix3m']['vix3m'].dropna() if 'vix3m' in raw_dict else _empty_dt
    hy_df = raw_dict.get('hy_spread')
    if hy_df is not None and not hy_df.empty:
        hy_daily = hy_df['hy_spread'].dropna()
    else:
        hy_daily = _empty_dt

    # Amihud 일별 평균 (전 종목 합산)
    amihud_daily_list = []                             # 티커별 Amihud 시리즈 모음
    for ticker, df_t in amihud_frames.items():         # 5개 메가캡 순회
        oc_ret = np.log(df_t['Close'] / df_t['Open']).abs()  # 시가→종가 로그 수익률 절대값
        dollar_vol = df_t['Close'] * df_t['Volume']   # 달러 거래량
        ami_t = oc_ret / dollar_vol.replace(0, np.nan)  # Amihud 비유동성
        amihud_daily_list.append(ami_t)                # 리스트에 추가
    amihud_avg_daily = pd.concat(amihud_daily_list, axis=1).mean(axis=1).dropna()  # 5종목 평균

    records = []                                       # 백필 결과 저장 리스트
    for date in spy_dates:                             # 각 영업일별 반복
        try:
            date_str = str(date.date()) if hasattr(date, 'date') else str(date)[:10]  # 날짜 문자열 변환

            # ① fundamental_gap: 해당 월 이전 최신 월별 값 (KR 은 미사용 — None)
            if fg_monthly is not None:
                fg_before = fg_monthly[fg_monthly.index <= date]
                fg_val = float(fg_before.iloc[-1]) if len(fg_before) > 0 else 0.0
            else:
                fg_val = 0.0

            # ② erp_zscore: 동일 로직
            ez_before = ez_monthly[ez_monthly.index <= date]  # 해당 날짜 이전 월별 값
            ez_val = float(ez_before.iloc[-1]) if len(ez_before) > 0 else 0.0  # 마지막 값 사용

            # ③ residual_corr: 해당 날짜 기준 20일 윈도우
            resid_before = residuals[residuals.index <= date].iloc[-20:]  # 20일 잔차
            pair_corrs = []                            # 페어와이즈 상관 저장
            for sector, stocks in SECTOR_STOCKS.items():  # 5개 섹터 순회
                avail = [s for s in stocks if s in resid_before.columns]  # 사용 가능 종목
                if len(avail) < 2:                     # 2개 미만이면 건너뜀
                    continue
                for s1, s2 in combinations(avail, 2):  # 모든 페어 조합
                    c = resid_before[s1].corr(resid_before[s2])  # 상관계수
                    pair_corrs.append(c)               # 추가
            rc_val = float(np.nanmean(pair_corrs)) if pair_corrs else 0.0  # 평균 상관

            # ④ dispersion: 해당 날짜 기준 20일 횡단면 std 평균
            avail_stocks = [s for s in ALL_STOCKS if s in stock_returns.columns]  # 사용 가능 종목
            ret_before = stock_returns[avail_stocks][stock_returns.index <= date].iloc[-20:]  # 20일 수익률
            disp_val = float(ret_before.std(axis=1).mean()) if len(ret_before) > 0 else 0.0  # 평균 분산

            # ⑤ amihud: 해당 날짜 기준 20일
            ami_before = amihud_avg_daily[amihud_avg_daily.index <= date].iloc[-20:]  # 20일 Amihud
            log_ami = np.log(ami_before.mean() + 1e-15) if len(ami_before) > 0 else 0.0  # 로그 변환
            ami_val = float(np.clip(log_ami, amihud_q01, amihud_q99))  # 윈저라이징

            # ⑥ vix_term: 해당 날짜 기준 최신 VIX/VIX3M (빈 시리즈면 1.0 fallback)
            if len(vix_daily) > 0 and len(vix3m_daily) > 0:
                vix_before = vix_daily[vix_daily.index <= date]
                vix3m_before = vix3m_daily[vix3m_daily.index <= date]
                if len(vix_before) > 0 and len(vix3m_before) > 0:
                    vt_val = float(vix_before.iloc[-1]) / float(vix3m_before.iloc[-1])
                else:
                    vt_val = 1.0
            else:
                vt_val = 1.0

            # ⑦ hy_spread: 해당 날짜 기준 최신값 (빈 시리즈면 0.0)
            if len(hy_daily) > 0:
                hy_before = hy_daily[hy_daily.index <= date]
                hy_val = float(hy_before.iloc[-1]) if len(hy_before) > 0 else 0.0
            else:
                hy_val = 0.0

            # ⑧ realized_vol: 해당 날짜 기준 20일 SPY 변동성
            spy_before = spy_ret[spy_ret.index <= date].iloc[-20:]  # 20일 SPY 수익률
            rv_val = float(spy_before.std() * np.sqrt(252)) if len(spy_before) > 0 else 0.0  # 연율화 변동성

            # 피처 벡터 구성 — region 따라 8(US) / 6(KR)
            full_values = {
                'fundamental_gap': fg_val,
                'erp_zscore':      ez_val,
                'residual_corr':   rc_val,
                'dispersion':      disp_val,
                'amihud':          ami_val,
                'vix_term':        vt_val,
                'hy_spread':       hy_val,
                'realized_vol':    rv_val,
            }
            feat_vec = np.array([[full_values[n] for n in feat_names]])  # (1, n_features)

            # HMM 예측
            feat_scaled = scaler.transform(feat_vec)   # 스케일링
            proba_raw = model.predict_proba(feat_scaled)[0]  # 상태 확률 (4,)

            # 상태 확률 → 국면 확률 변환
            proba_by_phase = {}                        # 국면별 확률
            for state_id, prob in enumerate(proba_raw):  # 4개 상태 순회
                phase_id = state_to_phase[state_id]    # 국면 ID 변환
                proba_by_phase[phase_id] = proba_by_phase.get(phase_id, 0.0) + float(prob)  # 누적

            hmm_phase = max(proba_by_phase, key=proba_by_phase.get)  # HMM 예측 국면 (이모지용)
            ns = float(compute_noise_score(feat_scaled, region=region)[0])  # noise_score 계산
            pred_phase, pred_name = score_to_regime_name(ns)  # score 기반 레짐 이름 결정

            # HMM 4-state 확률을 2-레짐(일치/불일치)으로 합산
            p_match = sum(proba_by_phase.get(ph, 0.0) for ph in (0, 1))
            p_mismatch = sum(proba_by_phase.get(ph, 0.0) for ph in (2, 3))
            proba_dict = {
                '펀더멘털-주가 일치': round(p_match, 4),
                '펀더멘털-주가 불일치': round(p_mismatch, 4),
            }

            # 피처 기여도 계산 (DB 저장용 옛 컨벤션 — repo 단에서 부호 반전)
            contributions = []
            for i, (fname, w, use_abs) in enumerate(weights_spec):
                sv = float(feat_scaled[0][i])
                contrib = w * abs(sv) if use_abs else w * sv
                contributions.append({
                    'name': fname, 'weight': w,
                    'value': round(float(feat_vec[0][i]), 4),
                    'contribution': round(contrib, 4),
                })
            contributions.sort(key=lambda x: abs(x['contribution']), reverse=True)

            feature_values = {fname: round(float(feat_vec[0][i]), 4)
                              for i, fname in enumerate(feat_names)}

            records.append({                           # 결과 레코드 추가
                'date': date_str,
                'regime_id': pred_phase,
                'regime_name': pred_name,
                'regime_emoji': PHASE_EMOJIS[hmm_phase],
                'noise_score': round(ns, 4),
                'probabilities': proba_dict,
                'feature_contributions': contributions,
                'feature_values': feature_values,
            })
        except Exception as e:
            print(f'[NoiseHMM-Backfill] {date} 건너뜀: {e}')  # 개별 날짜 실패 시 계속
            continue

    print(f'[NoiseHMM-Backfill-{region}] {len(records)}건 계산 완료')
    return records
