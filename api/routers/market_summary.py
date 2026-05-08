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


_SUMMARY_PROMPTS = {                                         # 시황 종합 요약 — 1줄 핵심 + 1줄 인사이트
    'ko': """/no_think
너는 한국어 시장 객관 설명자다. 시황 탭 입력 지표(공포탐욕·간극·경기 국면 등) 를 종합해 *2줄* 출력.

형식 (반드시 이 두 줄, 각 줄 앞에 이모지 1개):
1. [이모지] 핵심 한 줄 — 핵심 3지표 (심리 N · 신호 간극 +/-X · 경기 [국면]) 한 문장 압축, 60자 이내.
2. [이모지] 인사이트 한 줄 — 위 세 지표가 *서로 어떻게 맞물리는지* 메커니즘 1문장 (예: "탐욕인데 간극은 (-) → 심리와 신호가 어긋난 상태"). 80자 이내.

자문 가드 (절대 위반 금지):
- 매수/매도/추천/유리/불리/위험/안전/매수타이밍/상승전망/하락전망/예측/전망/기대/포트폴리오/목표가/수익률 보장 단어 금지.
- 미래 방향 추정 ("~할 것이다", "~로 이어질 가능성") 금지.
- "현재 데이터의 위치/상태/상관 사실" 만 진술. 일반론적 메커니즘 (교과서 인과) 만 인사이트로.

기타 규칙:
- 마크다운 X. 부드러운 어투 (~입니다, ~상태입니다).
- 영문 약어/snake_case 변수명 그대로 쓰지 말고 한국어 자연어로 (예: hy_spread → 하이일드 스프레드).
- *한자 절대 사용 금지* — 한글/영문/숫자/기호만 (예: "對立" → "대립", "中立" → "중립").
- 이모지 두 줄 다른 것 사용. 핵심: ⚖️🔄📊  인사이트: 🧭🔍💡.""",

    'en': """/no_think
You are an objective market describer in plain English. Synthesize the input indicators (Fear & Greed, gap, cycle phase, etc.) into *2 lines*.

Format (exactly two lines, each prefixed with one emoji):
1. [emoji] Headline — 3 key metrics (sentiment N · signal gap +/-X · cycle [phase]) in one short sentence, ≤90 chars.
2. [emoji] Insight — one-sentence mechanism describing how the three metrics *interlock* (e.g., "greed↑ while gap negative → overheating signal coexists with selling flow"), ≤110 chars.

Advice-risk guard (must not violate):
- NO words: buy/sell/recommend/favorable/risky/safe/timing/upside-outlook/downside-outlook/predict/forecast/expect/portfolio/target-price/return-guarantee.
- NO future-direction inference ("will", "may lead to").
- State only the *current position/state/correlation* facts; insight is a textbook mechanism only.

Other rules:
- No markdown. Professional yet accessible tone.
- Translate snake_case feature names to natural language (e.g., hy_spread → high-yield spread).
- NO Chinese characters in output (English/numbers/symbols only).
- Use different emojis on the two lines. Headline: ⚖️🔄📊  Insight: 🧭🔍💡.""",
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
    # 압축본 — fixed template 만 강제, 슬롯 규칙은 예시로 추론하도록.
    'ko': (
        "/no_think 한국어 금융 해설. 아래 지표로 다음 형식 1문장 작성.\n"
        '형식: "시장이 {밸류 라벨} 상태{이지만/이며} 시장 이성 점수가 {±수치}점으로, {합리적/비합리적}인 밸류를 가지고 있습니다."\n'
        "규칙: 라벨·이성 부호 일치 → 이며, 불일치 → 이지만. 양수 → 합리적, 음수 → 비합리적.\n"
        "필요 시 보조 1문장 추가 (공포탐욕 극단·RSI 극단·VIX>25·|이성|>2 등).\n"
        "≤180자, 마침표 끝, 이모지·마크다운·대시·콜론 X.\n"
        "예: 시장이 다소 고평가 상태이지만 시장 이성 점수가 +0.9점으로, 합리적인 밸류를 가지고 있습니다."
    ),
    'en': (
        "/no_think English financial commentary. Write 1 sentence in this exact format from indicators below.\n"
        'Format: "The market is {label}{connector} Market Rationality at {±value}, indicating a {reasonable/unreasonable} valuation."\n'
        "Rules: matching label-rationality direction → ', and with'; mismatch → ', but with'. + → reasonable, − → unreasonable.\n"
        "Optional 2nd sentence for extreme F&G/RSI/VIX>25/|rationality|>2.\n"
        "≤220 chars, period-ended, no emoji/markdown/em-dash/colon.\n"
        "Example: The market is somewhat overvalued, but with Market Rationality at +0.9, indicating a reasonable valuation."
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

    return {'summary': err['no_data'], 'error': True, 'cached': False, 'source': 'cache_miss'}


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
        payload = fetch_app_cache(_ai_summary_cache_key(lang, region))
        if payload and payload.get('summary'):
            with _ai_lock:
                _ai_cache[key] = {
                    'summary': payload['summary'],
                    'generated_at': payload.get('generated_at'),
                    'expires': now + _AI_TTL,
                }
            return {**payload, 'cached': True, 'source': 'app_cache'}
        out = _generate_ai_summary(lang, region)
        if out and out.get('summary'):
            payload = {**out, 'cached': False, 'source': 'generated'}
            try:
                upsert_app_cache(_ai_summary_cache_key(lang, region), {**out, 'cached': True, 'source': 'app_cache'})
            except Exception as e:
                print(f'[AI Summary] cache write failed: {e}')
            with _ai_lock:
                _ai_cache[key] = {
                    'summary': out['summary'],
                    'generated_at': out.get('generated_at'),
                    'expires': now + _AI_TTL,
                }
            return payload
        fallback = _fallback_ai_summary(lang, region)
        return {'summary': fallback, 'generated_at': _kst_now_str(), 'cached': False, 'source': 'fallback'}
    except Exception as e:
        print(f'[AI Summary] error: {e}')
        fallback = _fallback_ai_summary(lang, region)
        return {'summary': fallback or err['fail'], 'generated_at': _kst_now_str(), 'cached': False, 'source': 'fallback'}


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
        'fundamental': "/no_think 한국 사용자. *3 블록* 으로 출력.\n[1] 데이터 요약: 입력으로 들어온 시장 이성 점수·레짐·상위 기여 지표 값들을 모두 한 줄로 모아 정리 + '오늘 시장 이성 점수는 X (양수=이성 우위/음수=감정 우위)' 한 줄 요약.\n[2] 주요 변수 설명: 영향이 큰 지표 1~2 개 — 영문 변수명을 한글로 번역 + 그 변수가 *왜 모델 점수에 영향을 주는지* 쉽고 짧게 (한 줄/지표).\n[3] 인사이트: 데이터+변수 의미를 종합한 교과서적 패턴 한 줄.\n블록 사이 빈 줄(\\n\\n). 한자 절대 금지. 매수/매도/추천/유리/불리/위험/예측/전망/기대 단어 금지. 마크다운 X. ≤320자.",
        'signal':      "/no_think 한국 사용자. *3 블록* 으로 출력. 본 탭은 이상 탐지(평소와의 거리 D²). 'crash/surge 점수·간극' 개념 사용 금지 — D² 와 분위만.\n[1] 데이터 요약: D² 값·10년 분포 내 상위 N% 위치·90일 분위·주요 기여 지표·유사 과거 시점 등 입력값 모두 한 묶음으로 + 한 줄 요약 ('오늘 평소와의 거리는 X 로 10년 상위 N% 위치').\n[2] 주요 변수 설명: 기여 큰 지표 1~2 개 — 한국어 라벨 + *왜 이 변수가 거리 계산에 들어가는지* 쉽게 한 줄/지표.\n[3] 인사이트: 데이터·변수 의미 종합 교과서 패턴 한 줄.\n블록 사이 빈 줄(\\n\\n). 한자 금지. 매수/매도/추천/유리/불리/위험/안전/예측/전망/기대/상승·하락 압력·우위 단어 금지. 마크다운 X. ≤320자.",
        'sector':      "/no_think 한국 사용자. *3 블록* 으로 출력.\n[1] 데이터 요약: 입력의 경기 국면명·매크로 스냅샷·상위 섹터 모두 정리 + 한 줄 요약.\n[2] 주요 변수 설명: 핵심 매크로 지표 1~2 개 — 한국어 라벨 + *왜 그 지표가 경기 국면 분류에 영향 주는지* 쉽게.\n[3] 인사이트: 거시 사이클상 *교과서적*으로 그 국면에서 함께 거론되는 섹터 한 줄 (추천 X, 사실).\n블록 사이 빈 줄(\\n\\n). 한자 금지. 매수/매도/추천/유리/불리/예측/전망/수혜 단어 금지. 마크다운 X. ≤320자.",
        'sector-val':  "/no_think 한국 사용자 중립 비교. *3 블록* 으로 출력.\n[1] 데이터 요약: 평균 대비 차이가 큰 1~2 섹터의 PER/PBR 위치를 '평균 대비 +X%' 형태로 정리.\n[2] 주요 변수 설명: PER 평균 대비 차이가 *왜 의미 있는지* 쉽고 중립적으로 (고평가/저평가 단어 X).\n[3] 인사이트: 상대 위치 사실의 교과서적 의미 한 줄 (방향 예측 X).\n블록 사이 빈 줄(\\n\\n). 한자 금지. 가치판단(고평가/저평가/비싸다/싸다/매수/매도/추천/유리/불리) 절대 금지. 마크다운 X. ≤320자.",
        'sector-mom':  "/no_think 한국 사용자. *3 블록* 으로 출력.\n[1] 데이터 요약: 1주일·1개월 모멘텀 상위/하위 섹터 수치 정리.\n[2] 주요 변수 설명: 1주 수익률·랭크가 *왜 단기 로테이션 신호로 쓰이는지* 쉽게.\n[3] 인사이트: 경기 국면과 일치/배반 여부의 *교과서적* 의미 한 줄.\n블록 사이 빈 줄(\\n\\n). 한자 금지. 선반영/기대/예측/회복 전망/유리/불리/추천/매수/매도 단어 금지. 마크다운 X. ≤320자.",
    },
    'en': {
        'fundamental': "/no_think English. Output *3 blocks*.\n[1] Data summary: list all input numbers (rationality score, regime, top contributing indicators) in one block + one-line summary.\n[2] Variable explanation: 1-2 most impactful variables — translate snake_case to natural English + briefly explain WHY this variable feeds the score (one line each).\n[3] Insight: textbook pattern combining data + variable meaning, one line.\nSeparate blocks with blank line (\\n\\n). NO Chinese characters. NO buy/sell/recommend/favorable/risky/safe/predict/forecast/expect/outlook words. No markdown. ≤360 chars.",
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
            top_fc = sorted(fc, key=lambda x: abs(x.get('contribution', 0)), reverse=True)[:5] if fc else []
            if top_fc:
                # LLM 입력에 *한국어 라벨 + 의미 + 왜 영향 주는지* 까지 미리 합성하여 LLM 이 영문
                # snake_case 를 다시 번역할 필요가 없게 한다 (qwen 이 영문 변수명을 그대로 echo 하던 문제 해결).
                lines.append("Feature contributions (label, meaning, why it matters):" if is_en else "피처 기여도 (라벨·의미·왜 영향 주는지):")
                for f in top_fc:
                    nm = f.get('name', '?')
                    val = f.get('contribution', '?')
                    lines.append(f"  - {_ko_feature_why(nm, lang)}; "
                                 f"{'contribution' if is_en else '기여도'}: {val}")
            fv = regime.get('feature_values', {})            # 현재 피처 값 (JSONB)
            if isinstance(fv, str):                          # 문자열이면 JSON 파싱
                try:
                    fv = json.loads(fv)
                except Exception:
                    fv = {}
            if fv:
                lines.append("Current Values:" if is_en else "현재 지표값:")
                for k, v in list(fv.items())[:6]:            # 상위 6개 피처 값
                    lines.append(f"  {_ko_feature(k, lang)}: {v}")

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
        result = _groq_call(_EXPLAIN_PROMPTS[lang][tab], text, 150)
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
    """Rule-based 시황 요약 — LLM 미가용 시 폴백. 1줄 핵심 + 1줄 인사이트.

    자문 가드: 매수/매도/추천/예측/전망/유리/불리 등 금지. "현재 위치" 사실만.
    """
    try:
        today = get_market_summary_today(region=region)
        fg = today.get('fear_greed') or {}
        cs = today.get('crash_surge') or {}
        sector = fetch_sector_cycle_latest(region=region) or {}
        fg_score = fg.get('score')
        fg_label = fg.get('rating') or ''
        gap = cs.get('gap')
        phase = sector.get('phase_name')

        if lang == 'en':
            parts = []
            if fg_score is not None:
                parts.append(f"sentiment {fg_label} {round(float(fg_score))}")
            if gap is not None:
                parts.append(f"signal gap {_fmt_signed(gap)}")
            if phase:
                parts.append(f"cycle {phase}")
            line1 = "📊 " + ", ".join(parts) if parts else "📊 indicators loading"
            # textbook insight clause — co-occurrence pattern, no direction prediction
            insight_bits = []
            if fg_label and gap is not None:
                if 'greed' in fg_label.lower() and float(gap) < 0:
                    insight_bits.append("greed-leaning sentiment alongside negative signal gap is a textbook divergence pattern")
                elif 'fear' in fg_label.lower() and float(gap) > 0:
                    insight_bits.append("fear-leaning sentiment alongside positive signal gap is a textbook divergence pattern")
                else:
                    insight_bits.append("sentiment label and signal gap are pointing the same way (alignment pattern)")
            if not insight_bits:
                insight_bits.append("indicators co-positioned at current snapshot, read as state — not a direction call")
            line2 = "🔍 " + insight_bits[0] + "."
            return line1 + ".\n" + line2

        parts = []
        if fg_score is not None:
            parts.append(f"심리 {fg_label} {round(float(fg_score))}")
        if gap is not None:
            parts.append(f"신호 간극 {_fmt_signed(gap)}")
        if phase:
            parts.append(f"경기국면 {phase}")
        line1 = "📊 " + ", ".join(parts) if parts else "📊 지표 수집 중"
        insight_bits = []
        if fg_label and gap is not None:
            if '탐욕' in fg_label and float(gap) < 0:
                insight_bits.append("탐욕 쪽 심리와 음(-) 신호 간극이 같은 시점에 관측되는 *교과서적 괴리 패턴*")
            elif '공포' in fg_label and float(gap) > 0:
                insight_bits.append("공포 쪽 심리와 양(+) 신호 간극이 같은 시점에 관측되는 *교과서적 괴리 패턴*")
            else:
                insight_bits.append("심리 라벨과 신호 간극 방향이 같은 *정렬 패턴* (방향 예측 X)")
        if not insight_bits:
            insight_bits.append("지표들이 현재 스냅샷에서 공존하는 상태 — 방향 추정이 아닌 상태 기록")
        line2 = "🔍 " + insight_bits[0] + "입니다."
        return line1 + " 입니다.\n" + line2
    except Exception:
        return ('📊 indicators loading.\n🔍 commentary is using the latest numeric snapshot.'
                if lang == 'en'
                else '📊 지표 수집 중입니다.\n🔍 현재 지표 기준 스냅샷으로 안내 중입니다.')


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
            regime = fetch_noise_regime_current(region=region) or {}
            score = regime.get('noise_score')
            regime_name = regime.get('regime_name') or '-'
            fc = regime.get('feature_contributions') or []
            if isinstance(fc, str):
                try:
                    fc = json.loads(fc)
                except Exception:
                    fc = []
            fv = regime.get('feature_values') or {}
            if isinstance(fv, str):
                try:
                    fv = json.loads(fv)
                except Exception:
                    fv = {}
            top = sorted(fc, key=lambda x: abs(x.get('contribution', 0)), reverse=True)[:2]
            top_names = top[0].get('name') if top else None
            second_name = top[1].get('name') if len(top) > 1 else None
            contrib_str = ', '.join(
                f"{_ko_feature(x.get('name', '?'), lang)} {_fmt_signed(x.get('contribution', 0), 2)}"
                for x in top
            ) or '-'
            why_lines = "\n".join(
                f"  - {_ko_feature_why(x.get('name', '?'), lang)}"
                for x in top
            ) or '-'

            if lang == 'en':
                block1 = (
                    f"[Data] Regime: {regime_name}. Market Rationality Score: {_fmt_signed(score, 2)}"
                    f" (positive=rational, negative=emotional).\n"
                    f"Top contributors: {contrib_str}.\n"
                    f"Summary: today's rationality reading sits at {_fmt_signed(score, 2)}."
                )
                block2 = f"[Why these variables matter]\n{why_lines}"
                block3 = (
                    "[Insight] Variables together describe how aligned or detached price action is from "
                    "fundamentals — a textbook divergence/alignment readout, no direction inferred."
                )
            else:
                block1 = (
                    f"[데이터 요약] 레짐: {regime_name}. 시장 이성 점수: {_fmt_signed(score, 2)}"
                    f" (양수=이성 우위, 음수=감정 우위).\n"
                    f"상위 기여 지표: {contrib_str}.\n"
                    f"요약: 오늘 이성 점수는 {_fmt_signed(score, 2)} 위치입니다."
                )
                block2 = f"[주요 변수 설명 — 왜 모델에 영향을 주는지]\n{why_lines}"
                block3 = (
                    "[인사이트] 위 지표들이 함께 가리키는 *교과서적* 패턴은 심리·펀더멘털의 정렬 또는 괴리 정도이며, "
                    "이는 가격 흐름이 펀더멘털과 얼마나 맞물리고 있는지에 대한 사실 기록입니다 (방향 예측 X)."
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
                block1 = (
                    f"[데이터 요약] 평소와의 거리(D²): {d2 if d2 is not None else '-'}.\n"
                    f"위치: 10년 분포 내 상위 {top_pct}%"
                    f" / 90일 분위 {pct_90d}.\n"
                    f"주된 기여 지표: {contrib_str}.\n"
                    f"유사 과거 시점: {knn_str}.\n"
                    f"요약: 오늘 평소와의 거리는 10년 상위 {top_pct}% 위치입니다."
                )
                block2 = f"[주요 변수 설명 — 왜 거리 계산에 들어가는지]\n{why_lines}"
                block3 = (
                    "[인사이트] 위 지표들이 함께 가리키는 *교과서적* 패턴은 오늘 시장 상태가 10년 평소 분포와 얼마나 떨어졌는지의 "
                    "복합 거리이며, '평소와의 거리' 사실 기록일 뿐 방향 예측은 포함하지 않습니다."
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
            macro_str = ', '.join(f"{k} {v}" for k, v in list(ms.items())[:4]) or '-'
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
                    f"[데이터 요약] 경기 국면: {phase}.\n"
                    f"매크로 스냅샷: {macro_str}.\n"
                    f"함께 거론되는 섹터: {sectors}.\n"
                    f"요약: 매크로 지표 종합 결과 현재는 {phase} 국면 위치입니다."
                )
                block2 = (
                    "[주요 변수 설명 — 왜 모델에 영향을 주는지]\n"
                    "  - 매크로 지표(수익률 곡선·성장·물가)는 총수요와 공급의 위치를 추적하기 때문에 경기 국면 분류의 핵심 입력으로 들어갑니다."
                )
                block3 = (
                    f"[인사이트] {phase} 국면에서는 위 섹터들이 거시 사이클 문헌상 *교과서적*으로 함께 거론되는 동조 패턴이며, "
                    f"이는 사실 기록일 뿐 추천이 아닙니다."
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
                    f"[데이터 요약] 섹터별 PER 의 5년 평균 대비 위치 ('평균 대비 +X%' 형태).\n"
                    f"평균 대비 가장 높은 위치: {high_str}.\n"
                    f"평균 대비 가장 낮은 위치: {low_str}.\n"
                    f"요약: 위 수치는 상대 위치 기록일 뿐입니다."
                )
                block2 = (
                    "[주요 변수 설명 — 왜 의미 있는지]\n"
                    "  - PER 의 평균 대비 차이는 오늘의 주가/이익 비율을 *각 섹터 자체의 평소 범위* 안에서 표준화해 보여주기 때문에 "
                    "절대 수준과 무관한 상대 위치 프레임이 됩니다."
                )
                block3 = (
                    "[인사이트] 이 프레임은 각 섹터가 *자기 평소 범위* 안에서 어디에 있는지를 사실로 기록합니다. "
                    "상대 위치 기록일 뿐 고평가·저평가 판단이나 매수·매도 신호가 아닙니다."
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
                    f"[데이터 요약] 1주일 섹터 모멘텀.\n"
                    f"상위: {top_str}.\n"
                    f"하위: {bot_str}.\n"
                    f"요약: 순위는 과거 1주일 섹터 수익률 기준입니다."
                )
                block2 = (
                    "[주요 변수 설명 — 왜 모델에 영향을 주는지]\n"
                    "  - 1주 수익률 순위는 표준적인 단기 로테이션 지표로, 최근 1주간 또래 대비 더 움직인 섹터를 잡아내는 *실현 성과* 정보입니다."
                )
                block3 = (
                    "[인사이트] 상위 섹터가 현재 경기 국면과 정렬되는지/배반하는지가 *교과서적* 동조 또는 괴리 패턴이며, "
                    "이는 사실 정보일 뿐 방향 예측을 포함하지 않습니다."
                )
            return f"{block1}\n\n{block2}\n\n{block3}"
    except Exception as e:
        print(f'[AI Explain {tab}/{lang}/{region}] fallback error: {e}')

    return 'Commentary is temporarily using the latest numeric snapshot.' if lang == 'en' else '현재 지표 기준으로 해설을 준비했습니다.'


@router.get('/ai-explain')                                   # GET /api/market-summary/ai-explain
def get_ai_explain(tab: str = Query(..., description='fundamental, signal, sector, sector-val, sector-mom'),
                   lang: str = Query('ko'),
                   region: str = Query('us')):
    """2-tier 즉시 응답: in-memory cache → DB (ai_explain_cache).

    스케줄러가 미리 생성해 DB 적재한다. 캐시가 비면 사용자 요청에서는 생성하지 않는다.
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
            return {'explanation': _format_explain_blocks(cached['text']), 'tab': tab, 'cached': True}

    # 2차: DB cache (스케줄러 미리 적재)
    try:
        row = fetch_ai_explain(tab, lang, region)
    except Exception as e:
        print(f'[AI Explain {tab}/{lang}/{region}] DB read 실패 (계속 진행): {e}')
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

    # Cache miss: generate on demand, then fall back to a rule-based explanation.
    out = None
    try:
        out = _generate_ai_explain(tab, lang, region)
    except Exception as e:
        print(f'[AI Explain {tab}/{lang}/{region}] on-demand generation failed: {e}')

    if out and out.get('explanation'):
        try:
            upsert_ai_explain(tab, lang, region, out['explanation'])
        except Exception as e:
            print(f'[AI Explain {tab}/{lang}/{region}] cache write failed: {e}')
        with _explain_lock:
            _explain_cache[cache_key] = {
                'text': out['explanation'],
                'expires': now + _EXPLAIN_TTL,
            }
        return {
            'explanation': out['explanation'],
            'tab': tab,
            'cached': False,
            'generated_at': out.get('generated_at'),
            'source': 'generated',
        }

    fallback = _fallback_ai_explain(tab, lang, region)
    with _explain_lock:
        _explain_cache[cache_key] = {
            'text': fallback,
            'expires': now + _EXPLAIN_TTL,
        }
    return {
        'explanation': fallback or err['no_data'],
        'tab': tab,
        'cached': False,
        'generated_at': _kst_now_str(),
        'source': 'fallback',
    }
