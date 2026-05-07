"""시장 이상 탐지 (Anomaly Detection) API.

신호 탭 교체용 endpoint. anomaly_daily 테이블에서 read-only 조회만 — 계산은
스케줄러가 매일 1회 수행 (compute_today_anomaly).

자문 리스크 차단을 위해 응답은 모두 descriptive 필드 (D², percentile, contributors,
유사 과거 시점). "예측", "위험", "권장" 류 단어 미포함.
"""
from fastapi import APIRouter, Query
from database.repositories import fetch_anomaly_current, fetch_anomaly_history

router = APIRouter()


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'


@router.get('/current')
def get_current(region: str = Query('us')):
    """오늘의 이상도 단일 row.

    응답: {date, d2, percentile_10y, percentile_90d, feature_vector,
           top_contributors[], knn_dates[], n_history, region}
    빈 결과면 {empty: True} 반환.
    """
    region = _norm_region(region)
    row = fetch_anomaly_current(region=region)
    if not row:
        return {'empty': True, 'region': region}
    return {**row, 'region': region}


@router.get('/history')
def get_history(days: int = Query(2520, ge=30, le=4000), region: str = Query('us')):
    """이상도 D² 시계열 (차트용). default 2520 ≈ 10년 거래일.

    응답: {region, days_requested, count, series: [{date, d2, percentile_10y, percentile_90d}, ...]}
    """
    region = _norm_region(region)
    rows = fetch_anomaly_history(days=days, region=region)
    series = [
        {
            'date': r['date'],
            'd2': r.get('d2'),
            'percentile_10y': r.get('percentile_10y'),
            'percentile_90d': r.get('percentile_90d'),
        }
        for r in rows
    ]
    return {
        'region': region,
        'days_requested': days,
        'count': len(series),
        'series': series,
    }
