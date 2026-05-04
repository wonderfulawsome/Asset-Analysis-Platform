"""KR XGBoost Crash/Surge — 24 피처 일별 데이터 수집 + 피처 엔지니어링.

US collector/crash_surge_data.py 의 KR 등가. 차이점:
- SPY → KOSPI (^KS11), VIX → VKOSPI
- FRED 신용 (HY/BBB/CCC OAS) → ECOS KR 회사채 AA-3Y 스프레드 1개
- 부재 피처 (NFCI, SOFR, breakeven, VIX9D, SKEW 등) 모두 제외 — 학습 부실 방지
- 추가 피처: 외국인 순매수, USDKRW

라벨링은 US 와 동일 (3-class, ±10%, 20영업일 forward).
프론트 명명만 KR 모드에서 "20영업일 상승/하락 예측" 으로 직관 표시 (US 도 같은 분류기).
"""

from __future__ import annotations

import datetime as _dt
import warnings
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


# ── 24 피처 정의 (US 의 ALL_FEATURES 와 같은 역할) ──
KR_FEATURES = [
    # KOSPI 가격/추세 (7)
    'KOSPI_LOGRET_1D', 'KOSPI_LOGRET_5D', 'KOSPI_LOGRET_10D', 'KOSPI_LOGRET_20D',
    'KOSPI_DRAWDOWN_60D', 'KOSPI_MA_GAP_50', 'KOSPI_MA_GAP_200',
    # KOSPI 변동성 (4)
    'RV_5D', 'RV_21D', 'EWMA_VOL_L94', 'VOL_OF_VOL_21D',
    # VKOSPI (3)
    'VKOSPI_LEVEL', 'VKOSPI_CHANGE_1D', 'VKOSPI_PCTL_252D',
    # KR 신용 (3) — 회사채 AA-3Y - 국고채 3Y 스프레드
    'KR_CORP_AA3Y_SPREAD', 'KR_CORP_SPREAD_CHG_5D', 'KR_CORP_SPREAD_CHG_20D',
    # KR 금리 (2)
    'KR_DGS10_LEVEL', 'KR_T10Y3M_SLOPE',
    # 외국인 순매수 (2)
    'FOREIGN_NET_BUY_1D', 'FOREIGN_NET_BUY_5D',
    # 외부 (2)
    'USDKRW_RET_5D', 'WTI_RET_5D',
    # 거래대금 (1)
    'KOSPI_DOLLAR_VOL_Z_20D',
]

# 라벨 파라미터 — US 와 동일
FORWARD_WINDOW = 20
CRASH_THRESHOLD = -0.10
SURGE_THRESHOLD = 0.10


# ── 헬퍼 ──

def _strip_tz(obj):
    """타임존 제거."""
    if isinstance(obj, (pd.Series, pd.DataFrame)) and hasattr(obj.index, 'tz') and obj.index.tz is not None:
        obj = obj.copy()
        obj.index = obj.index.tz_localize(None)
    return obj


def _kospi_ohlcv(start: str, end: str | None = None) -> pd.DataFrame:
    """KOSPI(^KS11) OHLCV 3-tier fallback: pykrx → FDR → yfinance.

    Returns: DataFrame(index=Date, columns=['Open','High','Low','Close','Volume']).
    """
    end_dt = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_dt = _dt.date.fromisoformat(start)

    # 1차 pykrx
    try:
        from pykrx import stock
        df = stock.get_index_ohlcv(start_dt.strftime('%Y%m%d'),
                                    end_dt.strftime('%Y%m%d'), '1001')
        if df is not None and not df.empty and '종가' in df.columns:
            out = df.rename(columns={
                '시가': 'Open', '고가': 'High', '저가': 'Low',
                '종가': 'Close', '거래량': 'Volume',
            })
            return _strip_tz(out[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float))
    except Exception as e:
        print(f'[CrashSurge-KR] pykrx KOSPI 실패 → FDR: {e}')

    # 2차 FinanceDataReader
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader('KS11', start_dt, end_dt)
        if df is not None and not df.empty and 'Close' in df.columns:
            return _strip_tz(df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float))
    except Exception as e:
        print(f'[CrashSurge-KR] FDR KS11 실패 → yfinance: {e}')

    # 3차 yfinance
    try:
        import yfinance as yf
        df = yf.download('^KS11', start=start_dt, end=end_dt + _dt.timedelta(days=1),
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return _strip_tz(df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float))
    except Exception as e:
        print(f'[CrashSurge-KR] yfinance ^KS11 실패: {e}')
        return pd.DataFrame()


def _vkospi_close(start: str, end: str | None = None) -> pd.Series:
    """VKOSPI 일별 close — FDR 1차, KOSPI 20D RV proxy 2차."""
    end_dt = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_dt = _dt.date.fromisoformat(start)
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader('VKOSPI', start_dt, end_dt)
        if df is not None and not df.empty and 'Close' in df.columns:
            return _strip_tz(df['Close'].dropna())
    except Exception as e:
        print(f'[CrashSurge-KR] VKOSPI FDR 실패: {e}')
    return pd.Series(dtype=float)


def _kr_treasury(start: str, end: str | None = None) -> dict:
    """KR 10Y / 3M-3Y. ECOS 1차, FDR 2차. Returns {'kr_10y': Series, 'kr_3y': Series} (% 단위)."""
    end_dt = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_dt = _dt.date.fromisoformat(start)
    years = max(1, (end_dt - start_dt).days // 365 + 1)

    # 1차 ECOS
    try:
        from collector.ecos_macro import fetch_kr_treasury_yields
        bundle = fetch_kr_treasury_yields(years=years)
        kr10 = bundle.get('kr_10y')
        kr3 = bundle.get('kr_3y')
        if kr10 is not None and not kr10.empty:
            return {'kr_10y': _strip_tz(kr10), 'kr_3y': _strip_tz(kr3) if kr3 is not None else pd.Series(dtype=float)}
    except Exception as e:
        print(f'[CrashSurge-KR] ECOS 국고채 실패 → FDR: {e}')

    # 2차 FDR
    out = {}
    for sym, key in [('KR10YT=RR', 'kr_10y'), ('KR3YT=RR', 'kr_3y')]:
        try:
            import FinanceDataReader as fdr
            df = fdr.DataReader(sym, start_dt, end_dt)
            if df is not None and not df.empty and 'Close' in df.columns:
                out[key] = _strip_tz(df['Close'].dropna())
                continue
        except Exception:
            pass
        out[key] = pd.Series(dtype=float)
    return out


def _kr_corp_spread(start: str, end: str | None = None) -> pd.Series:
    """KR 회사채 AA-3Y - 국고채 3Y 스프레드 (% 단위). ECOS only (FDR 미지원)."""
    end_dt = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_dt = _dt.date.fromisoformat(start)
    years = max(1, (end_dt - start_dt).days // 365 + 1)
    try:
        from collector.ecos_macro import fetch_kr_corp_spread
        s = fetch_kr_corp_spread(years=years)
        if s is not None and not s.empty:
            return _strip_tz(s)
    except Exception as e:
        print(f'[CrashSurge-KR] ECOS 회사채 스프레드 실패: {e}')
    return pd.Series(dtype=float)


def _foreign_net_buy(start: str, end: str | None = None) -> pd.Series:
    """KOSPI 외국인 일별 순매수 (단위: 조 원). 기존 helper 재사용 + 단위 변환."""
    end_dt = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_dt = _dt.date.fromisoformat(start)
    days = max(60, (end_dt - start_dt).days + 1)
    try:
        from collector.market_data_kr import fetch_foreign_net_buy_kospi
        df = fetch_foreign_net_buy_kospi(days=days)
        if df is None or df.empty or 'net_buy' not in df.columns:
            return pd.Series(dtype=float)
        # 원 단위 → 조 원 단위 (10^12 로 나눔)
        s = (df['net_buy'].astype(float) / 1e12).dropna()
        return _strip_tz(s)
    except Exception as e:
        print(f'[CrashSurge-KR] 외국인 순매수 실패: {e}')
        return pd.Series(dtype=float)


def _yfinance_close(ticker: str, start: str, end: str | None = None) -> pd.Series:
    """yfinance close series (USDKRW 'KRW=X', WTI 'CL=F' 등)."""
    end_dt = _dt.date.fromisoformat(end) if end else _dt.date.today()
    start_dt = _dt.date.fromisoformat(start)
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start_dt, end=end_dt + _dt.timedelta(days=1),
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            return pd.Series(dtype=float)
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return _strip_tz(df['Close'].dropna())
    except Exception as e:
        print(f'[CrashSurge-KR] yfinance {ticker} 실패: {e}')
        return pd.Series(dtype=float)


# ── 데이터 수집 ──

def fetch_crash_surge_raw_kr(start: str = '2010-01-01') -> dict:
    """KR raw fetch — KOSPI OHLCV + VKOSPI + ECOS (10Y/3Y/회사채) + 외국인 + USDKRW + WTI.

    Returns:
        {'kospi': DataFrame, 'vkospi': Series, 'kr_10y': Series, 'kr_3y': Series,
         'kr_corp_spread': Series, 'foreign_net_buy': Series, 'usdkrw': Series, 'wti': Series}
    """
    today_str = _dt.date.today().isoformat()

    print('  [CrashSurge-KR] KOSPI OHLCV 수집...')
    kospi = _kospi_ohlcv(start, today_str)
    if kospi.empty:
        print('  [CrashSurge-KR] KOSPI fetch 완전 실패')
        return {}

    print('  [CrashSurge-KR] VKOSPI...')
    vkospi = _vkospi_close(start, today_str)

    print('  [CrashSurge-KR] KR 국고채 10Y/3Y...')
    treasury = _kr_treasury(start, today_str)

    print('  [CrashSurge-KR] KR 회사채 AA-3Y 스프레드...')
    corp_spread = _kr_corp_spread(start, today_str)

    print('  [CrashSurge-KR] 외국인 순매수...')
    foreign = _foreign_net_buy(start, today_str)

    print('  [CrashSurge-KR] USDKRW...')
    usdkrw = _yfinance_close('KRW=X', start, today_str)

    print('  [CrashSurge-KR] WTI...')
    wti = _yfinance_close('CL=F', start, today_str)

    return {
        'kospi': kospi,
        'vkospi': vkospi,
        'kr_10y': treasury.get('kr_10y', pd.Series(dtype=float)),
        'kr_3y': treasury.get('kr_3y', pd.Series(dtype=float)),
        'kr_corp_spread': corp_spread,
        'foreign_net_buy': foreign,
        'usdkrw': usdkrw,
        'wti': wti,
    }


def fetch_crash_surge_light_kr(lookback_days: int = 300) -> dict:
    """최근 N일 light fetch — daily inference 용 (스케줄러)."""
    start = (_dt.date.today() - _dt.timedelta(days=lookback_days)).isoformat()
    return fetch_crash_surge_raw_kr(start=start)


# ── 피처 엔지니어링 ──

def compute_features_kr(raw: dict) -> pd.DataFrame:
    """24 피처 DataFrame — KOSPI 영업일 인덱스 기준."""
    if not raw or 'kospi' not in raw or raw['kospi'].empty:
        return pd.DataFrame()

    kospi = raw['kospi']
    close = kospi['Close']
    high = kospi['High']
    low = kospi['Low']
    vol = kospi['Volume']

    feat = pd.DataFrame(index=kospi.index)

    # KOSPI 가격/추세 (7)
    for n in (1, 5, 10, 20):
        feat[f'KOSPI_LOGRET_{n}D'] = np.log(close / close.shift(n))
    feat['KOSPI_DRAWDOWN_60D'] = close / close.rolling(60).max() - 1
    feat['KOSPI_MA_GAP_50'] = close / close.rolling(50).mean() - 1
    feat['KOSPI_MA_GAP_200'] = close / close.rolling(200).mean() - 1

    # KOSPI 변동성 (4)
    daily_ret = np.log(close / close.shift(1))
    feat['RV_5D'] = daily_ret.rolling(5).std() * np.sqrt(252)
    feat['RV_21D'] = daily_ret.rolling(21).std() * np.sqrt(252)
    # EWMA λ=0.94 (RiskMetrics) — 벡터화 (US compute_features 와 동일 알고리즘)
    lam = 0.94
    ewma_var = daily_ret.copy() * 0
    if len(daily_ret) >= 21:
        ewma_var.iloc[0] = float(daily_ret.iloc[:21].var())
        for i in range(1, len(daily_ret)):
            r = daily_ret.iloc[i]
            ewma_var.iloc[i] = lam * ewma_var.iloc[i - 1] + (1 - lam) * (0 if pd.isna(r) else r * r)
    feat['EWMA_VOL_L94'] = np.sqrt(ewma_var) * np.sqrt(252)
    feat['VOL_OF_VOL_21D'] = feat['RV_5D'].rolling(21).std()

    # VKOSPI (3)
    vk = raw.get('vkospi', pd.Series(dtype=float))
    if not vk.empty:
        vk_aligned = vk.reindex(kospi.index).ffill()
        feat['VKOSPI_LEVEL'] = vk_aligned
        feat['VKOSPI_CHANGE_1D'] = vk_aligned.pct_change(1)
        feat['VKOSPI_PCTL_252D'] = vk_aligned.rolling(252).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )
    else:
        # VKOSPI 부재 시 KOSPI 20D RV × 100 proxy
        rv_proxy = (daily_ret.rolling(20).std() * np.sqrt(252) * 100).fillna(method='ffill')
        feat['VKOSPI_LEVEL'] = rv_proxy
        feat['VKOSPI_CHANGE_1D'] = rv_proxy.pct_change(1)
        feat['VKOSPI_PCTL_252D'] = rv_proxy.rolling(252).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )

    # KR 신용 — 회사채 AA-3Y 스프레드 (3)
    cs = raw.get('kr_corp_spread', pd.Series(dtype=float))
    if not cs.empty:
        cs_aligned = cs.reindex(kospi.index).ffill()
        feat['KR_CORP_AA3Y_SPREAD'] = cs_aligned
        feat['KR_CORP_SPREAD_CHG_5D'] = cs_aligned.diff(5)
        feat['KR_CORP_SPREAD_CHG_20D'] = cs_aligned.diff(20)
    else:
        feat['KR_CORP_AA3Y_SPREAD'] = 0.0
        feat['KR_CORP_SPREAD_CHG_5D'] = 0.0
        feat['KR_CORP_SPREAD_CHG_20D'] = 0.0

    # KR 금리 (2)
    kr10 = raw.get('kr_10y', pd.Series(dtype=float))
    kr3 = raw.get('kr_3y', pd.Series(dtype=float))
    if not kr10.empty:
        kr10_aligned = kr10.reindex(kospi.index).ffill()
        feat['KR_DGS10_LEVEL'] = kr10_aligned
        if not kr3.empty:
            kr3_aligned = kr3.reindex(kospi.index).ffill()
            feat['KR_T10Y3M_SLOPE'] = kr10_aligned - kr3_aligned
        else:
            feat['KR_T10Y3M_SLOPE'] = 0.0
    else:
        feat['KR_DGS10_LEVEL'] = 0.0
        feat['KR_T10Y3M_SLOPE'] = 0.0

    # 외국인 순매수 (2) — 단위 조 원
    fnb = raw.get('foreign_net_buy', pd.Series(dtype=float))
    if not fnb.empty:
        fnb_aligned = fnb.reindex(kospi.index).fillna(0.0)
        feat['FOREIGN_NET_BUY_1D'] = fnb_aligned
        feat['FOREIGN_NET_BUY_5D'] = fnb_aligned.rolling(5).sum()
    else:
        feat['FOREIGN_NET_BUY_1D'] = 0.0
        feat['FOREIGN_NET_BUY_5D'] = 0.0

    # 외부 (2)
    fx = raw.get('usdkrw', pd.Series(dtype=float))
    if not fx.empty:
        fx_aligned = fx.reindex(kospi.index).ffill()
        feat['USDKRW_RET_5D'] = np.log(fx_aligned / fx_aligned.shift(5))
    else:
        feat['USDKRW_RET_5D'] = 0.0

    wti = raw.get('wti', pd.Series(dtype=float))
    if not wti.empty:
        wti_aligned = wti.reindex(kospi.index).ffill()
        feat['WTI_RET_5D'] = np.log(wti_aligned / wti_aligned.shift(5))
    else:
        feat['WTI_RET_5D'] = 0.0

    # 거래대금 z-score (1)
    dv = close * vol
    dv_mean = dv.rolling(20).mean()
    dv_std = dv.rolling(20).std()
    feat['KOSPI_DOLLAR_VOL_Z_20D'] = (dv - dv_mean) / dv_std.replace(0, np.nan)

    # 컬럼 순서 보장
    feat = feat[KR_FEATURES]
    return feat


# ── 라벨 생성 — US 와 동일 ──

def compute_labels_kr(close: pd.Series) -> pd.Series:
    """3-class label: 0=정상, 1=하락 (crash), 2=상승 (surge). 20영업일 forward, ±10%."""
    fwd_ret = close.pct_change(FORWARD_WINDOW).shift(-FORWARD_WINDOW)
    crash_dates = fwd_ret[fwd_ret <= CRASH_THRESHOLD].index
    surge_dates = fwd_ret[fwd_ret >= SURGE_THRESHOLD].index

    label = pd.Series(0, index=close.index, name='label')
    # surge 먼저, crash 가 덮어씀 (crash 우선)
    for dt in surge_dates:
        loc = close.index.get_loc(dt)
        start = max(0, loc - FORWARD_WINDOW)
        label.iloc[start:loc + 1] = 2
    for dt in crash_dates:
        loc = close.index.get_loc(dt)
        start = max(0, loc - FORWARD_WINDOW)
        label.iloc[start:loc + 1] = 1
    return label
