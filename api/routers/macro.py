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
너는 한국어 금융 해설가다. 주어진 composite z-score 결과를 일반 투자자가
이해하도록 한 단락(2~3문장)으로 해설하라.

배경 지식:
- z_comp = 0.4·z_ERP + 0.3·z_VIX + 0.3·z_DD60 (가중 합성, 최근 5년 분포 기준)
- z_ERP: 주식 기대수익(1/PER) − 10년 국채 yield 의 z-score (ERP↑ → z↑)
- z_VIX: 공포지수 z-score (VIX↑ → z↑, 공포는 contrarian 저평가 신호)
- z_DD : SPY 60일 drawdown z-score (drawdown 깊을수록 z↑)
- z > +1: 명확한 저평가 / 0~+1: 다소 저평가 / -1~0: 다소 고평가 / z<-1: 명확한 고평가
- ERP 단독으로는 가격 충격에 둔감 → 공포·드로다운 합성으로 위기 reactive 신호 보강

설명할 내용:
1. 현재 z_comp 가 의미하는 것 — 어느 component 가 dominant 한지 한 줄 (예: "VIX↓·DD 작아 ERP 음수가 끌어내림")
2. 투자자에게 어떤 액션 (한 문장)
규칙:
- 2~3문장, 총 160자 이내
- 부드럽고 구체적인 어투
- "z_comp=X.X (z_ERP a, z_VIX b, z_DD c)" 한 번 언급
- 마크다운 금지"""

_val_sig_cache = {'data': None, 'ts': 0}
_VAL_SIG_TTL = 24 * 3600


@router.get('/valuation-signal')
def get_valuation_signal():
    """오늘 composite z + 60일 history + LLM 해설 (24h 캐시)."""
    now = _time.time()
    cached = _val_sig_cache['data']
    if cached and (now - _val_sig_cache['ts']) < _VAL_SIG_TTL:
        return {**cached, 'cached': True}

    today = fetch_valuation_signal_latest()
    history = fetch_valuation_signal_history(days=60)

    # composite z 가 비어있는 (legacy) 행이 있으면 backfill 강제
    needs_backfill = (
        not today
        or len(history) < 60
        or today.get('z_comp') is None
        or any(h.get('z_comp') is None for h in history)
    )
    if needs_backfill:
        from collector.valuation_signal import (
            fetch_valuation_signal_today, backfill_valuation_signal,
        )
        backfill = backfill_valuation_signal(days=60)
        if backfill:
            upsert_valuation_signal_bulk(backfill)
        rec_today = fetch_valuation_signal_today()
        if rec_today:
            upsert_valuation_signal(rec_today)
            today = rec_today
        history = fetch_valuation_signal_history(days=60)

    if not today:
        return {'error': 'no data'}

    from collector.valuation_signal import get_baselines
    baselines = get_baselines()

    z_comp_now = today.get('z_comp') or 0.0

    # LLM 해설 (Groq)
    try:
        from api.routers.market_summary import _groq_call
        import json as _json
        user_text = _json.dumps({
            'today': {k: today.get(k) for k in (
                'date', 'spy_per', 'earnings_yield', 'tnx_yield', 'erp',
                'vix', 'dd_60d', 'z_erp', 'z_vix', 'z_dd', 'z_comp', 'label',
            )},
            'baselines_5y': {
                'erp_mean_pct': round(baselines['erp']['mean'] * 100, 2),
                'erp_std_pct':  round(baselines['erp']['std']  * 100, 2),
                'vix_mean':     round(baselines['vix']['mean'], 2),
                'vix_std':      round(baselines['vix']['std'], 2),
                'dd_mean_pct':  round(baselines['dd']['mean']  * 100, 2),
                'dd_std_pct':   round(baselines['dd']['std']   * 100, 2),
                'weights': baselines.get('weights', {'erp': 0.4, 'vix': 0.3, 'dd': 0.3}),
            },
            'history_summary': {
                'days': len(history),
                'z_comp_min_60d': min((h.get('z_comp') or 0) for h in history) if history else None,
                'z_comp_max_60d': max((h.get('z_comp') or 0) for h in history) if history else None,
            },
        }, ensure_ascii=False, indent=2)
        interpretation = _groq_call(_VAL_SIG_PROMPT, user_text, max_tokens=240)
    except Exception as e:
        print(f'[valuation_signal] LLM 실패: {e}')
        interpretation = None

    if not interpretation:
        label = today.get('label', '')
        ze, zv, zd = today.get('z_erp', 0), today.get('z_vix', 0), today.get('z_dd', 0)
        if '저평가' in label:
            interpretation = (f"composite z={z_comp_now:+.2f}σ (ERP {ze:+.2f} · VIX {zv:+.2f} · DD {zd:+.2f}) — "
                              "5년 분포 대비 매력적 구간. 분할 매수 검토.")
        elif '명확한 고평가' in label:
            interpretation = (f"composite z={z_comp_now:+.2f}σ (ERP {ze:+.2f} · VIX {zv:+.2f} · DD {zd:+.2f}) — "
                              "5년 분포 대비 비싼 구간. 현금·채권 비중 검토.")
        else:
            interpretation = (f"composite z={z_comp_now:+.2f}σ (ERP {ze:+.2f} · VIX {zv:+.2f} · DD {zd:+.2f}) — "
                              "평균 부근. 큰 포지션 변경보다 관망.")

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