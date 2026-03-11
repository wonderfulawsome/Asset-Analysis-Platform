from fastapi import APIRouter
from database.repositories import fetch_noise_regime_current, fetch_noise_regime_history

router = APIRouter()


@router.get('/current')
def get_current():
    """현재 Noise vs Signal 국면 (단일 객체 반환)."""
    return fetch_noise_regime_current()


@router.get('/history')
def get_history(days: int = 30):
    """최근 N일 국면 히스토리."""
    return fetch_noise_regime_history(days)
