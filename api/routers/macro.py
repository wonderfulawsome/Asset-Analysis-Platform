import threading
from datetime import datetime, time as dtime
from fastapi import APIRouter
import pandas as pd
import pytz
import yfinance as yf
from database.repositories import (
    fetch_macro_latest2, fetch_fear_greed_latest2,
    fetch_valuation_signal_latest, fetch_valuation_signal_history,
    upsert_valuation_signal, upsert_valuation_signal_bulk,
)

router = APIRouter()

# 미국 동부시간 타임존
_ET = pytz.timezone('US/Eastern')
# 장 시작/종료 시각 (ET)
_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)

# 캐시: (값, 만료시각)
_vol_cache: dict = {'value': None, 'expires': 0}
_vol_lock = threading.Lock()
_CACHE_SEC = 300  # 5분 캐시


def _realtime_vol_ratio():
    """SPY 30분봉으로 동시간대 거래량 비율 계산. 장중에만 유효, 5분 캐시."""
    now_ts = datetime.now().timestamp()
    # 캐시 유효하면 바로 반환
    with _vol_lock:
        if _vol_cache['value'] is not None and now_ts < _vol_cache['expires']:
            return _vol_cache['value']
    try:
        now_et = datetime.now(_ET)
        # 주말이면 None
        if now_et.weekday() >= 5:
            return None
        # 장 시간 외면 None (전일 마감 데이터 사용)
        if not (_MARKET_OPEN <= now_et.time() <= _MARKET_CLOSE):
            return None
        # SPY 30분봉 1달치 다운로드
        df = yf.download('SPY', period='1mo', interval='30m', progress=False)
        vol = df['Volume'].squeeze()
        vol.index = vol.index.tz_convert(_ET)
        # 날짜/시간 분리
        dates = vol.index.date
        times = vol.index.time
        today = now_et.date()
        # 오늘 데이터 필터
        today_mask = dates == today
        if not today_mask.any():
            return None
        # 오늘 누적 거래량과 마지막 봉 시간
        today_cumvol = int(vol[today_mask].sum())
        last_time = times[today_mask][-1]
        # 과거 각 날짜별 동시간대(<=last_time) 누적 거래량
        past_mask = (dates != today) & (times <= last_time)
        past_vol = vol[past_mask]
        if past_vol.empty:
            return None
        past_dates = past_vol.index.date
        past_daily = pd.Series(past_vol.values, index=past_dates).groupby(level=0).sum()
        avg_past = past_daily.mean()
        if avg_past <= 0:
            return None
        result = round(today_cumvol / avg_past, 4)
        # 캐시 저장
        with _vol_lock:
            _vol_cache['value'] = result
            _vol_cache['expires'] = now_ts + _CACHE_SEC
        return result
    except Exception:
        return None


@router.get('/latest')
def get_latest():
    rows = fetch_macro_latest2()
    if not rows:
        return None
    current = rows[0]
    # 최신 레코드의 주요 값이 null이면(putcall만 별도 upsert된 경우) 이전 레코드로 보완
    if current.get('vix') is None and len(rows) >= 2 and rows[1].get('vix') is not None:
        prev_full = rows[1]
        for key in ('sp500_close', 'sp500_return', 'sp500_vol20', 'vix', 'tnx', 'yield_spread', 'dxy_return', 'sp500_rsi'):
            if current.get(key) is None and prev_full.get(key) is not None:
                current[key] = prev_full[key]
    if len(rows) >= 2:
        prev = rows[1]
        current['prev_vix'] = prev.get('vix')
        current['prev_sp500_vol20'] = prev.get('sp500_vol20')
    # 이중 안전장치: vix/vol이 0이면 유효한 과거 레코드에서 폴백 (주말/장후 대비)
    if not current.get('vix'):                               # vix가 0/None이면
        for prev_fb in rows[1:]:                             # 과거 레코드 순회
            if prev_fb.get('vix') and prev_fb['vix'] > 0:   # 유효한 값 찾을 때까지
                current['vix'] = prev_fb['vix']              # 유효한 VIX로 대체
                break
    if not current.get('sp500_vol20'):                       # vol이 0/None이면
        for prev_fb in rows[1:]:                             # 과거 레코드 순회
            if prev_fb.get('sp500_vol20') and prev_fb['sp500_vol20'] > 0:  # 유효한 값 찾을 때까지
                current['sp500_vol20'] = prev_fb['sp500_vol20']  # 유효한 거래량 비율로 대체
                break
    # 실시간 동시간대 거래량 비율 (장중이면 덮어쓰기)
    rt_vol = _realtime_vol_ratio()
    if rt_vol is not None:
        current['sp500_vol20'] = rt_vol
    return current


@router.get('/fear-greed')
def get_fear_greed():
    rows = fetch_fear_greed_latest2()
    if not rows:
        return None
    current = rows[0]
    if len(rows) >= 2:
        current['prev_score'] = rows[1].get('score')
    return current


# ─────────────────────────────────────────────────────────
# /valuation-signal — Composite Z (A1+C7) 기반 고/저평가 + LLM 해설 (24h 캐시)
# z_comp = 0.4·z_ERP(5Y) + 0.3·z_VIX + 0.3·z_DD60
# ─────────────────────────────────────────────────────────
import time as _time
_VAL_SIG_PROMPT = """/no_think
너는 한국어 금융 해설가다. 시장 평가 점수와 그 분해 데이터를 받아, **왜 이런
결과가 나왔는지 원인까지** 일반 투자자에게 설명한다.

배경:
- 종합 점수 = 주식 매력도(40%) + 공포 점수(30%) + 하락 충격 점수(30%) 의 가중합
- 모든 점수의 비교 기준은 "최근 5년 평균"
- 종합 점수 > +1.0 명확한 저평가 / 0~+1.0 다소 저평가 / -1.0~0 다소 고평가 / -1.0 미만 명확한 고평가

각 점수가 만들어지는 원인:
- "주식 매력도 점수" ← 주가수익비율(PER, 낮을수록 쌈) + 10년 국채금리(높을수록 안전자산 매력↑)
- "공포 점수"        ← 공포지수 VIX (높을수록 시장 불안)
- "하락 충격 점수"   ← 최근 60일 고점 대비 하락폭 (깊을수록 큰 낙폭)

응답 구성 (정확히 3문장, 총 200자 이내):
1. 종합 점수 X.XX점, "{라벨}" 영역.
2. **원인 분석** — input 의 "_가장_영향_큰_점수" 의 원인을 raw 값(PER, 국채금리, VIX,
   하락폭)과 5년 평균을 비교해 한 문장
   (예: "주가수익비율 28배로 평소 대비 다소 높음, 국채금리 4.35%도 상대적으로 높은 수준이라 주식 매력도가 낮아진 상태").
3. 보조 요인 한마디 + 신중한 액션 검토 제안 (관망 검토 / 분할 매수 검토 / 방어 비중 확대 검토 등).

규칙:
- **명사형 종결**: "~요/~다/~합니다" 금지. "~함/~임/~는 상태/~수준/~검토" 식 명사형으로 끝낼 것
- **중립적·신중한 어투**: "~ 깎였어요/미루세요/매력적입니다" 같은 단언 금지.
  "다소 ~한 수준/~ 검토 여지/~ 가능성 있음" 식 신중한 표현 사용
- 공식·영문 약어(z, σ, ERP, composite) 금지. PER·VIX 정도는 한글 풀이 후 사용 가능
- 마크다운·이모지 금지

좋은 예시 (명사형 + 신중):
"종합 점수 -0.63점, '다소 고평가' 영역. 주가수익비율 28배로 평소 대비 다소 높고
국채금리 4.35%도 상대적으로 높은 수준이라 주식 매력도 점수가 낮아진 상태. 60일
하락폭은 평소보다 작아 위기 신호 부재, 적극 매수보다는 관망 검토 여지."

나쁜 예시 (단언/~요체 — 피할 것):
"종합 점수 -0.63점으로 다소 고평가입니다. PER 28배라 비싸진 시기예요. 분할 매수는 미루세요." """

_val_sig_cache = {'data': None, 'ts': 0}
_VAL_SIG_TTL = 24 * 3600


def build_baseline_snapshot(baselines: dict) -> dict:
    """API 응답에서 baselines_5y 형태로 그대로 쓰는 dict — 스냅샷용."""
    return {
        'erp':     baselines.get('erp', {}),
        'vix':     baselines.get('vix', {}),
        'dd':      baselines.get('dd',  {}),
        'weights': baselines.get('weights', {'erp': 0.4, 'vix': 0.3, 'dd': 0.3}),
    }


def build_valuation_interpretation(today: dict, baselines: dict) -> str:
    """Groq LLM 호출 + 룰베이스 fallback. today + baselines 입력으로 해설 1문단 반환.

    스케줄러가 매일 1회 호출해 valuation_signal.interpretation 컬럼에 저장 → endpoint 는
    DB select 만으로 즉시 응답. endpoint 호출 시점에는 외부 LLM 호출 0회.
    """
    z_comp_now = today.get('z_comp') or 0.0
    ze = today.get('z_erp') or 0.0
    zv = today.get('z_vix') or 0.0
    zd = today.get('z_dd')  or 0.0
    contribs = {
        '주식 매력도 점수': ze * 0.4,
        '공포 점수':        zv * 0.3,
        '하락 충격 점수':   zd * 0.3,
    }
    dom_name = (min if z_comp_now < 0 else max)(contribs, key=contribs.get)

    # 1) Groq LLM
    try:
        from api.routers.market_summary import _groq_call
        import json as _json
        user_text = _json.dumps({
            '오늘': {
                '종합_점수':           round(z_comp_now, 2),
                '라벨':                today.get('label'),
                '_가장_영향_큰_점수':  dom_name,
                '주식_매력도_점수':    round(ze, 2),
                '공포_점수':           round(zv, 2),
                '하락_충격_점수':      round(zd, 2),
            },
            '오늘_raw_값': {
                '주가수익비율_PER':   today.get('spy_per'),
                '국채금리_pct':       round((today.get('tnx_yield') or 0) * 100, 2),
                '주식_매력도_pct':    round((today.get('erp') or 0) * 100, 2),
                '공포지수_VIX':       today.get('vix'),
                '60일_하락폭_pct':    round((today.get('dd_60d') or 0) * 100, 2),
            },
            '최근_5년_평균': {
                '주식_매력도_pct': round(baselines['erp']['mean'] * 100, 2),
                '공포지수':        round(baselines['vix']['mean'], 2),
                '60일_하락폭_pct': round(baselines['dd']['mean']  * 100, 2),
            },
        }, ensure_ascii=False, indent=2)
        interpretation = _groq_call(_VAL_SIG_PROMPT, user_text, max_tokens=320)
        if interpretation:
            return interpretation
    except Exception as e:
        print(f'[valuation_signal] LLM 실패: {e}')

    # 2) 룰베이스 fallback
    label = today.get('label', '')
    per   = today.get('spy_per') or 0
    tnx_p = (today.get('tnx_yield') or 0) * 100
    vix_v = today.get('vix') or 0
    dd_p  = (today.get('dd_60d') or 0) * 100
    m_vix = baselines['vix']['mean']
    m_dd  = baselines['dd']['mean'] * 100
    if dom_name == '주식 매력도 점수':
        cause = f"주가수익비율(PER) {per:.1f}배 + 국채금리 {tnx_p:.2f}% 조합으로 주식 매력도 점수가 5년 평균 대비 낮은 수준"
    elif dom_name == '공포 점수':
        cause = f"공포지수(VIX) {vix_v:.1f}, 5년 평균 {m_vix:.1f} 대비 시장 분위기가 한쪽으로 치우친 상태"
    else:
        cause = f"최근 60일 하락폭 {dd_p:+.2f}%, 5년 평균 {m_dd:+.2f}% 대비 영향이 두드러지는 수준"
    if '명확한 저평가' in label:
        return f"종합 점수 {z_comp_now:+.2f}점, '명확한 저평가' 영역. {cause}. 분할 매수 검토 여지 있음."
    if '다소 저평가' in label:
        return f"종합 점수 {z_comp_now:+.2f}점, '다소 저평가' 영역. {cause}. 관심 종목 점진 매수 검토 여지."
    if '명확한 고평가' in label:
        return f"종합 점수 {z_comp_now:+.2f}점, '명확한 고평가' 영역. {cause}. 현금·채권 비중 확대 검토 권장."
    return f"종합 점수 {z_comp_now:+.2f}점, '다소 고평가' 영역. {cause}. 관망 또는 방어 비중 확대 검토 여지."


@router.get('/valuation-signal')
def get_valuation_signal():
    """DB 만 select 하는 fast-path. 스케줄러 [Step 5d] 가 매일 raw·점수·LLM 해설·
    baseline 스냅샷 모두 미리 적재 → endpoint 는 단순 select. 외부 호출 0회.

    레거시 (interpretation/baseline_snapshot 미적재 행) 안전망:
    - on-the-fly 산출 후 응답 (단 그 결과는 DB 에 다시 적재 안 함 — scheduler 책임)
    """
    now = _time.time()
    cached = _val_sig_cache['data']
    if cached and (now - _val_sig_cache['ts']) < _VAL_SIG_TTL:
        return {**cached, 'cached': True}

    try:
        today = fetch_valuation_signal_latest()
        history = fetch_valuation_signal_history(days=90)
    except Exception as e:
        print(f'[valuation_signal] DB fetch 실패: {e}')
        return {'error': f'DB fetch failed: {type(e).__name__}: {str(e)[:200]}'}

    if not today:
        return {'error': 'no data'}

    # DB 에 사전 적재된 값 우선
    interpretation = today.get('interpretation')
    baseline_snapshot = today.get('baseline_snapshot')

    # 안전망: 사전 적재 안 됐으면 on-the-fly (느림 — 스케줄러 정상 동작 시 도달 X)
    if not interpretation or not baseline_snapshot:
        try:
            from collector.valuation_signal import get_baselines
            baselines = get_baselines()
            if not baseline_snapshot:
                baseline_snapshot = build_baseline_snapshot(baselines)
            if not interpretation:
                interpretation = build_valuation_interpretation(today, baselines)
        except Exception as e:
            print(f'[valuation_signal] fallback 실패: {e}')

    response = {
        'today': today,
        'history': history,
        'interpretation': interpretation,
        'baselines_5y': baseline_snapshot,
        'cached': False,
    }
    _val_sig_cache['data'] = response
    _val_sig_cache['ts'] = now
    return response