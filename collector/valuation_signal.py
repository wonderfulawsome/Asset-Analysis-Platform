"""US Composite Valuation Signal — 6-component z-score (시장 고/저평가).

z_comp = 0.25·z_CAPE + 0.25·z_BUFFETT + 0.20·z_TREND
       + 0.10·z_ERP  + 0.10·z_VIX     + 0.10·z_DD

부호 컨벤션 (모두 양수 = "저평가/공포" 방향):
- z_CAPE    : -(CAPE_today - 15Y mean) / 15Y std        (CAPE↑ → z↓ 고평가)
- z_BUFFETT : -(MV/GDP_today - 15Y mean) / 15Y std       (Buffett↑ → z↓ 고평가)
- z_TREND   : -(price/MA200 - 1 - 5Y mean) / 5Y std      (가격이 MA200 보다 멀수록 고평가)
- z_ERP     : (ERP_today - 5Y mean) / 5Y std             (ERP↑ → z↑ 저평가)
- z_VIX     : (VIX_today - 5Y mean) / 5Y std             (VIX↑ → contrarian 저평가 신호)
- z_DD      : -(DD60 - 5Y mean) / 5Y std                  (drawdown 더 음수 → z↑)

라벨:
- z > +1.0 : 명확한 저평가
- 0 ~ +1.0 : 다소 저평가
- -1.0 ~ 0 : 다소 고평가
- z < -1.0 : 명확한 고평가

Data sources:
- Shiller `ie_data.xls` (CAPE, ERP)
- FRED `WILL5000PRFC` / `GDP` (Buffett)
- yfinance `^GSPC` (trend, DD), `^VIX`, `^TNX`, `SPY`

Baseline 캐시: models/valuation_baselines.json (TTL 90일).
"""
import json
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

_BASELINE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models', 'valuation_baselines.json')
_BASELINE_TTL_DAYS = 90

# Composite weights — 6-component (Buffett·CAPE 구조 + 추세/심리)
W_CAPE, W_BUFFETT, W_TREND = 0.25, 0.25, 0.20
W_ERP, W_VIX, W_DD         = 0.10, 0.10, 0.10

_FALLBACK_ERP     = {'mean': 0.004,  'std': 0.013,  'n': 0, 'source': 'fallback'}
_FALLBACK_VIX     = {'mean': 19.25,  'std': 5.26,   'n': 0, 'source': 'fallback'}
_FALLBACK_DD      = {'mean': -0.0324,'std': 0.0417, 'n': 0, 'source': 'fallback'}
_FALLBACK_CAPE    = {'mean': 28.0,   'std': 6.0,    'n': 0, 'source': 'fallback'}
_FALLBACK_BUFFETT = {'mean': 1.50,   'std': 0.45,   'n': 0, 'source': 'fallback'}
_FALLBACK_TREND   = {'mean': 0.04,   'std': 0.10,   'n': 0, 'source': 'fallback'}


# ─────────────────────────────────────────────────────────
# Shiller spreadsheet 로더 (CAPE + ERP 공통 사용)
# ─────────────────────────────────────────────────────────

def _load_shiller_df() -> pd.DataFrame | None:
    """Shiller ie_data.xls → Date/P/E/CAPE/Rate GS10 정규화."""
    try:
        url = 'http://www.econ.yale.edu/~shiller/data/ie_data.xls'
        sh = pd.read_excel(url, sheet_name='Data', skiprows=7)
        # CAPE 열 이름은 'CAPE' 또는 'P/E10' (버전마다 다름)
        cape_col = next((c for c in sh.columns if str(c).strip().upper() in ('CAPE', 'P/E10', 'P/E10 RATIO')), None)
        keep = ['Date', 'P', 'E', 'Rate GS10']
        if cape_col:
            keep.append(cape_col)
        sh = sh[keep].dropna()
        sh = sh[sh['Date'].apply(lambda x: isinstance(x, (int, float)))].copy()
        sh['year'] = sh['Date'].apply(int)
        sh['mo'] = sh['Date'].apply(lambda x: round((x - int(x)) * 100))
        sh['ym'] = sh.apply(lambda r: f'{r.year:04d}-{r.mo:02d}', axis=1)
        if cape_col:
            sh = sh.rename(columns={cape_col: 'CAPE'})
        return sh
    except Exception as e:
        print(f'[valuation_signal] Shiller load 실패: {e}')
        return None


# ─────────────────────────────────────────────────────────
# Baselines
# ─────────────────────────────────────────────────────────

def _compute_erp_baseline_5y() -> dict:
    """Shiller(2010~) + yfinance 보강 → 최근 5년 monthly ERP 분포."""
    try:
        sh = _load_shiller_df()
        if sh is None or sh.empty:
            return _FALLBACK_ERP
        cutoff_year = datetime.now().year - 5
        sh5 = sh[sh['year'] >= cutoff_year].copy()
        sh5['ey']  = sh5['E'] / sh5['P']
        sh5['tnx'] = sh5['Rate GS10'] / 100.0
        sh5['erp'] = sh5['ey'] - sh5['tnx']
        erp_series = sh5.set_index('ym')['erp']

        if not sh5.empty:
            last_ym = sh5['ym'].iloc[-1]
            last_eps = float(sh5.iloc[-1]['E'])
            last_yr, last_mo = map(int, last_ym.split('-'))
            next_yr = last_yr + (1 if last_mo == 12 else 0)
            next_mo = 1 if last_mo == 12 else last_mo + 1
            start = f'{next_yr:04d}-{next_mo:02d}-01'
            gspc = yf.Ticker('^GSPC').history(start=start, interval='1mo', auto_adjust=False)
            tnx = yf.Ticker('^TNX').history(start=start, interval='1d', auto_adjust=False)
            if not gspc.empty and not tnx.empty:
                tnx_m = tnx['Close'].resample('ME').last()
                extra = []
                for idx, row in gspc.iterrows():
                    yr, mo = idx.year, idx.month
                    price_t = float(row['Close'])
                    if price_t <= 0:
                        continue
                    months_diff = (yr - last_yr) * 12 + (mo - last_mo)
                    eps_t = last_eps * (1.07 ** (months_diff / 12.0))
                    tnx_match = tnx_m[(tnx_m.index.year == yr) & (tnx_m.index.month == mo)]
                    if tnx_match.empty:
                        continue
                    erp_t = eps_t / price_t - float(tnx_match.iloc[0]) / 100.0
                    extra.append((f'{yr:04d}-{mo:02d}', erp_t))
                if extra:
                    erp_series = pd.concat([erp_series, pd.Series(dict(extra))])

        if len(erp_series) < 24:
            return _FALLBACK_ERP
        return {
            'mean': float(round(erp_series.mean(), 6)),
            'std':  float(round(erp_series.std(), 6)),
            'n':    int(len(erp_series)),
            'source': 'shiller+yfinance(5Y)',
        }
    except Exception as e:
        print(f'[valuation_signal] ERP baseline 실패: {e}')
        return _FALLBACK_ERP


def _compute_vix_baseline_5y() -> dict:
    try:
        vix = yf.Ticker('^VIX').history(period='5y', interval='1d', auto_adjust=False)
        if vix.empty or len(vix) < 60:
            return _FALLBACK_VIX
        return {
            'mean': float(round(vix['Close'].mean(), 4)),
            'std':  float(round(vix['Close'].std(), 4)),
            'n':    int(len(vix)),
            'source': 'yfinance(^VIX,5Y)',
        }
    except Exception as e:
        print(f'[valuation_signal] VIX baseline 실패: {e}')
        return _FALLBACK_VIX


def _compute_dd_baseline_5y() -> dict:
    try:
        spy = yf.Ticker('SPY').history(period='5y', interval='1d', auto_adjust=False)
        if spy.empty or len(spy) < 60:
            return _FALLBACK_DD
        spy['max60'] = spy['Close'].rolling(60, min_periods=1).max()
        spy['dd60']  = spy['Close'] / spy['max60'] - 1.0
        return {
            'mean': float(round(spy['dd60'].mean(), 6)),
            'std':  float(round(spy['dd60'].std(), 6)),
            'n':    int(len(spy)),
            'source': 'yfinance(SPY,5Y)',
        }
    except Exception as e:
        print(f'[valuation_signal] DD baseline 실패: {e}')
        return _FALLBACK_DD


def _compute_cape_baseline_15y() -> dict:
    """Shiller CAPE 15Y monthly 분포."""
    try:
        sh = _load_shiller_df()
        if sh is None or 'CAPE' not in sh.columns:
            return _FALLBACK_CAPE
        cutoff_year = datetime.now().year - 15
        s = sh[sh['year'] >= cutoff_year].copy()
        s = s[s['CAPE'].apply(lambda x: isinstance(x, (int, float)) and x > 0)]
        if len(s) < 60:
            return _FALLBACK_CAPE
        cape_series = s['CAPE'].astype(float)
        return {
            'mean': float(round(cape_series.mean(), 4)),
            'std':  float(round(cape_series.std(), 4)),
            'n':    int(len(cape_series)),
            'source': 'shiller(CAPE,15Y)',
        }
    except Exception as e:
        print(f'[valuation_signal] CAPE baseline 실패: {e}')
        return _FALLBACK_CAPE


def _fred_csv(series_id: str) -> pd.Series | None:
    """FRED public CSV 직접 다운로드 (API key 불필요)."""
    try:
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
        df = pd.read_csv(url)
        # 첫 컬럼=DATE, 두번째=값. 결측은 '.' 으로 들어옴.
        date_col, val_col = df.columns[0], df.columns[1]
        df[val_col] = pd.to_numeric(df[val_col], errors='coerce')
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        s = df.dropna(subset=[date_col, val_col]).set_index(date_col)[val_col].astype(float)
        s.name = series_id
        return s.sort_index()
    except Exception as e:
        print(f'[valuation_signal] FRED {series_id} fetch 실패: {e}')
        return None


def _wb_gdp_usa() -> pd.Series | None:
    """World Bank API → USA 연간 GDP (current US$, $ 단위). 일별 인덱스 변환 후 ffill 용 시리즈."""
    try:
        import urllib.request, json as _json
        url = 'https://api.worldbank.org/v2/country/USA/indicator/NY.GDP.MKTP.CD?format=json&date=2005:2027&per_page=50'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = _json.load(r)
        if not isinstance(payload, list) or len(payload) < 2:
            return None
        recs = payload[1] or []
        rows = [(int(r['date']), float(r['value']) / 1e9)  # → billions
                for r in recs if r.get('value') is not None]
        if not rows:
            return None
        rows.sort()
        # 연간 데이터를 해당 연도 1월 1일로 인덱싱
        idx = [pd.Timestamp(year=y, month=1, day=1) for y, _ in rows]
        vals = [v for _, v in rows]
        s = pd.Series(vals, index=pd.DatetimeIndex(idx), name='gdp_b')
        return s.sort_index()
    except Exception as e:
        print(f'[valuation_signal] World Bank GDP fetch 실패: {e}')
        return None


def _yf_wilshire_history(years: int = 15) -> pd.Series | None:
    """yfinance ^W5000 daily close. FRED WILL5000PRFC 와 단위 다름 (index level vs $B)
    이라 비율은 절대 100% 기준과 안 맞지만, z-score 산출용으론 충분."""
    try:
        period = f'{max(years, 2)}y'
        h = yf.Ticker('^W5000').history(period=period, interval='1d', auto_adjust=False)
        if h.empty:
            return None
        s = h['Close'].dropna().astype(float)
        s.name = 'wilshire'
        return s.sort_index()
    except Exception as e:
        print(f'[valuation_signal] yfinance ^W5000 fetch 실패: {e}')
        return None


def _buffett_series(years: int = 15) -> tuple[pd.Series | None, str]:
    """Buffett ratio 일별 시리즈 = market cap / GDP.

    1순위: FRED WILL5000PRFC ($B) / GDP ($B SAAR)
    2순위: yfinance ^W5000 (index level) / World Bank GDP ($B)
            — 단위 다르지만 z-score 산출 + 시계열 추이엔 충분.
    """
    wil_fred = _fred_csv('WILL5000PRFC')
    gdp_fred = _fred_csv('GDP')
    if wil_fred is not None and gdp_fred is not None and not wil_fred.empty and not gdp_fred.empty:
        cutoff = pd.Timestamp(datetime.now() - timedelta(days=years * 365 + 30))
        w = wil_fred[wil_fred.index >= cutoff]
        g = gdp_fred.reindex(w.index, method='ffill')
        ratio = (w / g).dropna()
        if len(ratio) >= 200:
            return ratio, 'fred(WILL5000PRFC/GDP)'

    wil_yf = _yf_wilshire_history(years=years)
    gdp_wb = _wb_gdp_usa()
    if wil_yf is not None and gdp_wb is not None and not wil_yf.empty and not gdp_wb.empty:
        # yfinance index 는 tz-aware → tz-naive 통일
        if wil_yf.index.tz is not None:
            wil_yf = wil_yf.copy()
            wil_yf.index = wil_yf.index.tz_localize(None)
        cutoff = pd.Timestamp(datetime.now() - timedelta(days=years * 365 + 30))
        w = wil_yf[wil_yf.index >= cutoff]
        g = gdp_wb.reindex(w.index, method='ffill')
        ratio = (w / g).dropna()
        if len(ratio) >= 200:
            return ratio, 'yfinance(^W5000)/wb(GDP)'

    return None, 'fallback'


def _compute_buffett_baseline_15y() -> dict:
    """Buffett ratio 15Y 일별 분포. FRED 1순위, yfinance ^W5000+세계은행 GDP 2순위."""
    try:
        ratio, src = _buffett_series(years=15)
        if ratio is None:
            return _FALLBACK_BUFFETT
        return {
            'mean': float(round(ratio.mean(), 4)),
            'std':  float(round(ratio.std(), 4)),
            'n':    int(len(ratio)),
            'source': src + '(15Y)',
        }
    except Exception as e:
        print(f'[valuation_signal] Buffett baseline 실패: {e}')
        return _FALLBACK_BUFFETT


def _compute_trend_baseline_5y() -> dict:
    """^GSPC close/MA200 - 1 5Y daily 분포 (MA200 warmup 위해 ~6Y fetch)."""
    try:
        gspc = yf.Ticker('^GSPC').history(period='6y', interval='1d', auto_adjust=False)
        if gspc.empty or len(gspc) < 400:
            return _FALLBACK_TREND
        close = gspc['Close']
        ma200 = close.rolling(200, min_periods=200).mean()
        gap = (close / ma200 - 1.0).dropna()
        # 최근 5년만 사용
        cutoff = datetime.now() - timedelta(days=5 * 365)
        gap = gap[gap.index >= pd.Timestamp(cutoff, tz=gap.index.tz)] if gap.index.tz else gap[gap.index >= cutoff]
        if len(gap) < 200:
            return _FALLBACK_TREND
        return {
            'mean': float(round(gap.mean(), 6)),
            'std':  float(round(gap.std(), 6)),
            'n':    int(len(gap)),
            'source': 'yfinance(^GSPC_MA200,5Y)',
        }
    except Exception as e:
        print(f'[valuation_signal] Trend baseline 실패: {e}')
        return _FALLBACK_TREND


def get_baselines(force_refresh: bool = False) -> dict:
    """6 baseline 합본 캐시. TTL 90일."""
    if not force_refresh and os.path.exists(_BASELINE_PATH):
        try:
            with open(_BASELINE_PATH, 'r') as f:
                cached = json.load(f)
            ts = datetime.fromisoformat(cached.get('computed_at', '2000-01-01'))
            has_all = all(k in cached for k in ('erp', 'vix', 'dd', 'cape_15y', 'buffett_15y', 'trend'))
            if has_all and datetime.now() - ts < timedelta(days=_BASELINE_TTL_DAYS):
                return cached
        except Exception:
            pass

    out = {
        'erp':        _compute_erp_baseline_5y(),
        'vix':        _compute_vix_baseline_5y(),
        'dd':         _compute_dd_baseline_5y(),
        'cape_15y':   _compute_cape_baseline_15y(),
        'buffett_15y':_compute_buffett_baseline_15y(),
        'trend':      _compute_trend_baseline_5y(),
        'weights': {
            'cape': W_CAPE, 'buffett': W_BUFFETT, 'trend': W_TREND,
            'erp':  W_ERP,  'vix':     W_VIX,     'dd':    W_DD,
        },
        'computed_at': datetime.now().isoformat(),
    }
    real_keys = ('erp', 'vix', 'dd', 'cape_15y', 'buffett_15y', 'trend')
    if all(out[k].get('source') != 'fallback' for k in real_keys):
        os.makedirs(os.path.dirname(_BASELINE_PATH), exist_ok=True)
        with open(_BASELINE_PATH, 'w') as f:
            json.dump(out, f, indent=2)
    return out


# ─────────────────────────────────────────────────────────
# Composite z + label
# ─────────────────────────────────────────────────────────

def _z(value: float, baseline: dict) -> float:
    std = baseline.get('std', 0)
    if std <= 0 or value is None:
        return 0.0
    return (value - baseline['mean']) / std


def compute_composite_z(
    erp: float,
    vix: float,
    dd_60d: float,
    baselines: dict,
    cape: float | None = None,
    buffett_ratio: float | None = None,
    price_vs_ma200: float | None = None,
) -> dict:
    """6-component z + composite z. 부호 컨벤션: 양수 = 저평가/공포 신호.

    cape/buffett/price_vs_ma200 결손 시 해당 component z=0 으로 처리 (가중 합 유지).
    """
    z_erp = _z(erp, baselines['erp'])
    z_vix = _z(vix, baselines['vix'])
    z_dd  = -_z(dd_60d, baselines['dd'])

    z_cape    = -_z(cape, baselines['cape_15y'])      if cape          is not None else 0.0
    z_buffett = -_z(buffett_ratio, baselines['buffett_15y']) if buffett_ratio is not None else 0.0
    z_trend   = -_z(price_vs_ma200, baselines['trend'])      if price_vs_ma200 is not None else 0.0

    z_comp = (W_CAPE  * z_cape +
              W_BUFFETT * z_buffett +
              W_TREND * z_trend +
              W_ERP   * z_erp +
              W_VIX   * z_vix +
              W_DD    * z_dd)
    return {
        'z_cape':    round(z_cape, 4),
        'z_buffett': round(z_buffett, 4),
        'z_trend':   round(z_trend, 4),
        'z_erp':     round(z_erp, 4),
        'z_vix':     round(z_vix, 4),
        'z_dd':      round(z_dd, 4),
        'z_comp':    round(z_comp, 4),
    }


def label_from_z_comp(z_comp: float) -> str:
    if z_comp > 1.0:
        return '명확한 저평가'
    if z_comp > 0.0:
        return '다소 저평가'
    if z_comp > -1.0:
        return '다소 고평가'
    return '명확한 고평가'


def erp_label(erp: float, baseline: dict | None = None) -> str:
    """레거시 호환."""
    if baseline is None:
        baseline = get_baselines()['erp']
    z = _z(erp, baseline)
    return label_from_z_comp(z)


# ─────────────────────────────────────────────────────────
# Buffett ratio (today) helper
# ─────────────────────────────────────────────────────────

def _fetch_buffett_today() -> float | None:
    try:
        ratio, _src = _buffett_series(years=2)
        if ratio is None or ratio.empty:
            return None
        return float(ratio.iloc[-1])
    except Exception as e:
        print(f'[valuation_signal] Buffett today 실패: {e}')
        return None


def _fetch_cape_today(shiller_df: pd.DataFrame | None = None) -> float | None:
    """Shiller 의 가장 최근 CAPE 값. 결손 시 ^GSPC + 10y avg E 로 보강."""
    sh = shiller_df if shiller_df is not None else _load_shiller_df()
    if sh is None or sh.empty:
        return None
    if 'CAPE' in sh.columns:
        s = sh[sh['CAPE'].apply(lambda x: isinstance(x, (int, float)) and x > 0)]
        if not s.empty:
            return float(s['CAPE'].iloc[-1])
    # fallback: 직접 계산
    try:
        last120 = sh.tail(120).copy()
        if last120.empty:
            return None
        avg_e = float(last120['E'].mean())
        last_p = float(last120['P'].iloc[-1])
        if avg_e <= 0:
            return None
        return last_p / avg_e
    except Exception:
        return None


# ─────────────────────────────────────────────────────────
# Daily fetch (today)
# ─────────────────────────────────────────────────────────

def fetch_valuation_signal_today() -> dict | None:
    try:
        spy = yf.Ticker('SPY')
        tnx_info = yf.Ticker('^TNX').info
        vix_info = yf.Ticker('^VIX').info
    except Exception as e:
        print(f'[valuation_signal] yfinance .info 실패: {e}')
        return None

    spy_per = spy.info.get('trailingPE')
    if not spy_per or spy_per <= 0:
        return None
    tnx_price = tnx_info.get('regularMarketPrice') or tnx_info.get('previousClose')
    vix_price = vix_info.get('regularMarketPrice') or vix_info.get('previousClose')
    if not tnx_price or not vix_price:
        return None

    try:
        # MA200 warmup 위해 ~250 거래일 (1y) 확보
        gspc_hist = yf.Ticker('^GSPC').history(period='1y', interval='1d', auto_adjust=False)
        spy_hist  = spy.history(period='3mo', interval='1d', auto_adjust=False)
        if spy_hist.empty or gspc_hist.empty:
            return None
        spy_today_close = float(spy_hist['Close'].iloc[-1])
        spy_60max = float(spy_hist['Close'].tail(60).max())
        dd_60d = spy_today_close / spy_60max - 1.0

        gspc_close = gspc_hist['Close']
        ma200_today = float(gspc_close.tail(200).mean()) if len(gspc_close) >= 200 else None
        gspc_today  = float(gspc_close.iloc[-1])
        price_vs_ma200 = (gspc_today / ma200_today - 1.0) if ma200_today else None
    except Exception as e:
        print(f'[valuation_signal] today 가격 계산 실패: {e}')
        return None

    earnings_yield = 1.0 / float(spy_per)
    tnx_yield = float(tnx_price) / 100.0
    erp = earnings_yield - tnx_yield
    vix = float(vix_price)

    cape_val    = _fetch_cape_today()
    buffett_val = _fetch_buffett_today()

    baselines = get_baselines()
    z = compute_composite_z(
        erp, vix, dd_60d, baselines,
        cape=cape_val,
        buffett_ratio=buffett_val,
        price_vs_ma200=price_vs_ma200,
    )

    return {
        'date': date.today().isoformat(),
        'spy_per': round(float(spy_per), 2),
        'earnings_yield': round(earnings_yield, 4),
        'tnx_yield': round(tnx_yield, 4),
        'erp': round(erp, 4),
        'vix': round(vix, 2),
        'dd_60d': round(dd_60d, 4),
        'cape': round(cape_val, 2) if cape_val is not None else None,
        'buffett_ratio': round(buffett_val, 4) if buffett_val is not None else None,
        'price_vs_ma200': round(price_vs_ma200, 4) if price_vs_ma200 is not None else None,
        **z,
        'label': label_from_z_comp(z['z_comp']),
    }


# ─────────────────────────────────────────────────────────
# Backfill
# ─────────────────────────────────────────────────────────

def backfill_valuation_signal(days: int = 90) -> list[dict]:
    """최근 N 거래일 historical: SPY/^GSPC/TNX/VIX + Shiller CAPE + FRED Buffett 일별 합성.

    - SPY EPS 일정 (오늘 trailingPE 로 역산), 일자별 PER → ERP
    - ^GSPC close / 200d MA 일자별 (warmup 위해 2y fetch)
    - CAPE: Shiller 월별 → 일자별 forward-fill
    - Buffett: WILL5000PRFC 일별 / GDP forward-fill
    - DD60: SPY 일별 rolling
    - 최종 z_comp 에 5d rolling 평활 (스파이크 제거)
    """
    try:
        spy = yf.Ticker('SPY')
        tnx = yf.Ticker('^TNX')
        vix = yf.Ticker('^VIX')
        gspc = yf.Ticker('^GSPC')
        spy_info = spy.info
        spy_per_today = spy_info.get('trailingPE')
        if not spy_per_today or spy_per_today <= 0:
            return []
        years_for_close = max(2, days // 250 + 2)
        period_long  = f'{years_for_close}y'
        period_short = '1y' if days <= 200 else f'{years_for_close}y'
        spy_hist  = spy.history(period=period_short, interval='1d', auto_adjust=False)
        tnx_hist  = tnx.history(period=period_short, interval='1d', auto_adjust=False)
        vix_hist  = vix.history(period=period_short, interval='1d', auto_adjust=False)
        gspc_hist = gspc.history(period=period_long,  interval='1d', auto_adjust=False)
    except Exception as e:
        print(f'[valuation_signal] backfill yfinance 실패: {e}')
        return []

    if spy_hist.empty or tnx_hist.empty or vix_hist.empty or gspc_hist.empty:
        return []

    spy_price_today = float(spy_hist['Close'].iloc[-1])
    eps_now = spy_price_today / float(spy_per_today)

    spy_hist = spy_hist.copy()
    spy_hist['max60'] = spy_hist['Close'].rolling(60, min_periods=1).max()
    spy_hist['dd60']  = spy_hist['Close'] / spy_hist['max60'] - 1.0

    gspc_hist = gspc_hist.copy()
    gspc_hist['ma200'] = gspc_hist['Close'].rolling(200, min_periods=200).mean()
    gspc_hist['gap'] = gspc_hist['Close'] / gspc_hist['ma200'] - 1.0
    gap_map = {idx.date().isoformat(): (None if pd.isna(row['gap']) else float(row['gap']))
               for idx, row in gspc_hist.iterrows()}

    tnx_map = {idx.date().isoformat(): float(row['Close'])
               for idx, row in tnx_hist.iterrows() if row['Close'] > 0}
    vix_map = {idx.date().isoformat(): float(row['Close'])
               for idx, row in vix_hist.iterrows() if row['Close'] > 0}

    # CAPE 월별 → 일별 forward-fill
    sh = _load_shiller_df()
    cape_daily: dict[str, float] = {}
    if sh is not None and 'CAPE' in sh.columns:
        try:
            sh_c = sh[sh['CAPE'].apply(lambda x: isinstance(x, (int, float)) and x > 0)].copy()
            sh_c['ts'] = pd.to_datetime(sh_c['ym'] + '-01', errors='coerce')
            sh_c = sh_c.dropna(subset=['ts']).set_index('ts').sort_index()['CAPE'].astype(float)
            # spy_hist index 와 동일한 일별 인덱스로 reindex + ffill
            daily_idx = pd.DatetimeIndex([pd.Timestamp(d.date()) for d in spy_hist.index])
            sh_aligned = sh_c.reindex(sh_c.index.union(daily_idx)).sort_index().ffill().reindex(daily_idx)
            cape_daily = {idx.date().isoformat(): (None if pd.isna(v) else float(v))
                          for idx, v in zip(daily_idx, sh_aligned.values)}
        except Exception as e:
            print(f'[valuation_signal] CAPE 일별 매핑 실패: {e}')

    # Buffett 일별 (FRED 우선, fallback yfinance ^W5000 + WB GDP)
    buffett_daily: dict[str, float] = {}
    try:
        ratio, _src = _buffett_series(years=max(2, years_for_close))
        if ratio is not None and not ratio.empty:
            buffett_daily = {idx.date().isoformat(): float(v)
                             for idx, v in ratio.items()
                             if pd.notna(v)}
    except Exception as e:
        print(f'[valuation_signal] Buffett 일별 fetch 실패: {e}')

    baselines = get_baselines()

    rows = []
    for idx, row in spy_hist.iterrows():
        d = idx.date().isoformat()
        spy_price = float(row['Close'])
        if spy_price <= 0:
            continue
        tnx_price = tnx_map.get(d)
        vix_price = vix_map.get(d)
        if tnx_price is None or vix_price is None:
            continue
        per_t = spy_price / eps_now
        ey_t  = 1.0 / per_t
        erp_t = ey_t - tnx_price / 100.0
        dd_t  = float(row['dd60'])
        cape_t    = cape_daily.get(d)
        buffett_t = buffett_daily.get(d)
        gap_t     = gap_map.get(d)
        z = compute_composite_z(
            erp_t, vix_price, dd_t, baselines,
            cape=cape_t,
            buffett_ratio=buffett_t,
            price_vs_ma200=gap_t,
        )
        rows.append({
            'date': d,
            'spy_per': round(per_t, 2),
            'earnings_yield': round(ey_t, 4),
            'tnx_yield': round(tnx_price / 100.0, 4),
            'erp': round(erp_t, 4),
            'vix': round(vix_price, 2),
            'dd_60d': round(dd_t, 4),
            'cape': round(cape_t, 2) if cape_t is not None else None,
            'buffett_ratio': round(buffett_t, 4) if buffett_t is not None else None,
            'price_vs_ma200': round(gap_t, 4) if gap_t is not None else None,
            **z,
        })

    if not rows:
        return []

    # 5d rolling 평활 (z_comp 스파이크 제거)
    df = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)
    df['z_comp'] = df['z_comp'].rolling(5, min_periods=1).mean().round(4)
    df['label'] = df['z_comp'].apply(label_from_z_comp)
    out = df.to_dict(orient='records')
    # DataFrame 변환 시 None → NaN 변환된 값 정리 (Supabase JSON serialize NaN 거부)
    import math as _math
    for r in out:
        for k, v in list(r.items()):
            if isinstance(v, float) and _math.isnan(v):
                r[k] = None
    return out[-days:]


# 레거시 호환
def get_erp_baseline(force_refresh: bool = False) -> dict:
    return get_baselines(force_refresh)['erp']
