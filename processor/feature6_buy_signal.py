"""매수 타이밍 시그널 (Step A+B+C) — 거래량·가격·인구·금리·인구이동 5변수 기반.

입력:
  - ts: fetch_region_timeseries(sgg_cd) 결과 (region_summary 의 stdg-월 매트릭스;
        같은 stats_ym 에 여러 stdg row 존재 — 함수 내부에서 ym 단위로 group by)
  - rate_ts: fetch_macro_rate_kr() 결과 (선택, 없으면 rate_score=None)
  - flow_ts: fetch_region_migration(sgg_cd) 결과 (선택, 없으면 flow_score=None)

비교 기준 (2026-05-02 변경):
  이번 달(t) 데이터는 월 중 집계라 노이즈 → 이전 달(t-1) 을 비교 기준으로,
  그 이전 모든 달(t-2 … t-N) 평균과 비교.
"""
from collections import defaultdict
from statistics import mean


def _consecutive_trend(values: list[float], end_idx: int) -> int:
    """end_idx 시점 기준 거꾸로 같은 부호 변화가 몇 개월 연속됐는지.

    +N = N개월 연속 상승 / -N = N개월 연속 하락 / 0 = 변화 없음 또는 데이터 부족.
    예: values[0..end_idx] 가 [100, 105, 110, 108] 이고 end_idx=3 이면
        diff = [+5, +5, -2] → end 부호가 음수, 1개월 연속 하락 → -1
    """
    if end_idx < 1:
        return 0
    last_diff = values[end_idx] - values[end_idx - 1]
    if last_diff == 0:
        return 0
    sign = 1 if last_diff > 0 else -1
    count = 0
    for i in range(end_idx, 0, -1):
        d = values[i] - values[i - 1]
        if (d > 0 and sign > 0) or (d < 0 and sign < 0):
            count += 1
        else:
            break
    return sign * count


def _group_ts_by_ym(ts: list[dict]) -> list[dict]:
    """stdg-월 매트릭스 → ym 단위 시군구 시계열 (과거 → 최신).

    trade_count·population sum / median_price_per_py 평균 (법정동 가중 X — 단순 평균).
    """
    by_ym: dict[str, dict] = defaultdict(lambda: {'trade': 0, 'prices': [], 'pop': 0})
    for r in ts:
        ym = r.get('stats_ym')
        if not ym:
            continue
        by_ym[ym]['trade'] += r.get('trade_count') or 0
        if r.get('median_price_per_py'):
            by_ym[ym]['prices'].append(r['median_price_per_py'])
        by_ym[ym]['pop'] += r.get('population') or 0
    out = []
    for ym in sorted(by_ym):
        d = by_ym[ym]
        out.append({
            'ym': ym,
            'trade_count': d['trade'],
            'median_price_per_py': mean(d['prices']) if d['prices'] else 0,
            'population': d['pop'],
        })
    return out


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
    # 이번 달 (t) 데이터는 월 중 집계라 미완성/노이즈 가능 → 이전 달(t-1) 기준으로 비교.
    # 비교 대상 = 그 이전 모든 달(t-2 … t-N) 평균 (거래량·가격 통일).
    # 입력이 stdg-월 매트릭스면 ym 단위로 group by 후 시계열로 변환.
    if ts and ts[0].get('stdg_cd') is not None:
        ts = _group_ts_by_ym(ts)
    if not ts or len(ts) < 3:
        return None

    target = ts[-2]            # 이전 달 (t-1) — 비교 기준
    older = ts[:-2]            # 그 이전 모든 달 (t-2 … t-N)

    # 거래량 변화율 — 이전 달 vs 그 이전 평균
    older_trades = [p.get("trade_count") or 0 for p in older]
    avg_older_trade = mean(older_trades) if older_trades else 0
    trade_chg = _safe_div(
        (target.get("trade_count") or 0) - avg_older_trade, avg_older_trade
    )

    # 가격 변화율 — 이전 달 vs 그 이전 평균 (MoM 아닌 long avg)
    older_prices = [p.get("median_price_per_py") for p in older if p.get("median_price_per_py")]
    avg_older_price = mean(older_prices) if older_prices else 0
    price_mom = _safe_div(
        (target.get("median_price_per_py") or 0) - avg_older_price, avg_older_price
    )

    # 인구 변화율 — 이전 달 vs 그 직전 (단일 비교, 인구 변동 작아 평균 의미 적음)
    earlier = ts[-3] if len(ts) >= 3 else target
    pop_chg = _safe_div(
        (target.get("population") or 0) - (earlier.get("population") or 0),
        earlier.get("population") or 0,
    )

    trade_score = _clamp(trade_chg * 100, -30, 30)
    price_score = _clamp(price_mom * 200, -30, 30)
    pop_score = _clamp(pop_chg * 500, -20, 20)

    # Step B / C — 외부 시계열이 들어오면 점수 추가
    target_ym = target.get("ym")        # 이전 달(t-1) 기준으로 시그널 산출
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

    # 지속성 — t-1 시점 기준 가격·거래량 N개월 연속 추세 + 12개월 평균 대비
    target_idx = len(ts) - 2  # t-1 (target)
    price_series = [r.get("median_price_per_py") or 0 for r in ts]
    trade_series = [r.get("trade_count") or 0 for r in ts]
    price_consec = _consecutive_trend(price_series, target_idx)
    trade_consec = _consecutive_trend(trade_series, target_idx)
    # 거래량 12개월 평균 대비 비율 (1.0 = 같음, 0.5 = 절반, 1.5 = 1.5배)
    long_window = trade_series[max(0, target_idx - 12):target_idx]   # t-1 직전 최대 12개월
    long_avg_trade = mean(long_window) if long_window else 0
    trade_vs_long_ratio = round(target.get("trade_count") / long_avg_trade, 2) if long_avg_trade else None

    breakdown = {
        "trade_chg_pct": round(trade_chg * 100, 2),
        "price_mom_pct": round(price_mom * 100, 2),
        "pop_chg_pct": round(pop_chg * 100, 2),
        # 지속성 (FeatureCard summary 문장 조합용)
        "price_consec_months": price_consec,        # +3 = 3개월 연속 상승, -2 = 2개월 연속 하락
        "trade_consec_months": trade_consec,
        "trade_vs_long_ratio": trade_vs_long_ratio, # t-1 거래량 / 직전 12개월 평균
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
