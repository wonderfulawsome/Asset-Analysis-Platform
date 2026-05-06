from collections import defaultdict
from statistics import mean, stdev
from fastapi import APIRouter, Query
from database.repositories import (
    fetch_sector_cycle_latest, fetch_sector_cycle_history, fetch_sector_macro_history,
    fetch_sector_valuation_latest, fetch_sector_valuation_history,
    upsert_app_cache, fetch_app_cache,
)
from processor.feature7_sector_momentum import compute_sector_momentum

router = APIRouter()


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'


def _app_cache_key(kind: str, region: str) -> str:
    return f'sector_cycle:{kind}:{region}'


@router.get('/current')
def get_current(region: str = Query('us')):
    """최신 경기국면 분석 결과 조회"""
    return fetch_sector_cycle_latest(region=_norm_region(region))


@router.get('/holdings-perf')
def get_holdings_perf(tickers: str = 'QQQ,SPY', region: str = Query('us')):
    """사용자 보유종목의 국면별 성과 조회"""
    data = fetch_sector_cycle_latest(region=_norm_region(region))
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
def get_history(days: int = 12, region: str = Query('us')):
    """최근 N건 경기국면 히스토리 조회"""
    return fetch_sector_cycle_history(days, region=_norm_region(region))


@router.get('/macro-history')
def get_macro_history(limit: int = 120, region: str = Query('us')):
    """최근 N개월 매크로 지표 히스토리 (10년 = 120개월)"""
    return fetch_sector_macro_history(limit, region=_norm_region(region))


# ── 신규 ─────────────────────────────────────────────────────

def compute_valuation_payload(region: str = 'us') -> dict:
    """12개 섹터 ETF 의 PER/PBR + z-score 사전 계산 payload."""
    region = _norm_region(region)
    HIST_MIN_N = 5  # z-score/% diff 최소 표본 수 — 그 미만이면 색상 판단만 보류
    MEAN_MIN_N = 1  # 평균 칸은 현재까지 누적된 표본이 1개라도 표시
    rows = fetch_sector_valuation_latest(region=region)
    if not rows:
        return {"phase_name": None, "valuations": [], "region": region}

    history = fetch_sector_valuation_history(days=365 * 10, region=region)  # 최대 10년치
    by_ticker_per: dict[str, list[float]] = defaultdict(list)
    by_ticker_pbr: dict[str, list[float]] = defaultdict(list)
    by_ticker_perw: dict[str, list[float]] = defaultdict(list)   # per_weighted 시계열
    for h in history:
        if h.get("per") is not None: by_ticker_per[h["ticker"]].append(h["per"])
        if h.get("pbr") is not None: by_ticker_pbr[h["ticker"]].append(h["pbr"])
        if h.get("per_weighted") is not None: by_ticker_perw[h["ticker"]].append(h["per_weighted"])

    def z(x, samples):
        if x is None or len(samples) < HIST_MIN_N: return None
        m, s = mean(samples), stdev(samples) if len(samples) >= 2 else 0
        if not s: return None
        return round((x - m) / s, 2)

    def diff_pct(x, samples):
        """평균 대비 % 차이. (x - mean) / mean * 100. mean 절대값 너무 작거나 부호 반대면 None."""
        if x is None or len(samples) < HIST_MIN_N: return None
        m = mean(samples)
        if m is None or abs(m) < 0.05: return None   # mean 0 근방이면 % 의미 없음
        if (m > 0 and x < 0) or (m < 0 and x > 0): return None  # 부호 다르면 % 해석 불가
        return round((x - m) / abs(m) * 100, 1)

    def hist_mean(samples):
        if len(samples) < MEAN_MIN_N: return None
        return round(mean(samples), 2)

    out = []
    for r in rows:
        per = r.get("per"); pbr = r.get("pbr"); perw = r.get("per_weighted")
        per_samples = by_ticker_per.get(r["ticker"], [])
        pbr_samples = by_ticker_pbr.get(r["ticker"], [])
        perw_samples = by_ticker_perw.get(r["ticker"], [])
        if region == 'kr':
            if per is not None and not per_samples:
                per_samples = [per]
            if pbr is not None and not pbr_samples:
                pbr_samples = [pbr]
        if perw is not None and not perw_samples:
            perw_samples = [perw]
        out.append({
            "ticker": r["ticker"],
            "sector_name": r.get("sector_name"),
            "per": per,
            "pbr": pbr,
            "per_weighted": perw,                       # ETF 보유종목 trailingPE 가중평균 (US/KR 공통)
            "per_z": z(per, per_samples),
            "pbr_z": z(pbr, pbr_samples),
            "per_mean": hist_mean(per_samples),         # 과거 평균 (10년 history mean)
            "pbr_mean": hist_mean(pbr_samples),
            "per_weighted_mean": hist_mean(perw_samples),
            "per_diff_pct": diff_pct(per, per_samples), # 평균 대비 % 차이 (중립 표시용)
            "pbr_diff_pct": diff_pct(pbr, pbr_samples),
            "per_weighted_diff_pct": diff_pct(perw, perw_samples),
            "hist_n": len(per_samples),
        })
    return {
        "phase_name": rows[0].get("phase_name"),
        "current_phase": rows[0].get("current_phase"),
        "as_of_date": rows[0].get("date"),
        "hist_min_n": HIST_MIN_N,
        "valuations": out,
        "region": region,
    }


def precompute_valuation(region: str = 'us') -> bool:
    """스케줄러용 — 섹터 밸류에이션 응답을 app_cache 에 적재."""
    region = _norm_region(region)
    payload = compute_valuation_payload(region)
    if not payload.get("valuations"):
        return False
    upsert_app_cache(_app_cache_key('valuation', region), payload)
    return True


def _valuation_payload_incomplete(payload, region: str = 'us') -> bool:
    """캐시 payload 가 화면 표를 채우기 부족한지 검사."""
    vals = payload.get("valuations") if isinstance(payload, dict) else None
    if not vals:
        return True
    if all(v.get("per") is None and v.get("per_mean") is None for v in vals):
        return True
    if region == 'kr':
        per_vals = [v.get("per") for v in vals if v.get("per") is not None]
        # 이전 fallback 버그로 모든 섹터가 KOSPI 시장 PER 하나로 동일하게 캐시된 payload 방어.
        if len(per_vals) > 1 and len({round(float(x), 2) for x in per_vals}) == 1:
            return True
    return False


def precompute_momentum(region: str = 'us') -> bool:
    """스케줄러용 — 섹터 모멘텀 응답을 app_cache 에 적재."""
    region = _norm_region(region)
    payload = compute_sector_momentum(region=region)
    if not payload.get("momentum"):
        return False
    upsert_app_cache(_app_cache_key('momentum', region), payload)
    _momentum_cache[region] = {"data": payload, "ts": time.time()}
    return True


@router.get('/valuation')
def get_valuation(region: str = Query('us')):
    """사전 계산된 섹터 ETF PER/PBR + z-score payload 조회.

    스케줄러가 app_cache 에 미리 적재하고, 사용자 요청은 cache select 만 수행.
    캐시 miss (KR 처럼 precompute 미실행 region) 면 즉석 compute fallback.
    """
    region = _norm_region(region)
    payload = fetch_app_cache(_app_cache_key('valuation', region))
    if payload and not _valuation_payload_incomplete(payload, region):
        return payload
    # fallback — DB 최신 row 로 payload 재구성. KR 은 PER/PBR 빈칸을 market fallback 으로 보정.
    payload = compute_valuation_payload(region)
    if payload.get("valuations"):
        try:
            upsert_app_cache(_app_cache_key('valuation', region), payload)
        except Exception:
            pass
    return payload


# 캐시 — 5분 TTL (계산 비용 없지만 동시 사용자 다발 호출 방어). region 별 분리.
import time
_momentum_cache: dict = {}                                     # {region: {data, ts}}
_MOMENTUM_TTL = 300


@router.get('/momentum')
def get_momentum(region: str = Query('us')):
    """사전 계산된 섹터 1주일·1개월 수익률 + 랭킹 조회.

    스케줄러가 app_cache 에 미리 적재하고, 사용자 요청은 cache select 만 수행.
    캐시 miss 면 즉석 compute fallback.
    """
    region = _norm_region(region)
    now = time.time()
    cached = _momentum_cache.get(region)
    if cached and (now - cached["ts"]) < _MOMENTUM_TTL:
        return cached["data"]
    payload = fetch_app_cache(_app_cache_key('momentum', region))
    if payload:
        _momentum_cache[region] = {"data": payload, "ts": now}
        return payload
    # fallback — 즉석 compute
    payload = compute_sector_momentum(region=region)
    if payload and payload.get("momentum"):
        _momentum_cache[region] = {"data": payload, "ts": now}
        try:
            upsert_app_cache(_app_cache_key('momentum', region), payload)
        except Exception:
            pass
        return payload
    return {"as_of_date": None, "momentum": [], "region": region, "cached": False}
