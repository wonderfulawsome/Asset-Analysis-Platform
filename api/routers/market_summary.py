import os                                                    # 환경변수 접근용
import time                                                  # 캐시 만료 시간 계산용
import threading                                             # 캐시 동시 접근 보호용 Lock
import json                                                  # JSONB 필드 파싱용
from datetime import datetime, timezone, timedelta           # KST 시간 변환용
from fastapi import APIRouter, Query                         # FastAPI 라우터 + 쿼리 파라미터
import yfinance as yf                                        # RSI 실시간 계산용 Yahoo Finance
from database.repositories import (                          # DB 조회 함수들
    fetch_fear_greed_latest,                                 # 최신 공포탐욕지수 조회
    fetch_index_prices_latest,                               # 최신 ETF 가격 조회
    fetch_macro_latest,                                      # 최신 거시지표 조회
    fetch_noise_regime_current,                              # 최신 Noise 국면 조회
    fetch_crash_surge_current,                               # 최신 폭락/급등 점수 조회
    fetch_crash_surge_history,                               # 30일 폭락/급등 히스토리 조회
    fetch_sector_cycle_latest,                               # 최신 경기국면 조회
)

router = APIRouter()                                         # /api/market-summary 라우터 생성

_GROQ_MODEL = 'qwen/qwen3-32b'                              # AI 해설에 사용할 Groq LLM 모델명


def _calc_rsi(period: int = 14) -> float:
    """SPY 종가 기반 RSI(14) 실시간 계산."""
    try:
        df = yf.download('SPY', period='2mo', progress=False)  # SPY 최근 2개월 종가 다운로드
        close = df['Close'].squeeze()                        # Series로 변환
        delta = close.diff()                                 # 일간 가격 변화
        gain = delta.clip(lower=0).rolling(period).mean()    # 14일 평균 상승폭
        loss = (-delta.clip(upper=0)).rolling(period).mean() # 14일 평균 하락폭
        rs = gain / loss                                     # 상대강도 = 평균상승/평균하락
        rsi = 100 - (100 / (1 + rs))                         # RSI 공식
        return round(float(rsi.iloc[-1]), 1)                 # 최신 RSI 반환
    except Exception:
        return 0                                             # 실패 시 0 반환


@router.get('/today')                                        # GET /api/market-summary/today
def get_market_summary_today():
    fg = fetch_fear_greed_latest()                           # 공포탐욕지수 조회
    prices = fetch_index_prices_latest()                     # ETF 가격 조회
    score = fg.get('score', 0) if fg else 0                  # 공포탐욕 점수 (없으면 0)
    rating = fg.get('rating', '-') if fg else '-'            # 등급 (Extreme Fear 등)
    target = {'SPY', 'QQQ', 'DIA'}                           # 평균 수익률 계산 대상 ETF
    changes = [p['change_pct'] for p in prices if p['ticker'] in target]  # 대상 ETF 등락률 추출
    avg_return = sum(changes) / len(changes) if changes else 0  # 평균 등락률
    macro = fetch_macro_latest()                             # 거시지표 조회
    rsi = macro.get('sp500_rsi') if macro else None          # DB에 저장된 RSI 사용
    if not rsi:                                              # DB에 RSI 없으면
        rsi = _calc_rsi()                                    # Yahoo에서 실시간 계산
    else:
        rsi = round(float(rsi), 1)                           # 소수점 1자리 반올림
    return {                                                 # 응답 반환
        'fear_greed': {'score': round(score), 'rating': rating},  # 공포탐욕 점수+등급
        'market_return': {'value': round(avg_return, 2)},    # 시장 평균 수익률
        'rsi': rsi,                                          # RSI(14)
    }


# ═══════════════════════════════════════════════════════════════
# Groq LLM 공통
# ═══════════════════════════════════════════════════════════════

def _groq_call(system_prompt: str, user_text: str, max_tokens: int = 300):
    """Groq API 호출 공통 함수."""
    api_key = os.getenv('GROQ_API_KEY')                      # 환경변수에서 API 키 가져오기
    if not api_key:                                          # 키가 없으면
        all_keys = list(os.environ.keys())                   # 전체 환경변수 목록 (디버깅용)
        print(f'[AI] GROQ_API_KEY not found. Total env vars: {len(all_keys)}. Keys containing GROQ/API/SUPA/FRED: {[k for k in all_keys if any(x in k.upper() for x in ("GROQ","API","SUPA","FRED"))]}')
        return None                                          # None 반환 → 호출측에서 에러 처리
    from groq import Groq                                    # Groq SDK 임포트 (지연 로딩)
    client = Groq(api_key=api_key)                           # Groq 클라이언트 생성
    completion = client.chat.completions.create(              # Chat Completion API 호출
        model=_GROQ_MODEL,                                   # 사용 모델 (qwen3-32b)
        messages=[                                           # 메시지 배열
            {'role': 'system', 'content': system_prompt},    # 시스템 프롬프트 (역할+규칙)
            {'role': 'user', 'content': user_text},          # 사용자 입력 (지표 데이터)
        ],
        temperature=0.7,                                     # 창의성 수준 (0~1)
        max_tokens=max_tokens,                               # 최대 출력 토큰 수
    )
    raw = completion.choices[0].message.content or ''         # LLM 응답 텍스트 추출
    import re                                                # 정규식 임포트
    raw = re.sub(r'<think>[\s\S]*?</think>', '', raw).strip()  # <think> 태그 제거 (CoT 흔적)
    return raw                                               # 정리된 응답 반환


def _kst_now_str():
    """현재 KST 시각을 'YYYY-MM-DD HH:MM' 형식 문자열로 반환."""
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')


# ═══════════════════════════════════════════════════════════════
# 시장 탭: AI 종합 요약
# ═══════════════════════════════════════════════════════════════

_ai_lock = threading.Lock()                                  # AI 요약 캐시 동시 접근 보호용 Lock
_AI_TTL = 900                                                # AI 요약 캐시 유효 시간 (900초 = 15분)


def _build_indicator_text(lang='ko'):
    """AI 요약 프롬프트에 전달할 지표 텍스트를 조합하는 함수."""
    lines = []                                               # 텍스트 줄 목록
    fg = fetch_fear_greed_latest()                           # 공포탐욕지수 조회
    if fg:
        if lang == 'en':
            lines.append(f"Fear & Greed Index: {fg.get('score', '?')} ({fg.get('rating', '?')})")
        else:
            lines.append(f"공포탐욕지수: {fg.get('score', '?')} ({fg.get('rating', '?')})")
    macro = fetch_macro_latest()                             # 거시지표 조회
    if macro:
        if lang == 'en':
            lines.append(f"S&P500 Daily Return: {macro.get('sp500_return', '?')}%")
            lines.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
            lines.append(f"VIX: {macro.get('vix', '?')}")
            lines.append(f"20D Volatility: {macro.get('sp500_vol20', '?')}")
            lines.append(f"10Y Rate: {macro.get('tnx', '?')}, Yield Spread: {macro.get('yield_spread', '?')}")
            if macro.get('putcall_ratio'):                    # Put/Call 비율이 있으면
                lines.append(f"Put/Call Ratio: {macro['putcall_ratio']}")
        else:
            lines.append(f"S&P500 일간수익률: {macro.get('sp500_return', '?')}%")
            lines.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
            lines.append(f"VIX: {macro.get('vix', '?')}")
            lines.append(f"20일 변동성: {macro.get('sp500_vol20', '?')}")
            lines.append(f"10Y금리: {macro.get('tnx', '?')}, 장단기차: {macro.get('yield_spread', '?')}")
            if macro.get('putcall_ratio'):                    # Put/Call 비율이 있으면
                lines.append(f"풋콜비율: {macro['putcall_ratio']}")
    regime = fetch_noise_regime_current()                    # Noise 국면 조회
    if regime:
        ns = regime.get('noise_score', 0)                    # Noise Score 값
        try:
            ns_val = float(ns)                               # 숫자로 변환
        except (TypeError, ValueError):
            ns_val = 0
        if lang == 'en':
            if ns_val < -1:                                  # -1 미만: 펀더멘털 잘 반영
                interp = 'Price well reflects fundamentals'
            elif ns_val < 0:                                 # -1~0: 약간 괴리
                interp = 'Minor divergence, mostly reflecting fundamentals'
            elif ns_val < 2:                                 # 0~2: 괴리 존재
                interp = 'Divergence between price and fundamentals'
            else:                                            # 2 이상: 큰 괴리
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
    cs = fetch_crash_surge_current()                         # 폭락/급등 점수 조회
    if cs:
        c_s = cs.get('crash_score') or cs.get('crash_prob') or 0  # 하락 점수 (필드명 호환)
        s_s = cs.get('surge_score') or cs.get('surge_prob') or 0  # 상승 점수 (필드명 호환)
        gap = round(s_s - c_s, 1)                            # 간극 = 상승 - 하락 (양수=상승 우위)
        if lang == 'en':
            lines.append(f"Crash Risk: {c_s}pts, Surge Potential: {s_s}pts, Gap: {gap:+.1f}pts")
        else:
            lines.append(f"하락 위험도: {c_s}점, 상승 기대도: {s_s}점, 간극: {gap:+.1f}점")
    prices = fetch_index_prices_latest()                     # ETF 가격 조회
    if prices:
        major = [p for p in prices if p.get('ticker') in ('SPY', 'QQQ', 'DIA', 'VOO', 'IWM')]  # 주요 5개 ETF
        for p in major:
            chg = p.get('change_pct', 0)                     # 등락률
            sign = '+' if chg >= 0 else ''                   # 양수면 + 접두사
            lines.append(f"{p['ticker']}: ${p.get('close', '?')} ({sign}{chg}%)")
    sector = fetch_sector_cycle_latest()                     # 경기국면 조회
    if sector:
        if lang == 'en':
            lines.append(f"Business Cycle: {sector.get('phase_name', '?')}")
        else:
            lines.append(f"경기국면: {sector.get('phase_name', '?')}")
    return '\n'.join(lines)                                  # 줄바꿈으로 합쳐서 반환


_SUMMARY_PROMPTS = {                                         # AI 종합 요약 시스템 프롬프트
    'ko': """/no_think
너는 투자자에게 쉽게 설명해주는 한국어 금융 애널리스트다.
주어진 지표를 종합해 시장 브리핑을 작성하라.

반드시 아래 4줄을 출력하라. 각 줄은 반드시 "제목 — 내용" 형식이다.
"—" (em dash) 앞뒤에 반드시 공백을 넣어라. 제목과 내용을 절대 붙여 쓰지 마라.

[이모지] 시장 심리 — (공포탐욕·VIX·RSI를 종합한 심리 해석 1문장)
[이모지] 방향성 — (간극(상승-하락) 수치와 방향 중심으로 단기 전망 1문장. 양수=상승 우위, 음수=하락 우위, 절대값이 클수록 확신)
[이모지] 펀더멘털 — (펀더멘털 주가 괴리 점수 기반 주가-펀더멘털 관계 1문장)
[이모지] 종합판단 — (위 3가지를 종합한 결론. 투자자 행동 제안 1문장)

예시:
❄️ 시장 심리 — 공포 지수 19로 극단적 공포 구간이며, 투자 심리가 크게 위축된 상황입니다.
📉 방향성 — 간극 -3.3으로 하락 쪽이 소폭 우세하나, 차이가 작아 방향성이 불분명합니다.
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
[emoji] Direction — (1 sentence focusing on the Gap value and direction. Positive=upside favored, negative=downside favored, larger absolute value=stronger conviction)
[emoji] Fundamentals — (1 sentence on price-fundamental relationship via Divergence Score 0-10)
[emoji] Overall — (1 sentence conclusion combining the above 3, with action suggestion)

Example:
❄️ Market Sentiment — Fear index at 19, deep in extreme fear territory with severely depressed investor sentiment.
📉 Direction — Gap at -3.3 tilts slightly toward downside, but the small spread suggests no clear direction.
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


_ai_cache = {'ko': {'summary': None, 'generated_at': None, 'expires': 0},  # 한국어 AI 요약 캐시
             'en': {'summary': None, 'generated_at': None, 'expires': 0}}  # 영어 AI 요약 캐시

_ERR_MSGS = {                                                # 에러 메시지 (한/영)
    'ko': {'no_data': '지표 데이터가 아직 준비되지 않았습니다.',
           'no_service': 'AI 요약 서비스가 설정되지 않았습니다.',
           'fail': 'AI 요약을 생성할 수 없습니다.'},
    'en': {'no_data': 'Indicator data is not yet available.',
           'no_service': 'AI summary service is not configured.',
           'fail': 'Unable to generate AI summary.'},
}

@router.get('/ai-summary')                                   # GET /api/market-summary/ai-summary
def get_ai_summary(lang: str = Query('ko')):                 # 언어 쿼리 파라미터 (기본 한국어)
    lang = lang if lang in ('ko', 'en') else 'ko'            # 유효하지 않은 언어면 한국어로
    err = _ERR_MSGS[lang]                                    # 해당 언어 에러 메시지 선택
    now = time.time()                                        # 현재 시각 (Unix timestamp)
    with _ai_lock:                                           # 캐시 접근 보호
        c = _ai_cache[lang]                                  # 해당 언어 캐시
        if c['summary'] and now < c['expires']:              # 캐시가 유효하면
            return {'summary': c['summary'], 'generated_at': c['generated_at'], 'cached': True}  # 캐시 반환
    try:
        text = _build_indicator_text(lang)                   # 지표 텍스트 조합
        if not text.strip():                                 # 데이터가 비어있으면
            return {'summary': err['no_data'], 'error': True}
        result = _groq_call(_SUMMARY_PROMPTS[lang], text, 400)  # Groq LLM 호출 (최대 400토큰)
        if not result:                                       # API 키 없으면
            return {'summary': err['no_service'], 'error': True}
        ts = _kst_now_str()                                  # 생성 시각 (KST)
        with _ai_lock:                                       # 캐시 갱신
            _ai_cache[lang].update({'summary': result, 'generated_at': ts, 'expires': now + _AI_TTL})
        return {'summary': result, 'generated_at': ts, 'cached': False}  # 새 결과 반환
    except Exception as e:                                   # 예외 발생 시
        print(f'[AI Summary] error: {e}')                    # 에러 로그
        return {'summary': err['fail'], 'error': True}       # 에러 응답


# ═══════════════════════════════════════════════════════════════
# 각 탭 AI 해설 (펀더멘털 / 신호 / 섹터)
# ═══════════════════════════════════════════════════════════════

_explain_cache = {}                                          # 탭별 AI 해설 캐시 딕셔너리
_explain_lock = threading.Lock()                             # 해설 캐시 동시 접근 보호용 Lock
_EXPLAIN_TTL = 900                                           # 해설 캐시 유효 시간 (15분)

_EXPLAIN_PROMPTS = {                                         # 탭별 AI 해설 시스템 프롬프트
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
- "간극(Gap)"은 상승 기대도에서 하락 위험도를 뺀 값이다
- 간극이 양수(+)이면 상승 기대가 더 높고, 음수(-)이면 하락 위험이 더 높다
- 간극의 절대값이 클수록 한쪽으로 강하게 기울어진 것이다
- 30일 추세에서 간극이 상승하면 상승 기대 증가, 하락하면 하락 위험 증가를 의미한다

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
- "Gap" is surge potential minus crash risk
- Positive gap = tilted toward upside; Negative gap = tilted toward downside risk
- Larger absolute gap = stronger tilt in one direction
- A rising 30-day gap trend signals increasing upside; falling signals increasing downside risk

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
    """각 탭(펀더멘털/신호/섹터)의 AI 해설에 전달할 데이터 텍스트를 조합."""
    is_en = (lang == 'en')                                   # 영어 여부 플래그
    lines = []                                               # 텍스트 줄 목록

    if tab == 'fundamental':                                 # ── 펀더멘털 탭 ──
        regime = fetch_noise_regime_current()                # Noise 국면 조회
        if regime:
            lines.append(f"{'Regime' if is_en else '레짐'}: {regime.get('regime_name', '?')}")  # 국면명
            if is_en:
                lines.append(f"Fundamental-Price Divergence Score: {regime.get('noise_score', '?')}")
            else:
                lines.append(f"펀더멘털 주가 괴리 점수: {regime.get('noise_score', '?')}")
            fc = regime.get('feature_contributions', [])     # 피처 기여도 (JSONB)
            if isinstance(fc, str):                          # 문자열이면 JSON 파싱
                try:
                    fc = json.loads(fc)
                except Exception:
                    fc = []
            if fc:
                lines.append("Feature Contributions:" if is_en else "피처 기여도:")
                for f in sorted(fc, key=lambda x: abs(x.get('contribution', 0)), reverse=True)[:5]:  # 기여도 절대값 상위 5개
                    lines.append(f"  {f.get('name', '?')}: {f.get('contribution', '?')}")
            fv = regime.get('feature_values', {})            # 현재 피처 값 (JSONB)
            if isinstance(fv, str):                          # 문자열이면 JSON 파싱
                try:
                    fv = json.loads(fv)
                except Exception:
                    fv = {}
            if fv:
                lines.append("Current Values:" if is_en else "현재 지표값:")
                for k, v in list(fv.items())[:6]:            # 상위 6개 피처 값
                    lines.append(f"  {k}: {v}")

    elif tab == 'signal':                                    # ── 신호 탭 ──
        cs = fetch_crash_surge_current()                     # 폭락/급등 현재 점수 조회
        if cs:
            crash_s = cs.get('crash_score') or cs.get('crash_prob') or 0  # 하락 점수
            surge_s = cs.get('surge_score') or cs.get('surge_prob') or 0  # 상승 점수
            gap = round(surge_s - crash_s, 1)                # 간극 = 상승 - 하락 (양수=상승 우위)
            if is_en:
                lines.append(f"Crash Risk: {crash_s}pts ({cs.get('crash_grade', '?')})")
                lines.append(f"Surge Potential: {surge_s}pts ({cs.get('surge_grade', '?')})")
                lines.append(f"Gap (Surge - Crash): {gap:+.1f}pts")
            else:
                lines.append(f"하락 위험도: {crash_s}점 ({cs.get('crash_grade', '?')})")
                lines.append(f"상승 기대도: {surge_s}점 ({cs.get('surge_grade', '?')})")
                lines.append(f"간극 (상승-하락): {gap:+.1f}점")

            # 30일 간극 추세 분석
            history = fetch_crash_surge_history(30)           # 최근 30일 히스토리 조회
            if history and len(history) >= 2:                 # 2건 이상 있으면 추세 분석
                gaps = []                                     # 날짜별 간극 목록
                for h in reversed(history):                   # 오래된 순으로 정렬
                    c_s = (h.get('crash_prob') or h.get('crash_score') or 0)  # 하락 점수
                    s_s = (h.get('surge_prob') or h.get('surge_score') or 0)  # 상승 점수
                    gaps.append({'date': h.get('date', '?'), 'gap': round(s_s - c_s, 1)})  # 간극 계산

                if len(gaps) >= 5:                            # 5건 이상이면 추세 비교 가능
                    recent_5 = [g['gap'] for g in gaps[-5:]]  # 최근 5일 간극
                    old_5 = [g['gap'] for g in gaps[:5]]      # 초기 5일 간극
                    recent_avg = round(sum(recent_5) / len(recent_5), 1)  # 최근 5일 평균
                    old_avg = round(sum(old_5) / len(old_5), 1)          # 초기 5일 평균
                    trend_delta = round(recent_avg - old_avg, 1)         # 추세 변화량

                    max_gap = max(gaps, key=lambda g: g['gap'])  # 가장 상승 우위인 날
                    min_gap = min(gaps, key=lambda g: g['gap'])  # 가장 하락 우위인 날

                    if is_en:
                        lines.append(f"\n30-Day Gap Trend:")
                        lines.append(f"  Early avg: {old_avg:+.1f} → Recent avg: {recent_avg:+.1f} (change: {trend_delta:+.1f})")
                        lines.append(f"  Most bullish: {max_gap['gap']:+.1f} ({max_gap['date']})")   # 최대 상승 우위
                        lines.append(f"  Most bearish: {min_gap['gap']:+.1f} ({min_gap['date']})")   # 최대 하락 우위
                        if trend_delta > 5:                   # 추세 +5 이상: 상승 기울기
                            lines.append(f"  Trend: Gap rising — tilting toward upside")
                        elif trend_delta < -5:                # 추세 -5 이하: 하락 기울기
                            lines.append(f"  Trend: Gap falling — tilting toward downside risk")
                        else:                                 # 그 외: 안정
                            lines.append(f"  Trend: Gap stable")
                    else:
                        lines.append(f"\n30일 간극 추세:")
                        lines.append(f"  초기 평균: {old_avg:+.1f} → 최근 평균: {recent_avg:+.1f} (변화: {trend_delta:+.1f})")
                        lines.append(f"  최대 상승 우위: {max_gap['gap']:+.1f} ({max_gap['date']})")
                        lines.append(f"  최대 하락 우위: {min_gap['gap']:+.1f} ({min_gap['date']})")
                        if trend_delta > 5:
                            lines.append(f"  추세: 간극 상승 중 — 상승 쪽으로 기울어지는 중")
                        elif trend_delta < -5:
                            lines.append(f"  추세: 간극 하락 중 — 하락 위험 쪽으로 기울어지는 중")
                        else:
                            lines.append(f"  추세: 간극 안정적 유지")

            shap = cs.get('shap_values', {})                 # SHAP 피처 중요도 (JSONB)
            if isinstance(shap, str):                        # 문자열이면 JSON 파싱
                try:
                    shap = json.loads(shap)
                except Exception:
                    shap = {}
            for label in ['crash', 'surge']:                 # crash/surge 각각의 SHAP 요인
                sv = shap.get(label, [])                     # 해당 라벨의 SHAP 값 리스트
                if sv:
                    lines.append(f"{label} {'key factors' if is_en else '주요 요인'}:")
                    for s in sv[:3]:                          # 상위 3개 요인
                        lines.append(f"  {s.get('name', '?')}: {s.get('value', '?')}")

    elif tab == 'sector':                                    # ── 섹터 탭 ──
        sc = fetch_sector_cycle_latest()                     # 경기국면 조회
        if sc:
            lines.append(f"{'Business Cycle' if is_en else '경기 국면'}: {sc.get('phase_name', '?')} {sc.get('phase_emoji', '')}")
            ms = sc.get('macro_snapshot', {})                # 매크로 스냅샷 (JSONB)
            if isinstance(ms, str):                          # 문자열이면 JSON 파싱
                try:
                    ms = json.loads(ms)
                except Exception:
                    ms = {}
            if ms:
                lines.append("Macro Snapshot:" if is_en else "매크로 스냅샷:")
                for k, v in list(ms.items())[:5]:            # 상위 5개 매크로 지표
                    lines.append(f"  {k}: {v}")
            top3 = sc.get('top3_sectors', [])                # 유리한 섹터 상위 3개
            if top3:
                lines.append("Favorable Sectors:" if is_en else "유리한 섹터:")
                for s in top3[:3]:                           # 3개 섹터 순회
                    if isinstance(s, dict):                  # dict 형식이면 섹터명+수익률
                        lines.append(f"  {s.get('sector', '?')}: {s.get('return', '?')}%")
                    else:                                    # 문자열이면 그대로
                        lines.append(f"  {s}")

    return '\n'.join(lines)                                  # 줄바꿈으로 합쳐서 반환


_EXPLAIN_ERR = {                                             # 해설 에러 메시지 (한/영)
    'ko': {'bad_tab': '지원하지 않는 탭입니다.',
           'no_data': '분석 데이터가 아직 준비되지 않았습니다.',
           'no_service': 'AI 해설 서비스가 설정되지 않았습니다.',
           'fail': 'AI 해설을 생성할 수 없습니다.'},
    'en': {'bad_tab': 'Unsupported tab.',
           'no_data': 'Analysis data is not yet available.',
           'no_service': 'AI commentary service is not configured.',
           'fail': 'Unable to generate AI commentary.'},
}

@router.get('/ai-explain')                                   # GET /api/market-summary/ai-explain
def get_ai_explain(tab: str = Query(..., description='fundamental, signal, sector'),  # 탭 파라미터 (필수)
                   lang: str = Query('ko')):                 # 언어 파라미터 (기본 한국어)
    lang = lang if lang in ('ko', 'en') else 'ko'            # 유효하지 않은 언어면 한국어로
    err = _EXPLAIN_ERR[lang]                                 # 해당 언어 에러 메시지
    if tab not in _EXPLAIN_PROMPTS['ko']:                    # 지원하지 않는 탭이면
        return {'explanation': err['bad_tab'], 'error': True}

    now = time.time()                                        # 현재 시각
    cache_key = f'explain_{tab}_{lang}'                      # 캐시 키 (예: explain_signal_ko)
    with _explain_lock:                                      # 캐시 접근 보호
        cached = _explain_cache.get(cache_key)               # 캐시 조회
        if cached and now < cached.get('expires', 0):        # 캐시가 유효하면
            return {'explanation': cached['text'], 'tab': tab, 'cached': True}  # 캐시 반환

    try:
        text = _build_explain_text(tab, lang)                # 탭별 데이터 텍스트 조합
        if not text.strip():                                 # 데이터가 비어있으면
            return {'explanation': err['no_data'], 'tab': tab, 'error': True}
        result = _groq_call(_EXPLAIN_PROMPTS[lang][tab], text, 300)  # Groq LLM 호출 (최대 300토큰)
        if not result:                                       # API 키 없으면
            return {'explanation': err['no_service'], 'tab': tab, 'error': True}
        with _explain_lock:                                  # 캐시 갱신
            _explain_cache[cache_key] = {'text': result, 'expires': now + _EXPLAIN_TTL}
        return {'explanation': result, 'tab': tab, 'cached': False}  # 새 해설 반환
    except Exception as e:                                   # 예외 발생 시
        print(f'[AI Explain {tab}] error: {e}')              # 에러 로그
        return {'explanation': err['fail'], 'tab': tab, 'error': True}  # 에러 응답
