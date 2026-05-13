import os                                                    # 환경변수 접근용
import time                                                  # 캐시 만료 시간 계산용
import threading                                             # 캐시 동시 접근 보호용 Lock
import json                                                  # JSONB 필드 파싱용
from datetime import datetime, timezone, timedelta           # KST 시간 변환용
from fastapi import APIRouter, Query, BackgroundTasks       # FastAPI 라우터 + 쿼리 파라미터 + 백그라운드 작업
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
    fetch_anomaly_current,                                   # 최신 이상 탐지 (평소 이탈도) 조회
    upsert_ai_headline,                                      # 홈 헤드라인 DB 캐시 upsert
    fetch_ai_headline,                                       # 홈 헤드라인 DB 캐시 조회
    upsert_ai_explain,                                       # 5탭 AI 해설 DB 캐시 upsert
    fetch_ai_explain,                                        # 5탭 AI 해설 DB 캐시 조회
    upsert_app_cache,                                        # 무거운 API 응답 사전 계산 캐시 upsert
    fetch_app_cache,                                         # 무거운 API 응답 사전 계산 캐시 조회
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


def _market_summary_today_cache_key(region: str) -> str:
    return f'market_summary_today_{region}'


def _compute_market_summary_today_payload(region: str) -> dict:
    """4개 fetch_* 합본. precompute + endpoint fallback 양쪽에서 공용."""
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
    return {
        'fear_greed': ({'score': round(score), 'rating': rating}
                        if has_fg else None),
        'market_return': {'value': round(avg_return, 2)},
        'rsi': rsi,
        'crash_surge': crash_surge,
        'region': region,
    }


def precompute_market_summary_today(region: str) -> bool:
    """스케줄러용 — 시장 요약 4개 fetch 합본을 app_cache 에 적재.
    endpoint 호출 시 4 RTT (~3s) → 1 RTT (~2s) 로 단축."""
    payload = _compute_market_summary_today_payload(region)
    if not payload:
        return False
    upsert_app_cache(_market_summary_today_cache_key(region), payload)
    return True


@router.get('/today')                                        # GET /api/market-summary/today
def get_market_summary_today(region: str = Query('us')):
    """app_cache 우선 (1 RTT). miss 시 live 4-RTT compute 폴백."""
    region = _norm_region(region)
    cached = fetch_app_cache(_market_summary_today_cache_key(region))
    if cached and isinstance(cached, dict):
        return {**cached, 'cached': True}
    # 폴백: 4 fetch 직렬 (스케줄러 미실행 환경)
    return _compute_market_summary_today_payload(region)


@router.get('/tab-headline')                                  # GET /api/market-summary/tab-headline
def get_tab_headlines(region: str = Query('us')):
    """8개 탭 한 줄 해설 일괄 조회. app_cache 우선, miss 시 live compute 폴백.
    룰베이스 (LLM 미사용). 초보자가 각 탭의 오늘 상태를 한 문장으로 파악.
    """
    from processor.tab_headline import fetch_tab_headlines     # 지연 임포트 (순환 방지)
    region = _norm_region(region)
    payload = fetch_tab_headlines(region)
    return payload or {'region': region, 'cached': False}


# ═══════════════════════════════════════════════════════════════
# Groq LLM 공통
# ═══════════════════════════════════════════════════════════════

_GROQ_DISABLED_LOGGED = False                                 # 비활성 경고 1회만 출력


def _groq_call(system_prompt: str, user_text: str, max_tokens: int = 300):
    """Groq API 호출 공통 함수.

    DISABLE_GROQ=true (또는 1, yes) 면 즉시 None 반환 — scheduler / endpoint /
    fallback 어느 경로로 들어와도 LLM 호출 0. 로컬 개발 시 Railway 와 quota 중복
    소진 방지용. .env 에 DISABLE_GROQ=true 만 넣으면 끝.
    """
    if os.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes'):
        global _GROQ_DISABLED_LOGGED
        if not _GROQ_DISABLED_LOGGED:
            print('[AI] DISABLE_GROQ flag detected — Groq 호출 모두 차단 (로컬 개발용 모드)')
            _GROQ_DISABLED_LOGGED = True
        return None
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
        temperature=0.3,                                     # 창의성 수준 (0~1) — 해설은 일관성 우선
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
    # 이상 탐지 (평소와의 거리 D²) — 신호 탭 crash/surge 폐기되고 anomaly 차트로 교체된 이후 정합 데이터 source.
    an = fetch_anomaly_current(region=region)
    if an:
        d2 = an.get('d2')
        pct_10y = an.get('percentile_10y')
        top_pct = round(100 - float(pct_10y), 1) if isinstance(pct_10y, (int, float)) else None
        if lang == 'en':
            lines.append(
                f"Anomaly Distance (D²): {d2}"
                + (f", top {top_pct}% in 10-year distribution" if top_pct is not None else "")
            )
        else:
            lines.append(
                f"평소와의 거리(D²): {d2}"
                + (f" — 10년 분포 내 상위 {top_pct}%" if top_pct is not None else "")
            )
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


_SUMMARY_PROMPTS = {                                         # 시황 종합 요약 — 4줄 "제목 — 내용" 형식 (옛 형식 복원, 신호탭 자리만 평소 이탈도 D² 로 교체)
    'ko': """/no_think
너는 투자자에게 쉽게 설명해주는 한국어 금융 애널리스트다.
주어진 지표를 종합해 시장 브리핑을 작성하라.

반드시 아래 4줄을 출력하라. 각 줄은 반드시 "제목 — 내용" 형식이다.
"—" (em dash) 앞뒤에 반드시 공백을 넣어라. 제목과 내용을 절대 붙여 쓰지 마라.

[이모지] 시장 심리 — (공포탐욕·VIX·RSI를 종합한 심리 해석 1문장)
[이모지] 평소 이탈도 — (평소와의 거리 D² 와 10년 분포 내 상위 N% 위치를 한 문장으로 묘사. 작을수록 평소 분포 중심, 클수록 평소에서 멀리 떨어진 상태)
[이모지] 펀더멘털 — (시장 이성 점수 기반 주가-펀더멘털 관계 1문장. 양수=이성, 음수=감정)
[이모지] 종합 — (위 3가지를 종합한 *현재 상태 기록* 1문장. 행동 제안·방향 예측 X. **반드시 "종합" 으로 시작**, "펀더멘털"·"심리"·"평소 이탈도" 로 시작 금지.)

예시:
❄️ 시장 심리 — 공포 지수 19로 극단적 공포 구간이며, 투자 심리가 크게 위축된 상태입니다.
📊 평소 이탈도 — D² 8.2 로 10년 상위 18% 위치, 평소 분포에서 다소 떨어진 상태입니다.
🧭 펀더멘털 — 이성 점수 -2.1로 주가와 펀더멘털 사이 괴리가 존재합니다.
🎯 종합 — 심리·시장 상태·펀더멘털이 같은 방향으로 평소에서 벗어난 *교과서적 동반 이격* 상태입니다.

이모지 선택:
- 공포/평소와 멈: 🔻❄️🌧️⚠️🥶  탐욕/극단: 🔥🚀☀️💪🟢  중간: ⚖️🔄🌤️
- 평소 이탈도: 📊📈📉🔍  펀더멘털 괴리: 🧭📉🔍  반영: ✅💎📊  인사이트: 🎯💡⭐🔑
- 4줄 모두 다른 이모지

자문 가드 (절대 위반 금지):
- 매수/매도/추천/유리/불리/위험/안전/매수타이밍/상승전망/하락전망/예측/전망/기대/포트폴리오/목표가/수익률 보장 단어 금지.
- *crash/surge·간극·상승 우위·하락 우위·신호 간극* 단어 금지 (옛 신호탭 폐기됨, 평소 이탈도 D² + 분위만 사용).
- 미래 방향 추정 ("~할 것이다", "~로 이어질 가능성") 금지.

기타 규칙:
- 반드시 "제목 — 내용" 형식 (— 앞뒤 공백 필수). 마크다운(**볼드** 등) 절대 사용 금지.
- 부드러운 어투 (~입니다, ~상태입니다). 각 줄 60자 이내.
- 영문 약어/snake_case 변수명 그대로 쓰지 말고 한국어 자연어로 (예: hy_spread → 하이일드 스프레드).
- *한자 절대 사용 금지* — 한글/영문/숫자/기호만.""",

    'en': """/no_think
You are a financial analyst who explains market conditions to investors in plain English.
Synthesize the given indicators into a market briefing.

Output exactly 4 lines. Each line must follow the format: "Title — Content".
Use an em dash "—" with spaces on both sides. Never merge the title and content.

[emoji] Market Sentiment — (1 sentence interpreting Fear & Greed, VIX, RSI)
[emoji] Anomaly Distance — (1 sentence describing today's D² and its top N% position in the 10-year distribution; smaller = closer to typical, larger = farther from typical)
[emoji] Fundamentals — (1 sentence on price-fundamental relationship via Market Rationality Score; positive=rational, negative=emotional)
[emoji] Overall — (1 sentence combining the above 3 as a *current-state record*; NO action suggestion, NO direction prediction)

Example:
❄️ Market Sentiment — Fear index at 19, deep in extreme fear with severely depressed sentiment.
📊 Anomaly Distance — D² 8.2 puts today in the top 18% of the 10-year distribution, somewhat off the typical center.
🧭 Fundamentals — Rationality score -2.1 shows a gap between price and fundamentals.
🎯 Overall — Sentiment, market state, and fundamentals all deviate from typical together — a textbook co-deviation pattern.

Emoji choices:
- Fear/typical: 🔻❄️🌧️⚠️🥶  Greed/extreme: 🔥🚀☀️💪🟢  Middle: ⚖️🔄🌤️
- Anomaly distance: 📊📈📉🔍  Fundamental divergence: 🧭📉🔍  Aligned: ✅💎📊  Overall: 🎯💡⭐🔑
- Use a different emoji for each line.

Advice-risk guard (must not violate):
- NO words: buy/sell/recommend/favorable/risky/safe/timing/upside-outlook/downside-outlook/predict/forecast/expect/portfolio/target-price/return-guarantee.
- NO crash/surge/gap/upside-edge/downside-edge/signal-gap terms (the old signal tab is deprecated; only D² + percentile).
- NO future-direction inference ("will", "may lead to").

Other rules:
- Strictly "Title — Content" format (spaces around — required). No markdown (no bold).
- Professional yet approachable tone. Each line under 80 characters.
- Translate snake_case feature names to natural language (e.g., hy_spread → high-yield spread).
- NO Chinese characters in output (English/numbers/symbols only).""",
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

    # ── 이상 탐지 탭 (평소와의 거리) ──
    # 신호 탭이 anomaly 차트로 교체된 이후 ([117]+) 동일 데이터 source 사용.
    section = []
    an = fetch_anomaly_current(region=region)
    if an:
        d2 = an.get('d2')
        pct_10y = an.get('percentile_10y')
        pct_90d = an.get('percentile_90d')
        top_pct = round(100 - float(pct_10y), 1) if isinstance(pct_10y, (int, float)) else None
        if is_en:
            section.append(f"Anomaly Distance (D²): {d2}")
            if top_pct is not None:
                section.append(f"Position: top {top_pct}% in 10-year distribution")
            if pct_90d is not None:
                section.append(f"90-day percentile: {pct_90d}")
        else:
            section.append(f"평소와의 거리(D²): {d2}")
            if top_pct is not None:
                section.append(f"위치: 10년 분포 내 상위 {top_pct}%")
            if pct_90d is not None:
                section.append(f"90일 분위: {pct_90d}")
    if section:
        lines.append(f"[{'Anomaly Tab' if is_en else '이상 탐지 탭'}]")
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
    # 2 문장 고정: 1) 요약 (심리·이상도·이성점수 데이터 묘사) 2) 인사이트 (조합의 객관적 의미).
    # 자문 리스크 가드 — *가치판단·예측·자문 단어 모두 금지*, 관찰·묘사만.
    'ko': (
        "/no_think 한국어 금융 해설. 아래 지표 중 다음 3 가지만 사용해 정확히 2 문장 작성.\n"
        "사용 지표: 심리(공포탐욕 점수·등급), 이상도(평소와의 거리 D² 위치 = 10년 분포 내 상위 N%), 이성 점수(양수=이성, 음수=감정).\n"
        "문장 1 [요약] — 세 지표 값을 그대로 묘사하는 한 문장.\n"
        "  예: '오늘 심리는 공포(38), 평소와의 거리는 상위 28%, 이성 점수는 +1.6입니다.'\n"
        "문장 2 [인사이트] — 세 지표 조합의 객관적 의미 한 문장 (관찰·묘사만, 판단·전망 X).\n"
        "  예: '심리 위축에도 펀더멘털 정합성이 유지되어 비대칭적 구간으로 관측됩니다.'\n"
        "절대 금지 단어 (출력에 *한 번이라도* 들어가면 안 됨):\n"
        "  매수, 매도, 추천, 매수 타이밍, 매도 타이밍, 상승 전망, 하락 전망, 예측, 전망, 기대, 확률,\n"
        "  *고평가, 저평가, 비싸다, 싸다, 합리적인 밸류, 적정 밸류, 비합리적, 적정 가격, 과대평가, 과소평가, 밸류, 평가, 판단*,\n"
        "  유리, 불리, 위험, 안전, 포트폴리오, 목표가, 수익률 보장.\n"
        "허용: 사실 묘사 (값과 위치), 일반론적 메커니즘 ('A 가 B 와 함께 관측됨'·'정합성 유지'·'비대칭 구간').\n"
        "규칙: 정확히 2 문장, 두 문장 사이 줄바꿈 X (한 줄에 둘 다 마침표로 구분). ≤200자.\n"
        "이모지·마크다운·대시(—)·콜론·물음표·느낌표 X. 한자 X. 두 문장 모두 마침표로 끝낼 것."
    ),
    'en': (
        "/no_think English financial commentary. Use only these 3 indicators below to write exactly 2 sentences.\n"
        "Indicators: Sentiment (Fear & Greed score & rating), Anomaly (D² position = top N% of 10-year distribution), Rationality (positive=rational, negative=emotional).\n"
        "Sentence 1 [Summary] — state all three values factually.\n"
        "  Example: 'Sentiment reads fearful (38), anomaly distance sits in the top 28%, rationality at +1.6.'\n"
        "Sentence 2 [Insight] — one objective interpretation of the combination (observation only, no judgment, no forecast).\n"
        "  Example: 'Sentiment is subdued while fundamental coherence persists, an asymmetric configuration is observed.'\n"
        "Banned words (must not appear even once):\n"
        "  buy, sell, recommend, timing, upside-outlook, downside-outlook, predict, forecast, expect, probability,\n"
        "  overvalued, undervalued, expensive, cheap, fair-value, reasonable-valuation, overpriced, underpriced, valuation-judgment, fairly-valued,\n"
        "  favorable, risky, safe, portfolio, target-price, return-guarantee.\n"
        "Allowed: factual description (values and positions), textbook mechanism ('A coexists with B', 'coherence persists', 'asymmetric configuration').\n"
        "Rules: exactly 2 sentences, no line break between them, ≤240 chars.\n"
        "No emoji, markdown, em-dash, colon, question mark, exclamation. No Chinese characters. Both end with a period."
    ),
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
    result = _groq_call(_HEADLINE_PROMPTS[lang], text, 150)
    if not result:
        return None
    cleaned = result.strip().replace('\n', ' ')
    import re as _re
    sentences = [s.strip() for s in _re.split(r'(?<=[.!?])\s+', cleaned) if s.strip()]
    kept = sentences[:2]
    # 요약 + 인사이트 사이를 \n 으로 분리 — 프론트(.home-ai-body white-space:pre-line) 가 줄바꿈 렌더.
    cleaned = '\n'.join(kept).strip()
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


def _ai_summary_cache_key(lang: str, region: str) -> str:
    return f'market_ai_summary:{region}:{lang}'


def _generate_ai_summary(lang: str, region: str) -> dict | None:
    """시장 탭 AI 요약을 생성. 스케줄러 precompute 전용."""
    text = _build_indicator_text(lang, region=region)
    if not text.strip():
        return None
    result = _groq_call(_SUMMARY_PROMPTS[lang], text, 400)
    if not result:
        return None
    return {'summary': result, 'generated_at': _kst_now_str(), 'cached': False}


def precompute_ai_summary(lang: str, region: str) -> bool:
    """스케줄러용 — 시장 탭 AI 요약 미리 생성 후 app_cache 에 저장."""
    region = _norm_region(region)
    lang = lang if lang in ('ko', 'en') else 'ko'
    out = _generate_ai_summary(lang, region)
    if not out:
        return False
    payload = {**out, 'cached': True, 'source': 'app_cache'}
    upsert_app_cache(_ai_summary_cache_key(lang, region), payload)
    with _ai_lock:
        _ai_cache[_cache_key(lang, region)] = {
            'summary': out['summary'],
            'generated_at': out['generated_at'],
            'expires': time.time() + _AI_TTL,
        }
    return True


# ── 옵션 C: 백그라운드 LLM 워커 ────────────────────────────────────────────
# 사용자 요청이 cache miss 시 즉시 fallback 응답 + 여기서 LLM 비동기 실행해
# 다음 요청용 캐시(_ai_cache + app_cache 또는 ai_explain_cache) 만 채운다.
# 한 키당 동시 실행 1건만 허용 (중복 LLM 호출·중복 비용 차단).
_bg_running: set[str] = set()
_bg_lock = threading.Lock()


def _bg_generate_summary(lang: str, region: str) -> None:
    """백그라운드: 시황 AI 요약 LLM 생성 → app_cache + in-memory 적재."""
    bg_key = f'summary:{lang}:{region}'
    with _bg_lock:
        if bg_key in _bg_running:
            return
        _bg_running.add(bg_key)
    try:
        out = _generate_ai_summary(lang, region)
        if out and out.get('summary'):
            try:
                upsert_app_cache(_ai_summary_cache_key(lang, region),
                                 {**out, 'cached': True, 'source': 'app_cache'})
            except Exception as e:
                print(f'[AI Summary BG] cache write failed: {e}')
            with _ai_lock:
                _ai_cache[_cache_key(lang, region)] = {
                    'summary': out['summary'],
                    'generated_at': out.get('generated_at'),
                    'expires': time.time() + _AI_TTL,
                }
            print(f'[AI Summary BG] {lang}/{region} 생성·캐시 완료')
    except Exception as e:
        print(f'[AI Summary BG] {lang}/{region} 실패: {e}')
    finally:
        with _bg_lock:
            _bg_running.discard(bg_key)


def _bg_generate_explain(tab: str, lang: str, region: str) -> None:
    """백그라운드: 5탭 AI 해설 LLM 생성 → ai_explain_cache + in-memory 적재."""
    bg_key = f'explain:{tab}:{lang}:{region}'
    with _bg_lock:
        if bg_key in _bg_running:
            return
        _bg_running.add(bg_key)
    try:
        out = _generate_ai_explain(tab, lang, region)
        if out and out.get('explanation'):
            try:
                upsert_ai_explain(tab, lang, region, out['explanation'])
            except Exception as e:
                print(f'[AI Explain BG {tab}/{lang}/{region}] cache write failed: {e}')
            cache_key = f'explain_{tab}_{lang}_{region}'
            with _explain_lock:
                _explain_cache[cache_key] = {
                    'text': out['explanation'],
                    'expires': time.time() + _EXPLAIN_TTL,
                }
            print(f'[AI Explain BG {tab}/{lang}/{region}] 생성·캐시 완료')
    except Exception as e:
        print(f'[AI Explain BG {tab}/{lang}/{region}] 실패: {e}')
    finally:
        with _bg_lock:
            _bg_running.discard(bg_key)


@router.get('/home-headline')
def get_home_headline(lang: str = Query('ko'), region: str = Query('us')):
    """홈 화면 상단 — 5개 탭 지표 비교 후 1~2문장 헤드라인.

    조회 우선순위: in-memory cache → DB (ai_headline_cache).
    스케줄러가 미리 생성해 DB 적재하며, 사용자 요청 중 LLM을 기다리지 않는다.
    """
    lang = lang if lang in ('ko', 'en') else 'ko'
    region = _norm_region(region)
    err = _ERR_MSGS[lang]
    key = _cache_key(lang, region)
    now = time.time()

    disable_groq = os.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes')

    if not disable_groq:
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

    # 3) rule-based fallback — _fallback_ai_summary 의 첫 두 라인으로 짧은 헤드라인 구성
    try:
        full = _fallback_ai_summary(lang, region)
        lines = [l for l in (full or '').splitlines() if l.strip()]
        head = '\n'.join(lines[:2]) if lines else (err.get('no_data') or '지표 동기화 후 표시됩니다.')
        return {'summary': head, 'generated_at': _kst_now_str(),
                'cached': False, 'source': 'fallback'}
    except Exception:
        return {'summary': err['no_data'], 'error': True, 'cached': False, 'source': 'cache_miss'}


@router.get('/ai-summary')                                   # GET /api/market-summary/ai-summary
def get_ai_summary(background_tasks: BackgroundTasks,
                   lang: str = Query('ko'),
                   region: str = Query('us')):
    """옵션 C: cache miss 시 즉시 fallback 응답 + 백그라운드에서 LLM 생성하여 다음 요청용
    캐시(app_cache + in-memory) 만 채운다. 사용자는 첫 요청도 ~1초 내 응답받고, 새로고침
    또는 다음 진입 시 LLM 결과 노출. 동일 키 동시 실행은 _bg_running 으로 차단.
    """
    lang = lang if lang in ('ko', 'en') else 'ko'
    region = _norm_region(region)
    err = _ERR_MSGS[lang]
    key = _cache_key(lang, region)
    now = time.time()
    # DISABLE_GROQ=true: 옛 LLM 캐시(in-memory/DB) 완전 무시하고 매번 fresh fallback 으로
    disable_groq = os.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes')
    if not disable_groq:
        # 1차: in-memory cache hit
        with _ai_lock:
            c = _ai_cache.get(key)
            if c and c['summary'] and now < c['expires']:
                return {'summary': c['summary'], 'generated_at': c['generated_at'], 'cached': True}
        # 2차: DB (app_cache) hit
        try:
            payload = fetch_app_cache(_ai_summary_cache_key(lang, region))
            if payload and payload.get('summary'):
                with _ai_lock:
                    _ai_cache[key] = {
                        'summary': payload['summary'],
                        'generated_at': payload.get('generated_at'),
                        'expires': now + _AI_TTL,
                    }
                return {**payload, 'cached': True, 'source': 'app_cache'}
        except Exception as e:
            print(f'[AI Summary] DB read 실패 (계속 진행): {e}')
    # 3차: cache miss → 즉시 fallback 응답 + 백그라운드 LLM 생성 (다음 요청용 캐시)
    try:
        fallback = _fallback_ai_summary(lang, region)
    except Exception as e:
        print(f'[AI Summary] fallback error: {e}')
        fallback = err.get('fail') or '현재 지표 기준으로 시장 상황을 점검 중입니다.'
    # DISABLE_GROQ=true: 백그라운드 LLM 생성 등록 안 함 (LLM 호출 0 강제)
    if os.getenv('DISABLE_GROQ', '').lower() not in ('true', '1', 'yes'):
        background_tasks.add_task(_bg_generate_summary, lang, region)
    return {'summary': fallback, 'generated_at': _kst_now_str(),
            'cached': False, 'source': 'fallback'}


# ═══════════════════════════════════════════════════════════════
# 각 탭 AI 해설 (펀더멘털 / 신호 / 섹터)
# ═══════════════════════════════════════════════════════════════

_explain_cache = {}                                          # 탭별 AI 해설 캐시 딕셔너리
_explain_lock = threading.Lock()                             # 해설 캐시 동시 접근 보호용 Lock
_EXPLAIN_TTL = 900                                           # 해설 캐시 유효 시간 (15분)

_EXPLAIN_PROMPTS = {                                         # 탭별 AI 해설 — 3 블록 구조
    # 출력 구조 (모든 탭 공통, 반드시 이 순서·형식):
    #   [블록 1] 데이터 요약 — 입력으로 받은 모든 핵심 수치를 빠짐없이 한 묶음으로 정리하고 한 줄 요약 추가.
    #   [블록 2] 주요 변수 설명 — 위 데이터 중 영향이 큰 변수 1~2 개에 대해 *왜 이 변수가 모델에 영향을
    #            주는지* 쉽고 짧게 설명 (한 줄/지표).
    #   [블록 3] 인사이트 — 데이터+변수 의미를 종합한 *교과서적* 패턴/관찰 한 줄. 방향 예측·자문 금지.
    #
    # 가독성 규칙 (모든 블록 공통):
    #   - 블록 사이는 *반드시 빈 줄(\n\n)* 로 분리.
    #   - 각 블록 안에서도 핵심 줄 사이에 \n 줄바꿈 활용.
    #   - 마크다운 X (별표 강조·헤더 #·표 등 금지).
    #   - *한자 절대 사용 금지* — 한글/영문/숫자/기호만. 예: "韓"·"美"·"中"·"對立" 등 모두 한글로 ("한국"·"미국"·"중국"·"대립").
    #
    # 변수명 번역 규칙 (영문 snake_case → 한국어 자연어 + 짧은 의미):
    #   hy_spread → 하이일드 스프레드(신용 위험 프리미엄)
    #   vix_term → VIX 텀 구조(단기/장기 변동성 비)
    #   erp_zscore → 주식 위험 프리미엄 z-점수
    #   fundamental_gap → 펀더멘털 갭(실적 vs 가격 괴리)
    #   residual_corr → 잔차 상관(개별주 동조성)
    #   dispersion → 종목 분산(수익률 격차)
    #   amihud → 유동성 비용(체결 충격)
    #   realized_vol → 실현 변동성
    #
    # 자문 가드 (절대 금지 단어):
    #   매수/매도/추천/유리/불리/위험/안전/매수타이밍/상승전망/하락전망/예측/전망/기대/선반영/
    #   포트폴리오/목표가/수익률 보장. 미래 방향 추정 ("~할 것이다", "~로 이어질 가능성") 금지.
    'ko': {
        'fundamental': "/no_think 한국 사용자. *3 블록* 으로 출력.\n본 탭은 펀더멘털 반영도 — 가격 변화율 − 이익 변화율 (log diff). 양수=가격이 이익을 추월, 음수=가격이 이익을 따라가지 못함, 0 근처=균형(반영). '이성/감정 점수'·'거품' 단어 절대 금지.\n[1] 데이터 요약: 입력의 펀더멘털 갭 값·10년 분포 내 상위 N%·1년 가격 추월률·분포 평균 등을 한 줄로 모아 + 한 줄 요약 ('오늘 펀더멘털 갭 X — 10년 상위 N% 추월 영역/하위 N% 압축 영역/균형 영역').\n[2] 주요 변수 설명: 가격(P) 와 이익(E) 의 1년 변화율을 한국어로 정리 + *왜 두 변화율 차이가 추월/압축 측정에 쓰이는지* 쉽고 짧게.\n[3] 인사이트: 데이터 종합한 교과서적 관찰 한 줄 (현재값이 분포 어느 위치인지 + 그 의미).\n블록 사이 빈 줄(\\n\\n). 한자 절대 금지. 매수/매도/추천/유리/불리/위험/예측/전망/기대/이성/감정/거품 단어 금지. 마크다운 X. ≤320자.",
        'signal':      "/no_think 한국 사용자. *3 블록* 으로 출력. 본 탭은 이상 탐지(평소와의 거리 D²). 'crash/surge 점수·간극' 개념 사용 금지 — D² 와 분위만.\n[1] 데이터 요약: D² 값·10년 분포 내 상위 N% 위치·90일 분위·주요 기여 지표·유사 과거 시점 등 입력값 모두 한 묶음으로 + 한 줄 요약 ('오늘 평소와의 거리는 X 로 10년 상위 N% 위치').\n[2] 주요 변수 설명: 기여 큰 지표 1~2 개 — 한국어 라벨 + *왜 이 변수가 거리 계산에 들어가는지* 쉽게 한 줄/지표.\n[3] 인사이트: 데이터·변수 의미 종합 교과서 패턴 한 줄.\n블록 사이 빈 줄(\\n\\n). 한자 금지. 매수/매도/추천/유리/불리/위험/안전/예측/전망/기대/상승·하락 압력·우위 단어 금지. 마크다운 X. ≤320자.",
        'sector':      "/no_think 한국 사용자. *3 블록* 으로 출력.\n[1] 데이터 요약: 입력의 경기 국면명·매크로 스냅샷·상위 섹터 모두 정리 + 한 줄 요약.\n[2] 주요 변수 설명: 핵심 매크로 지표 1~2 개 — 한국어 라벨 + *왜 그 지표가 경기 국면 분류에 영향 주는지* 쉽게.\n[3] 인사이트: 거시 사이클상 *교과서적*으로 그 국면에서 함께 거론되는 섹터 한 줄 (추천 X, 사실).\n블록 사이 빈 줄(\\n\\n). 한자 금지. 매수/매도/추천/유리/불리/예측/전망/수혜 단어 금지. 마크다운 X. ≤320자.",
        'sector-val':  "/no_think 한국 사용자 중립 비교. *3 블록* 으로 출력.\n[1] 데이터 요약: 평균 대비 차이가 큰 1~2 섹터의 PER/PBR 위치를 '평균 대비 +X%' 형태로 정리.\n[2] 주요 변수 설명: PER 평균 대비 차이가 *왜 의미 있는지* 쉽고 중립적으로 (고평가/저평가 단어 X).\n[3] 인사이트: 상대 위치 사실의 교과서적 의미 한 줄 (방향 예측 X).\n블록 사이 빈 줄(\\n\\n). 한자 금지. 가치판단(고평가/저평가/비싸다/싸다/매수/매도/추천/유리/불리) 절대 금지. 마크다운 X. ≤320자.",
        'sector-mom':  "/no_think 한국 사용자. *3 블록* 으로 출력.\n[1] 데이터 요약: 1주일·1개월 모멘텀 상위/하위 섹터 수치 정리.\n[2] 주요 변수 설명: 1주 수익률·랭크가 *왜 단기 로테이션 신호로 쓰이는지* 쉽게.\n[3] 인사이트: 경기 국면과 일치/배반 여부의 *교과서적* 의미 한 줄.\n블록 사이 빈 줄(\\n\\n). 한자 금지. 선반영/기대/예측/회복 전망/유리/불리/추천/매수/매도 단어 금지. 마크다운 X. ≤320자.",
    },
    'en': {
        'fundamental': "/no_think English. Output *3 blocks*.\nThis tab is fundamental gap — price change minus earnings change (log diff). Positive=price outpaced earnings, negative=price lagged earnings, near-zero=balanced. NEVER use 'rationality/emotion score' or 'bubble'.\n[1] Data summary: fundamental_gap value, top N% position in 10-year distribution, 1-year price outpace %, distribution mean — all in one block + one-line summary.\n[2] Variable explanation: 1-year price return (P) vs 1-year earnings return (E) — natural English + WHY the difference measures outpace/compression.\n[3] Insight: textbook pattern combining data + variable meaning, one line.\nSeparate blocks with blank line (\\n\\n). NO Chinese characters. NO buy/sell/recommend/favorable/risky/safe/predict/forecast/expect/outlook/rationality/emotion/bubble words. No markdown. ≤360 chars.",
        'signal':      "/no_think English. Output *3 blocks*. Anomaly tab — use D² and percentile only, NEVER crash/surge gap concepts.\n[1] Data summary: D² value, 10-year top N% position, 90-day percentile, top contributors, similar past dates — all inputs as one block + one-line summary ('today's distance from usual is X, in the top N% of the 10-year distribution').\n[2] Variable explanation: 1-2 top contributors — natural-language label + WHY this variable enters the distance calculation (one line each).\n[3] Insight: textbook pattern combining data + variable meaning, one line.\nSeparate blocks with blank line (\\n\\n). NO Chinese chars. NO buy/sell/recommend/favorable/risky/safe/predict/forecast/expect/upside/downside/pressure words. No markdown. ≤360 chars.",
        'sector':      "/no_think English. Output *3 blocks*.\n[1] Data summary: cycle phase name, macro snapshot, favored sectors — all input.\n[2] Variable explanation: 1-2 macro indicators — natural label + WHY they classify the cycle phase.\n[3] Insight: textbook macro-cycle co-occurrence with sectors (factual, no recommendation).\nSeparate blocks with blank line (\\n\\n). NO Chinese chars. NO buy/sell/recommend/favorable/benefits/predict/forecast words. No markdown. ≤360 chars.",
        'sector-val':  "/no_think English neutral comparison. Output *3 blocks*.\n[1] Data summary: 1-2 sectors with largest deviation in 'X% vs avg' form.\n[2] Variable explanation: WHY a PER deviation vs historical average is meaningful (neutral, NO over/under-valuation language).\n[3] Insight: textbook meaning of relative position (no direction prediction).\nSeparate blocks with blank line (\\n\\n). NO Chinese chars. NEVER use valuation judgments (overvalued/undervalued/expensive/cheap/buy/sell/recommend/favorable). No markdown. ≤360 chars.",
        'sector-mom':  "/no_think English. Output *3 blocks*.\n[1] Data summary: 1-week and 1-month momentum top/bottom sectors.\n[2] Variable explanation: WHY 1-week return / rank is used as a short-term rotation signal.\n[3] Insight: textbook meaning of alignment/divergence with the cycle phase, one line.\nSeparate blocks with blank line (\\n\\n). NO Chinese chars. NO priced-in/expect/predict/recovery-outlook/favorable/recommend/buy/sell. No markdown. ≤360 chars.",
    },
}


def _build_explain_text(tab: str, lang: str = 'ko', region: str = 'us') -> str:
    """각 탭(펀더멘털/신호/섹터)의 AI 해설에 전달할 데이터 텍스트를 조합."""
    region = _norm_region(region)
    is_en = (lang == 'en')                                   # 영어 여부 플래그
    lines = []                                               # 텍스트 줄 목록

    if tab == 'fundamental':                                 # ── 펀더멘털 탭 ──
        # fundamental_gap (log P diff - log E diff) 중심으로 데이터 빌드.
        # noise_score / 이성 점수 / 레짐 사용 안 함 — 사용자 요청.
        try:
            from api.routers.regime import get_fundamental_gap as _get_fg
            fg = _get_fg(region=region, days=2520)
        except Exception:
            fg = None
        if fg and fg.get('current'):
            cur = fg['current']
            stats = fg.get('stats', {})
            value = cur.get('value', 0.0)
            top_pct = cur.get('top_pct', 50)
            sign = cur.get('sign', 'neutral')
            try:
                price_outpace_pct = (pow(2.718281828, value) - 1) * 100  # log diff → %
            except Exception:
                price_outpace_pct = 0
            if is_en:
                zone = 'outpace (price > earnings)' if sign == 'bubble' else (
                    'compression (price < earnings)' if sign == 'compress' else 'balanced')
                lines.append(f"fundamental_gap (log P diff 12m − log E diff 12m): {value:+.4f}")
                lines.append(f"Position in distribution: top {top_pct}% ({zone})")
                lines.append(f"1-year price-vs-earnings outpace: {price_outpace_pct:+.1f}%")
                if stats:
                    lines.append(f"Distribution stats — mean {stats.get('mean')}, median {stats.get('median')}, "
                                 f"min {stats.get('min')}, max {stats.get('max')}, n={stats.get('count')}")
            else:
                zone = '추월 영역 (가격 > 이익)' if sign == 'bubble' else (
                    '압축 영역 (가격 < 이익)' if sign == 'compress' else '균형 (펀더멘털 반영)')
                lines.append(f"펀더멘털 갭 (가격 12개월 log 변화율 − 이익 12개월 log 변화율): {value:+.4f}")
                lines.append(f"분포 내 위치: 상위 {top_pct}% ({zone})")
                lines.append(f"1년 가격이 이익을 추월한 정도: {price_outpace_pct:+.1f}%")
                if stats:
                    lines.append(f"분포 통계 — 평균 {stats.get('mean')}, 중앙값 {stats.get('median')}, "
                                 f"최저 {stats.get('min')}, 최고 {stats.get('max')}, 표본 {stats.get('count')}개")

    elif tab == 'signal':                                    # ── 이상 탐지 탭 (평소 이탈도) ──
        # 이전엔 crash/surge 점수를 사용했으나 UI 가 anomaly 차트로 교체됨 ([117]+).
        # AI 해설도 anomaly_daily (D², percentile, top_contributors) 데이터로 빌드.
        an = fetch_anomaly_current(region=region)            # 최신 평소 이탈도 1행
        if an:
            d2 = an.get('d2')                                # 오늘 D² (평소와의 거리)
            pct_10y = an.get('percentile_10y')               # 10년 분포 누적 위치 (0~100)
            pct_90d = an.get('percentile_90d')               # 최근 90일 분포 위치
            top_pct = (round(100 - pct_10y, 1) if isinstance(pct_10y, (int, float)) else None)
            if is_en:
                lines.append(f"Anomaly Distance (D²): {d2}")
                if top_pct is not None:
                    lines.append(f"Position in 10-year distribution: top {top_pct}% (percentile {pct_10y})")
                if pct_90d is not None:
                    lines.append(f"Position in last 90-day distribution: percentile {pct_90d}")
            else:
                lines.append(f"평소와의 거리(D²): {d2}")
                if top_pct is not None:
                    lines.append(f"10년 분포 내 위치: 상위 {top_pct}% (분위 {pct_10y})")
                if pct_90d is not None:
                    lines.append(f"최근 90일 분포 내 위치: 분위 {pct_90d}")

            contribs = an.get('top_contributors') or []      # 영향도 분해
            if isinstance(contribs, str):
                try:
                    contribs = json.loads(contribs)
                except Exception:
                    contribs = []
            top_n = sorted(
                contribs,
                key=lambda c: abs((c.get('contribution') if isinstance(c, dict) else 0) or 0),
                reverse=True,
            )[:3]
            if top_n:
                # LLM 입력에 한국어 라벨·의미·왜 영향 주는지 미리 합성 (raw snake_case 영문이 LLM 출력에
                # 그대로 echo 되는 문제 차단).
                lines.append("Top contributors (label, meaning, why it matters):" if is_en else "주된 기여 지표 (라벨·의미·왜 영향 주는지):")
                for c in top_n:
                    if not isinstance(c, dict):
                        continue
                    nm = c.get('name', '?')
                    val = c.get('contribution', '?')
                    lines.append(f"  - {_ko_feature_why(nm, lang)}; "
                                 f"{'contribution' if is_en else '기여도'}: {val}")

            knn = an.get('knn_dates') or []                  # 평소 분포 내 가까운 과거 시점들
            if isinstance(knn, str):
                try:
                    knn = json.loads(knn)
                except Exception:
                    knn = []
            knn = [str(d) for d in knn[:3]] if knn else []
            if knn:
                lines.append(("Similar past dates (k-NN, regime-matched): " if is_en else "유사 과거 시점 (regime 일치): ") + ", ".join(knn))

    elif tab == 'sector-val':                                # ── 섹터 PER/PBR 비교 탭 (중립) ──
        # 가치판단 표현 (비싼/싼/expensive/cheap) 모두 제거. 평균 대비 % 차이만 서술.
        from api.routers.sector_cycle import get_valuation
        v = get_valuation()
        if v and v.get('valuations'):
            valid = [x for x in v['valuations'] if x.get('per_diff_pct') is not None]
            valid.sort(key=lambda x: x['per_diff_pct'], reverse=True)
            top_high = valid[:3]
            top_low = valid[-3:][::-1]
            if top_high:
                lines.append(("Largest positive deviation vs avg:" if is_en else "평균 대비 가장 높은 위치:"))
                for x in top_high:
                    lines.append(f"  {x['ticker']} ({x['sector_name']}): PER {x['per_diff_pct']:+.1f}% vs 5Y avg")
            if top_low:
                lines.append(("Largest negative deviation vs avg:" if is_en else "평균 대비 가장 낮은 위치:"))
                for x in top_low:
                    lines.append(f"  {x['ticker']} ({x['sector_name']}): PER {x['per_diff_pct']:+.1f}% vs 5Y avg")

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
                # 매크로 키를 한국어 라벨(의미) + 왜 영향 주는지 한 줄로 묶어 LLM 입력에 미리 변환.
                # raw 'pmi'/'yield_spread'/'anfci' 등이 LLM 출력에 그대로 echo 되는 문제 차단.
                lines.append("Macro Snapshot (label, meaning, why it matters):" if is_en
                             else "매크로 스냅샷 (라벨·의미·왜 영향 주는지):")
                for k, v in list(ms.items())[:5]:            # 상위 5개 매크로 지표
                    lines.append(f"  - {_ko_feature_why(k, lang)}; "
                                 f"{'value' if is_en else '값'}: {v}")
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

def _format_explain_blocks(text: str) -> str:
    """LLM 출력의 [1]/[2]/[3] 블록 마커 앞에 빈 줄(\\n\\n)을 강제 삽입.

    qwen 등 일부 모델이 시스템 프롬프트의 줄바꿈 지시를 무시하고 한 줄에
    "[1] ... [2] ... [3] ..." 로 합쳐서 내보내는 케이스가 있어 후처리.
    프론트 _formatExplainText 가 \\n → <br> 변환하므로 빈 줄이 화면 상의
    문단 분리로 렌더된다. 첫 [1] 앞에는 빈 줄을 넣지 않는다.
    """
    if not text:
        return text
    import re as _re
    parts = _re.split(r'\s*(\[[1-3]\])\s*', text)
    chunks = []
    for i in range(1, len(parts), 2):
        marker = parts[i]
        body = parts[i + 1].strip() if i + 1 < len(parts) else ''
        chunks.append(f'{marker} {body}'.rstrip())
    return '\n\n'.join(chunks) if chunks else text.strip()


def _generate_ai_explain(tab: str, lang: str, region: str) -> dict | None:
    """LLM 호출 → 정리된 해설 텍스트. 실패 시 None.

    Returns: {'explanation': str, 'generated_at': str} 또는 None.
    """
    try:
        text = _build_explain_text(tab, lang, region=region)
        if not text.strip():
            return None
        # max_tokens 500: _EXPLAIN_PROMPTS 가 3블록(데이터/변수설명/인사이트) 각 ≤320자를 요구하므로
        # 한국어 3 chars/token 환산으로 ~320~400 토큰 필요. 150 으로는 인사이트 블록이 컷오프됨.
        result = _groq_call(_EXPLAIN_PROMPTS[lang][tab], text, 500)
        if not result:
            return None
        formatted = _format_explain_blocks(result.strip())
        return {'explanation': formatted, 'generated_at': _kst_now_str()}
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


def _fmt_signed(v, digits: int = 1, suffix: str = '') -> str:
    if v is None:
        return '-'
    try:
        x = float(v)
    except Exception:
        return '-'
    return f"{'+' if x >= 0 else ''}{x:.{digits}f}{suffix}"


def _fallback_ai_summary(lang: str, region: str) -> str:
    """Rule-based 시황 요약 — LLM 미가용 시 폴백. 옛 4줄 "제목 — 내용" 형식 복원.

    데이터 source:
      - 공포탐욕지수 (fetch_fear_greed_latest) — 시장 심리
      - 평소와의 거리 D² + 상위 N% (fetch_anomaly_current) — 평소 이탈도
        (옛 crash/surge gap 은 신호탭 폐기로 사용 X)
      - 시장 이성 점수 (fetch_noise_regime_current) — 펀더멘털
      - 경기 국면 (fetch_sector_cycle_latest) — 종합
    자문 가드: 매수/매도/추천/예측/전망/유리/불리/간극/상승우위/하락우위 단어 금지.
    출력 형식: 4 줄, 각 줄 "[이모지] 제목 — 내용", 줄 사이 \n.
    """
    try:
        fg = fetch_fear_greed_latest(region=region) or {}
        an = fetch_anomaly_current(region=region) or {}
        regime = fetch_noise_regime_current(region=region) or {}
        sector = fetch_sector_cycle_latest(region=region) or {}

        fg_score = fg.get('score')
        fg_label = fg.get('rating') or ''
        d2 = an.get('d2')
        pct_10y = an.get('percentile_10y')
        top_pct = round(100 - float(pct_10y), 1) if isinstance(pct_10y, (int, float)) else None
        ns = regime.get('noise_score')
        phase = sector.get('phase_name')

        is_high_distance = top_pct is not None and top_pct <= 20
        is_low_distance  = top_pct is not None and top_pct >= 80
        is_greed = ('greed' in fg_label.lower()) or ('탐욕' in fg_label)
        is_fear  = ('fear'  in fg_label.lower()) or ('공포' in fg_label)

        if lang == 'en':
            # ── ❄️ 시장 심리 ──
            sent_emoji = '🔥' if is_greed else ('❄️' if is_fear else '⚖️')
            sent_body = (
                f"Fear & Greed at {round(float(fg_score))} ({fg_label})"
                if fg_score is not None else "sentiment data loading"
            )
            line1 = f"{sent_emoji} Market Sentiment — {sent_body}."
            # ── 📊 평소 이탈도 ──
            an_emoji = '📈' if is_high_distance else ('📊' if is_low_distance else '📉')
            an_body = (
                f"D² {d2}"
                + (f", top {top_pct}% in 10-year distribution" if top_pct is not None else "")
                if d2 is not None else "anomaly data loading"
            )
            line2 = f"{an_emoji} Anomaly Distance — {an_body}."
            # ── 🧭 펀더멘털 ──
            ns_body = (
                f"Rationality score {_fmt_signed(ns, 2)} ({'rational' if (ns or 0) >= 0 else 'emotional'} side)"
                if ns is not None else "rationality data loading"
            )
            line3 = f"🧭 Fundamentals — {ns_body}."
            # ── 🎯 종합 ──
            if is_greed and is_high_distance:
                summary = "greed sentiment co-occurs with a far-from-typical market state — textbook co-deviation"
            elif is_fear and is_high_distance:
                summary = "fear sentiment co-occurs with a far-from-typical market state — textbook co-deviation"
            elif is_low_distance:
                summary = "today's snapshot sits inside the 10-year typical range; sentiment is the differentiator"
            elif is_greed or is_fear:
                summary = "sentiment leans one way while market state sits in a moderate position — partial alignment"
            else:
                summary = "indicators co-positioned at current snapshot — state record, not a direction call"
            phase_tag = f" / cycle {phase}" if phase else ""
            line4 = f"🎯 Overall — {summary}{phase_tag}."
        else:
            # ── 간결 1~2문장 — 3 지표만 사용 (사용자 결정 2026-05-13) ──
            # 1) 일일 수익률 (KOSPI/S&P500), 2) RSI 과매수/과매도,
            # 3) 펀더멘털 (실적-주가 갭 percentile + 방향). 심리·이탈도·국면 등 노출 X.
            macro = fetch_macro_latest(region=region) or {}
            idx_name = 'KOSPI' if region == 'kr' else 'S&P500'

            # 일일 수익률 + RSI 한 문장
            ret_v = macro.get('sp500_return')
            rsi_v = macro.get('sp500_rsi')
            ret_phrase = ""
            if ret_v is not None:
                try:
                    ret_phrase = f"{idx_name} {float(ret_v):+.2f}%"
                except (TypeError, ValueError):
                    pass
            rsi_phrase = ""
            if rsi_v is not None:
                try:
                    rf = float(rsi_v)
                    if rf >= 70:
                        rsi_phrase = f"RSI {rf:.0f} 과매수권"
                    elif rf <= 30:
                        rsi_phrase = f"RSI {rf:.0f} 과매도권"
                    else:
                        rsi_phrase = f"RSI {rf:.0f} 정상권"
                except (TypeError, ValueError):
                    pass
            if ret_phrase and rsi_phrase:
                line1 = f"{ret_phrase}, {rsi_phrase}"
            elif ret_phrase:
                line1 = ret_phrase
            elif rsi_phrase:
                line1 = rsi_phrase
            else:
                line1 = f"{idx_name} 시황 데이터 수집 중"

            # 펀더멘털 (실적-주가 갭 percentile + 방향)
            line2 = "실적-주가 갭 데이터 수집 중"
            try:
                from api.routers.regime import get_fundamental_gap as _get_fg
                fg_res = _get_fg(region=region, days=2520)
                cur = (fg_res or {}).get('current') if isinstance(fg_res, dict) else None
                if cur:
                    tp_raw = cur.get('top_pct')
                    sign_v = cur.get('sign', 'neutral')
                    if tp_raw is not None:
                        tpf = float(tp_raw)
                        if sign_v == 'bubble':
                            ep = round(tpf, 1)
                            dir_word = "주가가 실적보다 빠르게 오른"
                        elif sign_v == 'compress':
                            ep = round(100 - tpf, 1)
                            dir_word = "주가가 실적을 따라가지 못한"
                        else:
                            ep = 50.0
                            dir_word = ""
                        if ep <= 5:
                            mag = "매우 큰 괴리"
                        elif ep <= 15:
                            mag = "드문 괴리"
                        elif ep <= 30:
                            mag = "약한 괴리"
                        elif ep <= 70:
                            mag = "평소 수준"
                        else:
                            mag = "정합 강한"
                        line2 = f"실적-주가 갭 상위 {ep}% ({dir_word} {mag}) 구간"
            except Exception as _e:
                print(f"[home headline] fundamental gap fetch 실패: {_e}")

            return f"{line1}. {line2}이다."

        return "\n".join([line1, line2, line3, line4])
    except Exception:
        if lang == 'en':
            return ("Today — indicators loading.\n"
                    "Context — distribution position will appear once data syncs.")
        return ("[오늘 한눈에] 지표 데이터 수집 중입니다.\n"
                "[왜 이런 결과] 데이터 동기화 후 표시됩니다.\n"
                "[현재 구간] 분석 준비 중입니다.")


# 기술 변수명 → (한국어 라벨, 의미, 왜 모델에 영향 주는지). LLM 미가용 fallback 에서 사용.
# 한자 절대 미사용 — 한글/영문/숫자/기호만.
_FEATURE_LABEL_KO = {
    'hy_spread':       ('하이일드 스프레드', '신용 위험 프리미엄',
                        '회사채 위험이 커지면 자금 경색을 시사해 시장 스트레스 신호로 산입됩니다'),
    'vix_term':        ('VIX 텀 구조', '단기/장기 변동성 비',
                        '단기 변동성이 장기보다 빠르게 오르면 임박한 위험 우려를 반영합니다'),
    'erp_zscore':      ('주식 위험 프리미엄 z-점수', '수익률에서 무위험 금리를 뺀 표준화값',
                        '주식이 채권 대비 얼마나 비싸/싸 보이는지를 z-점수로 표준화하여 모델에 들어갑니다'),
    'fundamental_gap': ('펀더멘털 갭', '실적과 가격의 괴리',
                        '실적 대비 가격이 멀어지면 펀더멘털과 분리된 움직임으로 해석되어 점수에 산입됩니다'),
    'residual_corr':   ('잔차 상관', '개별주 동조 강도',
                        '개별주가 시장 평균을 빼고 나서도 함께 움직이면 군집·쏠림이 큰 상태로 평가됩니다'),
    'dispersion':      ('종목 분산', '수익률 격차',
                        '종목 간 수익률 격차가 클수록 단일 거시 요인에 휩쓸리는 정도가 줄어든 상태로 산입됩니다'),
    'amihud':          ('유동성 비용', '체결 충격 비용',
                        '체결 시 가격 충격이 클수록 유동성이 얕아진 상태를 반영합니다'),
    'realized_vol':    ('실현 변동성', '실제 가격 진동',
                        '실제로 관측된 가격 진동 크기로 시장 흔들림을 그대로 반영합니다'),
    'vix':             ('VIX', '공포 지수',
                        '옵션 시장이 가격에 반영한 향후 변동성 기대치라 위험 인식을 직접 보여줍니다'),
    'rsi':             ('RSI', '상대 강도 지수',
                        '상승/하락 폭의 비율로 단기 과열·과매도 정도를 수치화한 표준 모멘텀 지표입니다'),
    'fear_greed':      ('공포탐욕지수', '심리 지표',
                        '여러 시장 지표를 묶어 만든 종합 심리 점수로 군중 심리 위치를 표현합니다'),
    'credit_spread':   ('신용 스프레드', '회사채 위험 프리미엄',
                        '회사채와 국채의 금리 차로, 자금 시장 신뢰도를 반영합니다'),
    'yield_curve':     ('수익률 곡선', '장단기 금리차',
                        '장기 금리에서 단기 금리를 뺀 값으로, 경기 사이클 위치를 반영합니다'),
    # 거시경제(섹터) 탭 매크로 지표 ── US 10
    'pmi':             ('제조업 PMI', '50 기준 확장/수축',
                        'PMI 가 50 이상이면 일반적으로 제조업 활동 확장 신호로 해석되어 경기 국면 분류 입력으로 쓰입니다'),
    'yield_spread':    ('장단기 금리차', '10Y-3M 스프레드',
                        '장기 금리에서 단기 금리를 뺀 값으로 경기 사이클 위치(역전 시 둔화·역전 해소 시 회복)를 반영합니다'),
    'anfci':           ('금융환경지수', '신용·유동성 통합 스트레스',
                        '신용·유동성·위험 지표를 하나로 합친 값으로 자금시장 환경을 한 수치로 요약합니다'),
    'icsa_yoy':        ('신규실업수당 청구 YoY', '고용 시장 변화',
                        '일자리 손실 속도를 추적해 경기 둔화/확장의 단기 신호로 쓰입니다'),
    'permit_yoy':      ('주택 착공허가 YoY', '주거 투자 선행',
                        '미래 건설 활동의 선행 지표로 거시 사이클 진입을 예고합니다'),
    'real_retail_yoy': ('실질 소매판매 YoY', '가계 소비 모멘텀',
                        '인플레이션 보정 후 가계 소비 흐름으로 경기 확장 강도를 반영합니다'),
    'capex_yoy':       ('설비투자 YoY', '기업 투자',
                        '기업의 미래 생산 능력 확장 의지를 반영해 사이클 후반 강도 지표로 쓰입니다'),
    'real_income_yoy': ('실질 가처분 소득 YoY', '가계 구매력',
                        '인플레이션 보정 후 가계 소득 흐름으로 소비 여력의 기반을 보여줍니다'),
    'pmi_chg3m':       ('PMI 3개월 변화', 'PMI 모멘텀',
                        '단기 변화율로 사이클 전환점 신호를 잡아내는 보조 지표입니다'),
    'capex_yoy_chg3m': ('설비투자 3개월 변화', '투자 모멘텀',
                        '기업 투자 흐름의 단기 변화율을 추적합니다'),
    # KR 8
    'kr_indpro_yoy':   ('한국 산업생산 YoY', '제조업 산출량',
                        '한국 제조업 산출량의 전년 동기 대비 변화로 한국 사이클 위치를 반영합니다'),
    'kr_yield_spread': ('한국 장단기 금리차', '사이클 위치',
                        '한국 국채의 장단기 금리차로 한국 경기 사이클 위치를 반영합니다'),
    'kr_credit_spread':('한국 신용 스프레드', '자금 시장 신뢰도',
                        '한국 회사채-국채 금리차로 한국 자금시장 환경을 보여줍니다'),
    'kr_unemp_rate':   ('한국 실업률', '고용 여건',
                        '한국 노동시장 여유 정도로 가계 구매력의 기반을 반영합니다'),
    'kr_permit_yoy':   ('한국 주택 착공허가 YoY', '주거 투자 선행',
                        '한국 미래 건설 활동의 선행 지표입니다'),
    'kr_retail_yoy':   ('한국 소매판매 YoY', '가계 소비',
                        '한국 가계 소비 흐름의 전년 대비 변화입니다'),
    'kr_capex_yoy':    ('한국 설비투자 YoY', '기업 투자',
                        '한국 기업의 설비 투자 흐름입니다'),
    'kr_cpi_yoy':      ('한국 소비자물가 YoY', '인플레이션',
                        '한국 소비자물가 상승률로 통화정책·기업 마진과 연동됩니다'),
}
_FEATURE_LABEL_EN = {
    'hy_spread':       ('high-yield spread', 'credit risk premium',
                        'wider corporate-bond spreads signal funding stress and feed the model as a risk signal'),
    'vix_term':        ('VIX term structure', 'short/long vol ratio',
                        'short-term vol rising faster than long-term implies near-term stress concern'),
    'erp_zscore':      ('equity risk premium z-score', 'return minus risk-free, standardized',
                        'standardized measure of how rich/cheap stocks look versus bonds, fed into the model'),
    'fundamental_gap': ('fundamental gap', 'earnings vs price divergence',
                        'when price drifts from earnings, the model reads it as a fundamentals-disconnect signal'),
    'residual_corr':   ('residual correlation', 'single-stock co-movement',
                        'if stocks still co-move after stripping the market factor, it indicates herding'),
    'dispersion':      ('return dispersion', 'cross-stock spread',
                        'wider cross-stock dispersion means less single-factor dominance, fed into the model'),
    'amihud':          ('Amihud illiquidity', 'execution impact cost',
                        'higher execution impact reflects shallower liquidity'),
    'realized_vol':    ('realized volatility', 'actual price oscillation',
                        'observed price oscillation directly reflects market turbulence'),
    'vix':             ('VIX', 'fear index',
                        'options-market expected forward volatility, a direct read of perceived risk'),
    'rsi':             ('RSI', 'relative strength index',
                        'standard momentum gauge of short-term overbought/oversold via up/down ratio'),
    'fear_greed':      ('Fear & Greed', 'sentiment index',
                        'composite sentiment score blending several market indicators'),
    'credit_spread':   ('credit spread', 'corporate bond risk premium',
                        'corporate-vs-treasury yield gap reflecting funding-market confidence'),
    'yield_curve':     ('yield curve', 'long-short rate gap',
                        'long-minus-short rate spread reflecting business-cycle position'),
    # macro indicators (sector tab) — US 10
    'pmi':             ('Manufacturing PMI', '50 = expansion/contraction line',
                        'PMI > 50 generally signals manufacturing expansion, fed into cycle phase classification'),
    'yield_spread':    ('yield spread', '10Y minus 3M',
                        'long-minus-short rate gap reflects cycle position (inversion = slowdown signal)'),
    'anfci':           ('NFCI', 'financial conditions index',
                        'composite of credit/liquidity/risk indicators, summarizes funding-market environment'),
    'icsa_yoy':        ('Initial Claims YoY', 'labor market change',
                        'tracks job-loss pace as a short-cycle slowdown/expansion signal'),
    'permit_yoy':      ('Building Permits YoY', 'residential investment lead',
                        'leading indicator of future construction, signals cycle entry'),
    'real_retail_yoy': ('Real Retail Sales YoY', 'consumption momentum',
                        'inflation-adjusted household spending flow, reflects expansion strength'),
    'capex_yoy':       ('Capex YoY', 'business investment',
                        'firms\' future capacity expansion intent, late-cycle strength gauge'),
    'real_income_yoy': ('Real Disposable Income YoY', 'household purchasing power',
                        'inflation-adjusted income flow, foundation of consumption capacity'),
    'pmi_chg3m':       ('PMI 3-month change', 'PMI momentum',
                        'short-term rate of change captures cycle inflection signals'),
    'capex_yoy_chg3m': ('Capex 3-month change', 'investment momentum',
                        'short-term rate of change in business investment flow'),
    # KR 8
    'kr_indpro_yoy':   ('Korea IP YoY', 'manufacturing output',
                        'YoY change in Korea manufacturing output reflects KR cycle position'),
    'kr_yield_spread': ('Korea yield spread', 'cycle position',
                        'Korean Treasury long-short rate gap reflects KR cycle position'),
    'kr_credit_spread':('Korea credit spread', 'funding-market confidence',
                        'Korean corporate-vs-Treasury yield gap, KR funding environment'),
    'kr_unemp_rate':   ('Korea unemployment rate', 'labor slack',
                        'Korean labor market slack, foundation of household purchasing power'),
    'kr_permit_yoy':   ('Korea Building Permits YoY', 'residential investment lead',
                        'leading indicator of future Korean construction'),
    'kr_retail_yoy':   ('Korea Retail Sales YoY', 'household consumption',
                        'YoY change in Korean household spending'),
    'kr_capex_yoy':    ('Korea Capex YoY', 'business investment',
                        'flow of Korean business investment'),
    'kr_cpi_yoy':      ('Korea CPI YoY', 'inflation',
                        'Korean consumer-price growth, ties to monetary policy and corporate margins'),
}


def _ko_feature(name: str, lang: str = 'ko') -> str:
    """기술 변수명 → '라벨(의미)' 형식. 미매핑 시 원본."""
    if not name:
        return '?'
    key = str(name).lower().strip()
    table = _FEATURE_LABEL_EN if lang == 'en' else _FEATURE_LABEL_KO
    if key in table:
        label, meaning, _why = table[key]
        return f'{label}({meaning})'
    return str(name)


def _ko_feature_why(name: str, lang: str = 'ko') -> str:
    """기술 변수명 → '라벨(의미) — 왜 모델에 영향 주는지' 한 줄."""
    if not name:
        return '?'
    key = str(name).lower().strip()
    table = _FEATURE_LABEL_EN if lang == 'en' else _FEATURE_LABEL_KO
    if key in table:
        label, meaning, why = table[key]
        return f'{label}({meaning}) — {why}'
    return str(name)


def _fallback_ai_explain(tab: str, lang: str, region: str) -> str:
    """Rule-based 탭 해설 — LLM 미가용 시 폴백.

    자문 가드: 매수/매도/추천/유리/불리/예측/전망/기대 등 금지. 현재 사실 + 일반론적 메커니즘만.
    영문 변수명은 _ko_feature 로 한국어 + 짧은 의미 형식 변환.
    """
    try:
        if tab == 'fundamental':
            # fundamental_gap (가격 12개월 변화율 − 이익 12개월 변화율) 중심 폴백 텍스트.
            # noise_score / 이성·감정 점수 / 거품 단어 사용 X.
            try:
                from api.routers.regime import get_fundamental_gap as _get_fg
                fg = _get_fg(region=region, days=2520)
            except Exception:
                fg = None
            cur = (fg or {}).get('current') or {}
            stats = (fg or {}).get('stats') or {}
            value = cur.get('value')
            top_pct = cur.get('top_pct')
            sign = cur.get('sign', 'neutral')
            try:
                outpace = (pow(2.718281828, value) - 1) * 100 if value is not None else None
            except Exception:
                outpace = None

            if lang == 'en':
                zone = ('outpace (price > earnings)' if sign == 'bubble' else
                        'compression (price < earnings)' if sign == 'compress' else
                        'balanced')
                block1 = (
                    f"[Data] fundamental_gap: {_fmt_signed(value, 4)}.\n"
                    f"Position: top {top_pct}% of {stats.get('count')}-sample distribution ({zone}).\n"
                    f"1-year price-vs-earnings outpace: {_fmt_signed(outpace, 1) if outpace is not None else '-'}%.\n"
                    f"Distribution stats — mean {stats.get('mean')}, median {stats.get('median')}, "
                    f"min {stats.get('min')}, max {stats.get('max')}."
                )
                block2 = (
                    "[Why these variables matter]\n"
                    "  - 1-year price log return (P) and 1-year earnings log return (E) — their difference "
                    "isolates how much price moved relative to earnings.\n"
                    "  - When P moves far ahead of E (positive gap), the P/E multiple expanded; "
                    "when E moves ahead (negative gap), the multiple compressed."
                )
                block3 = (
                    "[Insight] Today's reading sits where price-earnings expansion vs compression "
                    "places the market in the historical distribution — a factual position readout, "
                    "no direction inferred."
                )
            else:
                zone = ('가격이 이익을 추월한 구간' if sign == 'bubble' else
                        '이익이 가격을 추월한 구간' if sign == 'compress' else
                        '가격과 이익이 비슷한 속도인 구간')
                outpace_str = f"{_fmt_signed(outpace, 1)}%" if outpace is not None else '-'
                block1 = (
                    f"[오늘 한눈에] 최근 1년 동안 가격이 이익을 {outpace_str} 추월했으며, {zone}입니다.\n"
                    f"이 격차는 10년 표본({stats.get('count')}개) 중 상위 {top_pct}% 위치입니다."
                )
                # 영향 큰 두 변수 (가격, 이익) 의 1년 변화율 풀이
                if value is not None and outpace is not None:
                    if sign == 'bubble':
                        impact = (
                            "주가는 빠르게 올랐는데 기업 이익은 그만큼 따라오지 못해 둘 사이 격차가 벌어진 상태"
                            "다 보니, 자연스럽게 P/E 배수가 평소보다 확장되었습니다"
                        )
                    elif sign == 'compress':
                        impact = (
                            "기업 이익이 가격보다 빠르게 늘어 P/E 배수가 평소보다 압축된 상태로, "
                            "가격이 이익을 충분히 반영하지 못하고 있는 구간입니다"
                        )
                    else:
                        impact = (
                            "가격과 이익이 비슷한 속도로 움직여 P/E 배수가 평소 범위 안에 머무는 균형 구간입니다"
                        )
                else:
                    impact = "데이터 동기화 후 영향 분석 표시됩니다"
                block2 = f"[왜 이 결과] {impact}."
                block3 = (
                    f"[참고] 10년 분포에서 평균 {stats.get('mean')}, 중앙값 {stats.get('median')}, "
                    f"범위 {stats.get('min')} ~ {stats.get('max')}. "
                    f"오늘 위치(상위 {top_pct}%)는 사실 기록으로, 향후 방향은 알 수 없습니다."
                )
            return f"{block1}\n\n{block2}\n\n{block3}"

        if tab == 'signal':
            an = fetch_anomaly_current(region=region) or {}
            d2 = an.get('d2')
            pct_10y = an.get('percentile_10y')
            pct_90d = an.get('percentile_90d')
            top_pct = round(100 - float(pct_10y), 1) if isinstance(pct_10y, (int, float)) else None
            contribs = an.get('top_contributors') or []
            if isinstance(contribs, str):
                try:
                    contribs = json.loads(contribs)
                except Exception:
                    contribs = []
            top_n = sorted(
                [c for c in contribs if isinstance(c, dict)],
                key=lambda c: abs((c.get('contribution') or 0)),
                reverse=True,
            )[:2]
            knn = an.get('knn_dates') or []
            if isinstance(knn, str):
                try:
                    knn = json.loads(knn)
                except Exception:
                    knn = []
            knn_str = ', '.join(
                (k.get('date', '?') if isinstance(k, dict) else str(k))
                for k in (knn or [])[:3]
            ) or '-'
            contrib_str = ', '.join(
                f"{_ko_feature(c.get('name', '?'), lang)} {_fmt_signed(c.get('contribution', 0), 2)}"
                for c in top_n
            ) or '-'
            why_lines = "\n".join(
                f"  - {_ko_feature_why(c.get('name', '?'), lang)}"
                for c in top_n
            ) or '-'

            if lang == 'en':
                block1 = (
                    f"[Data] Anomaly Distance (D²): {d2 if d2 is not None else '-'}.\n"
                    f"Position: top {top_pct}% of 10-year distribution"
                    f" / 90-day percentile {pct_90d}.\n"
                    f"Top contributors: {contrib_str}.\n"
                    f"Similar past dates: {knn_str}.\n"
                    f"Summary: today's distance from usual sits at top {top_pct}%."
                )
                block2 = f"[Why these variables matter]\n{why_lines}"
                block3 = (
                    "[Insight] Together the indicators describe HOW today's snapshot deviates from the 10-year typical mix — "
                    "a textbook 'how-different-from-usual' state, with no direction inferred."
                )
            else:
                d2_str = f"{d2}" if d2 is not None else '-'
                block1 = (
                    f"[오늘 한눈에] 시장 이탈도(D²) {d2_str}, 10년 분포 상위 {top_pct}% 위치입니다.\n"
                    f"오늘 거리를 끌어올린 주된 변수: {contrib_str}."
                )
                # 변수 풀이 (왜 이 변수들이 거리를 키웠는지)
                if why_lines and why_lines != '-':
                    impact_lines = why_lines.replace('  - ', '- ')
                    block2 = f"[왜 이 결과]\n{impact_lines}"
                else:
                    block2 = "[왜 이 결과] 데이터 동기화 후 영향 분석 표시됩니다."
                block3 = (
                    f"[참고] 비슷한 거리가 관측됐던 과거 시점: {knn_str}. "
                    "거리 수치는 오늘 시장이 10년 평소 패턴과 얼마나 떨어졌는지의 사실 기록이며, "
                    "이후 방향은 알 수 없습니다."
                )
            return f"{block1}\n\n{block2}\n\n{block3}"

        if tab == 'sector':
            sc = fetch_sector_cycle_latest(region=region) or {}
            phase = sc.get('phase_name') or '-'
            ms = sc.get('macro_snapshot') or {}
            if isinstance(ms, str):
                try:
                    ms = json.loads(ms)
                except Exception:
                    ms = {}
            # 매크로 키를 한국어 라벨(의미) 로 변환해 LLM/사용자 양쪽이 영문 snake_case 보지 않게.
            macro_str = ', '.join(f"{_ko_feature(k, lang)} {v}" for k, v in list(ms.items())[:4]) or '-'
            top3 = sc.get('top3_sectors') or []
            sectors = ', '.join(
                f"{x.get('sector')}({x.get('return')}%)" if isinstance(x, dict) and x.get('return') is not None
                else str(x.get('sector') if isinstance(x, dict) else x)
                for x in top3[:3]
            ) or '-'
            if lang == 'en':
                block1 = (
                    f"[Data] Cycle phase: {phase}.\n"
                    f"Macro snapshot: {macro_str}.\n"
                    f"Co-discussed sectors: {sectors}.\n"
                    f"Summary: current macro readouts position the cycle at the {phase} phase."
                )
                block2 = (
                    "[Why these variables matter]\n"
                    "  - Macro indicators (yield curve, growth, inflation) drive cycle classification because they "
                    "track aggregate demand/supply position, which is what the cycle phase summarizes."
                )
                block3 = (
                    f"[Insight] In the {phase} phase, the listed sectors are textbook-typically co-discussed in "
                    f"macro-cycle literature — a co-occurrence record, not a recommendation."
                )
            else:
                block1 = (
                    f"[오늘 한눈에] 현재 경기 국면은 '{phase}'으로 분류됩니다.\n"
                    f"이 판단의 근거가 된 매크로 지표: {macro_str}."
                )
                # 매크로 지표가 어떻게 국면 분류에 영향을 주는지 풀이
                impact_bits = []
                if 'pmi' in str(ms).lower() or 'PMI' in macro_str:
                    impact_bits.append("제조업 PMI는 50을 기준으로 확장(>50)/수축(<50)을 가른 신호")
                if '금리차' in macro_str or 'yield' in macro_str.lower():
                    impact_bits.append("장단기 금리차는 경기 사이클 위치(역전 시 둔화·정상화 시 회복)를 비춥니다")
                if '금융환경' in macro_str:
                    impact_bits.append("금융환경지수는 자금 시장의 스트레스 정도를 한 수치로 요약합니다")
                if '실업' in macro_str:
                    impact_bits.append("실업청구 변화는 고용 시장의 단기 흐름을 보여줍니다")
                if not impact_bits:
                    impact_bits.append("위 매크로 지표들의 조합이 현재 경기 국면 분류 결과에 영향을 주었습니다")
                block2 = "[왜 이 결과] " + ". ".join(impact_bits) + "."
                block3 = (
                    f"[함께 거론되는 섹터] {sectors}. "
                    f"'{phase}' 국면에서는 위 섹터들이 거시 사이클 문헌상 자주 함께 거론되는 동조 패턴 — "
                    "사실 기록일 뿐 추천 정보가 아닙니다."
                )
            return f"{block1}\n\n{block2}\n\n{block3}"

        if tab == 'sector-val':
            from api.routers.sector_cycle import get_valuation
            v = get_valuation(region=region)
            vals = v.get('valuations') if isinstance(v, dict) else []
            valid = [x for x in (vals or []) if x.get('per_diff_pct') is not None]
            valid.sort(key=lambda x: x['per_diff_pct'], reverse=True)
            top_high = valid[:2]
            top_low = valid[-2:][::-1] if len(valid) >= 2 else []
            high_str = ', '.join(
                f"{x.get('ticker')}({x.get('sector_name')}) {x.get('per_diff_pct'):+.1f}%"
                for x in top_high
            ) or '-'
            low_str = ', '.join(
                f"{x.get('ticker')}({x.get('sector_name')}) {x.get('per_diff_pct'):+.1f}%"
                for x in top_low
            ) or '-'
            if lang == 'en':
                block1 = (
                    f"[Data] Sector PER position vs 5-year average (form: 'X% vs avg').\n"
                    f"Largest positive deviation: {high_str}.\n"
                    f"Largest negative deviation: {low_str}.\n"
                    f"Summary: deviations are reported as relative position only."
                )
                block2 = (
                    "[Why this variable matters]\n"
                    "  - PER deviation vs historical average is meaningful because it standardizes today's price-to-earnings "
                    "against each sector's own typical band — a relative-position frame that is neutral to absolute level."
                )
                block3 = (
                    "[Insight] The frame describes where each sector currently sits in its own historical band. "
                    "It is a relative-position record, not an over/undervaluation judgment, and not a buy/sell signal."
                )
            else:
                block1 = (
                    f"[오늘 한눈에] 섹터별 PER이 각 섹터의 5년 평균에서 얼마나 떨어져 있는지를 본 결과입니다.\n"
                    f"평균보다 높은 쪽: {high_str}.\n"
                    f"평균보다 낮은 쪽: {low_str}."
                )
                block2 = (
                    "[왜 이 결과] PER 자체의 절대 수준은 섹터마다 차이가 커서 그대로 비교하면 의미가 흐려집니다. "
                    "그래서 각 섹터의 *자기 5년 평소 PER* 을 기준으로 오늘 위치를 표준화해 보여줍니다. "
                    "같은 +50%라도 변동성 큰 섹터엔 흔하고, 안정 섹터엔 드문 거리입니다."
                )
                block3 = (
                    "[참고] 위 수치는 각 섹터가 자기 평소 범위 안에서 어디에 있는지의 상대 위치 기록입니다. "
                    "고평가·저평가 판단이나 매수·매도 신호가 아닙니다."
                )
            return f"{block1}\n\n{block2}\n\n{block3}"

        if tab == 'sector-mom':
            from processor.feature7_sector_momentum import compute_sector_momentum
            m = compute_sector_momentum(region=region)
            mom = m.get('momentum') if isinstance(m, dict) else []
            ranked_top = sorted([x for x in (mom or []) if x.get('rank') is not None], key=lambda x: x['rank'])[:3]
            ranked_bot = sorted([x for x in (mom or []) if x.get('rank') is not None], key=lambda x: x['rank'], reverse=True)[:3]
            top_str = ', '.join(
                f"{x.get('ticker')}({x.get('sector_name')}) 1주 {_fmt_signed(x.get('return_1w'), 1, '%')}"
                for x in ranked_top
            ) or '-'
            bot_str = ', '.join(
                f"{x.get('ticker')}({x.get('sector_name')}) 1주 {_fmt_signed(x.get('return_1w'), 1, '%')}"
                for x in ranked_bot
            ) or '-'
            if lang == 'en':
                block1 = (
                    f"[Data] 1-week sector momentum.\n"
                    f"Top by rank: {top_str}.\n"
                    f"Bottom by rank: {bot_str}.\n"
                    f"Summary: ranking is from past 1-week sector returns."
                )
                block2 = (
                    "[Why this variable matters]\n"
                    "  - 1-week return ranking is a standard short-horizon rotation gauge — it captures which sectors moved "
                    "more than peers over the most recent week, which is information about realized performance only."
                )
                block3 = (
                    "[Insight] Whether top-ranked sectors align with the current cycle phase or diverge from it is a "
                    "textbook co-occurrence/divergence pattern — informational only, no direction inferred."
                )
            else:
                block1 = (
                    f"[오늘 한눈에] 최근 1주일 섹터별 수익률 순위입니다.\n"
                    f"가장 많이 오른 섹터: {top_str}.\n"
                    f"가장 많이 내린 섹터: {bot_str}."
                )
                block2 = (
                    "[왜 이 결과] 1주 수익률 순위는 단기 자금이 어느 섹터로 쏠리고 어디서 빠졌는지를 그대로 보여주는 지표입니다. "
                    "최근 5거래일 사이 또래 섹터 대비 더 움직인 곳이 위쪽, 덜 움직였거나 빠진 곳이 아래쪽에 자리합니다."
                )
                block3 = (
                    "[참고] 위 순위는 *이미 실현된* 1주일 성과의 사실 기록입니다. "
                    "현재 경기 국면과 어떻게 어우러지는지 비교용으로만 쓰이며, 향후 방향을 예측하지는 않습니다."
                )
            return f"{block1}\n\n{block2}\n\n{block3}"
    except Exception as e:
        print(f'[AI Explain {tab}/{lang}/{region}] fallback error: {e}')

    return 'Commentary is temporarily using the latest numeric snapshot.' if lang == 'en' else '현재 지표 기준으로 해설을 준비했습니다.'


@router.get('/ai-explain')                                   # GET /api/market-summary/ai-explain
def get_ai_explain(background_tasks: BackgroundTasks,
                   tab: str = Query(..., description='fundamental, signal, sector, sector-val, sector-mom'),
                   lang: str = Query('ko'),
                   region: str = Query('us')):
    """옵션 C 적용:
    1) in-memory cache hit → 즉시 응답.
    2) DB (ai_explain_cache) hit → 즉시 응답 + in-memory 채움.
    3) cache miss → *fallback 즉시 응답* + 백그라운드에서 LLM 생성하여 다음 요청용 캐시 적재.
    동일 (tab,lang,region) 동시 LLM 실행은 _bg_running 으로 차단.
    """
    lang = lang if lang in ('ko', 'en') else 'ko'
    region = _norm_region(region)
    err = _EXPLAIN_ERR[lang]
    if tab not in _EXPLAIN_PROMPTS['ko']:
        return {'explanation': err['bad_tab'], 'error': True}

    now = time.time()
    cache_key = f'explain_{tab}_{lang}_{region}'             # region 별 캐시 분리

    # DISABLE_GROQ=true: 옛 LLM 캐시(in-memory/DB) 우회하고 매번 fresh fallback
    disable_groq = os.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes')

    if not disable_groq:
        # 1차: in-memory cache (TTL 안)
        with _explain_lock:
            cached = _explain_cache.get(cache_key)
            if cached and now < cached.get('expires', 0):
                return {'explanation': _format_explain_blocks(cached['text']), 'tab': tab, 'cached': True}

        # 2차: DB cache (스케줄러 미리 적재)
        try:
            row = fetch_ai_explain(tab, lang, region)
        except Exception as e:
            print(f'[AI Explain {tab}/{lang}/{region}] DB read 실패 (계속 진행): {e}')
            row = None
    else:
        row = None
    if row and row.get('explanation'):
        formatted = _format_explain_blocks(row['explanation'])
        with _explain_lock:
            _explain_cache[cache_key] = {
                'text': formatted,
                'expires': now + _EXPLAIN_TTL,
            }
        return {
            'explanation': formatted,
            'tab': tab,
            'cached': True,
            'generated_at': row.get('generated_at'),
        }

    # 3차: cache miss → fallback 즉시 응답 + 백그라운드 LLM 생성 등록 (다음 요청용 캐시).
    # fallback 은 _explain_cache 에 *짧게* 저장하지 않는다 — 다음 요청은 BG 결과나 DB 를
    # 다시 확인하도록 두어, BG 가 끝나는 즉시 LLM 결과로 자연 교체되게 함.
    fallback = _fallback_ai_explain(tab, lang, region)
    if not disable_groq:
        background_tasks.add_task(_bg_generate_explain, tab, lang, region)
    return {
        'explanation': fallback or err['no_data'],
        'tab': tab,
        'cached': False,
        'generated_at': _kst_now_str(),
        'source': 'fallback',
    }
