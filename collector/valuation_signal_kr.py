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

# 가중치 — 구조 valuation(per+trend) 0.75, 단기 sentiment(erp+vix+dd) 0.25
# 사용자 요청 "급등 후 평온 시점이 저평가로 잘못 측정됨" 해결 + chart spike 회피.
# VKOSPI proxy(RV) / DD60 의 noise 가 시계열 spike 만들어 sentiment 가중치 축소.
W_PER, W_TREND = 0.45, 0.30       # 구조 valuation (CAPE-like + trend gap) — 0.75
W_ERP, W_VIX, W_DD = 0.10, 0.05, 0.10  # 단기 sentiment — 0.25 (이전 0.40 → 0.25)

# 베이스라인 산출 실패 시 fallback (대략적 historical 값 — 첫 실행 보호용)
_FALLBACK_ERP = {'mean': 0.02, 'std': 0.015, 'n': 0, 'source': 'fallback'}
_FALLBACK_VKOSPI = {'mean': 18.0, 'std': 5.0, 'n': 0, 'source': 'fallback'}
_FALLBACK_DD = {'mean': -0.04, 'std': 0.05, 'n': 0, 'source': 'fallback'}
_FALLBACK_PER_LT = {'mean': 14.0, 'std': 8.0, 'n': 0, 'source': 'fallback'}     # KOSPI 장기 PER ~14, 실측 std 5~10 추정
_FALLBACK_TREND = {'mean': 0.02, 'std': 0.16, 'n': 0, 'source': 'fallback'}     # 평균 +2% 이격, 실측 std 0.16

# PER hard fallback (캐시도 없는 첫 실행 보호용 — KOSPI 장기 평균 ~14)
_HARD_FALLBACK_PER = 14.0


def _load_last_known_per() -> float | None:
    """baseline JSON 에 캐싱된 마지막 정상 KOSPI PER 반환 (없으면 None)."""
    try:
        with open(_BASELINE_PATH) as f:
            data = json.load(f)
        cached = data.get('last_known_per')
        if cached and float(cached) > 0:
            return float(cached)
    except Exception:
        pass
    return None


def _save_last_known_per(per: float) -> None:
    """정상 PER 값을 baseline JSON 에 머지 저장 (다음 실패 시 fallback 으로 사용)."""
    try:
        if not per or per <= 0:
            return
        data = {}
        if os.path.exists(_BASELINE_PATH):
            try:
                with open(_BASELINE_PATH) as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data['last_known_per'] = round(float(per), 2)
        data['last_known_per_updated_at'] = datetime.now().isoformat()
        os.makedirs(os.path.dirname(_BASELINE_PATH), exist_ok=True)
        with open(_BASELINE_PATH, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f'[valuation_kr] last_known_per 저장 실패: {e}')


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


def _compute_kospi_per_baseline_15y() -> dict:
    """KOSPI 일별 PER 의 15Y 분포 — CAPE-style 절대 valuation 앵커.

    사용자 요청 "급등 후 평온 시점이 저평가로 잘못 측정됨" 해결 핵심.
    PER 이 historical 평균 대비 +1σ 면 z_per_cheap = -1 → composite 음수 기여.
    """
    try:
        from pykrx import stock
        end = date.today().strftime('%Y%m%d')
        start = (date.today() - timedelta(days=365 * 15 + 30)).strftime('%Y%m%d')
        df = stock.get_index_fundamental(start, end, '1001')
        if df is None or df.empty:
            return _FALLBACK_PER_LT
        per = df['PER'].replace(0, np.nan).dropna()
        cutoff = pd.Timestamp(date.today() - timedelta(days=365 * 15))
        per = per[per.index >= cutoff]
        if len(per) < 200:
            print(f'[valuation_kr] PER 15Y baseline 표본 부족: {len(per)}')
            return _FALLBACK_PER_LT
        return {'mean': float(per.mean()), 'std': float(per.std()),
                'n': int(len(per)), 'source': 'pykrx_15y'}
    except Exception as e:
        print(f'[valuation_kr] PER 15Y baseline 실패: {e}')
        return _FALLBACK_PER_LT


def _compute_kospi_trend_baseline_5y() -> dict:
    """KOSPI close / 200d MA - 1 의 5Y 분포 — 추세 대비 가격 위치 신호.

    +이면 추세 위(상승 모멘텀/과열 가능), -이면 추세 아래(부진).
    """
    try:
        close = _kospi_close_dual(years=6)  # MA200 warmup 위해 +1Y 여유
        if close.empty:
            return _FALLBACK_TREND
        ma200 = close.rolling(200).mean()
        gap = (close / ma200 - 1.0).dropna()
        cutoff = pd.Timestamp(date.today() - timedelta(days=365 * 5))
        gap = gap[gap.index >= cutoff]
        if len(gap) < 200:
            return _FALLBACK_TREND
        return {'mean': float(gap.mean()), 'std': float(gap.std()),
                'n': int(len(gap)), 'source': 'kospi_ma200_5y'}
    except Exception as e:
        print(f'[valuation_kr] TREND baseline 실패: {e}')
        return _FALLBACK_TREND


def get_kr_baselines(force_refresh: bool = False) -> dict:
    """5 baseline 합본 + JSON 디스크 캐시 (TTL 90일).

    이전 3-baseline 스키마(erp/vix/dd) 캐시는 자동 무효화 — per_15y / trend 키
    누락 시 force-refresh 와 동일하게 재계산.
    """
    if not force_refresh and os.path.exists(_BASELINE_PATH):
        try:
            with open(_BASELINE_PATH) as f:
                cached = json.load(f)
            updated = datetime.fromisoformat(cached.get('updated_at', '2000-01-01'))
            has_new_schema = 'per_15y' in cached and 'trend' in cached
            if has_new_schema and (datetime.now() - updated).days < _BASELINE_TTL_DAYS:
                return cached
        except Exception:
            pass

    bundle = {
        'erp':     _compute_kr_erp_baseline_5y(),
        'vix':     _compute_vkospi_baseline_5y(),
        'dd':      _compute_kr_dd_baseline_5y(),
        'per_15y': _compute_kospi_per_baseline_15y(),
        'trend':   _compute_kospi_trend_baseline_5y(),
        'updated_at': datetime.now().isoformat(),
        'weights': {
            'per_15y': W_PER, 'trend': W_TREND,
            'erp': W_ERP, 'vix': W_VIX, 'dd': W_DD,
        },
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


def compute_composite_z(
    erp: float,
    vix: float,
    dd_60d: float,
    baselines: dict,
    kospi_per: float | None = None,
    price_vs_ma200: float | None = None,
) -> dict:
    """5-요소 합산 z. 모두 양수 = 저평가 방향.

    추가 항목 (절대 valuation 앵커):
      - z_per:   PER 15Y 평균 대비 현재 PER. 부호 반전(높은 PER=비쌈→음수 기여).
      - z_trend: 가격 vs 200d MA. 부호 반전(이격 큰 양수=비쌈→음수 기여).
    이 둘이 추가되어 단기 sentiment(erp+vix+dd) 만으로 "급등 후 평온 = 저평가"
    오판하던 문제 해결. kospi_per / price_vs_ma200 미전달 시 0 기여 (backward compat).
    """
    z_erp = _z(erp, baselines['erp'])
    z_vix = _z(vix, baselines['vix'])
    z_dd = -_z(dd_60d, baselines['dd'])  # DD 더 음수 → z↑
    # PER, TREND — 부호 반전 (높은 값 = 비쌈 = 저평가 음수)
    z_per = -_z(kospi_per, baselines.get('per_15y', _FALLBACK_PER_LT)) if kospi_per is not None else 0.0
    z_trend = -_z(price_vs_ma200, baselines.get('trend', _FALLBACK_TREND)) if price_vs_ma200 is not None else 0.0
    z_comp = (W_PER * z_per + W_TREND * z_trend
              + W_ERP * z_erp + W_VIX * z_vix + W_DD * z_dd)
    return {
        'z_per': round(z_per, 4),
        'z_trend': round(z_trend, 4),
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
        # KOSPI PER fallback 체인: pykrx → DART 시총가중 → 캐시 → 14.0
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
            print(f'[valuation_kr] PER pykrx 실패: {e}')
        # DART fallback — pykrx 차단 시 KOSPI200 시총가중 시장 PER (24h 캐시)
        if not kospi_per or kospi_per <= 0:
            try:
                from collector.dart_fundamentals import compute_kospi_market_per_dart
                dart_result = compute_kospi_market_per_dart()
                if dart_result and dart_result.get('per') and dart_result['per'] > 0:
                    kospi_per = dart_result['per']
                    print(f"[valuation_kr] PER fallback (DART KOSPI200 시총가중 {kospi_per:.2f}, "
                          f"cov {dart_result['coverage']*100:.0f}%, n={dart_result['n_per']}) 사용")
            except Exception as e:
                print(f'[valuation_kr] DART PER fallback 실패: {e}')
        if not kospi_per or kospi_per <= 0:
            cached = _load_last_known_per()
            if cached:
                kospi_per = cached
                print(f'[valuation_kr] PER fallback (캐싱된 마지막 정상값 {cached:.2f}) 사용')
            else:
                kospi_per = _HARD_FALLBACK_PER
                print(f'[valuation_kr] PER fallback ({_HARD_FALLBACK_PER}, 캐시 없음) 사용')
        else:
            _save_last_known_per(kospi_per)

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

        # Trend gap — 가격 vs 200d MA. close 시리즈는 이미 1Y 분이라 200d MA 계산 가능.
        # close 가 200일 이상이면 마지막 200일 평균. 미만이면 None (z_trend 0 기여).
        price_vs_ma200 = None
        if len(close) >= 200:
            ma200 = float(close.tail(200).mean())
            if ma200 > 0:
                price_vs_ma200 = kospi_today / ma200 - 1.0

        baselines = get_kr_baselines()
        z = compute_composite_z(
            erp, vix, dd_60d, baselines,
            kospi_per=kospi_per,
            price_vs_ma200=price_vs_ma200,
        )

        return {
            'date': date.today().isoformat(),
            'spy_per': round(kospi_per, 2),         # 컬럼명은 그대로 (의미: KOSPI PER)
            'earnings_yield': round(earnings_yield, 4),
            'tnx_yield': round(tnx_yield, 4),
            'erp': round(erp, 4),
            'vix': round(vix, 2),                   # 의미: VKOSPI
            'dd_60d': round(dd_60d, 4),
            'price_vs_ma200': round(price_vs_ma200, 4) if price_vs_ma200 is not None else None,
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

    # KOSPI 종가 — pykrx → FDR → yfinance 폴백.
    # 200d MA warmup 위해 최소 2년 — 기존 1년은 첫 ~150일 trend NaN → z_trend=0 기여 →
    # 그 날만 z_comp 양수 spike. tail(days) 추출 전에 충분한 warmup 확보.
    years_for_close = max(2, (period_days // 365) + 2)
    close = _kospi_close_dual(years=years_for_close)
    if close.empty:
        print('[valuation_kr] KOSPI close 비어있음 — backfill 중단')
        return []

    # KOSPI PER backfill 체인: pykrx → DART 시총가중 (오늘자 평탄) → 캐시 → 14.0
    per_series = None
    try:
        from pykrx import stock
        fund = stock.get_index_fundamental(start.strftime('%Y%m%d'),
                                            end.strftime('%Y%m%d'), '1001')
        if fund is not None and not fund.empty and 'PER' in fund.columns:
            per_series = fund['PER'].replace(0, np.nan)
    except Exception as e:
        print(f'[valuation_kr] PER pykrx 실패: {e}')
    # DART fallback — KOSPI200 시총가중. backfill 은 오늘자 시장 PER 을 평탄 적용 (24h 캐시)
    if per_series is None or per_series.empty:
        try:
            from collector.dart_fundamentals import compute_kospi_market_per_dart
            dart_result = compute_kospi_market_per_dart()
            if dart_result and dart_result.get('per') and dart_result['per'] > 0:
                per_series = pd.Series(dart_result['per'], index=close.index)
                print(f"[valuation_kr] PER backfill (DART KOSPI200 시총가중 {dart_result['per']:.2f}, "
                      f"cov {dart_result['coverage']*100:.0f}%, 평탄) 사용")
        except Exception as e:
            print(f'[valuation_kr] DART PER backfill 실패: {e}')
    if per_series is None or per_series.empty:
        cached = _load_last_known_per()
        fallback_per = cached if cached else _HARD_FALLBACK_PER
        per_series = pd.Series(fallback_per, index=close.index)
        src = '캐싱된 마지막 정상값' if cached else f'하드 fallback {_HARD_FALLBACK_PER}'
        print(f'[valuation_kr] PER fallback ({src}, {fallback_per:.2f} 평탄) 사용')
    else:
        # 정상 PER 마지막 값 → 캐시 갱신 (다음 실패 시 활용)
        last_valid = per_series.dropna()
        if not last_valid.empty:
            _save_last_known_per(float(last_valid.iloc[-1]))

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

    # 200d MA gap — backfill 도 동일 신호 제공 위해 추가 (warmup 200일 필요)
    ma200 = close.rolling(200).mean()
    trend = (close / ma200 - 1.0)

    # 5-comp 용 PER 시계열 — pykrx fundamental 의 일별 PER (실패 시 평탄 fallback).
    # spike 방지: PER 미산출일은 z_per=0 으로 빠지면 그 날만 z_comp 양수로 솟구침.
    # → DART 단발 평탄값 또는 캐시된 last-known PER 로 close.index 평탄 시리즈 강제.
    kospi_per_series = None
    try:
        from pykrx import stock
        fund = stock.get_index_fundamental(start.strftime('%Y%m%d'), end.strftime('%Y%m%d'), '1001')
        if fund is not None and not fund.empty and 'PER' in fund.columns:
            kospi_per_series = fund['PER'].replace(0, np.nan)
            kospi_per_series = kospi_per_series.reindex(close.index).ffill().bfill()
    except Exception as e:
        print(f'[valuation_kr] backfill PER 시계열(pykrx) 실패: {e}')
    if kospi_per_series is None or kospi_per_series.dropna().empty:
        flat_per = None
        try:
            from collector.dart_fundamentals import compute_kospi_market_per_dart
            dart_result = compute_kospi_market_per_dart()
            if dart_result and dart_result.get('per') and dart_result['per'] > 0:
                flat_per = float(dart_result['per'])
                print(f"[valuation_kr] backfill PER fallback (DART KOSPI200 시총가중 {flat_per:.2f}, 평탄) 사용")
        except Exception as e:
            print(f'[valuation_kr] backfill DART PER fallback 실패: {e}')
        if flat_per is None:
            flat_per = _load_last_known_per() or _HARD_FALLBACK_PER
            print(f'[valuation_kr] backfill PER fallback (last_known/hard {flat_per}, 평탄) 사용')
        kospi_per_series = pd.Series(flat_per, index=close.index)

    # 시계열 결합 (날짜 인덱스 정렬, forward-fill 으로 비거래일 보간)
    components = [
        close.rename('close'),
        ey.rename('ey'),
        tnx_yield.rename('tnx'),
        vix_series.rename('vix'),
        dd.rename('dd'),
        trend.rename('trend'),
        kospi_per_series.rename('kospi_per'),     # 항상 채워진 PER 시리즈 (위에서 fallback 보장)
    ]
    df = pd.concat(components, axis=1).ffill().bfill().dropna(subset=['close', 'ey', 'tnx', 'vix', 'dd'])

    df['erp'] = df['ey'] - df['tnx']

    # 최근 days 만 추출
    df = df.tail(days)

    baselines = get_kr_baselines()
    rows = []
    for idx, r in df.iterrows():
        # backfill 도 PER + trend 인자 전달 — 컬럼 없거나 NaN 면 None 으로 0 기여
        per_val = r.get('kospi_per') if 'kospi_per' in df.columns else None
        if per_val is not None and (pd.isna(per_val) or per_val <= 0):
            per_val = None
        trend_val = r.get('trend')
        if trend_val is not None and pd.isna(trend_val):
            trend_val = None
        z = compute_composite_z(float(r['erp']), float(r['vix']),
                                 float(r['dd']), baselines,
                                 kospi_per=float(per_val) if per_val is not None else None,
                                 price_vs_ma200=float(trend_val) if trend_val is not None else None)
        # spy_per — kospi_per_series 가 항상 채워져 있어 row.kospi_per 그대로 사용
        spy_per_val = round(float(per_val), 2) if per_val is not None else 0.0
        rows.append({
            'date': idx.strftime('%Y-%m-%d'),
            'spy_per': spy_per_val,
            'earnings_yield': round(float(r['ey']), 4),
            'tnx_yield': round(float(r['tnx']), 4),
            'erp': round(float(r['erp']), 4),
            'vix': round(float(r['vix']), 2),
            'dd_60d': round(float(r['dd']), 4),
            'price_vs_ma200': round(float(trend_val), 4) if trend_val is not None else None,
            **z,
            'label': label_from_z_comp(z['z_comp']),
        })

    # z_comp history 5일 rolling smoothing — 잔존 sentiment noise spike 제거.
    # raw z_per/z_trend/z_erp/z_vix/z_dd 는 그대로 유지, 합산 z_comp + label 만 평탄화.
    # fetch_today (single point) 는 smoothing 안 함 — 차트 끝 1점 약간의 차이는 허용.
    if rows:
        zc_series = pd.Series([r['z_comp'] for r in rows])
        zc_smoothed = zc_series.rolling(5, min_periods=1).mean().round(4)
        for i, r in enumerate(rows):
            r['z_comp'] = float(zc_smoothed.iloc[i])
            r['label'] = label_from_z_comp(r['z_comp'])
    return rows
