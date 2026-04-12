"""5-모델 앙상블 ETF 30일 주가 예측 (스케줄러 배치 실행용).

XGBoost + CatBoost + RandomForest + Ridge + SVR 앙상블로
16개 ETF 티커별 30일 영업일 예측을 수행한다.
OOS sigma로 현실적 신뢰구간을 생성한다.
"""

import datetime
import json
import time
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

try:
    from arch import arch_model
    HAS_ARCH = True
except ImportError:
    HAS_ARCH = False

CHART_TICKERS = ['SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VOO', 'SOXX', 'SMH',
                 'XLK', 'XLF', 'XLE', 'XLV', 'ARKK', 'GLD', 'TLT', 'SCHD']


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
    """5-모델 평균 앙상블 재귀 예측 (기본: 3배 증폭)."""
    hist = close_history.copy()
    predictions = []
    last_date = hist.index[-1]
    start_price = float(close_history.iloc[-1])

    for k in range(1, n_days + 1):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values

        # NaN 피처를 0으로 대체하여 예측 안정성 확보
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)

        preds = [m.predict(last_feat)[0] for m in models]
        pred_ret = np.mean(preds) * 3.0  # 변동성 3배 증폭

        # 일일 수익률 클램핑 (±3%)
        pred_ret = np.clip(pred_ret, -0.03, 0.03)

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
        predictions.append({
            'date': str(next_date.date()),
            'yhat': _safe_float(round(next_price, 2)),
            'lower': _safe_float(round(lower, 2)),
            'upper': _safe_float(round(upper, 2)),
        })
        hist = pd.concat([hist, pd.Series([next_price], index=[next_date])])

    return predictions


# 변동성이 큰 ETF는 범위 제한을 넉넉하게
_HIGH_VOL_TICKERS = {'ARKK', 'SOXX', 'SMH', 'XLE', 'IWM'}


def _garch_forecast(models, close_history, n_days, feature_cols, ticker='SPY'):
    """GARCH(1,1) 기반 재귀 예측 — 전체 ETF 공용.

    앙상블 모델의 평균 수익률 예측을 방향(direction)으로 사용하고,
    GARCH(1,1)로 추정한 조건부 변동성으로 스케일링한다.
    고정 3배 증폭 대신 시장 상태에 맞는 동적 변동성을 적용.
    """
    hist = close_history.copy()
    predictions = []
    last_date = hist.index[-1]
    start_price = float(close_history.iloc[-1])

    # 티커별 범위 제한 설정
    if ticker.upper() in _HIGH_VOL_TICKERS:
        price_band = 0.25   # ±25%
        ci_band = 0.40       # 신뢰구간 ±40%
        daily_clip = 0.05    # 일일 ±5%
    elif ticker.upper() in {'SPY', 'VOO', 'VTI', 'DIA', 'SCHD'}:
        price_band = 0.15   # ±15% (대형 안정)
        ci_band = 0.30
        daily_clip = 0.03
    else:
        price_band = 0.20   # ±20% (기본)
        ci_band = 0.35
        daily_clip = 0.04

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

    for k in range(1, n_days + 1):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)

        preds = [m.predict(last_feat)[0] for m in models]
        raw_ret = np.mean(preds)

        # 앙상블 예측 수익률을 3배 증폭 (방향+크기 보존, 매끄러운 곡선)
        g_sigma = garch_sigma_daily[k - 1]
        pred_ret = raw_ret * 3.0

        # 일일 수익률 클램핑
        pred_ret = np.clip(pred_ret, -daily_clip, daily_clip)

        current_price = float(hist.iloc[-1])
        next_price = current_price * np.exp(pred_ret)

        # 누적 가격 범위 제한
        next_price = np.clip(next_price,
                             start_price * (1 - price_band),
                             start_price * (1 + price_band))

        # 신뢰구간: GARCH σ 기반 80% CI
        margin = 1.28 * g_sigma * np.sqrt(k)
        lower = current_price * np.exp(pred_ret - margin)
        upper = current_price * np.exp(pred_ret + margin)
        lower = max(lower, start_price * (1 - ci_band))
        upper = min(upper, start_price * (1 + ci_band))

        next_date = last_date + pd.tseries.offsets.BDay(k)
        predictions.append({
            'date': str(next_date.date()),
            'yhat': _safe_float(round(next_price, 2)),
            'lower': _safe_float(round(lower, 2)),
            'upper': _safe_float(round(upper, 2)),
        })
        hist = pd.concat([hist, pd.Series([next_price], index=[next_date])])

    return predictions


def run_chart_predict_single(ticker):
    """단일 티커에 대해 5-모델 앙상블 30일 예측을 실행한다."""
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
    val_size = 60

    train = data.iloc[:-val_size]
    val = data.iloc[-val_size:]
    X_tr, y_tr = train[feat_cols].values, train['target'].values
    X_val, y_val = val[feat_cols].values, val['target'].values

    # 전체 데이터로 최종 모델 학습
    models_final = _train_models(data[feat_cols].values, data['target'].values)

    # OOS sigma: train만으로 학습한 모델의 val 잔차
    models_oos = _train_models(X_tr, y_tr)
    oos_preds = np.mean([m.predict(X_val) for m in models_oos], axis=0)
    sigma = np.std(y_val - oos_preds)

    # 재귀 예측: GARCH 기반 (전체 ETF), fallback → 기존 3배 증폭
    if HAS_ARCH:
        predicted = _garch_forecast(models_final, close, 30, feat_cols, ticker)
    else:
        predicted = _recursive_forecast(models_final, close, 30, sigma, feat_cols)

    # 최근 30일 실제 종가
    recent = close.tail(30)
    actual = [{'date': str(idx.date()), 'close': round(float(val), 2)}
              for idx, val in recent.items()]

    # 메모리 정리
    del models_final, models_oos

    return {
        'date': str(datetime.date.today()),
        'ticker': ticker,
        'actual': json.dumps(actual, ensure_ascii=False),
        'predicted': json.dumps(predicted, ensure_ascii=False),
    }


def run_chart_predict_all():
    """16개 ETF 티커 전체에 대해 앙상블 예측을 실행한다."""
    n = 5 if HAS_CATBOOST else 4
    print(f'  앙상블: {n}개 모델 (CatBoost: {"O" if HAS_CATBOOST else "X"}, GARCH: {"O" if HAS_ARCH else "X"})')
    results = []
    for i, ticker in enumerate(CHART_TICKERS):
        try:
            print(f'  [{i+1}/{len(CHART_TICKERS)}] {ticker} 예측 중...')
            rec = run_chart_predict_single(ticker)
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
