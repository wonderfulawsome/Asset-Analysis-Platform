"""KR ERP + Composite Z — 한국 시장 고/저평가 신호.

미국 collector/valuation_signal.py 의 KR 등가:
    z_comp = 0.4 · z_ERP_kr(5Y) + 0.3 · z_VKOSPI(5Y) + 0.3 · z_DD60_KOSPI(5Y)

데이터 소스:
- KOSPI PER : pykrx get_index_fundamental('1001')
- KR 10Y    : FinanceDataReader 'KR10YT=RR'
- VKOSPI    : FinanceDataReader 'VKOSPI'
- KOSPI 60d DD : pykrx get_index_ohlcv('1001')  종가 기반

Baseline 캐시: models/valuation_baselines_kr.json (TTL 90일).

라벨·가중치는 US 와 동일 시작 — KR 5Y 분포 확인 후 튜닝 가능.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

_BASELINE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'models',
    'valuation_baselines_kr.json',
)
_BASELINE_TTL_DAYS = 90

# US 와 동일한 가중치 (KR 분포 검증 후 조정 가능)
W_ERP, W_VIX, W_DD = 0.4, 0.3, 0.3

# 베이스라인 산출 실패 시 fallback (대략적 historical 값 — 첫 실행 보호용)
_FALLBACK_ERP = {'mean': 0.02, 'std': 0.015, 'n': 0, 'source': 'fallback'}
_FALLBACK_VKOSPI = {'mean': 18.0, 'std': 5.0, 'n': 0, 'source': 'fallback'}
_FALLBACK_DD = {'mean': -0.04, 'std': 0.05, 'n': 0, 'source': 'fallback'}


# ─────────────────────────────────────────────────────────────────────────────
# Baselines (5Y)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_kr_erp_baseline_5y() -> dict:
    """KOSPI 월별 ERP = (1/PER) - (KR 10Y / 100), 최근 5년 분포."""
    try:
        from pykrx import stock
        import FinanceDataReader as fdr

        end = date.today().strftime('%Y%m%d')
        start = (date.today() - timedelta(days=365 * 5 + 30)).strftime('%Y%m%d')

        # 일별 KOSPI fundamental → 월말 resample
        df = stock.get_index_fundamental(start, end, '1001')
        if df is None or df.empty:
            return _FALLBACK_ERP
        per = df['PER'].replace(0, np.nan).dropna()
        ey = 1.0 / per
        ey_monthly = ey.resample('M').last().dropna()

        # KR 10Y monthly — ECOS 1차, FDR 2차
        tnx_monthly = None
        try:
            from collector.ecos_macro import fetch_kr_treasury_yields
            bundle = fetch_kr_treasury_yields(years=5)
            s = bundle.get('kr_10y')
            if s is not None and not s.empty:
                tnx_monthly = (s / 100.0).resample('M').last().dropna()
        except Exception as e:
            print(f'[valuation_kr] ECOS KR 10Y 실패 → FDR: {e}')
        if tnx_monthly is None:
            tnx_df = fdr.DataReader('KR10YT=RR',
                                     date.today() - timedelta(days=365 * 5 + 30),
                                     date.today())
            if tnx_df is None or tnx_df.empty:
                return _FALLBACK_ERP
            tnx_monthly = (tnx_df['Close'] / 100.0).resample('M').last().dropna()

        # 월별 ERP = EY - tnx (인덱스 정렬)
        joined = pd.concat([ey_monthly, tnx_monthly], axis=1, keys=['ey', 'tnx']).dropna()
        erp = joined['ey'] - joined['tnx']
        # 최근 5년만
        cutoff = pd.Timestamp(date.today() - timedelta(days=365 * 5))
        erp = erp[erp.index >= cutoff]

        if len(erp) < 12:
            print(f'[valuation_kr] ERP baseline 표본 부족: {len(erp)}')
            return _FALLBACK_ERP

        return {
            'mean': float(erp.mean()),
            'std': float(erp.std()),
            'n': int(len(erp)),
            'source': 'pykrx+fdr',
        }
    except Exception as e:
        print(f'[valuation_kr] ERP baseline 실패: {e}')
        return _FALLBACK_ERP


def _compute_vkospi_baseline_5y() -> dict:
    """VKOSPI 5년 일별 분포."""
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader('VKOSPI',
                            date.today() - timedelta(days=365 * 5 + 30),
                            date.today())
        if df is None or df.empty or 'Close' not in df.columns:
            return _FALLBACK_VKOSPI
        s = df['Close'].dropna()
        cutoff = pd.Timestamp(date.today() - timedelta(days=365 * 5))
        s = s[s.index >= cutoff]
        if len(s) < 100:
            return _FALLBACK_VKOSPI
        return {'mean': float(s.mean()), 'std': float(s.std()),
                'n': int(len(s)), 'source': 'fdr'}
    except Exception as e:
        print(f'[valuation_kr] VKOSPI baseline 실패: {e}')
        return _FALLBACK_VKOSPI


def _kospi_close_dual(years: int) -> pd.Series:
    """KOSPI 일별 close — pykrx → FDR(KS11) 폴백."""
    end = date.today()
    start = end - timedelta(days=years * 365 + 90)
    try:
        from pykrx import stock
        df = stock.get_index_ohlcv(start.strftime('%Y%m%d'),
                                    end.strftime('%Y%m%d'), '1001')
        if df is not None and not df.empty:
            return df['종가']
    except Exception:
        pass
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader('KS11', start, end)
        if df is None or df.empty or 'Close' not in df.columns:
            return pd.Series(dtype=float)
        return df['Close']
    except Exception as e:
        print(f'[valuation_kr] KOSPI FDR 폴백 실패: {e}')
        return pd.Series(dtype=float)


def _compute_kr_dd_baseline_5y() -> dict:
    """KOSPI 60일 rolling drawdown 의 5년 분포."""
    try:
        close = _kospi_close_dual(years=5)
        if close.empty:
            return _FALLBACK_DD
        roll_max = close.rolling(60).max()
        dd = (close / roll_max - 1.0).dropna()
        cutoff = pd.Timestamp(date.today() - timedelta(days=365 * 5))
        dd = dd[dd.index >= cutoff]
        if len(dd) < 100:
            return _FALLBACK_DD
        return {'mean': float(dd.mean()), 'std': float(dd.std()),
                'n': int(len(dd)), 'source': 'kospi_dual'}
    except Exception as e:
        print(f'[valuation_kr] DD baseline 실패: {e}')
        return _FALLBACK_DD


def get_kr_baselines(force_refresh: bool = False) -> dict:
    """3 baseline 합본 + JSON 디스크 캐시 (TTL 90일)."""
    if not force_refresh and os.path.exists(_BASELINE_PATH):
        try:
            with open(_BASELINE_PATH) as f:
                cached = json.load(f)
            updated = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
            if (datetime.now() - updated).days < _BASELINE_TTL_DAYS:
                return cached
        except Exception:
            pass

    bundle = {
        'erp': _compute_kr_erp_baseline_5y(),
        'vix': _compute_vkospi_baseline_5y(),
        'dd':  _compute_kr_dd_baseline_5y(),
        'updated_at': datetime.now().isoformat(),
        'weights': {'erp': W_ERP, 'vix': W_VIX, 'dd': W_DD},
    }
    try:
        os.makedirs(os.path.dirname(_BASELINE_PATH), exist_ok=True)
        with open(_BASELINE_PATH, 'w') as f:
            json.dump(bundle, f, indent=2)
    except Exception as e:
        print(f'[valuation_kr] baseline 캐시 저장 실패: {e}')
    return bundle


# ─────────────────────────────────────────────────────────────────────────────
# z 산출 + 라벨
# ─────────────────────────────────────────────────────────────────────────────

def _z(value: float, baseline: dict) -> float:
    std = baseline.get('std', 0)
    if not std:
        return 0.0
    return (value - baseline['mean']) / std


def compute_composite_z(erp: float, vix: float, dd_60d: float, baselines: dict) -> dict:
    """3-요소 합산 z. 모두 양수=저평가/공포 방향."""
    z_erp = _z(erp, baselines['erp'])
    z_vix = _z(vix, baselines['vix'])
    z_dd = -_z(dd_60d, baselines['dd'])  # DD 더 음수 → z↑
    z_comp = W_ERP * z_erp + W_VIX * z_vix + W_DD * z_dd
    return {
        'z_erp': round(z_erp, 4),
        'z_vix': round(z_vix, 4),
        'z_dd': round(z_dd, 4),
        'z_comp': round(z_comp, 4),
    }


def label_from_z_comp(z_comp: float) -> str:
    if z_comp > 1.0:
        return '명확한 저평가'
    if z_comp > 0:
        return '다소 저평가'
    if z_comp > -1.0:
        return '다소 고평가'
    return '명확한 고평가'


# ─────────────────────────────────────────────────────────────────────────────
# Daily fetch
# ─────────────────────────────────────────────────────────────────────────────

def fetch_valuation_signal_today_kr() -> dict | None:
    """오늘의 KOSPI PER + KR 10Y + VKOSPI + DD60 → composite z + label.

    폴백: PER → 14.0, KR 10Y → 3.5%, VKOSPI → KOSPI 20D RV.
    """
    try:
        # KOSPI PER — pykrx 만 지원, 실패시 14.0
        kospi_per = None
        try:
            from pykrx import stock
            end = date.today().strftime('%Y%m%d')
            start = (date.today() - timedelta(days=10)).strftime('%Y%m%d')
            fund = stock.get_index_fundamental(start, end, '1001')
            if fund is not None and not fund.empty:
                pv = fund['PER'].dropna()
                if len(pv) > 0:
                    kospi_per = float(pv.iloc[-1])
        except Exception as e:
            print(f'[valuation_kr] PER fetch 실패: {e}')
        if not kospi_per or kospi_per <= 0:
            print('[valuation_kr] PER fallback 14.0 사용')
            kospi_per = 14.0

        # KOSPI close (60+ days for DD) — pykrx → FDR → yfinance 폴백
        close = _kospi_close_dual(years=1)
        if close.empty or len(close) < 60:
            print('[valuation_kr] KOSPI close 60일 이상 데이터 없음')
            return None
        kospi_today = float(close.iloc[-1])
        kospi_60max = float(close.tail(60).max())
        dd_60d = kospi_today / kospi_60max - 1.0

        # KR 10Y — ECOS 1차, FDR 2차, fallback 3차
        tnx_yield = None
        try:
            from collector.ecos_macro import fetch_kr_treasury_yields
            bundle = fetch_kr_treasury_yields(years=1)
            s = bundle.get('kr_10y')
            if s is not None and not s.empty:
                tnx_yield = float(s.iloc[-1]) / 100.0
                print(f'[valuation_kr] ECOS KR 10Y today {tnx_yield*100:.2f}% 사용')
        except Exception as e:
            print(f'[valuation_kr] ECOS KR 10Y 실패: {e}')
        if tnx_yield is None:
            try:
                import FinanceDataReader as fdr
                tnx_df = fdr.DataReader('KR10YT=RR',
                                         date.today() - timedelta(days=10), date.today())
                if tnx_df is not None and not tnx_df.empty and 'Close' in tnx_df.columns:
                    tnx_yield = float(tnx_df['Close'].iloc[-1]) / 100.0
            except Exception as e:
                print(f'[valuation_kr] KR 10Y FDR 실패: {e}')
        if tnx_yield is None:
            tnx_yield = 0.035
            print('[valuation_kr] KR 10Y fallback 3.5% 사용')

        # VKOSPI — FDR 실패시 KOSPI 20D RV
        vix = None
        try:
            import FinanceDataReader as fdr
            vk_df = fdr.DataReader('VKOSPI',
                                   date.today() - timedelta(days=10), date.today())
            if vk_df is not None and not vk_df.empty and 'Close' in vk_df.columns:
                vix = float(vk_df['Close'].iloc[-1])
        except Exception as e:
            print(f'[valuation_kr] VKOSPI FDR 실패: {e}')
        if vix is None:
            ret = close.pct_change()
            rv = (ret.rolling(20).std() * np.sqrt(252) * 100).dropna()
            if len(rv) > 0:
                vix = float(rv.iloc[-1])
                print(f'[valuation_kr] VKOSPI proxy (KOSPI 20D RV) {vix:.2f} 사용')
            else:
                vix = 18.0  # 마지막 방어선

        earnings_yield = 1.0 / kospi_per
        erp = earnings_yield - tnx_yield

        baselines = get_kr_baselines()
        z = compute_composite_z(erp, vix, dd_60d, baselines)

        return {
            'date': date.today().isoformat(),
            'spy_per': round(kospi_per, 2),         # 컬럼명은 그대로 (의미: KOSPI PER)
            'earnings_yield': round(earnings_yield, 4),
            'tnx_yield': round(tnx_yield, 4),
            'erp': round(erp, 4),
            'vix': round(vix, 2),                   # 의미: VKOSPI
            'dd_60d': round(dd_60d, 4),
            **z,
            'label': label_from_z_comp(z['z_comp']),
        }
    except Exception as e:
        print(f'[valuation_kr] today fetch 실패: {e}')
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Backfill
# ─────────────────────────────────────────────────────────────────────────────

def backfill_valuation_signal_kr(days: int = 90) -> list[dict]:
    """최근 N 영업일 KR 시장 밸류 시계열.

    각 component 별로 try/except 분리 → 일부 실패해도 나머지로 진행. PER 폴백 14.0,
    KR 10Y 폴백 3.5%, VKOSPI 폴백 KOSPI RV.
    """
    period_days = max(days * 2, 180)
    end = date.today()
    start = end - timedelta(days=period_days)

    # KOSPI 종가 — pykrx → FDR → yfinance 폴백
    years_for_close = max(1, (period_days // 365) + 1)
    close = _kospi_close_dual(years=years_for_close)
    if close.empty:
        print('[valuation_kr] KOSPI close 비어있음 — backfill 중단')
        return []

    # KOSPI fundamental (PER) — pykrx 만 지원, 실패시 14.0 평탄 시리즈
    per_series = None
    try:
        from pykrx import stock
        fund = stock.get_index_fundamental(start.strftime('%Y%m%d'),
                                            end.strftime('%Y%m%d'), '1001')
        if fund is not None and not fund.empty and 'PER' in fund.columns:
            per_series = fund['PER'].replace(0, np.nan)
    except Exception as e:
        print(f'[valuation_kr] PER pykrx 실패 → fallback 14.0: {e}')
    if per_series is None or per_series.empty:
        per_series = pd.Series(14.0, index=close.index)
        print('[valuation_kr] PER fallback (14.0 평탄) 사용')

    ey = 1.0 / per_series

    # KR 10Y — ECOS 1차, FDR 2차, fallback 3차
    tnx_yield = None
    try:
        from collector.ecos_macro import fetch_kr_treasury_yields
        years = max(1, (period_days // 365) + 1)
        bundle = fetch_kr_treasury_yields(years=years)
        s = bundle.get('kr_10y')
        if s is not None and not s.empty:
            tnx_yield = (s / 100.0)
            print(f'[valuation_kr] ECOS KR 10Y {len(tnx_yield)}건 사용')
    except Exception as e:
        print(f'[valuation_kr] ECOS KR 10Y 실패: {e}')
    if tnx_yield is None:
        try:
            import FinanceDataReader as fdr
            tnx_df = fdr.DataReader('KR10YT=RR', start, end)
            if tnx_df is not None and not tnx_df.empty and 'Close' in tnx_df.columns:
                tnx_yield = tnx_df['Close'] / 100.0
        except Exception as e:
            print(f'[valuation_kr] KR 10Y FDR 실패: {e}')
    if tnx_yield is None:
        tnx_yield = pd.Series(0.035, index=close.index)
        print('[valuation_kr] KR 10Y fallback 3.5% 사용')

    # VKOSPI — FDR → KOSPI RV proxy
    try:
        import FinanceDataReader as fdr
        vk_df = fdr.DataReader('VKOSPI', start, end)
        if vk_df is None or vk_df.empty or 'Close' not in vk_df.columns:
            raise ValueError('empty')
        vix_series = vk_df['Close']
    except Exception as e:
        print(f'[valuation_kr] VKOSPI FDR 실패 → KOSPI RV proxy: {e}')
        ret = close.pct_change()
        vix_series = (ret.rolling(20).std() * np.sqrt(252) * 100).dropna()

    roll60_max = close.rolling(60).max()
    dd = close / roll60_max - 1.0

    # 4 시계열 결합 (날짜 인덱스 정렬, forward-fill 으로 비거래일 보간)
    df = pd.concat([
        close.rename('close'),
        ey.rename('ey'),
        tnx_yield.rename('tnx'),
        vix_series.rename('vix'),
        dd.rename('dd'),
    ], axis=1).ffill().dropna()

    df['erp'] = df['ey'] - df['tnx']

    # 최근 days 만 추출
    df = df.tail(days)

    baselines = get_kr_baselines()
    rows = []
    for idx, r in df.iterrows():
        z = compute_composite_z(float(r['erp']), float(r['vix']),
                                 float(r['dd']), baselines)
        rows.append({
            'date': idx.strftime('%Y-%m-%d'),
            'spy_per': round(float(per_series.loc[:idx].iloc[-1]), 2),
            'earnings_yield': round(float(r['ey']), 4),
            'tnx_yield': round(float(r['tnx']), 4),
            'erp': round(float(r['erp']), 4),
            'vix': round(float(r['vix']), 2),
            'dd_60d': round(float(r['dd']), 4),
            **z,
            'label': label_from_z_comp(z['z_comp']),
        })
    return rows
