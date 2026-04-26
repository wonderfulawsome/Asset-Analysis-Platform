from collections import defaultdict
from statistics import mean, stdev
from fastapi import APIRouter
from database.repositories import (
    fetch_sector_cycle_latest, fetch_sector_cycle_history, fetch_sector_macro_history,
    fetch_sector_valuation_latest, fetch_sector_valuation_history,
)
from processor.feature7_sector_momentum import compute_sector_momentum

router = APIRouter()


@router.get('/current')
def get_current():
    """최신 경기국면 분석 결과 조회"""
    return fetch_sector_cycle_latest()


@router.get('/holdings-perf')
def get_holdings_perf(tickers: str = 'QQQ,SPY'):
    """사용자 보유종목의 국면별 성과 조회"""
    data = fetch_sector_cycle_latest()
    if not data:
        return None
    ticker_list = [t.strip().upper() for t in tickers.split(',') if t.strip()]
    full_perf = data.get('phase_holding_perf', {})
    filtered = {}
    for phase, perfs in full_perf.items():
        filtered[phase] = {t: perfs[t] for t in ticker_list if t in perfs}
    return {
        'phase_name': data['phase_name'],
        'phase_emoji': data['phase_emoji'],
        'phase_holding_perf': filtered,
    }


@router.get('/history')
def get_history(days: int = 12):
    """최근 N건 경기국면 히스토리 조회"""
    return fetch_sector_cycle_history(days)


@router.get('/macro-history')
def get_macro_history(limit: int = 120):
    """최근 N개월 매크로 지표 히스토리 (10년 = 120개월)"""
    return fetch_sector_macro_history(limit)


# ── 신규 ─────────────────────────────────────────────────────

@router.get('/valuation')
def get_valuation():
    """12개 섹터 ETF 의 PER/PBR + z-score (각 티커의 자기 자신 historical 기준).

    z = (x_today - μ_ticker) / σ_ticker
        μ, σ 는 sector_valuation 테이블에 누적된 같은 ticker 의 과거 시계열로 산출.
        샘플 < HIST_MIN_N 이면 z=null (시계열 부족 → 색 회색).
    양수 = 자기 자신의 historical 평균보다 비쌈, 음수 = 평균보다 쌈.
    """
    HIST_MIN_N = 5  # 시계열 최소 표본 수 — 그 미만이면 z 산출 안 함
    rows = fetch_sector_valuation_latest()
    if not rows:
        return {"phase_name": None, "valuations": []}

    history = fetch_sector_valuation_history(days=365 * 5)  # 최대 5년치
    by_ticker_per: dict[str, list[float]] = defaultdict(list)
    by_ticker_pbr: dict[str, list[float]] = defaultdict(list)
    for h in history:
        if h.get("per") is not None: by_ticker_per[h["ticker"]].append(h["per"])
        if h.get("pbr") is not None: by_ticker_pbr[h["ticker"]].append(h["pbr"])

    def z(x, samples):
        if x is None or len(samples) < HIST_MIN_N: return None
        m, s = mean(samples), stdev(samples) if len(samples) >= 2 else 0
        if not s: return None
        return round((x - m) / s, 2)

    out = []
    for r in rows:
        per = r.get("per"); pbr = r.get("pbr")
        out.append({
            "ticker": r["ticker"],
            "sector_name": r.get("sector_name"),
            "per": per,
            "pbr": pbr,
            "per_z": z(per, by_ticker_per.get(r["ticker"], [])),
            "pbr_z": z(pbr, by_ticker_pbr.get(r["ticker"], [])),
            "hist_n": len(by_ticker_per.get(r["ticker"], [])),
        })
    return {
        "phase_name": rows[0].get("phase_name"),
        "current_phase": rows[0].get("current_phase"),
        "as_of_date": rows[0].get("date"),
        "hist_min_n": HIST_MIN_N,
        "valuations": out,
    }


# 캐시 — 5분 TTL (계산 비용 없지만 동시 사용자 다발 호출 방어)
import time
_momentum_cache: dict = {"data": None, "ts": 0}
_MOMENTUM_TTL = 300


@router.get('/momentum')
def get_momentum():
    """11개 섹터의 1M·3M·6M 수익률 + 현재 phase 예상 순위 비교."""
    now = time.time()
    if _momentum_cache["data"] and (now - _momentum_cache["ts"]) < _MOMENTUM_TTL:
        return _momentum_cache["data"]
    result = compute_sector_momentum()
    _momentum_cache.update({"data": result, "ts": now})
    return result
