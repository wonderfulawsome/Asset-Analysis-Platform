import os
import time
import threading
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query
import yfinance as yf
from database.repositories import (
    fetch_fear_greed_latest,
    fetch_index_prices_latest,
    fetch_macro_latest,
    fetch_noise_regime_current,
    fetch_crash_surge_current,
    fetch_crash_surge_history,
    fetch_sector_cycle_latest,
)

router = APIRouter()

_GROQ_MODEL = 'qwen/qwen3-32b'


def _calc_rsi(period: int = 14) -> float:
    """SPY 종가 기반 RSI(14) 실시간 계산."""
    try:
        df = yf.download('SPY', period='2mo', progress=False)
        close = df['Close'].squeeze()
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi.iloc[-1]), 1)
    except Exception:
        return 0


@router.get('/today')
def get_market_summary_today():
    fg = fetch_fear_greed_latest()
    prices = fetch_index_prices_latest()
    score = fg.get('score', 0) if fg else 0
    rating = fg.get('rating', '-') if fg else '-'
    target = {'SPY', 'QQQ', 'DIA'}
    changes = [p['change_pct'] for p in prices if p['ticker'] in target]
    avg_return = sum(changes) / len(changes) if changes else 0
    macro = fetch_macro_latest()
    rsi = macro.get('sp500_rsi') if macro else None
    if not rsi:
        rsi = _calc_rsi()
    else:
        rsi = round(float(rsi), 1)
    return {
        'fear_greed': {'score': round(score), 'rating': rating},
        'market_return': {'value': round(avg_return, 2)},
        'rsi': rsi,
    }


# ═══════════════════════════════════════════════════════════════
# Groq LLM 공통
# ═══════════════════════════════════════════════════════════════

def _groq_call(system_prompt: str, user_text: str, max_tokens: int = 300):
    """Groq API 호출 공통 함수."""
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        all_keys = list(os.environ.keys())
        print(f'[AI] GROQ_API_KEY not found. Total env vars: {len(all_keys)}. Keys containing GROQ/API/SUPA/FRED: {[k for k in all_keys if any(x in k.upper() for x in ("GROQ","API","SUPA","FRED"))]}')
        return None
    from groq import Groq
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )
    raw = completion.choices[0].message.content or ''
    # 혹시 남아있는 <think> 태그 제거
    import re
    raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()
    return raw


def _kst_now_str():
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')


# ═══════════════════════════════════════════════════════════════
# 시장 탭: AI 종합 요약
# ═══════════════════════════════════════════════════════════════

_ai_lock = threading.Lock()
_AI_TTL = 900


def _build_indicator_text(lang='ko'):
    lines = []
    fg = fetch_fear_greed_latest()
    if fg:
        if lang == 'en':
            lines.append(f"Fear & Greed Index: {fg.get('score', '?')} ({fg.get('rating', '?')})")
        else:
            lines.append(f"공포탐욕지수: {fg.get('score', '?')} ({fg.get('rating', '?')})")
    macro = fetch_macro_latest()
    if macro:
        if lang == 'en':
            lines.append(f"S&P500 Daily Return: {macro.get('sp500_return', '?')}%")
            lines.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
            lines.append(f"VIX: {macro.get('vix', '?')}")
            lines.append(f"20D Volatility: {macro.get('sp500_vol20', '?')}")
            lines.append(f"10Y Rate: {macro.get('tnx', '?')}, Yield Spread: {macro.get('yield_spread', '?')}")
            if macro.get('putcall_ratio'):
                lines.append(f"Put/Call Ratio: {macro['putcall_ratio']}")
        else:
            lines.append(f"S&P500 일간수익률: {macro.get('sp500_return', '?')}%")
            lines.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
            lines.append(f"VIX: {macro.get('vix', '?')}")
            lines.append(f"20일 변동성: {macro.get('sp500_vol20', '?')}")
            lines.append(f"10Y금리: {macro.get('tnx', '?')}, 장단기차: {macro.get('yield_spread', '?')}")
            if macro.get('putcall_ratio'):
                lines.append(f"풋콜비율: {macro['putcall_ratio']}")
    regime = fetch_noise_regime_current()
    if regime:
        ns = regime.get('noise_score', 0)
        try:
            ns_val = float(ns)
        except (TypeError, ValueError):
            ns_val = 0
        if lang == 'en':
            if ns_val < -1:
                interp = 'Price well reflects fundamentals'
            elif ns_val < 0:
                interp = 'Minor divergence, mostly reflecting fundamentals'
            elif ns_val < 2:
                interp = 'Divergence between price and fundamentals'
            else:
                interp = 'Significant divergence from fundamentals'
            lines.append(f"Fundamental-Price Divergence Score: {ns} → {interp}")
            lines.append(f"  (Negative = reflecting fundamentals, higher positive = greater divergence)")
        else:
            if ns_val < -1:
                interp = '주가가 펀더멘털을 잘 반영 중'
            elif ns_val < 0:
                interp = '약간의 괴리가 있으나 대체로 반영'
            elif ns_val < 2:
                interp = '주가와 펀더멘털 사이 괴리 존재'
            else:
                interp = '주가와 펀더멘털이 크게 괴리됨'
            lines.append(f"펀더멘털 주가 괴리 점수: {ns} → {interp}")
            lines.append(f"  (음수일수록 펀더멘털 반영, 양수가 클수록 주가가 펀더멘털에서 괴리)")
    cs = fetch_crash_surge_current()
    if cs:
        c_s = cs.get('crash_prob', 0) or 0
        s_s = cs.get('surge_prob', 0) or 0
        gap = round(c_s - s_s, 1)
        if lang == 'en':
            lines.append(f"Crash Risk: {c_s}pts, Surge Potential: {s_s}pts, Gap: {gap:+.1f}pts")
        else:
            lines.append(f"하락 위험도: {c_s}점, 상승 기대도: {s_s}점, 간극: {gap:+.1f}점")
    prices = fetch_index_prices_latest()
    if prices:
        major = [p for p in prices if p.get('ticker') in ('SPY', 'QQQ', 'DIA', 'VOO', 'IWM')]
        for p in major:
            chg = p.get('change_pct', 0)
            sign = '+' if chg >= 0 else ''
            lines.append(f"{p['ticker']}: ${p.get('close', '?')} ({sign}{chg}%)")
    sector = fetch_sector_cycle_latest()
    if sector:
        if lang == 'en':
            lines.append(f"Business Cycle: {sector.get('phase_name', '?')}")
        else:
            lines.append(f"경기국면: {sector.get('phase_name', '?')}")
    return '\n'.join(lines)


_SUMMARY_PROMPTS = {
    'ko': """/no_think
너는 투자자에게 쉽게 설명해주는 한국어 금융 애널리스트다.
주어진 지표를 종합해 시장 브리핑을 작성하라.

반드시 아래 4줄을 출력하라. 각 줄은 반드시 "제목 — 내용" 형식이다.
"—" (em dash) 앞뒤에 반드시 공백을 넣어라. 제목과 내용을 절대 붙여 쓰지 마라.

[이모지] 시장 심리 — (공포탐욕·VIX·RSI를 종합한 심리 해석 1문장)
[이모지] 방향성 — (하락 위험도·상승 기대도를 종합한 단기 전망 1문장)
[이모지] 펀더멘털 — (펀더멘털 주가 괴리 점수 기반 주가-펀더멘털 관계 1문장)
[이모지] 종합판단 — (위 3가지를 종합한 결론. 투자자 행동 제안 1문장)

예시:
❄️ 시장 심리 — 공포 지수 19로 극단적 공포 구간이며, 투자 심리가 크게 위축된 상황입니다.
⚖️ 방향성 — 하락 위험은 높지만 순방향 점수가 양수로, 반등 가능성도 열려 있습니다.
🧭 펀더멘털 — 괴리 점수 2.1로 주가와 펀더멘털 사이 괴리가 존재합니다.
🎯 종합판단 — 공포 속 반등 기대가 있어, 분할 매수 관점의 접근이 유효해 보입니다.

이모지 선택:
- 공포/하락: 🔻❄️🌧️⚠️🥶  탐욕/상승: 🔥🚀☀️💪🟢  중립: ⚖️🔄🌤️
- 펀더멘털 괴리: 🧭📉🔍  반영: ✅💎📊  종합: 🎯💡⭐🔑
- 4줄 모두 다른 이모지

규칙:
- 반드시 "제목 — 내용" 형식 (— 앞뒤 공백 필수)
- 숫자를 넣되 해석 위주
- 부드러운 어투 (~입니다, ~보입니다)
- 각 줄 50자 이내
- 마크다운(**볼드** 등) 절대 사용 금지""",

    'en': """/no_think
You are a financial analyst who explains market conditions to investors in plain English.
Synthesize the given indicators into a market briefing.

Output exactly 4 lines. Each line must follow the format: "Title — Content".
Use an em dash "—" with spaces on both sides. Never merge the title and content.

[emoji] Market Sentiment — (1 sentence interpreting Fear & Greed, VIX, RSI)
[emoji] Direction — (1 sentence on short-term outlook from crash risk & surge potential)
[emoji] Fundamentals — (1 sentence on price-fundamental relationship via Divergence Score 0-10)
[emoji] Overall — (1 sentence conclusion combining the above 3, with action suggestion)

Example:
❄️ Market Sentiment — Fear index at 19, deep in extreme fear territory with severely depressed investor sentiment.
⚖️ Direction — Crash risk is high but positive net score suggests a rebound is possible.
🧭 Fundamentals — Divergence score of 2.1 shows a gap between stock prices and fundamentals.
🎯 Overall — With rebound potential amid fear, a dollar-cost averaging approach seems viable.

Emoji choices:
- Fear/decline: 🔻❄️🌧️⚠️🥶  Greed/rise: 🔥🚀☀️💪🟢  Neutral: ⚖️🔄🌤️
- Fundamental divergence: 🧭📉🔍  Aligned: ✅💎📊  Overall: 🎯💡⭐🔑
- Use a different emoji for each line

Rules:
- Strictly "Title — Content" format (spaces around — required)
- Include numbers but focus on interpretation
- Professional yet approachable tone
- Each line under 80 characters
- No markdown (**bold**, etc.) whatsoever""",
}


_ai_cache = {'ko': {'summary': None, 'generated_at': None, 'expires': 0},
             'en': {'summary': None, 'generated_at': None, 'expires': 0}}

_ERR_MSGS = {
    'ko': {'no_data': '지표 데이터가 아직 준비되지 않았습니다.',
           'no_service': 'AI 요약 서비스가 설정되지 않았습니다.',
           'fail': 'AI 요약을 생성할 수 없습니다.'},
    'en': {'no_data': 'Indicator data is not yet available.',
           'no_service': 'AI summary service is not configured.',
           'fail': 'Unable to generate AI summary.'},
}

@router.get('/ai-summary')
def get_ai_summary(lang: str = Query('ko')):
    lang = lang if lang in ('ko', 'en') else 'ko'
    err = _ERR_MSGS[lang]
    now = time.time()
    with _ai_lock:
        c = _ai_cache[lang]
        if c['summary'] and now < c['expires']:
            return {'summary': c['summary'], 'generated_at': c['generated_at'], 'cached': True}
    try:
        text = _build_indicator_text(lang)
        if not text.strip():
            return {'summary': err['no_data'], 'error': True}
        result = _groq_call(_SUMMARY_PROMPTS[lang], text, 400)
        if not result:
            return {'summary': err['no_service'], 'error': True}
        ts = _kst_now_str()
        with _ai_lock:
            _ai_cache[lang].update({'summary': result, 'generated_at': ts, 'expires': now + _AI_TTL})
        return {'summary': result, 'generated_at': ts, 'cached': False}
    except Exception as e:
        print(f'[AI Summary] error: {e}')
        return {'summary': err['fail'], 'error': True}


# ═══════════════════════════════════════════════════════════════
# 각 탭 AI 해설
# ═══════════════════════════════════════════════════════════════

_explain_cache = {}
_explain_lock = threading.Lock()
_EXPLAIN_TTL = 900

_EXPLAIN_PROMPTS = {
    'ko': {
        'fundamental': """/no_think
너는 한국어 금융 해설가다. 주어진 펀더멘털 주가 괴리 분석 결과를 일반 투자자가 이해하도록 쉽게 설명하라.

배경 지식:
- "펀더멘털 주가 괴리 점수"는 주가가 펀더멘털에서 얼마나 벗어났는지를 나타내는 점수다
- 음수(-): 주가가 펀더멘털(기업 가치)을 잘 반영하고 있다는 뜻 (이성적 시장)
- 양수(+): 주가가 펀더멘털에서 벗어나 감정이나 유동성에 의해 움직이고 있다는 뜻 (감정적 시장)
- 양수가 클수록 괴리가 심함 (0~2: 약간 괴리, 2 이상: 큰 괴리)
- 피처(feature)는 이 점수를 구성하는 개별 지표들이다

설명할 내용:
1. 현재 어떤 상태인지 (괴리 점수 값이 의미하는 것)
2. 왜 이런 결과가 나왔는지 (피처 기여도 상위 3개를 쉬운 말로)
3. 투자자에게 어떤 의미인지

규칙:
- 3~4문장, 총 150자 이내
- 전문 용어 사용 시 괄호로 쉬운 설명 추가
- 줄바꿈으로 문단 구분
- 마크다운/불릿 금지
- 부드러운 어투""",

        'signal': """/no_think
너는 한국어 금융 해설가다. 주어진 하락/상승 예측 결과를 일반 투자자가 이해하도록 쉽게 설명하라.

배경 지식:
- "간극(Gap)"은 하락 위험도에서 상승 기대도를 뺀 값이다
- 간극이 양수(+)이면 하락 위험이 더 높고, 음수(-)이면 상승 기대가 더 높다
- 간극의 절대값이 클수록 한쪽으로 강하게 기울어진 것이다
- 30일 추세에서 간극이 확대되면 위험 증가, 축소되면 기회 증가를 의미한다

설명할 내용:
1. 현재 간극이 얼마이고, 어느 쪽으로 기울어져 있는지 (점수 자체보다 간극의 크기와 방향에 집중)
2. 30일간 이 간극이 어떻게 변해왔는지 (확대/축소/안정 추세)
3. 이 간극 추세가 투자자에게 의미하는 바 (SHAP 상위 요인 1~2개 언급)

규칙:
- 3~4문장, 총 150자 이내
- 전문 용어 사용 시 괄호로 쉬운 설명 추가
- 줄바꿈으로 문단 구분
- 마크다운/불릿 금지
- 부드러운 어투""",

        'sector': """/no_think
너는 한국어 금융 해설가다. 주어진 경기 국면 분석 결과를 일반 투자자가 이해하도록 쉽게 설명하라.

설명할 내용:
1. 현재 어떤 경기 국면인지, 이 국면의 특징
2. 이 국면에서 유리한 섹터와 이유
3. 투자자가 참고할 포인트

규칙:
- 3~4문장, 총 150자 이내
- 전문 용어 사용 시 괄호로 쉬운 설명 추가
- 줄바꿈으로 문단 구분
- 마크다운/불릿 금지
- 부드러운 어투""",
    },
    'en': {
        'fundamental': """/no_think
You are a financial commentator. Explain the given Fundamental-Price Divergence analysis in plain English for everyday investors.

Background:
- "Fundamental-Price Divergence Score" measures how far price has deviated from fundamentals
- Negative (-): price reflects fundamentals (company value) well (rational market)
- Positive (+): price has deviated from fundamentals, driven by sentiment or liquidity (emotional market)
- Higher positive = greater divergence (0~2: mild, 2+: significant)
- Features are individual indicators that compose this score

Explain:
1. Current state (what the divergence score value means)
2. Why this result occurred (top 3 feature contributors in plain language)
3. What it means for investors

Rules:
- 3-4 sentences, under 200 characters total
- Add parenthetical explanations for technical terms
- Separate paragraphs with line breaks
- No markdown/bullets
- Professional yet approachable tone""",

        'signal': """/no_think
You are a financial commentator. Explain the given crash/surge prediction results in plain English for everyday investors.

Background:
- "Gap" is crash risk minus surge potential
- Positive gap = tilted toward downside risk; Negative gap = tilted toward upside potential
- Larger absolute gap = stronger tilt in one direction
- A widening 30-day gap trend signals increasing risk; narrowing signals increasing opportunity

Explain:
1. Current gap size and direction (focus on the gap rather than individual scores)
2. How this gap has evolved over the past 30 days (widening/narrowing/stable trend)
3. What this gap trend means for investors (mention 1-2 top SHAP factors)

Rules:
- 3-4 sentences, under 200 characters total
- Add parenthetical explanations for technical terms
- Separate paragraphs with line breaks
- No markdown/bullets
- Professional yet approachable tone""",

        'sector': """/no_think
You are a financial commentator. Explain the given business cycle analysis in plain English for everyday investors.

Explain:
1. Current business cycle phase and its characteristics
2. Which sectors benefit in this phase and why
3. Key takeaways for investors

Rules:
- 3-4 sentences, under 200 characters total
- Add parenthetical explanations for technical terms
- Separate paragraphs with line breaks
- No markdown/bullets
- Professional yet approachable tone""",
    },
}


def _build_explain_text(tab: str, lang: str = 'ko') -> str:
    is_en = (lang == 'en')
    lines = []
    if tab == 'fundamental':
        regime = fetch_noise_regime_current()
        if regime:
            lines.append(f"{'Regime' if is_en else '레짐'}: {regime.get('regime_name', '?')}")
            if is_en:
                lines.append(f"Fundamental-Price Divergence Score: {regime.get('noise_score', '?')}")
            else:
                lines.append(f"펀더멘털 주가 괴리 점수: {regime.get('noise_score', '?')}")
            fc = regime.get('feature_contributions', [])
            if isinstance(fc, str):
                try:
                    fc = json.loads(fc)
                except Exception:
                    fc = []
            if fc:
                lines.append("Feature Contributions:" if is_en else "피처 기여도:")
                for f in sorted(fc, key=lambda x: abs(x.get('contribution', 0)), reverse=True)[:5]:
                    lines.append(f"  {f.get('name', '?')}: {f.get('contribution', '?')}")
            fv = regime.get('feature_values', {})
            if isinstance(fv, str):
                try:
                    fv = json.loads(fv)
                except Exception:
                    fv = {}
            if fv:
                lines.append("Current Values:" if is_en else "현재 지표값:")
                for k, v in list(fv.items())[:6]:
                    lines.append(f"  {k}: {v}")

    elif tab == 'signal':
        cs = fetch_crash_surge_current()
        if cs:
            crash_s = cs.get('crash_prob', 0) or 0
            surge_s = cs.get('surge_prob', 0) or 0
            gap = round(crash_s - surge_s, 1)
            if is_en:
                lines.append(f"Crash Risk: {crash_s}pts ({cs.get('crash_grade', '?')})")
                lines.append(f"Surge Potential: {surge_s}pts ({cs.get('surge_grade', '?')})")
                lines.append(f"Gap (Crash - Surge): {gap:+.1f}pts")
            else:
                lines.append(f"하락 위험도: {crash_s}점 ({cs.get('crash_grade', '?')})")
                lines.append(f"상승 기대도: {surge_s}점 ({cs.get('surge_grade', '?')})")
                lines.append(f"간극 (하락-상승): {gap:+.1f}점")

            # 30일 간극 추세 분석
            history = fetch_crash_surge_history(30)
            if history and len(history) >= 2:
                gaps = []
                for h in reversed(history):  # 오래된 순으로 정렬
                    c_s = (h.get('crash_prob') or h.get('crash_score') or 0)
                    s_s = (h.get('surge_prob') or h.get('surge_score') or 0)
                    gaps.append({'date': h.get('date', '?'), 'gap': round(c_s - s_s, 1)})

                if len(gaps) >= 5:
                    recent_5 = [g['gap'] for g in gaps[-5:]]
                    old_5 = [g['gap'] for g in gaps[:5]]
                    recent_avg = round(sum(recent_5) / len(recent_5), 1)
                    old_avg = round(sum(old_5) / len(old_5), 1)
                    trend_delta = round(recent_avg - old_avg, 1)

                    max_gap = max(gaps, key=lambda g: g['gap'])
                    min_gap = min(gaps, key=lambda g: g['gap'])

                    if is_en:
                        lines.append(f"\n30-Day Gap Trend:")
                        lines.append(f"  Early avg: {old_avg:+.1f} → Recent avg: {recent_avg:+.1f} (change: {trend_delta:+.1f})")
                        lines.append(f"  Max gap: {max_gap['gap']:+.1f} ({max_gap['date']})")
                        lines.append(f"  Min gap: {min_gap['gap']:+.1f} ({min_gap['date']})")
                        if trend_delta > 5:
                            lines.append(f"  Trend: Gap widening toward crash risk")
                        elif trend_delta < -5:
                            lines.append(f"  Trend: Gap narrowing, surge potential increasing")
                        else:
                            lines.append(f"  Trend: Gap stable")
                    else:
                        lines.append(f"\n30일 간극 추세:")
                        lines.append(f"  초기 평균: {old_avg:+.1f} → 최근 평균: {recent_avg:+.1f} (변화: {trend_delta:+.1f})")
                        lines.append(f"  최대 간극: {max_gap['gap']:+.1f} ({max_gap['date']})")
                        lines.append(f"  최소 간극: {min_gap['gap']:+.1f} ({min_gap['date']})")
                        if trend_delta > 5:
                            lines.append(f"  추세: 간극 확대 중 — 하락 위험 쪽으로 기울어지는 중")
                        elif trend_delta < -5:
                            lines.append(f"  추세: 간극 축소 중 — 상승 기대가 높아지는 중")
                        else:
                            lines.append(f"  추세: 간극 안정적 유지")

            shap = cs.get('shap_values', {})
            if isinstance(shap, str):
                try:
                    shap = json.loads(shap)
                except Exception:
                    shap = {}
            for label in ['crash', 'surge']:
                sv = shap.get(label, [])
                if sv:
                    lines.append(f"{label} {'key factors' if is_en else '주요 요인'}:")
                    for s in sv[:3]:
                        lines.append(f"  {s.get('name', '?')}: {s.get('value', '?')}")

    elif tab == 'sector':
        sc = fetch_sector_cycle_latest()
        if sc:
            lines.append(f"{'Business Cycle' if is_en else '경기 국면'}: {sc.get('phase_name', '?')} {sc.get('phase_emoji', '')}")
            ms = sc.get('macro_snapshot', {})
            if isinstance(ms, str):
                try:
                    ms = json.loads(ms)
                except Exception:
                    ms = {}
            if ms:
                lines.append("Macro Snapshot:" if is_en else "매크로 스냅샷:")
                for k, v in list(ms.items())[:5]:
                    lines.append(f"  {k}: {v}")
            top3 = sc.get('top3_sectors', [])
            if top3:
                lines.append("Favorable Sectors:" if is_en else "유리한 섹터:")
                for s in top3[:3]:
                    if isinstance(s, dict):
                        lines.append(f"  {s.get('sector', '?')}: {s.get('return', '?')}%")
                    else:
                        lines.append(f"  {s}")

    return '\n'.join(lines)


_EXPLAIN_ERR = {
    'ko': {'bad_tab': '지원하지 않는 탭입니다.',
           'no_data': '분석 데이터가 아직 준비되지 않았습니다.',
           'no_service': 'AI 해설 서비스가 설정되지 않았습니다.',
           'fail': 'AI 해설을 생성할 수 없습니다.'},
    'en': {'bad_tab': 'Unsupported tab.',
           'no_data': 'Analysis data is not yet available.',
           'no_service': 'AI commentary service is not configured.',
           'fail': 'Unable to generate AI commentary.'},
}

@router.get('/ai-explain')
def get_ai_explain(tab: str = Query(..., description='fundamental, signal, sector'),
                   lang: str = Query('ko')):
    lang = lang if lang in ('ko', 'en') else 'ko'
    err = _EXPLAIN_ERR[lang]
    if tab not in _EXPLAIN_PROMPTS['ko']:
        return {'explanation': err['bad_tab'], 'error': True}

    now = time.time()
    cache_key = f'explain_{tab}_{lang}'
    with _explain_lock:
        cached = _explain_cache.get(cache_key)
        if cached and now < cached.get('expires', 0):
            return {'explanation': cached['text'], 'tab': tab, 'cached': True}

    try:
        text = _build_explain_text(tab, lang)
        if not text.strip():
            return {'explanation': err['no_data'], 'tab': tab, 'error': True}
        result = _groq_call(_EXPLAIN_PROMPTS[lang][tab], text, 300)
        if not result:
            return {'explanation': err['no_service'], 'tab': tab, 'error': True}
        with _explain_lock:
            _explain_cache[cache_key] = {'text': result, 'expires': now + _EXPLAIN_TTL}
        return {'explanation': result, 'tab': tab, 'cached': False}
    except Exception as e:
        print(f'[AI Explain {tab}] error: {e}')
        return {'explanation': err['fail'], 'tab': tab, 'error': True}
