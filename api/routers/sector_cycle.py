from fastapi import APIRouter
from database.repositories import fetch_sector_cycle_latest, fetch_sector_cycle_history

router = APIRouter()


@router.get('/current')
def get_current():
    """최신 경기국면 분석 결과 조회"""
    return fetch_sector_cycle_latest()


@router.get('/holdings-perf')
def get_holdings_perf(tickers: str = 'QQQ,SPY'):
    """사용자 보유종목의 국면별 성과 조회"""
    data = fetch_sector_cycle_latest()
    if not data:
        return None
    ticker_list = [t.strip().upper() for t in tickers.split(',') if t.strip()]
    full_perf = data.get('phase_holding_perf', {})
    filtered = {}
    for phase, perfs in full_perf.items():
        filtered[phase] = {t: perfs[t] for t in ticker_list if t in perfs}
    return {
        'phase_name': data['phase_name'],
        'phase_emoji': data['phase_emoji'],
        'phase_holding_perf': filtered,
    }


@router.get('/history')
def get_history(days: int = 12):
    """최근 N건 경기국면 히스토리 조회"""
    return fetch_sector_cycle_history(days)
