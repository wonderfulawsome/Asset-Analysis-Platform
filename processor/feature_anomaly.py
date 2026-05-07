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
KNN_GAP_DAYS = 90                                            # 최근 N일은 k-NN 검색에서 제외 (trivial match 방지)
TOP_CONTRIBUTORS_K = 3                                       # 상위 기여 피처 개수
MAHAL_RIDGE = 1e-6                                           # Σ 정규화 (ill-conditioning 방지)


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
    return df.set_index('date').sort_index()


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


def build_feature_panel(region: str = 'us') -> pd.DataFrame:
    """8 noise 피처 + 2 추가 피처 = 10 피처 일별 패널 (forward-fill 없음, 결측 그대로)."""
    noise = _load_noise_features(region)
    if noise.empty:
        return pd.DataFrame(columns=ALL_FEATURES)
    start = noise.index.min().strftime('%Y-%m-%d')
    extras = _load_extras_yfinance(start)
    panel = noise.join(extras, how='left')
    return panel[ALL_FEATURES]


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
        contribs = _decompose_d2(x, mu, sig_inv, ALL_FEATURES)
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

        # k-NN: hist 내에서 (오늘 ↔ 그날) pairwise Mahalanobis 거리 최소 K개
        # gap: 최근 KNN_GAP_DAYS 일은 제외 (trivial match)
        gap_cutoff = dt - pd.Timedelta(days=KNN_GAP_DAYS)
        knn_pool = hist.loc[hist.index < gap_cutoff]
        if len(knn_pool) > 0:
            diff_p = knn_pool.values - x
            d_pair = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', diff_p, sig_inv, diff_p), 0))
            order = np.argsort(d_pair)[:KNN_K]
            knn = [
                {'date': str(knn_pool.index[j].date()), 'distance': round(float(d_pair[j]), 3)}
                for j in order
            ]
        else:
            knn = []

        feature_vector = {n: round(float(v), 4) for n, v in zip(ALL_FEATURES, x)}
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

    contribs = _decompose_d2(x, mu, sig_inv, ALL_FEATURES)
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
    if len(knn_pool) > 0:
        diff_p = knn_pool.values - x
        d_pair = np.sqrt(np.maximum(np.einsum('ij,jk,ik->i', diff_p, sig_inv, diff_p), 0))
        order = np.argsort(d_pair)[:KNN_K]
        knn = [
            {'date': str(knn_pool.index[j].date()), 'distance': round(float(d_pair[j]), 3)}
            for j in order
        ]
    else:
        knn = []

    return {
        'date': str(dt.date()),
        'd2': round(d2, 3),
        'percentile_10y': round(pct_10y, 2) if pct_10y is not None else None,
        'percentile_90d': round(pct_90d, 2) if pct_90d is not None else None,
        'feature_vector': {n: round(float(v), 4) for n, v in zip(ALL_FEATURES, x)},
        'top_contributors': [{'name': c['name'], 'contribution': round(c['contribution'], 3)}
                             for c in top],
        'knn_dates': knn,
        'n_history': int(len(hist)),
    }
