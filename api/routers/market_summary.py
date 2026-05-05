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
    fetch_valuation_signal_latest,                           # 최신 시장 밸류(z_comp) 조회
    upsert_ai_headline,                                      # 홈 헤드라인 DB 캐시 upsert
    fetch_ai_headline,                                       # 홈 헤드라인 DB 캐시 조회
    upsert_ai_explain,                                       # 5탭 AI 해설 DB 캐시 upsert
    fetch_ai_explain,                                        # 5탭 AI 해설 DB 캐시 조회
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


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'


@router.get('/today')                                        # GET /api/market-summary/today
def get_market_summary_today(region: str = Query('us')):
    region = _norm_region(region)
    fg = fetch_fear_greed_latest(region=region)              # 공포탐욕지수 조회
    prices = fetch_index_prices_latest(region=region)        # ETF 가격 조회
    has_fg = fg is not None and fg.get('score') is not None  # KR 미적재 시 None
    score = fg.get('score', 0) if has_fg else None
    rating = fg.get('rating', '-') if has_fg else None
    # 주요 지수 — region 별 (US: SPY/QQQ/DIA, KR: KODEX 200·TIGER 200·KOSDAQ150)
    if region == 'kr':
        target = {'069500', '102110', '232080'}
    else:
        target = {'SPY', 'QQQ', 'DIA'}
    changes = [p['change_pct'] for p in prices if p['ticker'] in target]
    avg_return = sum(changes) / len(changes) if changes else 0
    macro = fetch_macro_latest(region=region)
    rsi = macro.get('sp500_rsi') if macro else None
    if not rsi and region == 'us':
        rsi = _calc_rsi()
    elif rsi:
        rsi = round(float(rsi), 1)
    cs = fetch_crash_surge_current(region=region)            # 폭락/급등 점수 조회
    crash_surge = None
    if cs:
        crash_s = cs.get('crash_score') or cs.get('crash_prob')
        surge_s = cs.get('surge_score') or cs.get('surge_prob')
        if crash_s is not None and surge_s is not None:
            crash_surge = {
                'crash': round(float(crash_s), 1),
                'surge': round(float(surge_s), 1),
                'gap': round(float(surge_s) - float(crash_s), 1),  # 양수=상승 우위
            }
    return {                                                 # 응답 반환
        # KR 처럼 미적재 region 은 fear_greed=null → 프론트가 "준비 중" 처리
        'fear_greed': ({'score': round(score), 'rating': rating}
                        if has_fg else None),
        'market_return': {'value': round(avg_return, 2)},
        'rsi': rsi,
        'crash_surge': crash_surge,
        'region': region,
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
        temperature=0.3,                                     # 창의성 수준 (0~1) — 해설은 일관성 中
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


def _market_labels(region: str, lang: str) -> dict:
    """region 별 시장 라벨 사전 (LLM 프롬프트용).

    macro_raw 의 컬럼명(sp500_*, vix, tnx)은 영구 유지하되, 사용자/LLM 에 노출되는
    라벨만 region 별로 분기.
    """
    is_en = (lang == 'en')
    if region == 'kr':
        return {
            'index_name':    'KOSPI' if is_en else 'KOSPI',
            'index_return':  'KOSPI Daily Return' if is_en else 'KOSPI 일간수익률',
            'vol20_label':   'KOSPI 20D Volatility' if is_en else 'KOSPI 20일 변동성',
            'vix_name':      'VKOSPI',
            'rate_name':     'KR 10Y' if is_en else 'KR 10Y 국고채',
            'spread_name':   'KR Yield Spread' if is_en else 'KR 장단기차',
            'major_tickers': ('069500', '102110', '232080', '229200'),  # KODEX 200 / TIGER 200 / 코스닥150
            'price_unit':    '원',
        }
    return {
        'index_name':    'S&P500',
        'index_return':  'S&P500 Daily Return' if is_en else 'S&P500 일간수익률',
        'vol20_label':   '20D Volatility' if is_en else '20일 변동성',
        'vix_name':      'VIX',
        'rate_name':     '10Y Rate' if is_en else '10Y금리',
        'spread_name':   'Yield Spread' if is_en else '장단기차',
        'major_tickers': ('SPY', 'QQQ', 'DIA', 'VOO', 'IWM'),
        'price_unit':    '$',
    }


def _build_indicator_text(lang='ko', region: str = 'us'):
    """AI 요약 프롬프트에 전달할 지표 텍스트를 조합하는 함수."""
    region = _norm_region(region)
    L = _market_labels(region, lang)
    lines = []                                               # 텍스트 줄 목록
    fg = fetch_fear_greed_latest(region=region)              # 공포탐욕지수 조회
    if fg:
        if lang == 'en':
            lines.append(f"Fear & Greed Index: {fg.get('score', '?')} ({fg.get('rating', '?')})")
        else:
            lines.append(f"공포탐욕지수: {fg.get('score', '?')} ({fg.get('rating', '?')})")
    macro = fetch_macro_latest(region=region)                # 거시지표 조회
    if macro:
        if lang == 'en':
            lines.append(f"{L['index_return']}: {macro.get('sp500_return', '?')}%")
            lines.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
            lines.append(f"{L['vix_name']}: {macro.get('vix', '?')}")
            lines.append(f"{L['vol20_label']}: {macro.get('sp500_vol20', '?')}")
            lines.append(f"{L['rate_name']}: {macro.get('tnx', '?')}, {L['spread_name']}: {macro.get('yield_spread', '?')}")
            if macro.get('putcall_ratio'):
                lines.append(f"Put/Call Ratio: {macro['putcall_ratio']}")
        else:
            lines.append(f"{L['index_return']}: {macro.get('sp500_return', '?')}%")
            lines.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
            lines.append(f"{L['vix_name']}: {macro.get('vix', '?')}")
            lines.append(f"{L['vol20_label']}: {macro.get('sp500_vol20', '?')}")
            lines.append(f"{L['rate_name']}: {macro.get('tnx', '?')}, {L['spread_name']}: {macro.get('yield_spread', '?')}")
            if macro.get('putcall_ratio'):
                lines.append(f"풋콜비율: {macro['putcall_ratio']}")
    regime = fetch_noise_regime_current(region=region)       # Noise 국면 조회
    if regime:
        ns = regime.get('noise_score', 0)                    # Noise Score 값
        try:
            ns_val = float(ns)                               # 숫자로 변환
        except (TypeError, ValueError):
            ns_val = 0
        if lang == 'en':
            if ns_val > 1:                                   # +1 초과: 펀더멘털 잘 반영 (이성)
                interp = 'Price well reflects fundamentals'
            elif ns_val > 0:                                 # 0~+1: 대체로 이성
                interp = 'Mostly reflecting fundamentals'
            elif ns_val > -2:                                # -2~0: 괴리 존재 (감정)
                interp = 'Divergence between price and fundamentals'
            else:                                            # -2 이하: 큰 괴리
                interp = 'Significant divergence from fundamentals'
            lines.append(f"Market Rationality Score: {ns} → {interp}")
            lines.append(f"  (Positive = rational/reflecting fundamentals, larger negative = more emotional/divergent)")
        else:
            if ns_val > 1:
                interp = '주가가 펀더멘털을 잘 반영 중 (이성적 시장)'
            elif ns_val > 0:
                interp = '대체로 펀더멘털 반영 중'
            elif ns_val > -2:
                interp = '주가와 펀더멘털 사이 괴리 존재 (감정적 시장)'
            else:
                interp = '주가와 펀더멘털이 크게 괴리됨 (감정 지배)'
            lines.append(f"시장 이성 점수: {ns} → {interp}")
            lines.append(f"  (양수일수록 이성적/펀더멘털 반영, 음수가 클수록 감정적/괴리)")
    cs = fetch_crash_surge_current(region=region)            # 폭락/급등 점수 조회
    if cs:
        c_s = cs.get('crash_score') or cs.get('crash_prob') or 0  # 하락 점수 (필드명 호환)
        s_s = cs.get('surge_score') or cs.get('surge_prob') or 0  # 상승 점수 (필드명 호환)
        gap = round(s_s - c_s, 1)                            # 간극 = 상승 - 하락 (양수=상승 우위)
        if lang == 'en':
            lines.append(f"Crash Risk: {c_s}pts, Surge Potential: {s_s}pts, Gap: {gap:+.1f}pts")
        else:
            lines.append(f"하락 위험도: {c_s}점, 상승 기대도: {s_s}점, 간극: {gap:+.1f}점")
    prices = fetch_index_prices_latest(region=region)        # ETF 가격 조회
    if prices:
        major = [p for p in prices if p.get('ticker') in L['major_tickers']]
        for p in major:
            chg = p.get('change_pct', 0)
            sign = '+' if chg >= 0 else ''
            tk_label = p.get('name') or p['ticker']
            lines.append(f"{tk_label} ({p['ticker']}): {L['price_unit']}{p.get('close', '?')} ({sign}{chg}%)")
    sector = fetch_sector_cycle_latest(region=region)        # 경기국면 조회
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
[이모지] 펀더멘털 — (시장 이성 점수 기반 주가-펀더멘털 관계 1문장. 양수=이성, 음수=감정)
[이모지] 종합판단 — (위 3가지를 종합한 결론. 투자자 행동 제안 1문장)

예시:
❄️ 시장 심리 — 공포 지수 19로 극단적 공포 구간이며, 투자 심리가 크게 위축된 상황입니다.
📉 방향성 — 간극 -3.3으로 하락 쪽이 소폭 우세하나, 차이가 작아 방향성이 불분명합니다.
🧭 펀더멘털 — 이성 점수 -2.1로 주가와 펀더멘털 사이 괴리가 존재합니다.
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
[emoji] Fundamentals — (1 sentence on price-fundamental relationship via Market Rationality Score; positive=rational, negative=emotional)
[emoji] Overall — (1 sentence conclusion combining the above 3, with action suggestion)

Example:
❄️ Market Sentiment — Fear index at 19, deep in extreme fear territory with severely depressed investor sentiment.
📉 Direction — Gap at -3.3 tilts slightly toward downside, but the small spread suggests no clear direction.
🧭 Fundamentals — Rationality score of -2.1 shows a gap between stock prices and fundamentals.
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


_ai_cache: dict = {}                                         # 키: f"{lang}_{region}", 값: {summary, generated_at, expires}

_ERR_MSGS = {                                                # 홈 헤드라인 에러 메시지 (한/영)
    # 토큰 한도 초과 / API 실패 / 데이터 미준비 등 모든 실패 케이스 동일 멘트로 통일
    # ([95] 와 동일한 패턴 — _EXPLAIN_ERR 의 home-headline 등가).
    'ko': {'no_data': '해설 서비스 개선중.',
           'no_service': '해설 서비스 개선중.',
           'fail': '해설 서비스 개선중.'},
    'en': {'no_data': 'Commentary service is being improved.',
           'no_service': 'Commentary service is being improved.',
           'fail': 'Commentary service is being improved.'},
}

def _build_home_indicator_text(lang: str = 'ko', region: str = 'us') -> str:
    """홈 헤드라인용 — 4개 탭별로 그룹화한 핵심 지표 텍스트.

    LLM 이 탭별 지표를 비교해 가장 주목할 신호 1개를 직접 고를 수 있도록 설계.
    """
    region = _norm_region(region)
    L = _market_labels(region, lang)
    is_en = (lang == 'en')
    lines = []

    # ── 시장 탭 ──
    section = []
    fg = fetch_fear_greed_latest(region=region)
    if fg:
        section.append(f"{'Fear & Greed' if is_en else '공포탐욕지수'}: {fg.get('score', '?')} ({fg.get('rating', '?')})")
    macro = fetch_macro_latest(region=region)
    if macro:
        section.append(f"{L['index_return']}: {macro.get('sp500_return', '?')}%")
        section.append(f"RSI(14): {macro.get('sp500_rsi', '?')}")
        section.append(f"{L['vix_name']}: {macro.get('vix', '?')}")
        section.append(f"{L['vol20_label']}: {macro.get('sp500_vol20', '?')}")
        if macro.get('putcall_ratio'):
            section.append(f"{'Put/Call Ratio' if is_en else '풋콜비율'}: {macro['putcall_ratio']}")
    if section:
        lines.append(f"[{'Market Tab' if is_en else '시장 탭'}]")
        lines.extend(section)
        lines.append("")

    # ── 펀더멘털 탭 ──
    section = []
    regime = fetch_noise_regime_current(region=region)
    if regime:
        ns = regime.get('noise_score', 0)
        try:
            ns_val = float(ns)
        except (TypeError, ValueError):
            ns_val = 0
        if is_en:
            if ns_val > 1: interp = 'rational'
            elif ns_val > 0: interp = 'mostly rational'
            elif ns_val > -2: interp = 'emotional/divergent'
            else: interp = 'strongly emotional'
            section.append(f"Market Rationality Score: {ns} ({interp})")
            section.append(f"Phase: {regime.get('regime_name', '?')}")
        else:
            if ns_val > 1: interp = '이성적 시장'
            elif ns_val > 0: interp = '대체로 이성'
            elif ns_val > -2: interp = '괴리 존재 (감정적)'
            else: interp = '강한 감정 지배'
            section.append(f"시장 이성 점수: {ns} ({interp})")
            section.append(f"국면: {regime.get('regime_name', '?')}")
        fc = regime.get('feature_contributions', [])
        if isinstance(fc, str):
            try: fc = json.loads(fc)
            except Exception: fc = []
        if fc:
            top2 = sorted(fc, key=lambda x: abs(x.get('contribution', 0) or 0), reverse=True)[:2]
            tags = ', '.join(f"{f.get('name','?')}={f.get('contribution',0):+.2f}" for f in top2)
            section.append(f"{'Top contributors' if is_en else '주요 기여'}: {tags}")
    if section:
        lines.append(f"[{'Fundamental Tab' if is_en else '펀더멘털 탭'}]")
        lines.extend(section)
        lines.append("")

    # ── 신호 탭 ──
    section = []
    cs = fetch_crash_surge_current(region=region)
    if cs:
        c_s = cs.get('crash_score') or cs.get('crash_prob') or 0
        s_s = cs.get('surge_score') or cs.get('surge_prob') or 0
        gap = round(s_s - c_s, 1)
        if is_en:
            section.append(f"Crash Risk: {c_s}pts ({cs.get('crash_grade', '?')})")
            section.append(f"Surge Potential: {s_s}pts ({cs.get('surge_grade', '?')})")
            section.append(f"Gap (Surge - Crash): {gap:+.1f}pts")
        else:
            section.append(f"하락 위험도: {c_s}점 ({cs.get('crash_grade', '?')})")
            section.append(f"상승 기대도: {s_s}점 ({cs.get('surge_grade', '?')})")
            section.append(f"간극(상승-하락): {gap:+.1f}점")
    if section:
        lines.append(f"[{'Signal Tab' if is_en else '신호 탭'}]")
        lines.extend(section)
        lines.append("")

    # ── 섹터 탭 ──
    section = []
    sector = fetch_sector_cycle_latest(region=region)
    if sector:
        if is_en:
            section.append(f"Business Cycle Phase: {sector.get('phase_name', '?')}")
        else:
            section.append(f"경기국면: {sector.get('phase_name', '?')}")
    if section:
        lines.append(f"[{'Sector Tab' if is_en else '섹터 탭'}]")
        lines.extend(section)
        lines.append("")

    # ── 시장 밸류 탭 ──
    section = []
    val = fetch_valuation_signal_latest(region=region)
    if val:
        z_comp = val.get('z_comp')
        label = val.get('label')
        erp = val.get('erp')
        per = val.get('spy_per')                              # KR 도 같은 컬럼명에 KOSPI PER 저장
        vix = val.get('vix')                                  # KR 은 VKOSPI
        per_label = f"{L['index_name']} PER"
        if is_en:
            if z_comp is not None:
                section.append(f"Composite Valuation z_comp: {z_comp:+.2f} ({label or '?'})")
                section.append("  (positive = undervalued/cheap, negative = overvalued/expensive)")
            if erp is not None:
                section.append(f"ERP (Equity Risk Premium): {erp:+.4f}")
            if per is not None:
                section.append(f"{per_label}: {per}")
            if vix is not None:
                section.append(f"{L['vix_name']}: {vix}")
        else:
            if z_comp is not None:
                section.append(f"시장 밸류 z_comp: {z_comp:+.2f} ({label or '?'})")
                section.append("  (양수 = 저평가/싸짐, 음수 = 고평가/비쌈)")
            if erp is not None:
                section.append(f"ERP (주식 위험 프리미엄): {erp:+.4f}")
            if per is not None:
                section.append(f"{per_label}: {per}")
            if vix is not None:
                section.append(f"{L['vix_name']}: {vix}")
    if section:
        lines.append(f"[{'Market Valuation Tab' if is_en else '시장 밸류 탭'}]")
        lines.extend(section)

    return '\n'.join(lines).strip()


_HEADLINE_PROMPTS = {
    'ko': """/no_think
너는 한국어 금융 애널리스트다. 아래는 패시브 대시보드 5개 탭(시장·펀더멘털·신호·섹터·시장 밸류)의 핵심 지표다.
홈 화면 헤드라인을 정확히 다음 **고정 형식** 으로 작성하라.

**[필수 — 첫 문장 고정 템플릿]**
"시장이 {밸류 라벨} 상태{연결어} 시장 이성 점수가 {부호}{수치}점으로, {판단}인 밸류를 가지고 있습니다."

세 슬롯 채우는 법:
1) {밸류 라벨}: 시장 밸류 탭의 label 그대로 사용 ("저평가", "적정", "다소 고평가", "고평가" 등)
2) {연결어}: 라벨 방향과 이성 점수 부호의 부호 일치 여부로 결정
   - 라벨 부정적(고평가류) + 이성 점수 양수 → **"이지만"** (반전 — 고평가지만 합리적)
   - 라벨 긍정적(저평가/적정) + 이성 점수 음수 → **"이지만"** (반전 — 적정이지만 비합리적)
   - 라벨 부정적 + 이성 점수 음수 → **"이며"** (강화 — 고평가에 비합리적)
   - 라벨 긍정적 + 이성 점수 양수 → **"이며"** (강화 — 저평가에 합리적)
3) {부호}{수치}: 시장 이성 점수 그대로. 양수면 "+0.9", 음수면 "-1.2" 등
4) {판단}:
   - 이성 점수 양수(+) → "합리적"
   - 이성 점수 음수(-) → "비합리적"

**[선택] 두 번째 문장 — 보조 신호**
다음 중 가장 두드러진 신호 하나를 1문장으로 보조 언급 (없으면 생략):
- 공포탐욕 극단값 (25 미만 / 75 초과)
- RSI 극단값 (30 미만 / 70 초과)
- 신호 탭 |gap| 20 이상
- VIX 25 초과
- 시장 이성 점수 절대값 ±2 이상이면 "감정적/이성적 흐름이 두드러집니다" 로 강조

출력 규칙:
- 1~2 문장, 각 문장 끝에 마침표
- 총 180자 이내
- 부드럽고 신중한 어투
- 이모지·마크다운·대시(—)·콜론(:) 금지
- **첫 문장은 반드시 위 고정 템플릿 형식 그대로** — "시장이 ... 상태{이지만/이며} 시장 이성 점수가 ...점으로, ...인 밸류를 가지고 있습니다."

예시:
시장이 다소 고평가 상태이지만 시장 이성 점수가 +0.9점으로, 합리적인 밸류를 가지고 있습니다.
시장이 적정 상태이며 시장 이성 점수가 +1.5점으로, 합리적인 밸류를 가지고 있습니다. 공포탐욕 78로 탐욕 구간이 부각됩니다.
시장이 고평가 상태이며 시장 이성 점수가 -2.3점으로, 비합리적인 밸류를 가지고 있습니다. 감정적 흐름이 두드러집니다.
시장이 저평가 상태이지만 시장 이성 점수가 -1.2점으로, 비합리적인 밸류를 가지고 있습니다.""",

    'en': """/no_think
You are a financial analyst. Below are key indicators across 5 tabs (market, fundamental, signal, sector, market valuation).
Write a home headline using exactly this **fixed template** for the first sentence.

**[REQUIRED — first-sentence fixed template]**
"The market is {label}{connector} Market Rationality at {sign}{value}, indicating a {judgment} valuation."

Slots:
1) {label}: valuation label verbatim ("undervalued", "fair", "somewhat overvalued", "overvalued")
2) {connector}: choose by direction agreement
   - Negative label (overvalued) + positive rationality → ", but with" (reversal)
   - Positive label (under/fair) + negative rationality → ", but with" (reversal)
   - Negative label + negative rationality → ", and with" (alignment)
   - Positive label + positive rationality → ", and with" (alignment)
3) {sign}{value}: rationality score with sign (e.g., "+0.9", "-1.2")
4) {judgment}:
   - positive rationality → "reasonable"
   - negative rationality → "unreasonable"

**[OPTIONAL] Second sentence — supporting signal** (omit if all moderate):
F&G extreme, RSI extreme, |gap| >= 20, VIX > 25, or |rationality| >= 2.

Output: 1-2 sentences, under 220 chars, professional tone, no emoji/markdown/em-dash/colon.

Examples:
The market is somewhat overvalued, but with Market Rationality at +0.9, indicating a reasonable valuation.
The market is fair, and with Market Rationality at +1.5, indicating a reasonable valuation.
The market is overvalued, and with Market Rationality at -2.3, indicating an unreasonable valuation. Strong emotional flow stands out.""",
}

_headline_cache: dict = {}  # 키: f"{lang}_{region}", 값: {summary, generated_at, expires}
_headline_lock = threading.Lock()


def _cache_key(lang: str, region: str) -> str:
    """region 별 캐시 키 생성."""
    return f'{lang}_{region}'


def _generate_home_headline(lang: str, region: str) -> dict | None:
    """LLM 호출 + 결과 정리 → {'summary', 'generated_at'}. 실패 시 None.

    스케줄러 (job_kr / job) 와 endpoint fallback 양쪽에서 공유.
    """
    text = _build_home_indicator_text(lang, region=region)
    if not text.strip():
        return None
    result = _groq_call(_HEADLINE_PROMPTS[lang], text, 350)
    if not result:
        return None
    cleaned = result.strip().replace('\n', ' ')
    import re as _re
    sentences = [s.strip() for s in _re.split(r'(?<=[.!?])\s+', cleaned) if s.strip()]
    kept = sentences[:2]
    cleaned = ' '.join(kept).strip()
    if cleaned and not cleaned.endswith(('.', '!', '?')):
        cleaned += '.'
    return {'summary': cleaned, 'generated_at': _kst_now_str()}


def precompute_home_headline(lang: str, region: str) -> bool:
    """스케줄러용 — 헤드라인 미리 생성 후 ai_headline_cache 에 upsert. 성공 시 True."""
    region = _norm_region(region)
    lang = lang if lang in ('ko', 'en') else 'ko'
    out = _generate_home_headline(lang, region)
    if not out:
        return False
    upsert_ai_headline(region, lang, out['summary'], out['generated_at'])
    # 메모리 캐시도 함께 채워 즉시 hit 보장
    with _headline_lock:
        _headline_cache[_cache_key(lang, region)] = {
            'summary': out['summary'],
            'generated_at': out['generated_at'],
            'expires': time.time() + _AI_TTL,
        }
    return True


@router.get('/home-headline')
def get_home_headline(lang: str = Query('ko'), region: str = Query('us')):
    """홈 화면 상단 — 5개 탭 지표 비교 후 1~2문장 헤드라인.

    조회 우선순위: in-memory cache → DB (ai_headline_cache) → LLM 즉석 호출.
    스케줄러 (scheduler/job_kr.py, job.py) 가 미리 생성해 DB 적재 — 사용자 첫 진입에서도 빠름.
    """
    lang = lang if lang in ('ko', 'en') else 'ko'
    region = _norm_region(region)
    err = _ERR_MSGS[lang]
    key = _cache_key(lang, region)
    now = time.time()

    # 1) in-memory hot cache (TTL 만료 전이면 가장 빠름)
    with _headline_lock:
        c = _headline_cache.get(key)
        if c and c['summary'] and now < c['expires']:
            return {'summary': c['summary'], 'generated_at': c['generated_at'], 'cached': True}

    # 2) DB 캐시 (스케줄러 미리 생성한 row)
    try:
        row = fetch_ai_headline(region, lang)
        if row and row.get('summary'):
            with _headline_lock:
                _headline_cache[key] = {
                    'summary': row['summary'],
                    'generated_at': row.get('generated_at'),
                    'expires': now + _AI_TTL,
                }
            return {'summary': row['summary'],
                    'generated_at': row.get('generated_at'),
                    'cached': True, 'source': 'db'}
    except Exception as e:
        print(f'[Home Headline] DB 조회 실패: {e}')

    # 3) DB 미적재 — LLM 즉석 fallback (스케줄러 도입 전 첫 실행 또는 신규 region 추가 시)
    try:
        out = _generate_home_headline(lang, region)
        if not out:
            return {'summary': err['no_data'], 'error': True}
        with _headline_lock:
            _headline_cache[key] = {
                'summary': out['summary'],
                'generated_at': out['generated_at'],
                'expires': now + _AI_TTL,
            }
        # DB 에도 저장 (다음부터는 즉시 응답)
        try:
            upsert_ai_headline(region, lang, out['summary'], out['generated_at'])
        except Exception as e:
            print(f'[Home Headline] DB 저장 실패 (응답은 정상): {e}')
        return {'summary': out['summary'], 'generated_at': out['generated_at'],
                'cached': False, 'source': 'llm'}
    except Exception as e:
        print(f'[Home Headline] error: {e}')
        return {'summary': err['fail'], 'error': True}


@router.get('/ai-summary')                                   # GET /api/market-summary/ai-summary
def get_ai_summary(lang: str = Query('ko'), region: str = Query('us')):
    lang = lang if lang in ('ko', 'en') else 'ko'
    region = _norm_region(region)
    err = _ERR_MSGS[lang]
    key = _cache_key(lang, region)
    now = time.time()
    with _ai_lock:
        c = _ai_cache.get(key)
        if c and c['summary'] and now < c['expires']:
            return {'summary': c['summary'], 'generated_at': c['generated_at'], 'cached': True}
    try:
        text = _build_indicator_text(lang, region=region)
        if not text.strip():
            return {'summary': err['no_data'], 'error': True}
        result = _groq_call(_SUMMARY_PROMPTS[lang], text, 400)
        if not result:
            return {'summary': err['no_service'], 'error': True}
        ts = _kst_now_str()
        with _ai_lock:
            _ai_cache[key] = {'summary': result, 'generated_at': ts, 'expires': now + _AI_TTL}
        return {'summary': result, 'generated_at': ts, 'cached': False}
    except Exception as e:
        print(f'[AI Summary] error: {e}')
        return {'summary': err['fail'], 'error': True}


# ═══════════════════════════════════════════════════════════════
# 각 탭 AI 해설 (펀더멘털 / 신호 / 섹터)
# ═══════════════════════════════════════════════════════════════

_explain_cache = {}                                          # 탭별 AI 해설 캐시 딕셔너리
_explain_lock = threading.Lock()                             # 해설 캐시 동시 접근 보호용 Lock
_EXPLAIN_TTL = 900                                           # 해설 캐시 유효 시간 (15분)

_EXPLAIN_PROMPTS = {                                         # 탭별 AI 해설 시스템 프롬프트 (압축본)
    # 토큰 절약: 시스템 프롬프트 ~600 → ~120 토큰. max_tokens 300 → 150. temperature 0.7 → 0.3.
    # 배경 지식·예시 모두 제거 — 사용자 입력 텍스트가 이미 라벨/구조 충분.
    'ko': {
        'fundamental': "/no_think 한국 투자자 대상 해설. 시장 이성 점수(양수=이성/음수=감정·절대값↑=감정↑)와 피처 기여도 상위 2~3개로 현 상태→원인→투자 의미 3문장. ≤140자, 마크다운 X, 부드러운 어투.",
        'signal':      "/no_think 한국 투자자 대상 해설. 간극=상승−하락(양수=상승우위) + 30일 추세(증가/감소/안정) + SHAP 상위 1~2개 요인. 현 간극→추세→의미 3문장. ≤140자, 마크다운 X, 부드러운 어투.",
        'sector':      "/no_think 한국 투자자 대상 해설. 현 경기 국면 특징 + 유리한 섹터 + 투자 포인트 3문장. ≤140자, 마크다운 X, 부드러운 어투.",
        'sector-val':  "/no_think 한국 투자자 대상 해설. 펀더멘털 갭(가격성장−EPS성장, 양수=비싸짐) z-score 기준 비싼 섹터 1~2 + 싼 섹터 1~2 + 시장 메시지 3문장. ≤160자, 마크다운 X, 부드러운 어투.",
        'sector-mom':  "/no_think 한국 투자자 대상 해설. 3M 모멘텀 상위 + 예상 대비 오버/언더퍼폼 + 경기국면과 일치/배반 3문장. ≤160자, 마크다운 X, 부드러운 어투.",
    },
    'en': {
        'fundamental': "/no_think Plain-English commentary. Market Rationality (+rational/−emotional, larger |negative|=stronger emotion) + top 2-3 feature contributors. State→cause→investor meaning, 3 sentences ≤180 chars. No markdown.",
        'signal':      "/no_think Plain-English commentary. Gap = surge − crash (+upside / −downside) + 30-day trend (rising/falling/stable) + top 1-2 SHAP factors. Current→trend→meaning, 3 sentences ≤180 chars. No markdown.",
        'sector':      "/no_think Plain-English commentary. Current cycle phase + favorable sectors + investor takeaway, 3 sentences ≤180 chars. No markdown.",
        'sector-val':  "/no_think Plain-English commentary. Fundamental Gap (price growth − EPS growth, + = expensive). Top 1-2 expensive + top 1-2 cheap sectors by z-score + market signal, 3 sentences ≤200 chars. No markdown.",
        'sector-mom':  "/no_think Plain-English commentary. Top 3M momentum + biggest over/underperform vs expected + alignment with cycle phase, 3 sentences ≤200 chars. No markdown.",
    },
}


def _build_explain_text(tab: str, lang: str = 'ko', region: str = 'us') -> str:
    """각 탭(펀더멘털/신호/섹터)의 AI 해설에 전달할 데이터 텍스트를 조합."""
    region = _norm_region(region)
    is_en = (lang == 'en')                                   # 영어 여부 플래그
    lines = []                                               # 텍스트 줄 목록

    if tab == 'fundamental':                                 # ── 펀더멘털 탭 ──
        regime = fetch_noise_regime_current(region=region)   # Noise 국면 조회
        if regime:
            lines.append(f"{'Regime' if is_en else '레짐'}: {regime.get('regime_name', '?')}")  # 국면명
            if is_en:
                lines.append(f"Market Rationality Score: {regime.get('noise_score', '?')}")
            else:
                lines.append(f"시장 이성 점수: {regime.get('noise_score', '?')}")
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
        cs = fetch_crash_surge_current(region=region)        # 폭락/급등 현재 점수 조회
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
            history = fetch_crash_surge_history(30, region=region)  # 최근 30일 히스토리 조회
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

    elif tab == 'sector-val':                                # ── 섹터 펀더멘털 갭 탭 ──
        from api.routers.sector_cycle import get_valuation
        v = get_valuation()
        if v and v.get('valuations'):
            phase = v.get('phase_name')
            if phase:
                lines.append(f"{'Cycle' if is_en else '현재 국면'}: {phase}")
            # 가장 비싸진 / 가장 싸진 섹터 (z-score 기준)
            valid = [x for x in v['valuations'] if x.get('per_z') is not None]
            valid.sort(key=lambda x: x['per_z'], reverse=True)
            top = valid[:3]   # 가장 비쌈
            bot = valid[-3:][::-1]  # 가장 쌈 (역순)
            if top:
                lines.append(("Most expensive:" if is_en else "가장 비싸진 섹터:"))
                for x in top:
                    fg_pct = (x['per'] * 100) if x['per'] is not None else None
                    fg_str = f"{fg_pct:+.1f}%" if fg_pct is not None else "?"
                    lines.append(f"  {x['ticker']} ({x['sector_name']}): FG={fg_str}, z={x['per_z']:+.2f}")
            if bot:
                lines.append(("Most cheap:" if is_en else "가장 싸진 섹터:"))
                for x in bot:
                    fg_pct = (x['per'] * 100) if x['per'] is not None else None
                    fg_str = f"{fg_pct:+.1f}%" if fg_pct is not None else "?"
                    lines.append(f"  {x['ticker']} ({x['sector_name']}): FG={fg_str}, z={x['per_z']:+.2f}")

    elif tab == 'sector-mom':                                # ── 섹터 모멘텀 탭 ──
        from processor.feature7_sector_momentum import compute_sector_momentum
        m = compute_sector_momentum(region=region)
        if m and m.get('momentum'):
            mom = m['momentum']
            # 1주일 수익률 기준 랭킹 상위 3 (rank ASC = 1위부터)
            top = sorted(
                [x for x in mom if x.get('rank') is not None],
                key=lambda x: x['rank']
            )[:3]
            bot = sorted(
                [x for x in mom if x.get('rank') is not None],
                key=lambda x: x['rank'], reverse=True
            )[:3]
            if top:
                lines.append(("Top momentum (1W):" if is_en else "모멘텀 상위 (1주일):"))
                for x in top:
                    r1w = x.get('return_1w')
                    r1m = x.get('return_1m')
                    lines.append(f"  rank {x['rank']}: {x['ticker']} ({x['sector_name']}): 1W {r1w:+.1f}%, 1M {r1m:+.1f}%")
            if bot:
                lines.append(("Bottom momentum (1W):" if is_en else "모멘텀 하위 (1주일):"))
                for x in bot:
                    r1w = x.get('return_1w')
                    r1m = x.get('return_1m')
                    lines.append(f"  rank {x['rank']}: {x['ticker']} ({x['sector_name']}): 1W {r1w:+.1f}%, 1M {r1m:+.1f}%")

    elif tab == 'sector':                                    # ── 섹터 탭 ──
        sc = fetch_sector_cycle_latest(region=region)        # 경기국면 조회
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
    # 토큰 한도 초과 / API 실패 / 데이터 미준비 등 모든 실패 케이스를 동일 멘트로 통일
    # (사용자 요청: 토큰 소진 시 등 일관된 안내). bad_tab 만 별도 — 잘못된 호출 표시.
    'ko': {'bad_tab': '지원하지 않는 탭입니다.',
           'no_data': '해설 서비스 개선중.',
           'no_service': '해설 서비스 개선중.',
           'fail': '해설 서비스 개선중.'},
    'en': {'bad_tab': 'Unsupported tab.',
           'no_data': 'Commentary service is being improved.',
           'no_service': 'Commentary service is being improved.',
           'fail': 'Commentary service is being improved.'},
}

def _generate_ai_explain(tab: str, lang: str, region: str) -> dict | None:
    """LLM 호출 → 정리된 해설 텍스트. 실패 시 None.

    Returns: {'explanation': str, 'generated_at': str} 또는 None.
    """
    try:
        text = _build_explain_text(tab, lang, region=region)
        if not text.strip():
            return None
        result = _groq_call(_EXPLAIN_PROMPTS[lang][tab], text, 150)
        if not result:
            return None
        return {'explanation': result.strip(), 'generated_at': _kst_now_str()}
    except Exception as e:
        print(f'[AI Explain {tab}/{lang}/{region}] generate error: {e}')
        return None


def precompute_ai_explain(tab: str, lang: str, region: str) -> bool:
    """스케줄러용 — 해설 미리 생성 후 ai_explain_cache 에 upsert. 성공 시 True.

    in-memory 캐시도 함께 채워 즉시 hit 보장.
    """
    if tab not in _EXPLAIN_PROMPTS.get('ko', {}):
        return False
    region = _norm_region(region)
    lang = lang if lang in ('ko', 'en') else 'ko'
    out = _generate_ai_explain(tab, lang, region)
    if not out:
        return False
    upsert_ai_explain(tab, lang, region, out['explanation'], out['generated_at'])
    cache_key = f'explain_{tab}_{lang}_{region}'
    with _explain_lock:
        _explain_cache[cache_key] = {
            'text': out['explanation'],
            'expires': time.time() + _EXPLAIN_TTL,
        }
    return True


@router.get('/ai-explain')                                   # GET /api/market-summary/ai-explain
def get_ai_explain(tab: str = Query(..., description='fundamental, signal, sector, sector-val, sector-mom'),
                   lang: str = Query('ko'),
                   region: str = Query('us')):
    """3-tier fallback: in-memory cache → DB (ai_explain_cache) → LLM 즉석 호출.

    스케줄러가 미리 생성해 DB 적재 — 사용자 첫 진입에서도 즉시 응답.
    """
    lang = lang if lang in ('ko', 'en') else 'ko'
    region = _norm_region(region)
    err = _EXPLAIN_ERR[lang]
    if tab not in _EXPLAIN_PROMPTS['ko']:
        return {'explanation': err['bad_tab'], 'error': True}

    now = time.time()
    cache_key = f'explain_{tab}_{lang}_{region}'             # region 별 캐시 분리

    # 1차: in-memory cache (TTL 안)
    with _explain_lock:
        cached = _explain_cache.get(cache_key)
        if cached and now < cached.get('expires', 0):
            return {'explanation': cached['text'], 'tab': tab, 'cached': True}

    # 2차: DB cache (스케줄러 미리 적재)
    try:
        row = fetch_ai_explain(tab, lang, region)
    except Exception as e:
        print(f'[AI Explain {tab}/{lang}/{region}] DB read 실패 (계속 진행): {e}')
        row = None
    if row and row.get('explanation'):
        with _explain_lock:
            _explain_cache[cache_key] = {
                'text': row['explanation'],
                'expires': now + _EXPLAIN_TTL,
            }
        return {
            'explanation': row['explanation'],
            'tab': tab,
            'cached': True,
            'generated_at': row.get('generated_at'),
        }

    # 3차: LLM 즉석 호출 (캐시 미스 fallback)
    try:
        out = _generate_ai_explain(tab, lang, region)
        if not out:
            return {'explanation': err['no_data'], 'tab': tab, 'error': True}
        # DB + memory 모두 채워 다음 호출 즉시 hit
        upsert_ai_explain(tab, lang, region, out['explanation'], out['generated_at'])
        with _explain_lock:
            _explain_cache[cache_key] = {
                'text': out['explanation'],
                'expires': now + _EXPLAIN_TTL,
            }
        return {
            'explanation': out['explanation'],
            'tab': tab,
            'cached': False,
            'generated_at': out['generated_at'],
        }
    except Exception as e:
        print(f'[AI Explain {tab}] error: {e}')
        return {'explanation': err['fail'], 'tab': tab, 'error': True}
