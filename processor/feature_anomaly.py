"""시장 이상 탐지 (Anomaly Detection) 계산 모듈.

신호 탭(crash_surge) 을 교체하는 descriptive 이상도 측정.

알고리즘:
    - 10 피처 벡터 x_t (noise_regime 8 + yield_curve + VIX 절대값)
    - rolling [t-10y, t-1] 로 historical 평균 μ, 공분산 Σ 추정 (look-ahead 방지)
    - Mahalanobis D²(t) = (x_t - μ)' Σ^-1 (x_t - μ)
    - percentile_10y / percentile_90d = D² 시계열 내 분위수
    - top_contributors = 각 피처의 D² 분해 기여 상위 K개
    - knn_dates = pairwise Mahalanobis 거리 가장 가까운 과거 K개 (최근 90일 제외)

자문 리스크 차단을 위해 출력은 모두 descriptive (관측·거리). 미래 단언 없음.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# ── 설정 (단일 위치 — 변경 시 백필도 같은 값으로 재계산 필요) ─────────────────
NOISE_FEATURES = [
    'fundamental_gap', 'erp_zscore', 'residual_corr',
    'dispersion', 'amihud', 'vix_term', 'hy_spread', 'realized_vol',
]
EXTRA_FEATURES = ['yield_curve', 'vix_abs']                  # noise_regime 외 추가 2개
ALL_FEATURES = NOISE_FEATURES + EXTRA_FEATURES               # 총 10개

ROLLING_YEARS = 10                                           # μ, Σ 추정 윈도우
MIN_HISTORY_DAYS = 252                                       # 최소 1년치는 있어야 D² 계산
PERCENTILE_90D_WINDOW = 90                                   # 단기 분위수 윈도우
KNN_K = 3                                                    # 유사 과거 시점 개수
KNN_GAP_DAYS = 365                                           # 최근 N일은 k-NN 검색에서 제외 ("역사적 유사 시점" 의미 보장 — 90일은 같은 regime 클러스터로 빠짐)
KNN_DIVERSITY_DAYS = 90                                      # 픽 1개당 ±N일 윈도 마스크 — 최소 3개월 간격 보장 (사용자 요청)
KNN_SIGN_AGREE_STRICT = 6                                    # 8개 피처 중 N개 이상 deviation 부호 일치 시 후보
KNN_SIGN_AGREE_RELAXED = 5                                   # strict 후보 < k*3 면 완화
KNN_SIGN_NEUTRAL_TOL = 0.3                                   # |deviation| < N σ 면 부호 무관 일치 처리
TOP_CONTRIBUTORS_K = 3                                       # 상위 기여 피처 개수
MAHAL_RIDGE = 1e-6                                           # Σ 정규화 (ill-conditioning 방지)
REGIME_MA_WINDOW = 200                                       # 시장 강세/하락 regime 판정 — 종가 vs 200영업일 SMA
REGIME_TICKERS = {'us': '^GSPC', 'kr': '^KS11'}              # region 별 시장 인덱스 (regime 판정용)


# ── 데이터 로딩 ────────────────────────────────────────────────────────────────

def _load_noise_features(region: str = 'us') -> pd.DataFrame:
    """noise_regime.feature_values JSONB 에서 8 피처 일별 시계열 로드."""
    from database.repositories import get_client
    client = get_client()
    rows = []
    page_size = 1000
    offset = 0
    while True:
        r = (
            client.table('noise_regime')
            .select('date,feature_values')
            .eq('region', region)
            .order('date', desc=False)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows.extend(r.data or [])
        if not r.data or len(r.data) < page_size:
            break
        offset += page_size
    if not rows:
        return pd.DataFrame()
    parsed = []
    for row in rows:
        fv = row.get('feature_values')
        if isinstance(fv, str):
            try:
                fv = json.loads(fv)
            except Exception:
                continue
        if not isinstance(fv, dict):
            continue
        rec = {'date': row['date']}
        for k in NOISE_FEATURES:
            v = fv.get(k)
            rec[k] = float(v) if v is not None else np.nan
        parsed.append(rec)
    df = pd.DataFrame(parsed)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()

    # 데이터 sanity 필터 — noise_regime 가 종종 hy_spread=0 같은 sentinel 값을 적재
    # (fetch_noise_regime_light 의 캐시 로직 결함). HY 스프레드는 historical 최저 ~1.5%
    # 라 0 이하는 데이터 오류. 그런 행은 panel 에서 제외.
    if 'hy_spread' in df.columns:
        invalid = df['hy_spread'] <= 0.1
        if invalid.any():
            print(f'[Anomaly] noise_regime sentinel rows 제외: {invalid.sum()}건 '
                  f'(hy_spread <= 0.1)')
            df = df.loc[~invalid]
    return df


def _load_extras_yfinance(start: str, end: Optional[str] = None) -> pd.DataFrame:
    """yfinance 에서 ^TNX, ^IRX, ^VIX 일별 close 로드 → yield_curve, vix_abs 계산."""
    import yfinance as yf
    end = end or (date.today() + timedelta(days=1)).isoformat()
    tickers = ['^TNX', '^IRX', '^VIX']
    df = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=False)
    if df.empty:
        return pd.DataFrame(columns=EXTRA_FEATURES)
    close = df['Close'] if isinstance(df.columns, pd.MultiIndex) else df[['Close']]
    if isinstance(df.columns, pd.MultiIndex):
        out = pd.DataFrame({
            'tnx': close['^TNX'] if '^TNX' in close else np.nan,
            'irx': close['^IRX'] if '^IRX' in close else np.nan,
            'vix_abs': close['^VIX'] if '^VIX' in close else np.nan,
        })
    else:
        # single ticker fallback (shouldn't happen with 3 tickers)
        out = pd.DataFrame({'tnx': np.nan, 'irx': np.nan, 'vix_abs': np.nan}, index=close.index)
    out['yield_curve'] = out['tnx'] - out['irx']                 # 10Y - 3M, % 단위
    out.index = pd.to_datetime(out.index).tz_localize(None) if out.index.tz else pd.to_datetime(out.index)
    return out[['yield_curve', 'vix_abs']].dropna(how='all')


def _load_market_regime(start: str, end: Optional[str] = None, region: str = 'us') -> pd.Series:
    """시장 강세장(1) / 하락장(0) 일별 라벨 — 종가 vs 200영업일 SMA.

    SMA 미정의 초기 구간은 NaN. region 별 인덱스(US: ^GSPC, KR: ^KS11) 를 yfinance 로 로드.
    look-ahead 안전: t 시점 라벨은 t 까지의 종가만 사용.
    """
    import yfinance as yf
    end = end or (date.today() + timedelta(days=1)).isoformat()
    ticker = REGIME_TICKERS.get(region, '^GSPC')
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df.empty:
        return pd.Series(dtype=float)
    close = df['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    sma = close.rolling(REGIME_MA_WINDOW).mean()
    regime = (close > sma).astype(float)
    regime[sma.isna()] = np.nan
    if regime.index.tz is not None:
        regime.index = regime.index.tz_localize(None)
    regime.index = pd.to_datetime(regime.index)
    return regime


def _filter_pool_by_regime(knn_pool: pd.DataFrame, today_regime: float,
                           regime_series: pd.Series, min_keep: int = None) -> pd.DataFrame:
    """today regime 과 같은 날짜만 남긴 knn_pool.

    today_regime 이 NaN 또는 regime_series 가 비면 원본 그대로 (200d SMA 미정의 등 fallback).
    필터 후 행 수 < min_keep 이면 원본 반환 — 같은 regime 후보가 너무 적어 매칭 자체가
    실패하는 것보다 mixed regime 이라도 K 개 채우는 쪽이 사용자 효용 큼.
    """
    min_keep = min_keep if min_keep is not None else KNN_K
    if knn_pool.empty or pd.isna(today_regime) or regime_series.empty:
        return knn_pool
    pool_regimes = regime_series.reindex(knn_pool.index, method='ffill', limit=2)
    same = (pool_regimes == today_regime).fillna(False).values
    filtered = knn_pool.loc[same]
    if len(filtered) < min_keep:
        return knn_pool
    return filtered


def build_feature_panel(region: str = 'us') -> pd.DataFrame:
    """8 noise 피처 + 2 추가 피처 = 10 피처 일별 패널 (forward-fill 없음, 결측 그대로).

    region 별 가용 피처가 다를 수 있음 (KR 의 경우 fundamental_gap / vix_term 미산출 →
    100% NaN). 이런 컬럼은 자동 제거해 region 별 동적 피처 차원으로 D² 계산.
    """
    noise = _load_noise_features(region)
    if noise.empty:
        return pd.DataFrame(columns=ALL_FEATURES)
    start = noise.index.min().strftime('%Y-%m-%d')
    extras = _load_extras_yfinance(start)
    panel = noise.join(extras, how='left')
    panel = panel[ALL_FEATURES]
    # region 별 모두-NaN 컬럼 자동 제거 — KR 은 ~8 피처로 차원 축소.
    all_nan_cols = panel.columns[panel.isna().all()].tolist()
    if all_nan_cols:
        print(f'[Anomaly] region={region} all-NaN 피처 제거: {all_nan_cols}')
        panel = panel.drop(columns=all_nan_cols)
    return panel


# ── Mahalanobis 계산 ──────────────────────────────────────────────────────────

def _safe_inv(cov: np.ndarray, ridge: float = MAHAL_RIDGE) -> np.ndarray:
    """공분산 역행렬 — ridge 추가로 ill-conditioning 방지."""
    n = cov.shape[0]
    return np.linalg.pinv(cov + ridge * np.eye(n))


def _mahalanobis_d2(x: np.ndarray, mu: np.ndarray, sig_inv: np.ndarray) -> float:
    """단일 점의 Mahalanobis 거리 제곱."""
    diff = x - mu
    return float(diff @ sig_inv @ diff.T)


def _decompose_d2(x: np.ndarray, mu: np.ndarray, sig_inv: np.ndarray, names: list[str]) -> list[dict]:
    """D² = sum_i [(x-μ)' Σ^-1]_i (x-μ)_i 의 피처별 기여 분해.

    contribution_i = (x_i - μ_i) * (Σ^-1 (x - μ))_i
    이 합이 D² (decomposition 합산은 D² 와 동일).
    """
    diff = x - mu
    weighted = sig_inv @ diff
    contribs = diff * weighted
    return [{'name': n, 'contribution': float(c)} for n, c in zip(names, contribs)]


def _sign_agreement_counts(today_dev: np.ndarray, past_devs: np.ndarray, sigmas: np.ndarray, tol: float = KNN_SIGN_NEUTRAL_TOL) -> np.ndarray:
    """피처별 deviation 부호 일치 개수 (배열 단위 vectorized).

    Args:
        today_dev: 오늘 deviation = today - μ, shape (D,)
        past_devs: 과거일 deviation = past - μ, shape (N, D)
        sigmas: 피처별 std (Σ 대각 sqrt), shape (D,) — z-score 변환용
        tol: |z-deviation| < tol 인 피처는 'near zero' 로 간주, 자동 부호 일치 처리

    Returns:
        (N,) 정수 배열, 각 행에서 today 와 일치한 피처 개수.
    """
    # z-score 변환 (피처 스케일 무관 부호 비교)
    sig_safe = np.where(sigmas > 1e-12, sigmas, 1.0)
    today_z = today_dev / sig_safe
    past_z = past_devs / sig_safe[None, :]

    today_sign = np.sign(today_z)
    today_near_zero = np.abs(today_z) < tol  # (D,)
    past_signs = np.sign(past_z)             # (N, D)
    past_near_zero = np.abs(past_z) < tol    # (N, D)

    same_sign = past_signs == today_sign[None, :]
    near_zero = past_near_zero | today_near_zero[None, :]
    is_match = same_sign | near_zero
    return is_match.sum(axis=1)


def _knn_diversified(knn_pool, x: np.ndarray, sig_inv: np.ndarray, mu: np.ndarray = None,
                     cov: np.ndarray = None, k: int = None, diversity_days: int = None) -> list[dict]:
    """방향 일치 + 시간 다양화 k-NN.

    1. 후보 필터 — past day 의 피처 deviation 부호가 today 와 ≥ KNN_SIGN_AGREE_STRICT 개
       일치하는 행만 (후보 < k*3 이면 RELAXED 로 완화, 그래도 부족하면 거리만).
    2. 후보 중 Mahalanobis 거리 작은 순으로 정렬.
    3. 픽 1건당 ±diversity_days 윈도 마스크 (같은 regime 클러스터 차단).

    Args:
        knn_pool: 과거 후보 DataFrame (index=date, columns=features)
        x: 오늘 feature vector
        sig_inv: Σ⁻¹ (Mahalanobis 거리용)
        mu: 베이스라인 평균 (None 이면 부호 매칭 비활성, 거리만 사용)
        cov: 공분산 행렬 (sigma 추출용; None 이면 sigma=1 가정)
    """
    k = k or KNN_K
    diversity_days = diversity_days or KNN_DIVERSITY_DAYS

    diff_p = knn_pool.values - x
    d_pair = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', diff_p, sig_inv, diff_p), 0))

    # 방향 일치 필터 (mu 가 주어진 경우만)
    if mu is not None:
        sigmas = np.sqrt(np.diag(cov)) if cov is not None else np.ones_like(mu)
        today_dev = x - mu
        past_devs = knn_pool.values - mu
        sign_matches = _sign_agreement_counts(today_dev, past_devs, sigmas)

        # 단계적 임계값
        candidate_indices = None
        for min_match in (KNN_SIGN_AGREE_STRICT, KNN_SIGN_AGREE_RELAXED):
            mask = sign_matches >= min_match
            if mask.sum() >= k * 3:
                candidate_indices = np.where(mask)[0]
                break
        if candidate_indices is None:
            candidate_indices = np.arange(len(knn_pool))   # fallback: 전체
    else:
        candidate_indices = np.arange(len(knn_pool))

    order = candidate_indices[np.argsort(d_pair[candidate_indices])]

    selected: list[dict] = []
    remaining = np.zeros(len(knn_pool), dtype=bool)
    remaining[candidate_indices] = True
    for idx in order:
        if not remaining[idx]:
            continue
        selected.append({
            'date': str(knn_pool.index[idx].date()),
            'distance': round(float(d_pair[idx]), 3),
        })
        if len(selected) >= k:
            break
        pick_dt = knn_pool.index[idx]
        days_diff = np.abs((knn_pool.index - pick_dt).days)
        remaining = remaining & (days_diff > diversity_days)
    return selected


# ── 메인 처리 ──────────────────────────────────────────────────────────────────

def compute_anomaly_timeseries(
    region: str = 'us',
    rolling_years: int = ROLLING_YEARS,
    min_history: int = MIN_HISTORY_DAYS,
) -> pd.DataFrame:
    """역사 전체 D² 시계열 + percentile + contributors + k-NN 계산.

    반환 DataFrame columns:
        date, d2, percentile_10y, percentile_90d, n_history,
        feature_vector(JSON-serializable dict),
        top_contributors(list[dict]), knn_dates(list[dict])

    각 시점 t 에서:
        - μ_t, Σ_t = panel[t - rolling_years : t - 1] 로 추정
        - d2_t = Mahalanobis(panel[t], μ_t, Σ_t)
        - 표본 부족 시 (n_history < min_history) 행 자체 skip
    """
    panel = build_feature_panel(region)
    panel = panel.dropna(how='any')                                  # 10피처 모두 있는 날만
    if panel.empty or len(panel) < min_history:
        return pd.DataFrame()

    rolling_days = int(rolling_years * 365.25)
    rows = []
    cached_d2_history: list[float] = []                              # percentile 빠른 누적 계산용
    cached_d2_dates: list[pd.Timestamp] = []

    print(f'[Anomaly] panel rows={len(panel)} '
          f'range={panel.index.min().date()} ~ {panel.index.max().date()}')

    # 시장 regime 시계열 (강세장=1 / 하락장=0). 200d SMA warmup 위해 panel 시작보다
    # 충분히 앞서서 (400일 — 200영업일 + α) 가격 시계열을 받음.
    regime_start = (panel.index.min() - pd.Timedelta(days=400)).strftime('%Y-%m-%d')
    regime_series = _load_market_regime(regime_start, region=region)

    for i, dt in enumerate(panel.index):
        if i % 250 == 0 and i > 0:
            print(f'  progress {i}/{len(panel)} ({dt.date()})')

        window_start = dt - pd.Timedelta(days=rolling_days)
        hist = panel.loc[(panel.index >= window_start) & (panel.index < dt)]
        if len(hist) < min_history:
            continue

        x = panel.loc[dt].values.astype(float)
        mu = hist.values.mean(axis=0)
        cov = np.cov(hist.values, rowvar=False)
        sig_inv = _safe_inv(cov)
        d2 = _mahalanobis_d2(x, mu, sig_inv)
        if not np.isfinite(d2) or d2 < 0:
            continue

        # contributors (D² 분해)
        contribs = _decompose_d2(x, mu, sig_inv, panel.columns.tolist())
        top = sorted(contribs, key=lambda c: abs(c['contribution']), reverse=True)[:TOP_CONTRIBUTORS_K]

        # percentile_10y: D²(t) 가 hist 윈도우 내 D² 분포에서 차지하는 위치
        # — hist 의 모든 행에 대해 D² 다시 계산하면 비용 큼.
        # 대신 동일 (μ, Σ) 로 hist 내 D² 를 한 번에 계산 (벡터화).
        diff_h = hist.values - mu
        d2_hist = np.einsum('ij,jk,ik->i', diff_h, sig_inv, diff_h)
        d2_hist = d2_hist[np.isfinite(d2_hist) & (d2_hist >= 0)]
        if len(d2_hist) == 0:
            pct_10y = None
        else:
            pct_10y = float((d2_hist < d2).sum()) / len(d2_hist) * 100.0

        # percentile_90d: 최근 90일 D² 분포
        recent_start = dt - pd.Timedelta(days=PERCENTILE_90D_WINDOW)
        recent_idx = [i_ for i_, d in enumerate(cached_d2_dates) if d >= recent_start]
        if recent_idx:
            recent_d2 = np.array([cached_d2_history[i_] for i_ in recent_idx])
            pct_90d = float((recent_d2 < d2).sum()) / len(recent_d2) * 100.0
        else:
            pct_90d = None

        # k-NN: 시장 regime 사전 필터 → 방향 일치 → 거리 + 시간 다양화.
        gap_cutoff = dt - pd.Timedelta(days=KNN_GAP_DAYS)
        knn_pool = hist.loc[hist.index < gap_cutoff]
        if not regime_series.empty:
            today_regime_ser = regime_series.reindex([dt], method='ffill', limit=2)
            today_regime = today_regime_ser.iloc[0] if len(today_regime_ser) else np.nan
            knn_pool = _filter_pool_by_regime(knn_pool, today_regime, regime_series)
        knn = _knn_diversified(knn_pool, x, sig_inv, mu=mu, cov=cov) if len(knn_pool) > 0 else []

        feature_vector = {n: round(float(v), 4) for n, v in zip(panel.columns.tolist(), x)}
        rows.append({
            'date': str(dt.date()),
            'd2': round(d2, 3),
            'percentile_10y': round(pct_10y, 2) if pct_10y is not None else None,
            'percentile_90d': round(pct_90d, 2) if pct_90d is not None else None,
            'feature_vector': feature_vector,
            'top_contributors': [{'name': c['name'], 'contribution': round(c['contribution'], 3)}
                                 for c in top],
            'knn_dates': knn,
            'n_history': int(len(hist)),
        })
        cached_d2_history.append(d2)
        cached_d2_dates.append(dt)

    return pd.DataFrame(rows)


def compute_today_anomaly(region: str = 'us') -> Optional[dict]:
    """가장 최근 일자의 anomaly 단일 row 만 계산 (스케줄러 일별 갱신용).

    백필 결과가 이미 DB 에 있다는 전제 하에, 마지막 1행만 새로 만들어 upsert.
    """
    panel = build_feature_panel(region)
    panel = panel.dropna(how='any')
    if panel.empty:
        return None
    dt = panel.index.max()
    rolling_days = int(ROLLING_YEARS * 365.25)
    window_start = dt - pd.Timedelta(days=rolling_days)
    hist = panel.loc[(panel.index >= window_start) & (panel.index < dt)]
    if len(hist) < MIN_HISTORY_DAYS:
        return None
    x = panel.loc[dt].values.astype(float)
    mu = hist.values.mean(axis=0)
    cov = np.cov(hist.values, rowvar=False)
    sig_inv = _safe_inv(cov)
    d2 = _mahalanobis_d2(x, mu, sig_inv)
    if not np.isfinite(d2) or d2 < 0:
        return None

    contribs = _decompose_d2(x, mu, sig_inv, panel.columns.tolist())
    top = sorted(contribs, key=lambda c: abs(c['contribution']), reverse=True)[:TOP_CONTRIBUTORS_K]
    diff_h = hist.values - mu
    d2_hist = np.einsum('ij,jk,ik->i', diff_h, sig_inv, diff_h)
    d2_hist = d2_hist[np.isfinite(d2_hist) & (d2_hist >= 0)]
    pct_10y = float((d2_hist < d2).sum()) / len(d2_hist) * 100.0 if len(d2_hist) else None

    # percentile_90d 는 DB 에서 최근 90일 D² 가져와 계산
    from database.repositories import fetch_anomaly_history
    recent = fetch_anomaly_history(days=PERCENTILE_90D_WINDOW, region=region)
    if recent:
        recent_d2 = np.array([r['d2'] for r in recent if r.get('d2') is not None])
        pct_90d = float((recent_d2 < d2).sum()) / len(recent_d2) * 100.0 if len(recent_d2) else None
    else:
        pct_90d = None

    gap_cutoff = dt - pd.Timedelta(days=KNN_GAP_DAYS)
    knn_pool = hist.loc[hist.index < gap_cutoff]
    # 시장 regime (강세=1/하락=0) 사전 필터: today 와 같은 regime 인 과거일만 후보로 둠.
    if not knn_pool.empty:
        regime_start = (knn_pool.index.min() - pd.Timedelta(days=400)).strftime('%Y-%m-%d')
        regime_series = _load_market_regime(regime_start, region=region)
        if not regime_series.empty:
            today_regime_ser = regime_series.reindex([dt], method='ffill', limit=2)
            today_regime = today_regime_ser.iloc[0] if len(today_regime_ser) else np.nan
            knn_pool = _filter_pool_by_regime(knn_pool, today_regime, regime_series)
    knn = _knn_diversified(knn_pool, x, sig_inv, mu=mu, cov=cov) if len(knn_pool) > 0 else []

    return {
        'date': str(dt.date()),
        'd2': round(d2, 3),
        'percentile_10y': round(pct_10y, 2) if pct_10y is not None else None,
        'percentile_90d': round(pct_90d, 2) if pct_90d is not None else None,
        'feature_vector': {n: round(float(v), 4) for n, v in zip(panel.columns.tolist(), x)},
        'top_contributors': [{'name': c['name'], 'contribution': round(c['contribution'], 3)}
                             for c in top],
        'knn_dates': knn,
        'n_history': int(len(hist)),
    }
