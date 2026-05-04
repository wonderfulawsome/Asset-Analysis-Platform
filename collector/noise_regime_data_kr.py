"""KR Noise vs Signal HMM 피처 수집기 — 미국 noise_regime_data.py 의 한국 등가.

8개 월별 피처 (US 와 동일 명칭·의미, 데이터 소스만 KR):
1. fundamental_gap : KOSPI 12M log P − 12M log E (Shiller 등가, EPS = 1/PER * close)
2. erp_zscore     : KOSPI ERP rolling z (10Y window). EY − KR 10Y KTB
3. residual_corr  : 5 섹터 × 5종목 잔차 상관 (KOSPI 베타 제거)
4. dispersion     : 25종목 일간 수익률 횡단면 std 의 20일 평균
5. amihud         : 5 megacap |OC log return| / dollar_vol 평균 (로그·윈저라이즈)
6. vix_term       : VKOSPI / VKOSPI 60D 평균 (US 의 VIX/VIX3M 대체 — KR 은 3M 미공개)
7. hy_spread      : ICE BofA US HY OAS (글로벌 신용 환경, KR 시리즈 부족 시 미국 사용)
8. realized_vol   : KOSPI 일간 수익률 20일 std × √252
"""
from __future__ import annotations

import datetime as _dt
from io import StringIO
from itertools import combinations

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# KR 25 종목 (5 섹터 × 5) — 시총 상위 + 섹터 분산 (2026 기준)
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_STOCKS_KR = {
    'tech':       ['005930', '000660', '035420', '035720', '003670'],   # 삼성전자/SK하이닉스/NAVER/카카오/포스코
    'financial':  ['105560', '055550', '086790', '316140', '138930'],   # KB/신한/하나/우리/BNK
    'industrial': ['005380', '000270', '015760', '028260', '010130'],   # 현대차/기아/한국전력/삼성물산/고려아연
    'health':     ['207940', '068270', '326030', '196170', '091990'],   # 삼성바이오/셀트리온/SK바이오팜/알테오젠/셀트리온헬스케어
    'consumer':   ['097950', '035250', '003490', '047810', '011170'],   # CJ제일제당/강원랜드/대한항공/KAI/롯데케미칼
}
ALL_STOCKS_KR = [s for stocks in SECTOR_STOCKS_KR.values() for s in stocks]

# Amihud 5 megacap (시총 최상위)
AMIHUD_STOCKS_KR = ['005930', '000660', '035420', '035720', '207940']

FEATURE_NAMES_KR = [
    'fundamental_gap', 'erp_zscore', 'residual_corr',
    'dispersion', 'amihud', 'vix_term', 'hy_spread',
    'realized_vol',
]


# ─────────────────────────────────────────────────────────────────────────────
# Fetch helpers
# ─────────────────────────────────────────────────────────────────────────────

def _strip_tz(s):
    if isinstance(s, (pd.Series, pd.DataFrame)) and hasattr(s.index, 'tz') and s.index.tz is not None:
        s = s.copy()
        s.index = s.index.tz_localize(None)
    return s


def fetch_kospi_shiller_like(years: int = 7) -> pd.DataFrame:
    """KOSPI 월별 P (close) + E (EPS = close / PER).

    Returns: DataFrame(index=month-start, columns=['P','E','CAPE'])

    폴백: KOSPI close → pykrx/FDR/yfinance 3단; PER → pykrx 만, 실패시 14.0 평탄.
    """
    # KOSPI close — 기존 폴백 함수 재사용 (pykrx → FDR → yfinance ^KS11)
    daily_close = fetch_kospi_close_daily(years=years)
    if daily_close.empty:
        print('[KR-Noise] Shiller-like: KOSPI close 데이터 없음')
        return pd.DataFrame()
    close_monthly = daily_close.resample('MS').last().dropna()

    # PER — pykrx 만 지원. 실패시 캐싱된 last_known_per → 없으면 14.0 평탄
    per_monthly = None
    try:
        from pykrx import stock
        end = _dt.date.today()
        start = end - _dt.timedelta(days=years * 365 + 30)
        sd, ed = start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
        fund = stock.get_index_fundamental(sd, ed, '1001')
        if fund is not None and not fund.empty and 'PER' in fund.columns:
            per_monthly = (fund['PER'].replace(0, np.nan)
                            .resample('MS').last().dropna())
    except Exception as e:
        print(f'[KR-Noise] PER pykrx 실패 → fallback 사용: {e}')
    if per_monthly is None or per_monthly.empty:
        try:
            from collector.valuation_signal_kr import _load_last_known_per, _HARD_FALLBACK_PER
            cached = _load_last_known_per()
        except Exception:
            cached, _HARD_FALLBACK_PER = None, 14.0
        fallback_per = cached if cached else _HARD_FALLBACK_PER
        per_monthly = pd.Series(fallback_per, index=close_monthly.index)
        src = '캐싱된 마지막 정상값' if cached else f'하드 fallback {_HARD_FALLBACK_PER}'
        print(f'[KR-Noise] PER fallback ({src}, {fallback_per:.2f} 평탄) 사용')
    else:
        # 정상 PER 마지막 값 → 공용 캐시 갱신 (valuation_signal_kr 와 공유)
        try:
            from collector.valuation_signal_kr import _save_last_known_per
            last_valid = per_monthly.dropna()
            if not last_valid.empty:
                _save_last_known_per(float(last_valid.iloc[-1]))
        except Exception:
            pass

    df = pd.DataFrame({'P': close_monthly, 'PER': per_monthly}).dropna()
    if df.empty:
        return pd.DataFrame()
    df['E'] = df['P'] / df['PER']

    # CAPE 등가 — 최근 N년 E 평균
    df['E_smooth'] = df['E'].rolling(min(60, len(df)), min_periods=12).mean()
    df['CAPE'] = df['P'] / df['E_smooth']
    return df[['P', 'E', 'CAPE']].dropna()


def fetch_kr_10y_monthly(years: int = 7) -> pd.Series:
    """KR 10Y KTB monthly. ECOS 1차, FDR 2차 폴백 — 결과는 소수(0.035 등) 단위."""
    # 1차 ECOS
    try:
        from collector.ecos_macro import fetch_kr_treasury_yields
        bundle = fetch_kr_treasury_yields(years=years)
        s = bundle.get('kr_10y')
        if s is not None and not s.empty:
            return _strip_tz((s / 100.0).resample('MS').last().dropna())
    except Exception as e:
        print(f'[KR-Noise] ECOS KR 10Y 실패: {e}')
    # 2차 FDR (Yahoo)
    try:
        import FinanceDataReader as fdr
        end = _dt.date.today()
        start = end - _dt.timedelta(days=years * 365 + 30)
        df = fdr.DataReader('KR10YT=RR', start, end)
        if df is not None and not df.empty and 'Close' in df.columns:
            s = df['Close'].resample('MS').last().dropna() / 100.0
            return _strip_tz(s)
    except Exception as e:
        print(f'[KR-Noise] FDR KR 10Y 실패: {e}')
    return pd.Series(dtype=float)


def fetch_vkospi_daily(years: int = 7) -> pd.Series:
    """VKOSPI 일별 close."""
    try:
        import FinanceDataReader as fdr
        end = _dt.date.today()
        start = end - _dt.timedelta(days=years * 365 + 30)
        df = fdr.DataReader('VKOSPI', start, end)
        if df is None or df.empty or 'Close' not in df.columns:
            return pd.Series(dtype=float)
        return _strip_tz(df['Close'].dropna())
    except Exception as e:
        print(f'[KR-Noise] VKOSPI fetch 실패: {e}')
        return pd.Series(dtype=float)


def fetch_us_hy_spread(years: int = 7) -> pd.Series:
    """KR 회사채(AA-3Y) 스프레드 1차, 미국 HY OAS (FRED) 2차 폴백.

    KR 회사채 - KR 3Y 국고채 스프레드 (% 차이) 가 있으면 KR 신용 환경 정확히 반영.
    실패 시 미국 ICE BofA HY OAS — 글로벌 신용 환경 대용.
    """
    # 1차 ECOS — KR 회사채 스프레드
    try:
        from collector.ecos_macro import fetch_kr_corp_spread
        s = fetch_kr_corp_spread(years=years)
        if s is not None and not s.empty:
            return _strip_tz(s)
    except Exception as e:
        print(f'[KR-Noise] ECOS KR 회사채 스프레드 실패 → 미국 HY 폴백: {e}')
    # 2차 미국 HY OAS (FRED)
    try:
        import requests
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2'
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text), index_col=0, parse_dates=True)
        df.columns = ['hy_spread']
        df['hy_spread'] = pd.to_numeric(df['hy_spread'], errors='coerce')
        end = pd.Timestamp(_dt.date.today())
        start = end - pd.Timedelta(days=years * 365 + 30)
        return _strip_tz(df.loc[start:end, 'hy_spread'].dropna())
    except Exception as e:
        print(f'[KR-Noise] HY spread fetch 실패: {e}')
        return pd.Series(dtype=float)


def _stock_ohlcv_dual(ticker: str, years: int) -> pd.DataFrame:
    """종목 OHLCV — pykrx → FDR → yfinance(.KS) 3-단 폴백, 영어 컬럼."""
    end = _dt.date.today()
    start = end - _dt.timedelta(days=years * 365 + 30)
    # 1차 pykrx
    try:
        from pykrx import stock
        sd, ed = start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
        df = stock.get_market_ohlcv_by_date(sd, ed, ticker)
        if df is not None and not df.empty:
            return df.rename(columns={
                '시가': 'Open', '고가': 'High', '저가': 'Low',
                '종가': 'Close', '거래량': 'Volume',
            })
    except Exception:
        pass
    # 2차 FDR
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(ticker, start, end)
        if df is not None and not df.empty:
            return df  # 영어 컬럼
    except Exception:
        pass
    # 3차 yfinance (한국 종목: ticker.KS)
    try:
        import yfinance as yf
        df = yf.download(f'{ticker}.KS', start=start, end=end,
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if hasattr(df.columns, 'levels') and len(df.columns.levels) > 1:
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f'[KR-Noise] {ticker} 모든 폴백 실패: {e}')
        return pd.DataFrame()


def fetch_kr_stock_prices(tickers: list[str], years: int = 7) -> pd.DataFrame:
    """KR 종목들의 일별 종가 DataFrame (index=Date, columns=ticker)."""
    out = {}
    for tk in tickers:
        df = _stock_ohlcv_dual(tk, years)
        if df is None or df.empty or 'Close' not in df.columns:
            continue
        out[tk] = df['Close']
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_index()


def fetch_kr_amihud_stocks(tickers: list[str], years: int = 7) -> dict:
    """Amihud 산출용 — OHLCV 전체 필요. pykrx → FDR 폴백."""
    out = {}
    for tk in tickers:
        df = _stock_ohlcv_dual(tk, years)
        if df is None or df.empty or 'Close' not in df.columns:
            continue
        out[tk] = df
    return out


def fetch_kospi_close_daily(years: int = 7) -> pd.Series:
    """KOSPI 일별 종가 — pykrx → FDR (KS11) 폴백."""
    end = _dt.date.today()
    start = end - _dt.timedelta(days=years * 365 + 30)
    # 1차 pykrx
    try:
        from pykrx import stock
        sd, ed = start.strftime('%Y%m%d'), end.strftime('%Y%m%d')
        df = stock.get_index_ohlcv(sd, ed, '1001')
        if df is not None and not df.empty:
            return _strip_tz(df['종가'].dropna())
    except Exception:
        pass
    # 2차 FDR
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader('KS11', start, end)
        if df is None or df.empty or 'Close' not in df.columns:
            return pd.Series(dtype=float)
        return _strip_tz(df['Close'].dropna())
    except Exception as e:
        print(f'[KR-Noise] KOSPI FDR 폴백 실패: {e}')
        return pd.Series(dtype=float)


# ─────────────────────────────────────────────────────────────────────────────
# 피처 엔지니어링 — US compute_monthly_features 와 동일 구조
# ─────────────────────────────────────────────────────────────────────────────

def compute_monthly_features_kr(
    shiller_kr: pd.DataFrame,
    kr_10y_monthly: pd.Series,
    vkospi_daily: pd.Series,
    hy_spread_daily: pd.Series,
    stock_prices: pd.DataFrame,
    amihud_data: dict,
    kospi_close_daily: pd.Series,
) -> dict:
    """8개 월별 피처 + 윈저라이징. US 의 compute_monthly_features 와 같은 dict 구조 반환.

    Returns dict keys:
      'features', 'winsor_bounds', 'residuals', 'stock_returns',
      'amihud_frames', 'macro_raw', 'spy_ret' (KOSPI 일별 수익률), 'amihud_q01', 'amihud_q99'
    """

    # ── ① fundamental_gap ──
    sh = shiller_kr.copy()
    sh['log_P'] = np.log(sh['P'])
    sh['log_E'] = np.log(sh['E'].clip(lower=0.01))
    fundamental_gap = (sh['log_P'].diff(12) - sh['log_E'].diff(12)).dropna()
    fundamental_gap.name = 'fundamental_gap'

    # ── ② erp_zscore ──
    cape_series = sh['CAPE'].dropna()
    real_ey = 1.0 / cape_series
    if len(kr_10y_monthly) > 0:
        erp_df = pd.DataFrame({'ey': real_ey, 'tnx': kr_10y_monthly}).dropna()
        erp = erp_df['ey'] - erp_df['tnx']
        erp_rm = erp.rolling(120, min_periods=24).mean()    # 10년 (KR 데이터 짧으면 24개월 min)
        erp_rs = erp.rolling(120, min_periods=24).std()
        erp_zscore = ((erp - erp_rm) / erp_rs).abs().dropna()
    else:
        print('  [KR-Noise warn] KR 10Y 없음 → erp_zscore=0')
        erp_zscore = fundamental_gap * 0
    erp_zscore.name = 'erp_zscore'

    # ── ③ residual_corr + dispersion ──
    stock_returns = stock_prices.pct_change().dropna()
    spy_ret = _strip_tz(kospi_close_daily.pct_change().dropna())  # KOSPI 일간 수익률 = SPY 등가

    residuals = pd.DataFrame(index=stock_returns.index)
    for ticker in ALL_STOCKS_KR:
        if ticker not in stock_returns.columns or spy_ret is None:
            continue
        ret = stock_returns[ticker]
        cov_kospi = ret.rolling(60, min_periods=30).cov(spy_ret)
        kospi_var = spy_ret.rolling(60, min_periods=30).var()
        beta = cov_kospi / kospi_var
        residuals[ticker] = ret - beta * spy_ret
    residuals = residuals.dropna(how='all')

    # 섹터별 잔차 페어와이즈 상관 → 전체 평균
    sector_corrs = []
    for sector, stocks in SECTOR_STOCKS_KR.items():
        avail = [s for s in stocks if s in residuals.columns]
        if len(avail) < 2:
            continue
        pair_corrs = []
        for s1, s2 in combinations(avail, 2):
            rc = residuals[s1].rolling(20).corr(residuals[s2])
            pair_corrs.append(rc)
        if pair_corrs:
            sector_corrs.append(pd.concat(pair_corrs, axis=1).mean(axis=1))
    if sector_corrs:
        daily_resid_corr = pd.concat(sector_corrs, axis=1).mean(axis=1).dropna()
        residual_corr_monthly = _strip_tz(daily_resid_corr).resample('MS').mean().dropna()
    else:
        residual_corr_monthly = fundamental_gap * 0
    residual_corr_monthly.name = 'residual_corr'

    # 횡단면 dispersion
    avail_stocks = [s for s in ALL_STOCKS_KR if s in stock_returns.columns]
    if avail_stocks:
        cross_std = stock_returns[avail_stocks].std(axis=1)
        disp_daily = cross_std.rolling(20).mean().dropna()
        dispersion_monthly = _strip_tz(disp_daily).resample('MS').mean().dropna()
    else:
        dispersion_monthly = fundamental_gap * 0
    dispersion_monthly.name = 'dispersion'

    # ── ④ amihud ──
    amihud_per_stock = []
    for tk, df_t in amihud_data.items():
        if 'Close' not in df_t.columns or 'Open' not in df_t.columns or 'Volume' not in df_t.columns:
            continue
        oc_ret = np.log(df_t['Close'] / df_t['Open']).abs()
        dollar_vol = df_t['Close'] * df_t['Volume']
        ami_t = oc_ret / dollar_vol.replace(0, np.nan)
        amihud_per_stock.append(ami_t)

    if amihud_per_stock:
        amihud_avg = pd.concat(amihud_per_stock, axis=1).mean(axis=1).dropna()
        amihud_rolling = amihud_avg.rolling(20).mean().dropna()
        log_amihud = np.log(amihud_rolling + 1e-15)
        amihud_q01 = log_amihud.quantile(0.01)
        amihud_q99 = log_amihud.quantile(0.99)
        log_amihud_w = _strip_tz(log_amihud.clip(amihud_q01, amihud_q99))
        amihud_monthly = log_amihud_w.resample('MS').mean().dropna()
    else:
        amihud_monthly = fundamental_gap * 0
        amihud_q01 = 0.0
        amihud_q99 = 0.0
    amihud_monthly.name = 'amihud'

    # ── ⑤ vix_term ── VKOSPI / VKOSPI 60D 평균 (US VIX/VIX3M 대체)
    if len(vkospi_daily) > 0:
        vk_60d = vkospi_daily.rolling(60, min_periods=20).mean()
        vix_term_daily = (vkospi_daily / vk_60d).replace([np.inf, -np.inf], np.nan).dropna()
        vix_term = vix_term_daily.resample('MS').last().dropna()
    else:
        vix_term = amihud_monthly * 0 + 1.0
    vix_term.name = 'vix_term'

    # ── ⑥ hy_spread ── 미국 HY OAS (글로벌 신용)
    if len(hy_spread_daily) > 0:
        hy_spread_monthly = hy_spread_daily.resample('MS').last().dropna()
    else:
        hy_spread_monthly = amihud_monthly * 0
    hy_spread_monthly.name = 'hy_spread'

    # ── ⑦ realized_vol ── KOSPI 20일 std × √252
    if spy_ret is not None and len(spy_ret) > 0:
        rv_daily = spy_ret.rolling(20).std() * np.sqrt(252)
        realized_vol_monthly = _strip_tz(rv_daily).resample('MS').mean().dropna()
    else:
        realized_vol_monthly = amihud_monthly * 0
    realized_vol_monthly.name = 'realized_vol'

    # ── 병합 ──
    all_series = {
        'fundamental_gap': fundamental_gap,
        'erp_zscore': erp_zscore,
        'residual_corr': residual_corr_monthly,
        'dispersion': dispersion_monthly,
        'amihud': amihud_monthly,
        'vix_term': vix_term,
        'hy_spread': hy_spread_monthly,
        'realized_vol': realized_vol_monthly,
    }
    features = pd.DataFrame({k: _strip_tz(v) for k, v in all_series.items()})
    features = features.dropna()
    if len(features) == 0:
        print('[KR-Noise] 피처 병합 결과 0행 — 데이터 정렬 실패 가능')
    else:
        print(f'[KR-Noise] 피처 병합: {features.shape} | {features.index[0].date()} ~ {features.index[-1].date()}')

    # 윈저라이징 (1/99 퍼센타일)
    winsor_bounds = {}
    for col in features.columns:
        q01, q99 = features[col].quantile(0.01), features[col].quantile(0.99)
        winsor_bounds[col] = (float(q01), float(q99))
        features[col] = features[col].clip(q01, q99)

    return {
        'features': features,
        'winsor_bounds': winsor_bounds,
        'residuals': residuals,
        'stock_returns': stock_returns,
        'amihud_frames': amihud_data,
        'macro_raw': {
            'vkospi': vkospi_daily.to_frame('vkospi'),
            'hy_spread': hy_spread_daily.to_frame('hy_spread') if len(hy_spread_daily) > 0 else pd.DataFrame(),
            'kr_10y': kr_10y_monthly.to_frame('kr_10y'),
        },
        'spy_ret': spy_ret,                              # 호환을 위해 'spy_ret' 키 유지 (실제론 KOSPI ret)
        'amihud_q01': float(amihud_q01),
        'amihud_q99': float(amihud_q99),
    }


def fetch_all_kr(years: int = 7) -> dict:
    """원-shot fetch — KR 모든 raw 데이터 + compute_monthly_features_kr 호출까지."""
    print(f'[KR-Noise] {years}년치 raw 데이터 수집 시작 (~5~10분 소요)...')

    print('  ① KOSPI Shiller 등가...')
    shiller_kr = fetch_kospi_shiller_like(years=years)
    if shiller_kr.empty:
        return {}

    print('  ② KR 10Y monthly...')
    kr_10y = fetch_kr_10y_monthly(years=years)

    print('  ③ VKOSPI daily...')
    vkospi = fetch_vkospi_daily(years=years)

    print('  ④ US HY spread daily (글로벌 신용)...')
    hy = fetch_us_hy_spread(years=years)

    print(f'  ⑤ KR 25 종목 일별 close ({len(ALL_STOCKS_KR)}종)...')
    stock_prices = fetch_kr_stock_prices(ALL_STOCKS_KR, years=years)

    print(f'  ⑥ Amihud 5 megacap OHLCV...')
    amihud_data = fetch_kr_amihud_stocks(AMIHUD_STOCKS_KR, years=years)

    print('  ⑦ KOSPI 일별 close (베타 기준)...')
    kospi_daily = fetch_kospi_close_daily(years=years)

    print('  ⑧ 8피처 산출 + 윈저라이징...')
    bundle = compute_monthly_features_kr(
        shiller_kr, kr_10y, vkospi, hy, stock_prices, amihud_data, kospi_daily,
    )
    return bundle
