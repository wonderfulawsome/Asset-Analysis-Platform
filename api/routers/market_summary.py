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

_ai_cache = {'summary': None, 'generated_at': None, 'expires': 0}
_ai_lock = threading.Lock()
_AI_TTL = 900


def _build_indicator_text():
    lines = []
    fg = fetch_fear_greed_latest()
    if fg:
        lines.append(f"공포탐욕지수: {fg.get('score', '?')} ({fg.get('rating', '?')})")
    macro = fetch_macro_latest()
    if macro:
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
        if ns_val < -1:
            interp = '주가가 펀더멘털을 잘 반영 중'
        elif ns_val < 0:
            interp = '약간의 괴리가 있으나 대체로 반영'
        elif ns_val < 2:
            interp = '주가와 펀더멘털 사이 괴리 존재'
        else:
            interp = '주가와 펀더멘털이 크게 괴리됨'
        lines.append(f"Noise Score(펀더멘털-주가 괴리 점수): {ns} → {interp}")
        lines.append(f"  (음수일수록 펀더멘털 반영, 양수가 클수록 주가가 펀더멘털에서 괴리)")
    cs = fetch_crash_surge_current()
    if cs:
        lines.append(f"하락 위험도: {cs.get('crash_prob', '?')}점, 상승 기대도: {cs.get('surge_prob', '?')}점, 순방향: {cs.get('net_score', '?')}")
    prices = fetch_index_prices_latest()
    if prices:
        major = [p for p in prices if p.get('ticker') in ('SPY', 'QQQ', 'DIA', 'VOO', 'IWM')]
        for p in major:
            chg = p.get('change_pct', 0)
            sign = '+' if chg >= 0 else ''
            lines.append(f"{p['ticker']}: ${p.get('close', '?')} ({sign}{chg}%)")
    sector = fetch_sector_cycle_latest()
    if sector:
        lines.append(f"경기국면: {sector.get('phase_name', '?')}")
    return '\n'.join(lines)


_SUMMARY_PROMPT = """/no_think
너는 투자자에게 쉽게 설명해주는 한국어 금융 애널리스트다.
주어진 지표를 종합해 시장 브리핑을 작성하라.

반드시 아래 4줄을 출력하라. 각 줄은 반드시 "제목 — 내용" 형식이다.
"—" (em dash) 앞뒤에 반드시 공백을 넣어라. 제목과 내용을 절대 붙여 쓰지 마라.

[이모지] 시장 심리 — (공포탐욕·VIX·RSI를 종합한 심리 해석 1문장)
[이모지] 방향성 — (하락 위험도·상승 기대도를 종합한 단기 전망 1문장)
[이모지] 펀더멘털 — (Noise Score 기반 주가-펀더멘털 관계 1문장)
[이모지] 종합판단 — (위 3가지를 종합한 결론. 투자자 행동 제안 1문장)

예시:
❄️ 시장 심리 — 공포 지수 19로 극단적 공포 구간이며, 투자 심리가 크게 위축된 상황입니다.
⚖️ 방향성 — 하락 위험은 높지만 순방향 점수가 양수로, 반등 가능성도 열려 있습니다.
🧭 펀더멘털 — Noise Score 2.1로 주가와 펀더멘털 사이 괴리가 존재합니다.
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
- 마크다운(**볼드** 등) 절대 사용 금지"""


@router.get('/ai-summary')
def get_ai_summary():
    now = time.time()
    with _ai_lock:
        if _ai_cache['summary'] and now < _ai_cache['expires']:
            return {'summary': _ai_cache['summary'], 'generated_at': _ai_cache['generated_at'], 'cached': True}
    try:
        text = _build_indicator_text()
        if not text.strip():
            return {'summary': '지표 데이터가 아직 준비되지 않았습니다.', 'error': True}
        result = _groq_call(_SUMMARY_PROMPT, text, 400)
        if not result:
            return {'summary': 'AI 요약 서비스가 설정되지 않았습니다.', 'error': True}
        ts = _kst_now_str()
        with _ai_lock:
            _ai_cache.update({'summary': result, 'generated_at': ts, 'expires': now + _AI_TTL})
        return {'summary': result, 'generated_at': ts, 'cached': False}
    except Exception as e:
        print(f'[AI Summary] 오류: {e}')
        return {'summary': 'AI 요약을 생성할 수 없습니다.', 'error': True}


# ═══════════════════════════════════════════════════════════════
# 각 탭 AI 해설
# ═══════════════════════════════════════════════════════════════

_explain_cache = {}
_explain_lock = threading.Lock()
_EXPLAIN_TTL = 900

_EXPLAIN_PROMPTS = {
    'fundamental': """/no_think
너는 한국어 금융 해설가다. 주어진 Noise vs Signal 분석 결과를 일반 투자자가 이해하도록 쉽게 설명하라.

배경 지식:
- Noise Score는 "펀더멘털-주가 괴리 점수"이다
- 음수(-): 주가가 펀더멘털(기업 가치)을 잘 반영하고 있다는 뜻
- 양수(+): 주가가 펀더멘털에서 벗어나 감정이나 유동성에 의해 움직이고 있다는 뜻
- 양수가 클수록 괴리가 심함 (0~2: 약간 괴리, 2 이상: 큰 괴리)
- 피처(feature)는 이 점수를 구성하는 개별 지표들이다

설명할 내용:
1. 현재 어떤 상태인지 (Noise Score 값이 의미하는 것)
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

설명할 내용:
1. 현재 하락 위험도와 상승 기대도가 각각 어느 수준인지
2. 어떤 요인이 가장 크게 작용하고 있는지 (SHAP 상위 3개 중심)
3. 투자자가 주의할 점

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
}


def _build_explain_text(tab: str) -> str:
    lines = []
    if tab == 'fundamental':
        regime = fetch_noise_regime_current()
        if regime:
            lines.append(f"레짐: {regime.get('regime_name', '?')}")
            lines.append(f"Noise Score: {regime.get('noise_score', '?')}")
            fc = regime.get('feature_contributions', [])
            if isinstance(fc, str):
                try:
                    fc = json.loads(fc)
                except Exception:
                    fc = []
            if fc:
                lines.append("피처 기여도:")
                for f in sorted(fc, key=lambda x: abs(x.get('contribution', 0)), reverse=True)[:5]:
                    lines.append(f"  {f.get('name', '?')}: {f.get('contribution', '?')}")
            fv = regime.get('feature_values', {})
            if isinstance(fv, str):
                try:
                    fv = json.loads(fv)
                except Exception:
                    fv = {}
            if fv:
                lines.append("현재 지표값:")
                for k, v in list(fv.items())[:6]:
                    lines.append(f"  {k}: {v}")

    elif tab == 'signal':
        cs = fetch_crash_surge_current()
        if cs:
            lines.append(f"하락 위험도: {cs.get('crash_prob', '?')}점 ({cs.get('crash_grade', '?')})")
            lines.append(f"상승 기대도: {cs.get('surge_prob', '?')}점 ({cs.get('surge_grade', '?')})")
            lines.append(f"순방향 점수: {cs.get('net_score', '?')}")
            shap = cs.get('shap_values', {})
            if isinstance(shap, str):
                try:
                    shap = json.loads(shap)
                except Exception:
                    shap = {}
            for label in ['crash', 'surge']:
                sv = shap.get(label, [])
                if sv:
                    lines.append(f"{label} 주요 요인:")
                    for s in sv[:3]:
                        lines.append(f"  {s.get('name', '?')}: {s.get('value', '?')}")

    elif tab == 'sector':
        sc = fetch_sector_cycle_latest()
        if sc:
            lines.append(f"경기 국면: {sc.get('phase_name', '?')} {sc.get('phase_emoji', '')}")
            ms = sc.get('macro_snapshot', {})
            if isinstance(ms, str):
                try:
                    ms = json.loads(ms)
                except Exception:
                    ms = {}
            if ms:
                lines.append("매크로 스냅샷:")
                for k, v in list(ms.items())[:5]:
                    lines.append(f"  {k}: {v}")
            top3 = sc.get('top3_sectors', [])
            if top3:
                lines.append("유리한 섹터:")
                for s in top3[:3]:
                    if isinstance(s, dict):
                        lines.append(f"  {s.get('sector', '?')}: {s.get('return', '?')}%")
                    else:
                        lines.append(f"  {s}")

    return '\n'.join(lines)


@router.get('/ai-explain')
def get_ai_explain(tab: str = Query(..., description='fundamental, signal, sector')):
    if tab not in _EXPLAIN_PROMPTS:
        return {'explanation': '지원하지 않는 탭입니다.', 'error': True}

    now = time.time()
    cache_key = f'explain_{tab}'
    with _explain_lock:
        cached = _explain_cache.get(cache_key)
        if cached and now < cached.get('expires', 0):
            return {'explanation': cached['text'], 'tab': tab, 'cached': True}

    try:
        text = _build_explain_text(tab)
        if not text.strip():
            return {'explanation': '분석 데이터가 아직 준비되지 않았습니다.', 'tab': tab, 'error': True}
        result = _groq_call(_EXPLAIN_PROMPTS[tab], text, 300)
        if not result:
            return {'explanation': 'AI 해설 서비스가 설정되지 않았습니다.', 'tab': tab, 'error': True}
        with _explain_lock:
            _explain_cache[cache_key] = {'text': result, 'expires': now + _EXPLAIN_TTL}
        return {'explanation': result, 'tab': tab, 'cached': False}
    except Exception as e:
        print(f'[AI Explain {tab}] 오류: {e}')
        return {'explanation': 'AI 해설을 생성할 수 없습니다.', 'tab': tab, 'error': True}
