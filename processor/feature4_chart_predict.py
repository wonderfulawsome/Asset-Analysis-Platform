"""5-모델 앙상블 ETF 30일 주가 예측 (스케줄러 배치 실행용).

XGBoost + CatBoost + RandomForest + Ridge + SVR 앙상블로
16개 ETF 티커별 30일 영업일 예측을 수행한다.
OOS sigma로 현실적 신뢰구간을 생성한다.
"""

import datetime
import json
import os
import time
import joblib
import numpy as np
import pandas as pd
import yfinance as yf
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.svm import SVR
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer

try:
    from catboost import CatBoostRegressor
    HAS_CATBOOST = True
except ImportError:
    HAS_CATBOOST = False

from arch import arch_model

CHART_TICKERS = ['SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VOO', 'SOXX', 'SMH',
                 'XLK', 'XLF', 'XLE', 'XLV', 'ARKK', 'GLD', 'TLT', 'SCHD']

# 5-모델 앙상블 직렬화 위치 — Stage 1+2 학습/추론 분리
CHART_MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models', 'chart_models')


def _save_chart_models(models, feature_cols, ticker):
    """5-모델 앙상블 + 피처 컬럼 + 학습 시각을 .pkl 로 저장."""
    os.makedirs(CHART_MODELS_DIR, exist_ok=True)
    bundle = {
        'models': models,
        'feature_cols': feature_cols,
        'trained_at': datetime.datetime.utcnow().isoformat(),
    }
    path = os.path.join(CHART_MODELS_DIR, f'{ticker}.pkl')
    joblib.dump(bundle, path)


def _load_chart_models(ticker):
    """저장된 5-모델 앙상블 load. 없으면 (None, None)."""
    path = os.path.join(CHART_MODELS_DIR, f'{ticker}.pkl')
    if not os.path.exists(path):
        return None, None
    try:
        bundle = joblib.load(path)
        return bundle['models'], bundle['feature_cols']
    except Exception as e:
        print(f'[chart_predict] {ticker} .pkl load 실패: {e}')
        return None, None


def _rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def build_features_v2(close):
    feat = pd.DataFrame(index=close.index)

    for d in [1, 2, 3, 5, 10, 20]:
        feat[f'ret_{d}d'] = np.log(close / close.shift(d))

    for w in [5, 20, 60, 120, 200]:
        feat[f'sma{w}_ratio'] = close / close.rolling(w).mean()

    feat['rsi_14'] = _rsi(close, 14)

    log_ret = np.log(close / close.shift(1))
    feat['vol_5d'] = log_ret.rolling(5).std() * np.sqrt(252)
    feat['vol_20d'] = log_ret.rolling(20).std() * np.sqrt(252)
    feat['vol_ratio'] = feat['vol_5d'] / feat['vol_20d']

    feat['drawdown_60d'] = close / close.rolling(60).max() - 1

    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20
    feat['bb_position'] = (close - bb_lower) / (bb_upper - bb_lower)

    feat['mean_revert_200'] = (close / close.rolling(200).mean()) - 1

    feat['roc_10'] = close.pct_change(10)
    feat['roc_20'] = close.pct_change(20)

    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9).mean()
    feat['macd_hist'] = (macd - macd_signal) / close

    feat['sma60_120_ratio'] = close.rolling(60).mean() / close.rolling(120).mean()
    feat['ret_60d'] = np.log(close / close.shift(60))

    return feat


def _train_models(X, y):
    """5개 모델을 학습하여 리스트로 반환한다."""
    models = []

    m_xgb = xgb.XGBRegressor(n_estimators=300, max_depth=4, learning_rate=0.05,
                              subsample=0.8, colsample_bytree=0.8, random_state=42)
    m_xgb.fit(X, y, verbose=False)
    models.append(m_xgb)

    if HAS_CATBOOST:
        m_cb = CatBoostRegressor(iterations=300, depth=4, learning_rate=0.05,
                                 subsample=0.8, random_seed=42, verbose=0)
        m_cb.fit(X, y)
        models.append(m_cb)

    m_rf = RandomForestRegressor(n_estimators=300, max_depth=8, min_samples_leaf=5,
                                 max_features=0.7, random_state=42, n_jobs=-1)
    m_rf.fit(X, y)
    models.append(m_rf)

    m_ridge = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), Ridge(alpha=1.0))
    m_ridge.fit(X, y)
    models.append(m_ridge)

    m_svr = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(),
                          SVR(kernel='rbf', C=1.0, epsilon=0.001))
    m_svr.fit(X, y)
    models.append(m_svr)

    return models


def _safe_float(v):
    """NaN/Inf를 None으로 변환하여 JSON 직렬화 안전하게 처리."""
    if v is None:
        return None
    f = float(v)
    if np.isnan(f) or np.isinf(f):
        return None
    return f


def _recursive_forecast(models, close_history, n_days, sigma, feature_cols):
    """5-모델 평균 앙상블 재귀 예측 (변동성 3배 증폭).

    EMA 스무딩(α=0.3) + 3일 이동평균 후처리로 톱니 패턴 방지.
    GARCH 미사용 — 단순 3배 증폭만 사용.
    """
    hist = close_history.copy()
    raw_predictions = []
    last_date = hist.index[-1]
    start_price = float(close_history.iloc[-1])

    # EMA 스무딩 상태 (방향 플리핑 억제)
    ema_ret = 0.0
    alpha = 0.3  # 낮을수록 더 부드러움

    for k in range(1, n_days + 1):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values

        # NaN 피처를 0으로 대체하여 예측 안정성 확보
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)

        preds = [m.predict(last_feat)[0] for m in models]
        raw_ret = np.mean(preds)

        # 변동성 3배 증폭
        scaled_ret = raw_ret * 3.0

        # EMA 스무딩: 재귀 피드백에 의한 지그재그 방지
        ema_ret = alpha * scaled_ret + (1 - alpha) * ema_ret
        pred_ret = float(np.clip(ema_ret, -0.03, 0.03))  # 일일 ±3%

        current_price = float(hist.iloc[-1])
        next_price = current_price * np.exp(pred_ret)

        # 누적 가격 범위 제한: 시작가 대비 ±30%
        next_price = np.clip(next_price, start_price * 0.7, start_price * 1.3)

        margin = 1.28 * sigma * np.sqrt(k)
        lower = current_price * np.exp(pred_ret - margin)
        upper = current_price * np.exp(pred_ret + margin)
        # 신뢰구간도 범위 제한
        lower = max(lower, start_price * 0.5)
        upper = min(upper, start_price * 1.5)

        next_date = last_date + pd.tseries.offsets.BDay(k)
        raw_predictions.append({
            'date': str(next_date.date()),
            'yhat': next_price,
            'lower': lower,
            'upper': upper,
        })
        hist = pd.concat([hist, pd.Series([next_price], index=[next_date])])

    # 최종 스무딩: 3일 이동평균으로 잔여 진동 제거
    yhats = [p['yhat'] for p in raw_predictions]
    for i in range(1, len(yhats) - 1):
        yhats[i] = (yhats[i - 1] + yhats[i] + yhats[i + 1]) / 3.0

    predictions = []
    for i, p in enumerate(raw_predictions):
        predictions.append({
            'date': p['date'],
            'yhat': _safe_float(round(yhats[i], 2)),
            'lower': _safe_float(round(p['lower'], 2)),
            'upper': _safe_float(round(p['upper'], 2)),
        })

    return predictions


# 변동성이 큰 ETF는 범위 제한을 넉넉하게
_HIGH_VOL_TICKERS = {'ARKK', 'SOXX', 'SMH', 'XLE', 'IWM'}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1+2: GJR-GARCH(1,1,1) + Skew-t + Filtered Historical Simulation
# ─────────────────────────────────────────────────────────────────────────────
# 노트북 검증 결과 (forecast_gjr_garch_fhs_experiment.ipynb):
#   - 89 시점 walk-forward p05 coverage 93.3% (이상 95% 거의 도달)
#   - prob_down_5pct 신호는 약함 → mean 강조 X, 분위수 강조
#   - hard clipping/scaling 모두 제거 — FHS 가 자연 변동성 표현
def _garch_skewt_fhs_forecast(models, close_history, n_days, feature_cols, ticker='SPY',
                                n_sims=1000, garch_window=252, sanity_clip=0.10):
    """GJR-GARCH(1,1,1) + Skew-t + FHS Monte Carlo 30일 예측.

    Args:
        models: 5-모델 앙상블 (mean path μ̂ 산출용)
        close_history: 종가 시계열 (학습 데이터 전체)
        n_days: 예측 일수 (30)
        feature_cols: build_features_v2 의 컬럼명
        ticker: 정보용
        n_sims: Monte Carlo path 개수 (기본 1000)
        garch_window: GJR-GARCH 적합 윈도우 (기본 252일 = 1년)
        sanity_clip: 일별 log-return clip 한계 (기본 ±10%, 극단치 방어용)

    Returns:
        dict with:
          - 'forecast': list[{date, mean, median, p05, p10, p90, p95}] × n_days
          - 'sample_paths': list[list[float]] (30개 샘플 가격 path × n_days)
          - 'metrics': {expected_return_30d, var_5pct_30d, var_10pct_30d,
                        prob_up_30d, prob_down_5pct_30d, prob_down_10pct_30d}
          - 'predicted': legacy [{date, yhat, lower, upper}] (하위 호환, p10~p90)
          - 'metadata': {model, garch_window_days, n_simulations, version}
    """
    from arch import arch_model

    hist = close_history.copy()
    last_date = hist.index[-1]
    S0 = float(hist.iloc[-1])

    # ── 1) Mean path μ̂ — 5-모델 앙상블 recursive forecast (hard clip 제거)
    mu_path = []
    for k in range(n_days):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)
        preds = [m.predict(last_feat)[0] for m in models]
        raw_ret = float(np.mean(preds))
        # sanity clip — 모델 outlier prediction 방어 (production 안전)
        raw_ret = float(np.clip(raw_ret, -sanity_clip, sanity_clip))
        mu_path.append(raw_ret)
        next_price = float(hist.iloc[-1]) * np.exp(raw_ret)
        next_date = last_date + pd.tseries.offsets.BDay(k + 1)
        hist = pd.concat([hist, pd.Series([next_price], index=[next_date])])

    mu_path = np.array(mu_path)
    future_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=n_days)

    # ── 2) GJR-GARCH(1,1,1) + Skew-t fit on 1년 윈도우
    try:
        log_ret_pct = (np.log(close_history / close_history.shift(1)).dropna()) * 100
        log_ret_window = log_ret_pct.iloc[-garch_window:]
        am = arch_model(log_ret_window, vol='Garch', p=1, o=1, q=1,
                        mean='Zero', dist='skewt')
        res = am.fit(disp='off', show_warning=False)

        std_resid = (res.resid / res.conditional_volatility).dropna().values
        omega = res.params['omega']
        alpha = res.params.get('alpha[1]', 0.0)
        gamma = res.params.get('gamma[1]', 0.0)
        beta = res.params['beta[1]']
        last_var = float(res.conditional_volatility.iloc[-1] ** 2)
        last_eps = float(res.resid.iloc[-1])
    except Exception as e:
        # GARCH 적합 실패 시 fallback: 최근 60일 실현 변동성으로 정규 분포 가정
        print(f'[chart_predict] {ticker} GARCH 적합 실패, fallback: {e}')
        log_ret = np.log(close_history / close_history.shift(1)).dropna()
        sigma_fallback = float(log_ret.tail(60).std()) * 100
        std_resid = np.random.standard_normal(500)
        omega, alpha, gamma, beta = sigma_fallback ** 2 * 0.05, 0.1, 0.1, 0.85
        last_var = sigma_fallback ** 2
        last_eps = 0.0

    # ── 3) FHS Monte Carlo n_sims path
    rng = np.random.default_rng(42)
    paths = np.zeros((n_sims, n_days))
    for s in range(n_sims):
        var_t, eps_t = last_var, last_eps
        for h in range(n_days):
            I = 1.0 if eps_t < 0 else 0.0
            var_t = omega + alpha * eps_t**2 + gamma * eps_t**2 * I + beta * var_t
            z = rng.choice(std_resid)
            eps_t = np.sqrt(max(var_t, 1e-9)) * z
            day_ret = mu_path[h] + eps_t / 100.0
            paths[s, h] = float(np.clip(day_ret, -sanity_clip, sanity_clip))

    price_paths = S0 * np.exp(np.cumsum(paths, axis=1))

    # ── 4) 분위수 산출
    p05 = np.percentile(price_paths, 5, axis=0)
    p10 = np.percentile(price_paths, 10, axis=0)
    p50 = np.percentile(price_paths, 50, axis=0)
    p90 = np.percentile(price_paths, 90, axis=0)
    p95 = np.percentile(price_paths, 95, axis=0)
    mean_path_price = price_paths.mean(axis=0)

    forecast = []
    legacy_predicted = []
    for i, d in enumerate(future_dates):
        date_str = str(d.date())
        forecast.append({
            'date': date_str,
            'mean': _safe_float(round(mean_path_price[i], 2)),
            'median': _safe_float(round(p50[i], 2)),
            'p05': _safe_float(round(p05[i], 2)),
            'p10': _safe_float(round(p10[i], 2)),
            'p90': _safe_float(round(p90[i], 2)),
            'p95': _safe_float(round(p95[i], 2)),
        })
        # 하위 호환 — yhat=median, lower=p10, upper=p90 (80% 신뢰)
        legacy_predicted.append({
            'date': date_str,
            'yhat': _safe_float(round(p50[i], 2)),
            'lower': _safe_float(round(p10[i], 2)),
            'upper': _safe_float(round(p90[i], 2)),
        })

    # ── 5) Sample paths (30개만 직렬화 — payload 크기 관리)
    sample_idx = rng.choice(n_sims, min(30, n_sims), replace=False)
    sample_paths = [
        [_safe_float(round(v, 2)) for v in price_paths[i].tolist()]
        for i in sample_idx
    ]

    # ── 6) Metrics
    last_prices = price_paths[:, -1]
    ret = last_prices / S0 - 1
    metrics = {
        'expected_return_30d': _safe_float(round(float(np.median(ret)), 4)),
        'var_5pct_30d': _safe_float(round(float(np.percentile(ret, 5)), 4)),
        'var_10pct_30d': _safe_float(round(float(np.percentile(ret, 10)), 4)),
        'prob_up_30d': _safe_float(round(float((last_prices > S0).mean()), 4)),
        'prob_down_5pct_30d': _safe_float(round(float((ret < -0.05).mean()), 4)),
        'prob_down_10pct_30d': _safe_float(round(float((ret < -0.10).mean()), 4)),
    }

    return {
        'forecast': forecast,
        'sample_paths': sample_paths,
        'metrics': metrics,
        'predicted': legacy_predicted,
        'metadata': {
            'model': 'XGB+CatBoost+RF+Ridge+SVR ensemble + GJR-GARCH(1,1,1)-SkewT + FHS',
            'garch_window_days': garch_window,
            'n_simulations': n_sims,
            'version': '2.0.0',
        },
    }


def _garch_forecast(models, close_history, n_days, feature_cols, ticker='SPY'):
    """GARCH(1,1) 기반 재귀 예측 — 전체 ETF 공용.

    앙상블 모델의 평균 수익률 예측을 GARCH(1,1) σ로 스케일링하되,
    EMA 스무딩으로 방향 연속성을 확보하여 지그재그 예측을 방지한다.
    (기존 sign-only 방식은 raw_ret이 작을 때 부호가 쉽게 뒤집혀 톱니 패턴 발생)
    """
    hist = close_history.copy()
    predictions = []
    last_date = hist.index[-1]
    start_price = float(close_history.iloc[-1])

    # 티커별 범위 제한 설정
    if ticker.upper() in _HIGH_VOL_TICKERS:
        price_band = 0.25   # ±25%
        ci_band = 0.40       # 신뢰구간 ±40%
        daily_clip = 0.04    # 일일 ±4% (기존 5% → 4%, 스무딩으로 보정)
    elif ticker.upper() in {'SPY', 'VOO', 'VTI', 'DIA', 'SCHD'}:
        price_band = 0.15   # ±15% (대형 안정)
        ci_band = 0.30
        daily_clip = 0.025   # 일일 ±2.5% (기존 3% → 2.5%)
    else:
        price_band = 0.20   # ±20% (기본)
        ci_band = 0.35
        daily_clip = 0.03    # 일일 ±3% (기존 4% → 3%)

    # --- GARCH(1,1) 적합 ---
    log_ret = (np.log(close_history / close_history.shift(1)).dropna()) * 100  # % 스케일
    garch_sigma_daily = []

    try:
        am = arch_model(log_ret, vol='Garch', p=1, q=1, mean='Zero', dist='t')
        res = am.fit(disp='off', show_warning=False)
        # n_days 만큼 조건부 분산 예측
        fcast = res.forecast(horizon=n_days, reindex=False)
        # variance → daily σ (% → 소수)
        for k in range(n_days):
            var_k = fcast.variance.iloc[0, k]
            garch_sigma_daily.append(np.sqrt(var_k) / 100.0)
    except Exception:
        # GARCH 적합 실패 시 최근 20일 실현 변동성 사용
        raw_ret = np.log(close_history / close_history.shift(1)).dropna()
        fallback_sigma = float(raw_ret.tail(20).std())
        garch_sigma_daily = [fallback_sigma] * n_days

    ema_ret = 0.0
    alpha = 0.3
    raw_predictions = []

    for k in range(1, n_days + 1):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)

        preds = [m.predict(last_feat)[0] for m in models]
        raw_ret = np.mean(preds)

        g_sigma = garch_sigma_daily[k - 1]
        scaled_ret = raw_ret * 3.0

        # EMA 스무딩: 재귀 피드백에 의한 지그재그 방지
        ema_ret = alpha * scaled_ret + (1 - alpha) * ema_ret
        pred_ret = np.clip(ema_ret, -daily_clip, daily_clip)

        current_price = float(hist.iloc[-1])
        next_price = current_price * np.exp(pred_ret)
        next_price = np.clip(next_price,
                             start_price * (1 - price_band),
                             start_price * (1 + price_band))

        margin = 1.28 * g_sigma * np.sqrt(k)
        lower = current_price * np.exp(pred_ret - margin)
        upper = current_price * np.exp(pred_ret + margin)
        lower = max(lower, start_price * (1 - ci_band))
        upper = min(upper, start_price * (1 + ci_band))

        next_date = last_date + pd.tseries.offsets.BDay(k)
        raw_predictions.append({
            'date': str(next_date.date()),
            'yhat': next_price,
            'lower': lower,
            'upper': upper,
        })
        hist = pd.concat([hist, pd.Series([next_price], index=[next_date])])

    # 최종 스무딩: 3일 이동평균으로 잔여 진동 제거
    yhats = [p['yhat'] for p in raw_predictions]
    for i in range(1, len(yhats) - 1):
        yhats[i] = (yhats[i - 1] + yhats[i] + yhats[i + 1]) / 3.0

    predictions = []
    for i, p in enumerate(raw_predictions):
        predictions.append({
            'date': p['date'],
            'yhat': _safe_float(round(yhats[i], 2)),
            'lower': _safe_float(round(p['lower'], 2)),
            'upper': _safe_float(round(p['upper'], 2)),
        })

    return predictions


def run_chart_predict_single(ticker, train=False):
    """단일 티커에 대해 5-모델 앙상블 30일 예측.

    Args:
        ticker: ETF 티커
        train: True 면 5-모델 재학습 + .pkl 저장 (월 1회 cron 용).
               False 면 .pkl load 후 추론만 (3시간 cron 용).
               .pkl 없으면 자동 fallback 으로 1회 학습 + 저장.
    """
    df = yf.download(ticker, period='max', interval='1d',
                     auto_adjust=True, progress=False)
    if df.empty:
        return None

    if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
        df.columns = df.columns.get_level_values(0)

    close = df['Close']
    features = build_features_v2(close)
    target = np.log(close / close.shift(1)).shift(-1)
    target.name = 'target'
    data = features.join(target).dropna()

    if len(data) < 200:
        return None

    feat_cols = [c for c in data.columns if c != 'target']

    # Stage 1+2: 학습/추론 분리
    if train:
        # 학습 모드 — 5-모델 재학습 + .pkl 저장
        models_final = _train_models(data[feat_cols].values, data['target'].values)
        _save_chart_models(models_final, feat_cols, ticker)
    else:
        # 추론 모드 — .pkl load 시도, 없으면 1회 학습 + 저장 (fallback)
        models_final, saved_cols = _load_chart_models(ticker)
        if models_final is None:
            print(f'[chart_predict] {ticker} .pkl 없음 — 1회 학습 + 저장')
            models_final = _train_models(data[feat_cols].values, data['target'].values)
            _save_chart_models(models_final, feat_cols, ticker)
        else:
            # 학습 시점 컬럼 사용 (피처 변경 시 보호)
            feat_cols = saved_cols

    # 추론: GJR-GARCH-Skew-t + FHS Monte Carlo
    fc_result = _garch_skewt_fhs_forecast(
        models_final, close, 30, feat_cols, ticker=ticker
    )

    # 최근 30일 실제 종가
    recent = close.tail(30)
    actual = [{'date': str(idx.date()), 'close': round(float(val), 2)}
              for idx, val in recent.items()]

    # 메모리 정리
    del models_final

    # 새 형식 — predicted JSONB 안에 forecast/sample_paths/metrics/predicted(legacy) 모두 포함
    # 기존 chart_predict_result 테이블 schema 변경 X
    predicted_payload = {
        'forecast': fc_result['forecast'],
        'sample_paths': fc_result['sample_paths'],
        'metrics': fc_result['metrics'],
        'predicted': fc_result['predicted'],         # legacy 하위 호환
        'metadata': fc_result['metadata'],
    }

    return {
        'date': str(datetime.date.today()),
        'ticker': ticker,
        'actual': json.dumps(actual, ensure_ascii=False),
        'predicted': json.dumps(predicted_payload, ensure_ascii=False),
    }


def run_chart_predict_all(train=False):
    """16개 ETF 전체에 대해 앙상블 예측 (default 추론 모드).

    Args:
        train: True 면 16 ETF 모두 재학습 (월 1회 cron 용)
               False 면 .pkl load 후 추론만 (3시간 cron 용)
    """
    n = 5 if HAS_CATBOOST else 4
    mode = '학습+추론' if train else '추론만 (.pkl load)'
    print(f'  앙상블: {n}개 모델, 모드: {mode}')
    results = []
    for i, ticker in enumerate(CHART_TICKERS):
        try:
            print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 진행 중...')
            rec = run_chart_predict_single(ticker, train=train)
            if rec:
                results.append(rec)
                print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 완료')
            else:
                print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 데이터 없음, 건너뜀')
        except Exception as e:
            print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 실패: {e}')
        if i < len(CHART_TICKERS) - 1:
            time.sleep(1)
    return results
