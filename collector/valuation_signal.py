"""ERP + Composite Z (A1+C7) — 시장 고/저평가 신호.

라벨링 = composite z-score 기반 (단순 ERP z 한계를 보완):
    z_comp = 0.4 · z_ERP(5Y) + 0.3 · z_VIX(5Y) + 0.3 · z_DD60(5Y)

각 component (모두 양수 = "저평가/공포" 방향으로 통일):
- z_ERP : (ERP_today - 5Y monthly mean) / 5Y monthly std    (ERP↑ → z↑)
- z_VIX : (VIX_today - 5Y daily mean) / 5Y daily std         (VIX↑ → z↑, 공포=contrarian 저평가)
- z_DD  : -(DD60_today - 5Y daily mean) / 5Y daily std       (drawdown 더 음수 → z↑)

라벨 (z_comp 기반):
- z > +1.0 : 명확한 저평가
- 0 ~ +1.0 : 다소 저평가
- -1.0 ~ 0 : 다소 고평가
- z < -1.0 : 명확한 고평가

배경: 단독 ERP z 는 가격 충격에 둔감 (trailing PE stale + flight-to-safety 가
TNX 도 같이 떨어뜨려 상쇄). VIX·drawdown 합성으로 위기 reactive 신호 보강.
미-이란 전쟁(2026-02-28) backtest 에서 prod 15Y "명확한 고평가 41/41" →
composite "다소 저평가 20일/41일" 진입 검증 (notebooks/erp_valuation_experiment.ipynb).

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

# Composite weights — 노트북 검증 완료 (max z=+0.84σ, 라벨 50% 다소 저평가 진입)
W_ERP, W_VIX, W_DD = 0.4, 0.3, 0.3

_FALLBACK_ERP = {'mean': 0.004, 'std': 0.013, 'n': 0, 'source': 'fallback'}
_FALLBACK_VIX = {'mean': 19.25, 'std': 5.26, 'n': 0, 'source': 'fallback'}
_FALLBACK_DD  = {'mean': -0.0324, 'std': 0.0417, 'n': 0, 'source': 'fallback'}


# ─────────────────────────────────────────────────────────
# Baselines (5Y)
# ─────────────────────────────────────────────────────────

def _compute_erp_baseline_5y() -> dict:
    """Shiller(2010~) + yfinance 보강 → 최근 5년 monthly ERP 분포."""
    try:
        url = 'http://www.econ.yale.edu/~shiller/data/ie_data.xls'
        sh = pd.read_excel(url, sheet_name='Data', skiprows=7)
        sh = sh[['Date', 'P', 'E', 'Rate GS10']].dropna()
        sh = sh[sh['Date'].apply(lambda x: isinstance(x, (int, float)))].copy()
        sh['year'] = sh['Date'].apply(int)
        sh['mo'] = sh['Date'].apply(lambda x: round((x - int(x)) * 100))
        sh['ym'] = sh.apply(lambda r: f'{r.year:04d}-{r.mo:02d}', axis=1)

        cutoff_year = datetime.now().year - 5
        sh5 = sh[sh['year'] >= cutoff_year].copy()
        sh5['ey'] = sh5['E'] / sh5['P']
        sh5['tnx'] = sh5['Rate GS10'] / 100.0
        sh5['erp'] = sh5['ey'] - sh5['tnx']
        erp_series = sh5.set_index('ym')['erp']

        # Shiller 마지막 ~ 오늘 yfinance 보강 (EPS 7%/yr 선형 grow)
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
            print(f'[valuation_signal] ERP baseline 데이터 부족: {len(erp_series)}')
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


def get_baselines(force_refresh: bool = False) -> dict:
    """3 baseline 합본 캐시. TTL 90일."""
    if not force_refresh and os.path.exists(_BASELINE_PATH):
        try:
            with open(_BASELINE_PATH, 'r') as f:
                cached = json.load(f)
            ts = datetime.fromisoformat(cached.get('computed_at', '2000-01-01'))
            if datetime.now() - ts < timedelta(days=_BASELINE_TTL_DAYS):
                return cached
        except Exception:
            pass

    out = {
        'erp':  _compute_erp_baseline_5y(),
        'vix':  _compute_vix_baseline_5y(),
        'dd':   _compute_dd_baseline_5y(),
        'weights': {'erp': W_ERP, 'vix': W_VIX, 'dd': W_DD},
        'computed_at': datetime.now().isoformat(),
    }
    if all(out[k].get('source') != 'fallback' for k in ('erp', 'vix', 'dd')):
        os.makedirs(os.path.dirname(_BASELINE_PATH), exist_ok=True)
        with open(_BASELINE_PATH, 'w') as f:
            json.dump(out, f, indent=2)
    return out


# ─────────────────────────────────────────────────────────
# Composite z + label
# ─────────────────────────────────────────────────────────

def _z(value: float, baseline: dict) -> float:
    std = baseline.get('std', 0)
    if std <= 0:
        return 0.0
    return (value - baseline['mean']) / std


def compute_composite_z(erp: float, vix: float, dd_60d: float, baselines: dict) -> dict:
    """3 component z + composite z. 부호 컨벤션: 양수 = 저평가/공포 신호."""
    z_erp = _z(erp, baselines['erp'])
    z_vix = _z(vix, baselines['vix'])
    z_dd  = -_z(dd_60d, baselines['dd'])     # DD 더 음수 → z↑
    z_comp = W_ERP * z_erp + W_VIX * z_vix + W_DD * z_dd
    return {
        'z_erp':  round(z_erp, 4),
        'z_vix':  round(z_vix, 4),
        'z_dd':   round(z_dd, 4),
        'z_comp': round(z_comp, 4),
    }


def label_from_z_comp(z_comp: float) -> str:
    if z_comp > 1.0:
        return '명확한 저평가'
    if z_comp > 0.0:
        return '다소 저평가'
    if z_comp > -1.0:
        return '다소 고평가'
    return '명확한 고평가'


# 하위 호환 (기존 macro.py 가 import) — 새 라벨 함수로 위임
def erp_label(erp: float, baseline: dict | None = None) -> str:
    """레거시 호환. 새 코드는 label_from_z_comp() 직접 사용."""
    if baseline is None:
        baseline = get_baselines()['erp']
    z = _z(erp, baseline)
    return label_from_z_comp(z)


# ─────────────────────────────────────────────────────────
# Daily fetch (today)
# ─────────────────────────────────────────────────────────

def fetch_valuation_signal_today() -> dict | None:
    """오늘의 SPY PER + TNX yield + VIX + 60일 DD → composite z + label."""
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

    # DD60: SPY 최근 60+ 거래일 fetch (실제론 3mo 면 충분)
    try:
        spy_hist = spy.history(period='3mo', interval='1d', auto_adjust=False)
        if spy_hist.empty:
            return None
        spy_today_close = float(spy_hist['Close'].iloc[-1])
        spy_60max = float(spy_hist['Close'].tail(60).max())
        dd_60d = spy_today_close / spy_60max - 1.0
    except Exception as e:
        print(f'[valuation_signal] DD60 계산 실패: {e}')
        return None

    earnings_yield = 1.0 / float(spy_per)
    tnx_yield = float(tnx_price) / 100.0
    erp = earnings_yield - tnx_yield
    vix = float(vix_price)

    baselines = get_baselines()
    z = compute_composite_z(erp, vix, dd_60d, baselines)

    return {
        'date': date.today().isoformat(),
        'spy_per': round(float(spy_per), 2),
        'earnings_yield': round(earnings_yield, 4),
        'tnx_yield': round(tnx_yield, 4),
        'erp': round(erp, 4),
        'vix': round(vix, 2),
        'dd_60d': round(dd_60d, 4),
        **z,
        'label': label_from_z_comp(z['z_comp']),
    }


# ─────────────────────────────────────────────────────────
# Backfill (60일)
# ─────────────────────────────────────────────────────────

def backfill_valuation_signal(days: int = 60) -> list[dict]:
    """최근 N 거래일 historical: SPY+TNX+VIX 일봉 → daily ERP·DD·z·label.

    가정: SPY EPS 일정 (오늘 기준 trailingPE 로 역산). DD60 은 일자별 rolling.
    """
    try:
        spy = yf.Ticker('SPY')
        tnx = yf.Ticker('^TNX')
        vix = yf.Ticker('^VIX')
        spy_info = spy.info
        spy_per_today = spy_info.get('trailingPE')
        if not spy_per_today or spy_per_today <= 0:
            return []

        # 60일 + 60일 rolling buffer 위해 5mo 이상 필요
        period = '6mo' if days <= 60 else f'{max(2, days // 15 + 2)}mo'
        spy_hist = spy.history(period=period, interval='1d', auto_adjust=False)
        tnx_hist = tnx.history(period=period, interval='1d', auto_adjust=False)
        vix_hist = vix.history(period=period, interval='1d', auto_adjust=False)
    except Exception as e:
        print(f'[valuation_signal] backfill yfinance 실패: {e}')
        return []

    if spy_hist.empty or tnx_hist.empty or vix_hist.empty:
        return []

    spy_price_today = float(spy_hist['Close'].iloc[-1])
    eps_now = spy_price_today / float(spy_per_today)

    # rolling 60일 max (인덱스 보존)
    spy_hist = spy_hist.copy()
    spy_hist['max60'] = spy_hist['Close'].rolling(60, min_periods=1).max()
    spy_hist['dd60']  = spy_hist['Close'] / spy_hist['max60'] - 1.0

    tnx_map = {idx.date().isoformat(): float(row['Close'])
               for idx, row in tnx_hist.iterrows() if row['Close'] > 0}
    vix_map = {idx.date().isoformat(): float(row['Close'])
               for idx, row in vix_hist.iterrows() if row['Close'] > 0}

    baselines = get_baselines()

    out = []
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

        z = compute_composite_z(erp_t, vix_price, dd_t, baselines)
        out.append({
            'date': d,
            'spy_per': round(per_t, 2),
            'earnings_yield': round(ey_t, 4),
            'tnx_yield': round(tnx_price / 100.0, 4),
            'erp': round(erp_t, 4),
            'vix': round(vix_price, 2),
            'dd_60d': round(dd_t, 4),
            **z,
            'label': label_from_z_comp(z['z_comp']),
        })

    return out[-days:]


# 레거시 호환 (외부에서 import 가능)
def get_erp_baseline(force_refresh: bool = False) -> dict:
    return get_baselines(force_refresh)['erp']
