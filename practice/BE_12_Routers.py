# ============================================================
# BE_12_Routers — FastAPI 라우터 6개 통합 빈칸 연습
# 원본: api/routers/*.py (regime, macro, index_feed, sector_cycle, crash_surge, market_summary)
# 총 빈칸: 50개
# ============================================================
# `___` 빈칸을 채워서 코드를 완성하세요.

from fastapi import ___                                  # Q1

# ══════════════════════════════════════════════════════════════
# 1) regime.py — Noise vs Signal 국면 라우터
# ══════════════════════════════════════════════════════════════
from database.repositories import fetch_noise_regime_current, ___  # Q2

regime_router = ___()                                    # Q3

@regime_router.get('/___')                               # Q4
def regime_get_current():
    """현재 Noise vs Signal 국면 (단일 객체 반환)."""
    return ___()                                         # Q5

@regime_router.get('/___')                               # Q6
def regime_get_history(days: int = ___):                  # Q7
    """최근 N일 국면 히스토리."""
    return fetch_noise_regime_history(___)                # Q8


# ══════════════════════════════════════════════════════════════
# 2) index_feed.py — ETF 가격 라우터
# ══════════════════════════════════════════════════════════════
from database.repositories import ___                    # Q9

index_router = APIRouter()

@index_router.get('/___')                                # Q10
def get_index_latest():
    """DB에서 가장 최근 날짜의 ETF 가격/등락률 조회."""
    return ___()                                         # Q11


# ══════════════════════════════════════════════════════════════
# 3) sector_cycle.py — 섹터 경기국면 라우터
# ══════════════════════════════════════════════════════════════
from database.repositories import fetch_sector_cycle_latest, ___  # Q12

sector_router = APIRouter()

@sector_router.get('/current')
def sector_get_current():
    """최신 경기국면 분석 결과 조회."""
    return ___()                                         # Q13

@sector_router.get('/___')                               # Q14
def get_holdings_perf(tickers: str = '___'):              # Q15
    """사용자 보유종목의 국면별 성과 조회."""
    data = fetch_sector_cycle_latest()
    if not data:
        return ___                                       # Q16
    ticker_list = [t.strip().___() for t in tickers.split(',') if t.strip()]  # Q17
    full_perf = data.get('___', {})                      # Q18
    filtered = {}
    for phase, perfs in full_perf.___():                 # Q19
        filtered[phase] = {t: perfs[t] for t in ticker_list if t in perfs}
    return {
        '___': data['phase_name'],                       # Q20
        '___': data['phase_emoji'],                      # Q21
        'phase_holding_perf': filtered,
    }

@sector_router.get('/history')
def sector_get_history(days: int = ___):                  # Q22
    return fetch_sector_cycle_history(days)


# ══════════════════════════════════════════════════════════════
# 4) crash_surge.py — 폭락/급등 전조 라우터
# ══════════════════════════════════════════════════════════════
from database.repositories import fetch_crash_surge_current, ___, fetch_crash_surge_all, ___  # Q23~Q24
import ___                                              # Q25

crash_router = APIRouter()

# 방향성 분석 캐시
_dir_cache = {
    'cs_data': ___,                                      # Q26
    'macro_data': None,
    'loaded_at': ___,                                    # Q27
}
_CACHE_TTL = ___                                         # Q28

@crash_router.get('/current')
def crash_get_current():
    return ___()                                         # Q29

@crash_router.get('/history')
def crash_get_history(days: int = ___):                   # Q30
    return fetch_crash_surge_history(___)                 # Q31

@crash_router.get('/___')                                # Q32
def get_direction():
    """현재 net_score 기반 방향성 분석."""
    import numpy as np
    current = fetch_crash_surge_current()
    if not current or current.get('___') is None:         # Q33
        return None

    # 캐시 만료 확인
    now = time.___()                                     # Q34
    if _dir_cache['cs_data'] is None or (now - _dir_cache['___']) > _CACHE_TTL:  # Q35
        _dir_cache['cs_data'] = fetch_crash_surge_all()
        _dir_cache['macro_data'] = fetch_macro_closes()
        _dir_cache['loaded_at'] = ___                    # Q36

    cur_net = current.get('net_score', 0)
    margin = ___                                         # Q37

    # 유사 구간 분석 (5/10/20일 후 수익률)
    results = {}
    for horizon in [5, ___, ___]:                         # Q38~Q39

        # ... 수익률 통계 계산 로직 ...
        pass

    # 방향 판정 (10일 기준)
    if '10d' in results:
        up_ratio = results['10d']['___']                  # Q40
        if up_ratio >= ___:                               # Q41
            direction = '상승 우세'
        elif up_ratio <= ___:                             # Q42
            direction = '하락 우세'
        else:
            direction = '방향 불명'
    else:
        direction = '데이터 부족'

    return {'current_net_score': cur_net, 'direction': direction}


# ══════════════════════════════════════════════════════════════
# 5) market_summary.py — 마켓 오버뷰 라우터
# ══════════════════════════════════════════════════════════════
from database.repositories import fetch_fear_greed_latest, ___, fetch_macro_latest  # Q43
import yfinance as ___                                   # Q44

summary_router = APIRouter()

def _calc_rsi(period: int = ___) -> float:               # Q45
    """SPY 종가 기반 RSI(14) 실시간 계산."""
    try:
        df = yf.download('___', period='2mo', progress=False)  # Q46
        close = df['Close'].squeeze()
        delta = close.___()                              # Q47
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + ___))                    # Q48
        return round(float(rsi.iloc[___]), 1)             # Q49
    except Exception:
        return 0

@summary_router.get('/today')
def get_market_summary_today():
    fg = fetch_fear_greed_latest()
    prices = fetch_index_prices_latest()
    score = fg.get('___', 0) if fg else 0                # Q50
    target = {'SPY', 'QQQ', '___'}                       # Q51
    changes = [p['___'] for p in prices if p['ticker'] in target]  # Q52
    avg_return = sum(changes) / ___(changes) if changes else 0  # Q53
    return {
        'fear_greed': {'score': round(score), 'rating': fg.get('rating', '-') if fg else '-'},
        'market_return': {'value': round(avg_return, 2)},
    }


# ============================================================
# 정답표
# ============================================================
# | Q  | 빈칸                          | 정답                    |
# |----|-------------------------------|------------------------|
# | Q1 | from fastapi import ___       | APIRouter              |
# | Q2 | import ___                    | fetch_noise_regime_history |
# | Q3 | ___()                         | APIRouter              |
# | Q4 | '/___'                        | current                |
# | Q5 | ___()                         | fetch_noise_regime_current |
# | Q6 | '/___'                        | history                |
# | Q7 | days: int = ___               | 30                     |
# | Q8 | (___) 인자                    | days                   |
# | Q9 | import ___                    | fetch_index_prices_latest |
# | Q10| '/___'                        | latest                 |
# | Q11| ___()                         | fetch_index_prices_latest |
# | Q12| import ___                    | fetch_sector_cycle_history |
# | Q13| ___()                         | fetch_sector_cycle_latest |
# | Q14| '/___'                        | holdings-perf          |
# | Q15| '___'                         | QQQ,SPY                |
# | Q16| return ___                    | None                   |
# | Q17| .___()                        | upper                  |
# | Q18| .get('___', {})               | phase_holding_perf     |
# | Q19| .___()                        | items                  |
# | Q20| '___'                         | phase_name             |
# | Q21| '___'                         | phase_emoji            |
# | Q22| days: int = ___               | 12                     |
# | Q23| import ___                    | fetch_crash_surge_history |
# | Q24| import ___                    | fetch_macro_closes     |
# | Q25| import ___                    | time                   |
# | Q26| 'cs_data': ___                | None                   |
# | Q27| 'loaded_at': ___              | 0                      |
# | Q28| _CACHE_TTL = ___              | 1800                   |
# | Q29| ___()                         | fetch_crash_surge_current |
# | Q30| days: int = ___               | 30                     |
# | Q31| (___) 인자                    | days                   |
# | Q32| '/___'                        | direction              |
# | Q33| .get('___')                   | net_score              |
# | Q34| time.___()                    | time                   |
# | Q35| ['___']                       | loaded_at              |
# | Q36| = ___                         | now                    |
# | Q37| margin = ___                  | 1.0                    |
# | Q38| ___                           | 10                     |
# | Q39| ___                           | 20                     |
# | Q40| ['___']                       | up_ratio               |
# | Q41| >= ___                        | 60                     |
# | Q42| <= ___                        | 40                     |
# | Q43| import ___                    | fetch_index_prices_latest |
# | Q44| as ___                        | yf                     |
# | Q45| period: int = ___             | 14                     |
# | Q46| '___'                         | SPY                    |
# | Q47| .___()                        | diff                   |
# | Q48| 1 + ___                       | rs                     |
# | Q49| .iloc[___]                    | -1                     |
# | Q50| .get('___', 0)                | score                  |
# | Q51| '___'                         | DIA                    |
# | Q52| p['___']                      | change_pct             |
# | Q53| ___(changes)                  | len                    |
# ============================================================
