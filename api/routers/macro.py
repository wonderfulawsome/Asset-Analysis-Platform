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
너는 한국어 금융 해설가다. 주어진 시장 평가 점수를 **일반 투자자**가 이해하도록
2~3문장으로 부드럽게 풀어 설명하라.

배경:
- 종합 점수 = 주식 매력도(40%) + 공포 점수(30%) + 하락 충격 점수(30%) 의 가중합.
  비교 기준은 "최근 5년 평균"
- 점수 > +1.0 = 명확한 저평가 (매수 기회) / 0 ~ +1.0 = 다소 저평가
- -1.0 ~ 0 = 다소 고평가 / -1.0 미만 = 명확한 고평가 (조심)
- 세 점수 모두 양수면 매수 기회 신호, 음수면 비싼 구간 신호

각 점수 의미:
- "주식 매력도 점수": 양수면 평소보다 쌈, 음수면 평소보다 비쌈
- "공포 점수": 양수면 평소보다 시장이 불안 (역설적으로 매수 기회 가능)
- "하락 충격 점수": 양수면 평소보다 큰 낙폭 (역시 매수 기회 가능)

설명할 내용:
1. 현재 종합 점수가 어느 영역인지 + 어느 하위 점수가 가장 영향 크게 줬는지
   (예: "주식 매력도 점수가 깎여 종합이 낮아짐")
2. 투자자에게 한 줄 액션 (관망 / 분할 매수 / 채권 비중 늘리기 등)

규칙:
- 2~3문장, 총 160자 이내
- 친근하지만 구체적인 어투. 공식·약어(z, σ, ERP, VIX) **금지**
- 한 번은 "종합 점수 X.XX점" 처럼 점수 수치 언급
- 마크다운·이모지 금지"""

_val_sig_cache = {'data': None, 'ts': 0}
_VAL_SIG_TTL = 24 * 3600


@router.get('/valuation-signal')
def get_valuation_signal():
    """오늘 composite z + 60일 history + LLM 해설 (24h 캐시).

    안전망: DB 스키마 미마이그레이션·yfinance 차단 등 예상 가능한 환경 차이로
    인한 실패는 500 대신 `{'error': '...'}` JSON 으로 반환.
    """
    now = _time.time()
    cached = _val_sig_cache['data']
    if cached and (now - _val_sig_cache['ts']) < _VAL_SIG_TTL:
        return {**cached, 'cached': True}

    try:
        today = fetch_valuation_signal_latest()
        history = fetch_valuation_signal_history(days=60)
    except Exception as e:
        print(f'[valuation_signal] DB fetch 실패: {e}')
        return {'error': f'DB fetch failed: {type(e).__name__}: {str(e)[:200]}'}

    # composite z 가 비어있는 (legacy) 행이 있으면 backfill 강제
    needs_backfill = (
        not today
        or len(history) < 60
        or today.get('z_comp') is None
        or any(h.get('z_comp') is None for h in history)
    )
    if needs_backfill:
        try:
            from collector.valuation_signal import (
                fetch_valuation_signal_today, backfill_valuation_signal,
            )
            backfill = backfill_valuation_signal(days=60)
            if backfill:
                try:
                    upsert_valuation_signal_bulk(backfill)
                except Exception as e:
                    # DB 컬럼 부재 등 마이그레이션 미완료 가능성
                    print(f'[valuation_signal] bulk upsert 실패 (DDL 미실행 의심): {e}')
                    return {
                        'error': 'schema_outdated',
                        'detail': f'DB 컬럼 누락 추정. supabase_tables.sql 의 ALTER TABLE 6컬럼 실행 필요. ({type(e).__name__}: {str(e)[:200]})',
                    }
            rec_today = fetch_valuation_signal_today()
            if rec_today:
                try:
                    upsert_valuation_signal(rec_today)
                except Exception as e:
                    print(f'[valuation_signal] today upsert 실패: {e}')
                today = rec_today
            history = fetch_valuation_signal_history(days=60)
        except Exception as e:
            print(f'[valuation_signal] backfill 실패: {e}')
            return {'error': f'backfill failed: {type(e).__name__}: {str(e)[:200]}'}

    if not today:
        return {'error': 'no data'}

    try:
        from collector.valuation_signal import get_baselines
        baselines = get_baselines()
    except Exception as e:
        print(f'[valuation_signal] baseline 실패: {e}')
        return {'error': f'baseline failed: {type(e).__name__}: {str(e)[:200]}'}

    z_comp_now = today.get('z_comp') or 0.0

    # LLM 해설 (Groq) — 평어 키로 입력 데이터 정제 (LLM 이 자연스럽게 평어로 답하도록)
    ze = today.get('z_erp')   or 0.0
    zv = today.get('z_vix')   or 0.0
    zd = today.get('z_dd')    or 0.0
    try:
        from api.routers.market_summary import _groq_call
        import json as _json
        user_text = _json.dumps({
            '오늘': {
                '종합_점수':           round(z_comp_now, 2),
                '라벨':                today.get('label'),
                '주식_매력도_점수':    round(ze, 2),
                '공포_점수':           round(zv, 2),
                '하락_충격_점수':      round(zd, 2),
                '주식_매력도_원본_pct': round((today.get('erp') or 0) * 100, 2),
                '공포지수_VIX':        today.get('vix'),
                '60일_하락폭_pct':     round((today.get('dd_60d') or 0) * 100, 2),
            },
            '최근_5년_평균': {
                '주식_매력도_pct': round(baselines['erp']['mean'] * 100, 2),
                '공포지수':        round(baselines['vix']['mean'], 2),
                '60일_하락폭_pct': round(baselines['dd']['mean']  * 100, 2),
            },
            '60일_종합점수_범위': {
                '최저': round(min((h.get('z_comp') or 0) for h in history), 2) if history else None,
                '최고': round(max((h.get('z_comp') or 0) for h in history), 2) if history else None,
            },
        }, ensure_ascii=False, indent=2)
        interpretation = _groq_call(_VAL_SIG_PROMPT, user_text, max_tokens=240)
    except Exception as e:
        print(f'[valuation_signal] LLM 실패: {e}')
        interpretation = None

    if not interpretation:
        # 평어 fallback
        label = today.get('label', '')
        # 어느 component 가 가장 dominant 한지 자동 판별
        contribs = {
            '주식 매력도': abs(ze * 0.4),
            '공포':        abs(zv * 0.3),
            '하락 충격':   abs(zd * 0.3),
        }
        dom = max(contribs, key=contribs.get)
        if '명확한 저평가' in label:
            interpretation = (f"종합 점수 {z_comp_now:+.2f}점 — 5년 평균보다 매력적인 구간이에요. "
                              f"{dom} 점수가 가장 크게 긍정 기여. 분할 매수를 고려해 보세요.")
        elif '다소 저평가' in label:
            interpretation = (f"종합 점수 {z_comp_now:+.2f}점 — 평균보다 살짝 매력적입니다. "
                              f"{dom} 점수가 주로 끌어올렸어요. 큰 베팅보다 관심 종목을 조금씩 담아보는 정도가 적절합니다.")
        elif '명확한 고평가' in label:
            interpretation = (f"종합 점수 {z_comp_now:+.2f}점 — 5년 평균 대비 비싼 구간입니다. "
                              f"{dom} 점수가 깎여 종합이 낮아졌어요. 현금이나 채권 비중을 늘리는 방어 전략을 고려하세요.")
        else:
            interpretation = (f"종합 점수 {z_comp_now:+.2f}점 — 다소 고평가된 상황이에요. "
                              f"{dom} 점수가 주된 원인입니다. 관망하거나 방어적인 포지션을 고려해 보세요.")

    response = {
        'today': today,
        'history': history,
        'interpretation': interpretation,
        'baselines_5y': {
            'erp':     baselines['erp'],
            'vix':     baselines['vix'],
            'dd':      baselines['dd'],
            'weights': baselines.get('weights', {'erp': 0.4, 'vix': 0.3, 'dd': 0.3}),
        },
        'cached': False,
    }
    _val_sig_cache['data'] = response
    _val_sig_cache['ts'] = now
    return response