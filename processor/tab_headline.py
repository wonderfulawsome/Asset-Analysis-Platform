"""탭 상단 한 줄 해설 — 룰베이스 (LLM 미사용).

각 탭의 데이터를 *전문 용어 → 실생활 표현* 으로 풀어서 설명.
초보자가 한 문장으로 이 탭이 무엇을 보여주는지 + 오늘 상태가 어떤지 이해.

예: "펀더멘털 주가 갭 상위 4%" (전문) → "실적 대비 주가 상승속도 상위 4% 수준" (풀이)

박스 좌측 칩 "오늘" 이 이미 붙으므로 룰 텍스트는 "오늘" prefix 생략.
자문 회피: "사라/팔아라" 금지, descriptive only.
"""

from datetime import datetime, timezone, timedelta                # 생성 시각 표기용
from typing import Optional                                       # 타입 힌트

from database.repositories import (                               # DB fetch 함수들
    fetch_macro_latest,                                           # 최신 매크로 (RSI, return, VIX, vol20)
    fetch_noise_regime_current,                                   # 최신 Noise 국면
    fetch_sector_cycle_latest,                                    # 최신 경기국면
    fetch_sector_valuation_latest,                                # 최신 섹터 PER/PBR
    fetch_valuation_signal_latest,                                # 최신 시장 밸류 (z_comp, label)
    fetch_anomaly_current,                                        # 최신 이상도 D²
    fetch_chart_predict,                                          # 차트 예측 결과
    fetch_app_cache,                                              # app_cache 조회
    upsert_app_cache,                                             # app_cache 저장
)

# ── 탭 키 정의 (frontend div id 와 1:1 매핑) ─────────────────────
# AI차트/시황 은 자체 카드 위계가 충분 → 헤드라인 박스 제외 (사용자 결정 2026-05-13).
TAB_KEYS = [
    'fundamental',                                                # 펀더멘털
    'signal',                                                     # 시장 이탈도
    'sector',                                                     # 거시경제 / 섹터 사이클
    'sector-val',                                                 # 섹터 밸류에이션
    'sector-mom',                                                 # 섹터 모멘텀
    'market-valuation',                                           # 시장 밸류 (ERP)
]


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'             # 안전 기본값


def _cache_key(region: str) -> str:
    return f"tab_headlines_{_norm_region(region)}"                # app_cache 키 (region 단위 1행)


# ── 룰 1: AI차트 — "5거래일 후 주가가 어떻게 움직일지 예상" ────────
def _headline_chart(region: str) -> str:
    ticker = 'SPY' if region == 'us' else '069500'                # 기준 티커
    name = 'S&P500' if region == 'us' else 'KODEX 200'            # 표시명
    pred = fetch_chart_predict(ticker, region=region)             # 예측 결과 조회
    if not pred:
        return f"{name} 예측 모델 준비 중. 차트와 과거 가격만 확인할 수 있어요."
    actual = pred.get('actual') or []
    predicted = pred.get('predicted') or []
    if not actual or not predicted:
        return f"{name} 예측 데이터 부재. 차트만 확인할 수 있어요."
    last_close = actual[-1].get('close')                          # 최근 실측 종가
    target_idx = min(4, len(predicted) - 1)                       # 5거래일 후 (인덱스 4)
    yhat = predicted[target_idx].get('yhat')                      # 5거래일 후 예측치
    if last_close is None or yhat is None:
        return f"{name} 예측 데이터 일부 결손."
    try:
        pct = (float(yhat) - float(last_close)) / float(last_close) * 100  # 변동률 %
    except (TypeError, ValueError, ZeroDivisionError):
        return f"{name} 예측 계산 실패."
    if pct > 1.0:
        return f"AI 예측: 앞으로 5거래일 동안 {name} 주가가 +{pct:.1f}% 정도 오를 것으로 보고 있어요."
    elif pct < -1.0:
        return f"AI 예측: 앞으로 5거래일 동안 {name} 주가가 {pct:.1f}% 정도 내릴 것으로 보고 있어요."
    else:
        return f"AI 예측: 앞으로 5거래일 동안 {name} 주가가 {pct:+.1f}% 수준의 보합권에 머물 것으로 보고 있어요."


# ── 룰 2: 시황 — "오늘 시장 움직임 + 상승/하락 속도" ─────────
def _headline_market(region: str) -> str:
    macro = fetch_macro_latest(region=region) or {}               # 매크로 1행
    rsi = macro.get('sp500_rsi')                                  # RSI(14)
    ret = macro.get('sp500_return')                               # 일간 수익률
    idx_name = 'S&P500' if region == 'us' else 'KOSPI'            # 표시명
    if rsi is None or ret is None:
        return f"{idx_name} 시황 데이터 적재 중."
    try:
        rsi_f = float(rsi)
        ret_f = float(ret)
    except (TypeError, ValueError):
        return f"{idx_name} 시황 데이터 파싱 실패."
    # RSI 를 사용자 친화 표현 "상승속도" 로 풀이
    if rsi_f >= 70:
        speed = "최근 상승 속도가 매우 빨라 과열 구간"
    elif rsi_f <= 30:
        speed = "최근 하락 속도가 매우 빨라 침체 구간"
    elif rsi_f >= 60:
        speed = "상승 흐름이 우세한 정상 구간"
    elif rsi_f <= 40:
        speed = "하락 흐름이 우세한 정상 구간"
    else:
        speed = "큰 쏠림 없는 평온한 구간"
    return f"{idx_name} 오늘 {ret_f:+.2f}% 움직였어요. {speed}이에요."


# ── 룰 3: 펀더멘털 — "실적 대비 주가 괴리 강도 + 풀이" ──
def _headline_fundamental(region: str) -> str:
    reg = fetch_noise_regime_current(region=region)               # Noise 국면 1행
    if not reg:
        return "펀더멘털 국면 데이터 준비 중."
    score = reg.get('noise_score')                                # 괴리 강도 (음수=괴리, 양수=정합)
    fv = reg.get('feature_values') or {}                          # 8 피처 단위값
    try:
        s = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        s = 0.0
    # fundamental_gap = 실적 대비 주가 괴리 (절댓값 ≈ 표준편차 단위)
    gap = fv.get('fundamental_gap')
    try:
        g = abs(float(gap)) if gap is not None else None
    except (TypeError, ValueError):
        g = None
    gap_phrase = f"(실적-주가 갭 {g:.2f}σ)" if g is not None else ""
    # noise_score 4분위 → 풀이
    if s > 1:
        return f"실적과 주가가 잘 맞물려 움직이는 정합 강한 구간{gap_phrase}. 펀더멘털이 가격에 충분히 반영된 상태이다."
    elif s > 0:
        return f"실적과 주가가 대체로 정합한 구간{gap_phrase}. 큰 괴리 없는 정상 상태이다."
    elif s > -2:
        return f"실적 대비 주가가 약간 따로 움직이는 약한 괴리 구간{gap_phrase}. 펀더멘털과 가격이 부분적으로 분리된 상태이다."
    else:
        return f"실적과 주가가 크게 따로 움직이는 큰 괴리 구간{gap_phrase}. 펀더멘털보다 심리가 가격을 끌고 가는 상태이다."


# ── 룰 4: 평소 이탈도 — "평소 대비 이탈 강도 percentile + 빈도 풀이" ──
def _headline_signal(region: str) -> str:
    an = fetch_anomaly_current(region=region)                     # anomaly_daily 1행
    if not an:
        return "시장 이탈도 데이터 준비 중."
    pct_10y = an.get('percentile_10y')
    if pct_10y is None:
        return "시장 이탈도 데이터 부재."
    try:
        top_pct = round(100 - float(pct_10y), 1)                  # 상위 %로 환산
    except (TypeError, ValueError):
        return "시장 이탈도 데이터 파싱 실패."
    # 출현 빈도 풀이 (top_pct % × 252 거래일 ≈ 1년 중 몇 영업일)
    freq_days = max(1, round(top_pct * 252 / 100))
    if top_pct <= 5:
        return f"시장이 평소 모습에서 벗어난 정도가 상위 {top_pct}% 수준. 최근 10년 중 약 {freq_days}영업일에 한 번꼴로 나타나는 매우 드문 구간이다."
    elif top_pct <= 10:
        return f"시장이 평소에서 벗어난 정도가 상위 {top_pct}% 수준. 최근 10년 중 약 {freq_days}영업일에 한 번꼴로 나타나는 드문 구간이다."
    elif top_pct <= 30:
        return f"시장이 평소에서 벗어난 정도가 상위 {top_pct}% 수준. 평소보다 약간 다른 구간이다."
    else:
        return f"시장이 평소 모습에 가까운 상태 (10년 분포 상위 {top_pct}% 수준). 큰 이탈 없는 정상 구간이다."


# ── 룰 5: 거시경제 / 섹터 사이클 — "경기 위치 + 시장 변동성" ────
_VIX_BASELINE = {'us': 19.2, 'kr': 25.0}                          # 평소 VIX/VKOSPI 기준선


def _headline_sector(region: str) -> str:
    sc = fetch_sector_cycle_latest(region=region)                 # 경기국면 1행
    macro = fetch_macro_latest(region=region) or {}               # VIX 가져오기
    if not sc:
        return "경기국면 데이터 준비 중."
    phase = sc.get('phase_name', '?')
    # 경기국면 풀이 (4단계 회복/확장/둔화/침체)
    phase_meaning = {
        '회복': '경기가 바닥을 지나 회복 흐름에 들어선 회복',
        '확장': '경기가 본격적으로 좋아지는 확장',
        '둔화': '경기 상승세가 꺾여 둔화되는 둔화',
        '침체': '경기가 바닥권에 머무는 침체',
    }.get(phase, phase)
    vix = macro.get('vix')
    vix_name = 'VIX(공포지수)' if region == 'us' else 'VKOSPI(공포지수)'
    base = _VIX_BASELINE[_norm_region(region)]
    if vix is None:
        return f"{phase_meaning} 국면. 변동성 데이터 부재 상태이다."
    try:
        v = float(vix)
    except (TypeError, ValueError):
        return f"{phase_meaning} 국면. 변동성 파싱 실패 상태이다."
    diff_pct = (v - base) / base * 100                            # 평소 대비 변동 %
    if diff_pct > 30:
        vstate = f"{vix_name} {v:.1f}로 평소({base:.0f}) 대비 +{diff_pct:.0f}% 높은 시장 불안감"
    elif diff_pct < -20:
        vstate = f"{vix_name} {v:.1f}로 평소({base:.0f}) 대비 {diff_pct:.0f}% 낮은 안정적 시장"
    else:
        vstate = f"{vix_name} {v:.1f}로 평소({base:.0f}) 수준의 변동성"
    return f"{vstate}. {phase_meaning} 국면이다."


# ── 룰 6: 섹터 밸류에이션 — "비싼 섹터 / 싼 섹터" ──────────────
def _headline_sector_val(region: str) -> str:
    rows = fetch_sector_valuation_latest(region=region)           # 섹터 밸류 최신 행들
    if not rows:
        return "섹터 밸류 데이터 준비 중."
    highs = []                                                    # 고평가 (z>+1)
    lows = []                                                     # 저평가 (z<-1)
    for r in rows:
        z = r.get('per_z') if r.get('per_z') is not None else r.get('per_weighted_z')
        if z is None:
            continue
        try:
            zf = float(z)
        except (TypeError, ValueError):
            continue
        label = r.get('sector_name') or r.get('ticker') or '?'
        if zf > 1:
            highs.append((label, zf))
        elif zf < -1:
            lows.append((label, zf))
    n_high, n_low = len(highs), len(lows)
    if n_high == 0 and n_low == 0:
        return "10년 평균 대비 가격 차이 큰 섹터 0개. 모든 섹터가 평소 가격대에 있는 정상 상태이다."
    parts = []
    if n_high:
        top = max(highs, key=lambda x: x[1])
        parts.append(f"평소보다 비싼 섹터 {n_high}개 (1σ↑, 최고 {top[0]})")
    if n_low:
        bot = min(lows, key=lambda x: x[1])
        parts.append(f"평소보다 싼 섹터 {n_low}개 (1σ↓, 최저 {bot[0]})")
    return "10년 평균 대비 " + ", ".join(parts) + " 상태이다."


# ── 룰 7: 섹터 모멘텀 — "이번 달 가장 많이 오른/내린 섹터" ──────
def _headline_sector_mom(region: str) -> str:
    payload = fetch_app_cache(f"momentum_{_norm_region(region)}")
    if not payload or not isinstance(payload, dict):
        return "섹터 모멘텀 데이터 준비 중."
    mom = payload.get('momentum') or []
    if not mom:
        return "섹터 모멘텀 데이터 준비 중."
    top = mom[0]                                                  # 1위
    bot = mom[-1] if len(mom) > 1 else None                       # 꼴찌
    top_name = top.get('sector_name') or top.get('ticker') or '?'
    top_r = top.get('return_1m')
    if top_r is None:
        return f"이번 달 1위 섹터 {top_name} 상태이다."
    try:
        top_rf = float(top_r)
    except (TypeError, ValueError):
        return f"이번 달 1위 섹터 {top_name} 상태이다."
    if bot is None:
        return f"이번 한 달 1위 섹터 {top_name} ({top_rf:+.1f}%) 상태이다."
    bot_name = bot.get('sector_name') or bot.get('ticker') or '?'
    bot_r = bot.get('return_1m')
    try:
        bot_rf = float(bot_r) if bot_r is not None else 0.0
        spread = abs(top_rf - bot_rf)
        return f"1위 {top_name} {top_rf:+.1f}% vs 꼴찌 {bot_name} {bot_rf:+.1f}%, 섹터 간 격차 {spread:.0f}%p의 양극화 구간이다."
    except (TypeError, ValueError):
        return f"이번 한 달 1위 섹터 {top_name} ({top_rf:+.1f}%) 상태이다."


# ── 룰 8: 시장 밸류 (ERP/Fed Model) — "현 주가가 평소 평균보다 비싼지" ──
def _headline_market_valuation(region: str) -> str:
    v = fetch_valuation_signal_latest(region=region)              # valuation_signal 1행
    if not v:
        return "시장 밸류 데이터 준비 중."
    z = v.get('z_comp')
    label = v.get('label') or ''
    if z is None:
        return f"현 시장 밸류 평가: '{label}'."
    try:
        zf = float(z)
    except (TypeError, ValueError):
        return f"현 시장 밸류 평가: '{label}'."
    # z_comp 를 사용자 친화 표현 "평소 평균 대비 비싼/싼" 으로 풀이
    if zf >= 1.0:
        return f"종합 점수 {zf:+.2f}σ, 평소 평균보다 싼 수준의 '{label}' 영역이다."
    elif zf >= 0.3:
        return f"종합 점수 {zf:+.2f}σ, 평소 평균보다 약간 싼 수준의 '{label}' 영역이다."
    elif zf >= -0.3:
        return f"종합 점수 {zf:+.2f}σ, 평소 평균과 비슷한 수준의 '{label}' 영역이다."
    elif zf >= -1.0:
        return f"종합 점수 {zf:+.2f}σ, 평소 평균보다 약간 비싼 수준의 '{label}' 영역이다."
    else:
        return f"종합 점수 {zf:+.2f}σ, 평소 평균보다 많이 비싼 수준의 '{label}' 영역이다."


# ── 디스패처 ──────────────────────────────────────────────────
# AI차트(_headline_chart) / 시황(_headline_market) 함수는 정의만 유지하고 디스패치 X
# (사용자 결정: 헤드라인 박스를 차트/시황 탭에서 제외 — 다른 카드가 같은 정보 노출).
_RULES = {                                                        # 탭 키 → 룰 함수 매핑
    'fundamental':      _headline_fundamental,
    'signal':           _headline_signal,
    'sector':           _headline_sector,
    'sector-val':       _headline_sector_val,
    'sector-mom':       _headline_sector_mom,
    'market-valuation': _headline_market_valuation,
}


def compute_all(region: str) -> dict:
    """8개 탭 헤드라인 전체 생성. 실패 항목은 fallback 메시지."""
    region = _norm_region(region)
    out: dict = {}
    for key, fn in _RULES.items():
        try:
            text = fn(region)
        except Exception as e:
            print(f"[tab_headline] {key}/{region} 실패: {e}")
            text = "데이터 일시 준비 중."
        out[key] = text
    out['region'] = region
    out['generated_at'] = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')
    return out


def precompute_tab_headlines(region: str) -> bool:
    """스케줄러용 — 8개 탭 한 줄 해설 생성 후 app_cache 1행 upsert.
    endpoint 호출 시 8 RTT (rule 마다 DB select) → 1 RTT (cache select) 로 단축.
    """
    region = _norm_region(region)
    try:
        payload = compute_all(region)
        upsert_app_cache(_cache_key(region), payload)
        return True
    except Exception as e:
        print(f"[tab_headline] precompute {region} 실패: {e}")
        return False


def fetch_tab_headlines(region: str) -> Optional[dict]:
    """endpoint 용 — app_cache 우선, miss 시 live compute 폴백."""
    region = _norm_region(region)
    cached = fetch_app_cache(_cache_key(region))
    if cached and isinstance(cached, dict):
        return {**cached, 'cached': True}
    payload = compute_all(region)
    payload['cached'] = False
    return payload
