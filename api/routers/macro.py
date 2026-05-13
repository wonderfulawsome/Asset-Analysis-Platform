import threading
from datetime import datetime, time as dtime
from fastapi import APIRouter, Query
import pandas as pd
import pytz
import yfinance as yf
from database.repositories import (
    fetch_macro_latest2, fetch_fear_greed_latest2,
    fetch_valuation_signal_latest, fetch_valuation_signal_history,
    upsert_valuation_signal, upsert_valuation_signal_bulk,
)

router = APIRouter()


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'

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
def get_latest(region: str = Query('us')):
    rows = fetch_macro_latest2(region=_norm_region(region))
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
def get_fear_greed(region: str = Query('us')):
    rows = fetch_fear_greed_latest2(region=_norm_region(region))
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
3. 보조 요인 한마디 + *현재 상태 기록* 한마디 (위치/구간/특성 묘사로 마무리).

자문 가드 (절대 위반 금지):
- 매수/매도/추천/관망/분할 매수/방어/공격/비중 확대/비중 축소/포지션/포트폴리오/타이밍 단어 금지
- "~ 검토", "~ 검토 여지", "~ 고려" 같은 액션 제안 표현 금지
- 미래 방향 추정("~상승할", "~하락할", "~이어질 가능성") 금지

규칙:
- **명사형 종결**: "~요/~다/~합니다" 금지. "~함/~임/~는 상태/~수준/~위치" 식 명사형으로 끝낼 것
- **중립적·신중한 어투**: 단언("~ 매력적입니다", "~ 매력 없음") 금지.
  "~ 한 수준", "~ 위치", "~ 구간", "~ 상태", "~ 패턴" 식 상태 기록 표현만 사용
- 공식·영문 약어(z, σ, ERP, composite) 금지. PER·VIX 정도는 한글 풀이 후 사용 가능
- 마크다운·이모지 금지

좋은 예시 (명사형 + 상태 기록):
"종합 점수 -0.63점, '다소 고평가' 영역. 주가수익비율 28배로 평소 대비 다소 높고
국채금리 4.35%도 상대적으로 높은 수준이라 주식 매력도 점수가 낮아진 상태. 60일
하락폭은 평소보다 작아 위기 신호 부재한 구간."

나쁜 예시 (단언/액션 제안 — 절대 피할 것):
"종합 점수 -0.63점으로 다소 고평가입니다. 분할 매수 검토 여지." """

_val_sig_cache = {'data': None, 'ts': 0}  # cache reload trigger 2026-05-10d kr-10y
_VAL_SIG_TTL = 24 * 3600


def build_baseline_snapshot(baselines: dict) -> dict:
    """API 응답에서 baselines_5y 형태로 그대로 쓰는 dict — 스냅샷용.

    KR 5-component (per_15y / trend), US 6-component (cape_15y / buffett_15y / trend)
    키를 모두 노출 — 프론트가 region 별 분포·formula 표시에 사용.
    옛 3-key 베이스라인도 backward-compat.
    """
    return {
        'erp':         baselines.get('erp', {}),
        'vix':         baselines.get('vix', {}),
        'dd':          baselines.get('dd',  {}),
        'per_15y':     baselines.get('per_15y', {}),       # KR
        'trend':       baselines.get('trend',   {}),       # KR + US
        'cape_15y':    baselines.get('cape_15y', {}),      # US
        'buffett_15y': baselines.get('buffett_15y', {}),   # US
        'weights':     baselines.get('weights', {'erp': 0.4, 'vix': 0.3, 'dd': 0.3}),
    }


def build_valuation_interpretation(today: dict, baselines: dict) -> str:
    """Groq LLM 호출 + 룰베이스 fallback. today + baselines 입력으로 해설 1문단 반환.

    스케줄러가 매일 1회 호출해 valuation_signal.interpretation 컬럼에 저장 → endpoint 는
    DB select 만으로 즉시 응답. endpoint 호출 시점에는 외부 LLM 호출 0회.
    """
    z_comp_now = today.get('z_comp') or 0.0
    ze  = today.get('z_erp')     or 0.0
    zv  = today.get('z_vix')     or 0.0
    zd  = today.get('z_dd')      or 0.0
    zc  = today.get('z_cape')    or 0.0   # US
    zb  = today.get('z_buffett') or 0.0   # US
    zp  = today.get('z_per')     or 0.0   # KR
    zt  = today.get('z_trend')   or 0.0   # KR + US
    w   = (baselines or {}).get('weights', {})
    contribs: dict[str, float] = {
        '주식 매력도 점수': ze * float(w.get('erp', 0.4)),
        '공포 점수':        zv * float(w.get('vix', 0.3)),
        '하락 충격 점수':   zd * float(w.get('dd',  0.3)),
    }
    if zp and w.get('per'):       contribs['장기 PER 점수']   = zp * float(w['per'])
    if zc and w.get('cape'):      contribs['CAPE 점수']        = zc * float(w['cape'])
    if zb and w.get('buffett'):   contribs['Buffett 점수']     = zb * float(w['buffett'])
    if zt and w.get('trend'):     contribs['추세 점수']        = zt * float(w['trend'])
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

    # 2) 룰베이스 fallback — 자문 표현 0, 친근/이해 쉬운 톤
    label = today.get('label', '')
    per   = today.get('spy_per') or 0
    tnx_p = (today.get('tnx_yield') or 0) * 100
    vix_v = today.get('vix') or 0
    dd_p  = (today.get('dd_60d') or 0) * 100
    m_vix = baselines['vix']['mean']
    m_dd  = baselines['dd']['mean'] * 100
    cape_v    = today.get('cape')
    buffett_v = today.get('buffett_ratio')
    trend_v   = today.get('price_vs_ma200')
    if dom_name == '주식 매력도 점수':
        cause = (
            f"주가수익비율(PER) {per:.1f}배와 국채금리 {tnx_p:.2f}% 조합이 점수를 가장 크게 끌었습니다. "
            f"PER이 높을수록 같은 이익에 비해 가격이 비싼 구간이고, 국채금리가 높을수록 안전자산 수익이 좋아 주식의 상대 매력이 줄어드는 구조"
        )
    elif dom_name == '공포 점수':
        cause = (
            f"공포지수(VIX) {vix_v:.1f}, 5년 평균 {m_vix:.1f} 대비 시장 분위기가 한쪽으로 치우친 상태. "
            f"VIX는 옵션 시장이 향후 변동성을 어떻게 보는지의 가격이라 위험 인식을 직접 보여줍니다"
        )
    elif dom_name == 'CAPE 점수' and cape_v is not None:
        cause = (
            f"Shiller CAPE {cape_v:.1f}배 — 10년 평균 이익으로 계산한 장기 PER이 15년 분포에서 도드라진 위치. "
            f"단기 이익 흔들림을 평활화한 지표라 구조적 밸류에이션 위치를 보여줍니다"
        )
    elif dom_name == 'Buffett 점수' and buffett_v is not None:
        cause = (
            f"시가총액/GDP 비율 {buffett_v*100:.0f}% — 한 나라 주식 시장 전체 규모가 경제 규모 대비 얼마나 크게 잡혀 있는지의 비율. "
            f"장기 균형 수준과의 차이가 점수에 크게 반영되는 상태"
        )
    elif dom_name == '추세 점수' and trend_v is not None:
        cause = (
            f"S&P500 200일 평균선 대비 현재 위치 {trend_v*100:+.1f}%. "
            f"장기 추세선과 현재 가격 사이의 괴리가 점수에 크게 반영되고 있는 구간"
        )
    elif dom_name == '장기 PER 점수':
        cause = (
            f"15년 PER 분포 대비 현재 수준이 종합 점수에 가장 크게 기여하고 있는 상태. "
            f"긴 기간 동안의 PER 위치를 한 줄로 표준화한 지표"
        )
    else:
        cause = (
            f"최근 60일 고점 대비 하락폭 {dd_p:+.2f}%, 5년 평균 {m_dd:+.2f}% 대비 영향이 두드러지는 수준. "
            f"단기 가격 충격 폭이 평소와 얼마나 다른지가 점수에 크게 반영된 구간"
        )
    if '명확한 저평가' in label:
        regime = "주식이 5년 평균 대비 상대적으로 싸게 보이는 *명확한 저평가* 구간"
    elif '다소 저평가' in label:
        regime = "주식이 5년 평균 대비 다소 싸게 보이는 *다소 저평가* 구간"
    elif '명확한 고평가' in label:
        regime = "주식이 5년 평균 대비 상대적으로 비싸게 보이는 *명확한 고평가* 구간"
    else:
        regime = "주식이 5년 평균 대비 다소 비싸게 보이는 *다소 고평가* 구간"
    return f"종합 점수 {z_comp_now:+.2f}점, {regime}. {cause}."


@router.get('/valuation-signal')
def get_valuation_signal(
    region: str = Query('us'),
    days: int = Query(90, ge=10, le=5000),
):
    """DB 만 select 하는 fast-path. 스케줄러 [Step 5d] 가 매일 raw·점수·LLM 해설·
    baseline 스냅샷 모두 미리 적재 → endpoint 는 단순 select. 외부 호출 0회.

    days 파라미터: history 길이 (10~5000). 기본 90.
    days > 500 일 때 weekly downsample (5거래일 평균) 자동 적용 → payload 1/5.

    레거시 (interpretation/baseline_snapshot 미적재 행) 안전망:
    - on-the-fly 산출 후 응답 (단 그 결과는 DB 에 다시 적재 안 함 — scheduler 책임)
    """
    region = _norm_region(region)
    now = _time.time()
    # region+days 별 캐시키 분리 (days 다른 호출은 별도 캐시)
    cache_key = f'data_{region}_{days}'
    import os as _os_v
    disable_groq = _os_v.getenv('DISABLE_GROQ', '').lower() in ('true', '1', 'yes')
    cached = _val_sig_cache.get(cache_key)
    cached_ts = _val_sig_cache.get(f'ts_{region}_{days}', 0)
    # DISABLE_GROQ=true: in-memory cache 도 우회 — 매번 fresh rule-based fallback
    if cached and (now - cached_ts) < _VAL_SIG_TTL and not disable_groq:
        return {**cached, 'cached': True}

    try:
        today = fetch_valuation_signal_latest(region=region)
        history = fetch_valuation_signal_history(days=days, region=region)
        # 500+ 행이면 5거래일 평균으로 weekly downsample (그래프 모바일 렌더 + payload)
        if len(history) > 500:
            history = _weekly_downsample(history)
    except Exception as e:
        print(f'[valuation_signal] DB fetch 실패: {e}')
        return {'error': f'DB fetch failed: {type(e).__name__}: {str(e)[:200]}'}

    if not today:
        return {'error': 'no data'}

    # DB 에 사전 적재된 값 우선 — 단, DISABLE_GROQ=true 면 옛 LLM 응답 무시하고 fresh rule-based 강제
    interpretation = None if disable_groq else today.get('interpretation')
    baseline_snapshot = today.get('baseline_snapshot')

    # baseline snapshot — DB 의 stored snapshot 은 옛 cron 시점 weights 가 박혀 있을
    # 수 있어 (KR 5-comp 전환, US 3→6-comp 전환 등) frontend formula 텍스트가 옛 비율
    # 을 노출. region 무관 항상 rebuild 해서 현재 코드 상수 weights 가 노출되게 강제.
    baseline_snapshot = None

    # 안전망: 사전 적재 안 됐거나 옛 스키마면 on-the-fly (느림 — 스케줄러 정상 동작 시 도달 X)
    # region 별 분기 — KR 은 valuation_signal_kr.get_kr_baselines, US 는 valuation_signal.get_baselines
    if not interpretation or not baseline_snapshot:
        try:
            if region == 'kr':
                from collector.valuation_signal_kr import get_kr_baselines
                baselines = get_kr_baselines()
            else:
                from collector.valuation_signal import get_baselines
                baselines = get_baselines()
            if not baseline_snapshot:
                baseline_snapshot = build_baseline_snapshot(baselines)
            if not interpretation:
                interpretation = build_valuation_interpretation(today, baselines)
        except Exception as e:
            print(f'[valuation_signal] {region} fallback 실패: {e}')

    response = {
        'today': today,
        'history': history,
        'interpretation': interpretation,
        'baselines_5y': baseline_snapshot,
        'cached': False,
    }
    _val_sig_cache[cache_key] = response
    _val_sig_cache[f'ts_{region}_{days}'] = now
    return response


def _weekly_downsample(history: list[dict]) -> list[dict]:
    """daily history → 5거래일 평균 weekly. 라벨/문자열 필드는 마지막 값 유지."""
    if not history:
        return history
    bins: list[list[dict]] = []
    bucket: list[dict] = []
    for row in history:
        bucket.append(row)
        if len(bucket) >= 5:
            bins.append(bucket)
            bucket = []
    if bucket:
        bins.append(bucket)

    out = []
    numeric_keys = ('z_comp', 'z_cape', 'z_buffett', 'z_trend', 'z_per', 'z_erp', 'z_vix', 'z_dd',
                    'cape', 'buffett_ratio', 'price_vs_ma200', 'spy_per', 'erp', 'vix', 'dd_60d',
                    'earnings_yield', 'tnx_yield')
    for b in bins:
        last = b[-1]
        agg: dict = {'date': last['date'], 'region': last.get('region'), 'label': last.get('label')}
        for k in numeric_keys:
            vals = [r[k] for r in b if r.get(k) is not None]
            agg[k] = (sum(vals) / len(vals)) if vals else None
        out.append(agg)
    return out