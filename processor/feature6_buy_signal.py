"""매수 타이밍 시그널 (Step A+B+C) — 거래량·가격·인구·금리·인구이동 5변수 기반.

입력:
  - ts: fetch_region_timeseries(sgg_cd) 결과 (월별 시군구 rollup, 과거 → 최근)
  - rate_ts: fetch_macro_rate_kr() 결과 (선택, 없으면 rate_score=None)
  - flow_ts: fetch_region_migration(sgg_cd) 결과 (선택, 없으면 flow_score=None)

향후 확장:
  - Step D: narrative (Groq LLM 해설)
"""
from statistics import mean


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_div(a: float, b: float) -> float:
    """분모 0/None 방어 — 변화율 계산 시 base 가 0이면 0 반환."""
    if not b:
        return 0.0
    return a / b


def _compute_rate_score(rate_ts: list[dict] | None, target_ym: str | None) -> tuple[float | None, dict]:
    """ECOS 시계열 + 타깃월 → rate_score 와 breakdown.

    매수 친화도 =
      (1) 기준금리가 12개월 최고 대비 얼마나 떨어졌는지 (낮을수록 +)
      (2) 주담대 금리 MoM 변화 (떨어지면 +, 오르면 -)
    target_ym 까지의 데이터만 사용 (미래 누설 방지).
    """
    if not rate_ts or not target_ym:
        return None, {}
    # rate_ts 는 date YYYY-MM-DD ASC. target_ym(YYYYMM)에 해당하는 월의 1일 이전까지만
    target_prefix = f"{target_ym[:4]}-{target_ym[4:6]}"
    cutoff_idx = -1
    for i, r in enumerate(rate_ts):
        if r["date"].startswith(target_prefix):
            cutoff_idx = i
            break
    # target 월이 없으면 가장 가까운 과거 사용
    if cutoff_idx < 0:
        cutoff_idx = len(rate_ts) - 1
    window = rate_ts[max(0, cutoff_idx - 11): cutoff_idx + 1]  # 최근 12개월
    if len(window) < 2:
        return 0.0, {}

    base_now = window[-1].get("base_rate")
    base_max = max((r.get("base_rate") or 0) for r in window) or 0
    base_drop = (base_max - (base_now or 0)) / base_max if base_max else 0  # 0~1

    mort_now = window[-1].get("mortgage_rate")
    mort_prev = window[-2].get("mortgage_rate") if len(window) >= 2 else None
    mort_chg = _safe_div((mort_now or 0) - (mort_prev or 0), mort_prev or 0)  # 음수 = 하락

    # 점수: 기준금리 하락폭 *25 + 주담대 MoM 하락폭 *(-1000), 합 클램프 ±25
    score_raw = base_drop * 25 - mort_chg * 1000
    score = _clamp(score_raw, -25, 25)
    return round(score, 1), {
        "base_rate": base_now,
        "base_rate_drop_pct": round(base_drop * 100, 2),
        "mortgage_rate": mort_now,
        "mortgage_rate_mom_pct": round(mort_chg * 100, 3),
    }


def _compute_flow_score(flow_ts: list[dict] | None, target_ym: str | None) -> tuple[float | None, dict]:
    """KOSIS 시계열 + 타깃월 → flow_score (인구 순유입).

    target 월의 net_flow 가 양수면 +, 음수면 −.
    인구 규모 대비 정규화하지 않고 절대값에 가중치 (시군구 인구 수십만이라 net 1000 명도 의미).
    """
    if not flow_ts or not target_ym:
        return None, {}
    cur = next((r for r in flow_ts if r["stats_ym"] == target_ym), None)
    if not cur:
        return 0.0, {}
    net = cur.get("net_flow") or 0
    # net_flow ±1000 → ±10 점 (선형). 큰 절대값은 클램프.
    score = _clamp(net / 100, -20, 20)
    return round(score, 1), {
        "in_count": cur.get("in_count"),
        "out_count": cur.get("out_count"),
        "net_flow": net,
    }


def compute_buy_signal(
    ts: list[dict],
    rate_ts: list[dict] | None = None,
    flow_ts: list[dict] | None = None,
) -> dict | None:
    """월별 시계열 → 매수/관망/주의 시그널.

    Step A 변수만 있어도 동작. rate_ts/flow_ts 는 선택 — 있으면 점수에 합산.
    """
    if not ts or len(ts) < 2:
        return None

    latest = ts[-1]
    prev = ts[-2]

    # 거래량 변화율 — 최근월 vs 직전 평균
    prev_trades = [p.get("trade_count") or 0 for p in ts[:-1]]
    avg_prev_trade = mean(prev_trades) if prev_trades else 0
    trade_chg = _safe_div(
        (latest.get("trade_count") or 0) - avg_prev_trade, avg_prev_trade
    )

    # 가격 MoM
    price_mom = _safe_div(
        (latest.get("median_price_per_py") or 0) - (prev.get("median_price_per_py") or 0),
        prev.get("median_price_per_py") or 0,
    )

    # 인구 변화율
    pop_chg = _safe_div(
        (latest.get("population") or 0) - (prev.get("population") or 0),
        prev.get("population") or 0,
    )

    trade_score = _clamp(trade_chg * 100, -30, 30)
    price_score = _clamp(price_mom * 200, -30, 30)
    pop_score = _clamp(pop_chg * 500, -20, 20)

    # Step B / C — 외부 시계열이 들어오면 점수 추가
    target_ym = latest.get("ym")
    rate_score, rate_brk = _compute_rate_score(rate_ts, target_ym)
    flow_score, flow_brk = _compute_flow_score(flow_ts, target_ym)

    total = trade_score + price_score + pop_score
    if rate_score is not None:
        total += rate_score
    if flow_score is not None:
        total += flow_score

    # 임계값 — 가용 점수 합 ±15 이상이면 매수/주의
    if total >= 15:
        signal = "매수"
    elif total <= -15:
        signal = "주의"
    else:
        signal = "관망"

    breakdown = {
        "trade_chg_pct": round(trade_chg * 100, 2),
        "price_mom_pct": round(price_mom * 100, 2),
        "pop_chg_pct": round(pop_chg * 100, 2),
    }
    breakdown.update(rate_brk)
    breakdown.update(flow_brk)

    return {
        "stats_ym": target_ym,
        "signal": signal,
        "score": round(total, 1),
        "trade_score": round(trade_score, 1),
        "price_score": round(price_score, 1),
        "pop_score": round(pop_score, 1),
        "rate_score": rate_score,
        "flow_score": flow_score,
        "feature_breakdown": breakdown,
        "narrative": None,
    }
