import threading
from fastapi import APIRouter, Query
from database.repositories import (
    fetch_crash_surge_current, fetch_crash_surge_history,
    fetch_crash_surge_all, fetch_macro_closes, upsert_crash_surge,
    upsert_app_cache, fetch_app_cache,
)
import time                                              # 캐시 만료 체크용

router = APIRouter()


def _norm_region(region: str) -> str:
    return region if region in ('us', 'kr') else 'us'


# ── 수동 새로고침 상태 관리 ──
_refresh_running = False

# ── 방향성 분석 캐시 (매번 DB 조회 방지) ──
_dir_cache = {                                           # 캐시 딕셔너리
    'cs_data': None,                                     # crash_surge 전체 데이터
    'macro_data': None,                                  # macro 종가 데이터
    'loaded_at': 0,                                      # 마지막 로드 시각
}
_CACHE_TTL = 1800                                        # 캐시 유효 시간 30분 (초)


@router.get('/current')
def get_current(region: str = Query('us')):
    """최신 폭락/급등 전조 신호 조회."""
    return fetch_crash_surge_current(region=_norm_region(region))


@router.get('/history')
def get_history(days: int = 30, region: str = Query('us')):
    """최근 N일 폭락/급등 전조 히스토리."""
    return fetch_crash_surge_history(days, region=_norm_region(region))


def _direction_cache_key(region: str) -> str:
    return f'crash_surge_direction_{region}'


def _compute_direction_payload(region: str) -> dict | None:
    """현재 net_score 기반 방향성 분석 페이로드.
    전체 crash_surge + macro 시계열을 numpy 로 처리. precompute / fallback 공용."""
    import numpy as np
    region = _norm_region(region)
    current = fetch_crash_surge_current(region=region)
    if not current or current.get('net_score') is None:
        return None

    all_data = fetch_crash_surge_all(region=region)
    if not all_data or len(all_data) < 30:
        return {'current_net_score': current.get('net_score'), 'message': '백필 데이터 부족'}

    macro_rows = fetch_macro_closes(region=region)
    if not macro_rows:
        return {'current_net_score': current.get('net_score'), 'message': 'macro 데이터 부족'}

    all_data.sort(key=lambda x: x['date'])
    dates = [r['date'] for r in all_data]
    net_scores = [r.get('net_score', 0) or 0 for r in all_data]
    close_map = {r['date']: r.get('sp500_close') for r in macro_rows if r.get('sp500_close')}

    cur_net = current.get('net_score', 0)
    margin = 1.0

    results = {}
    for horizon in [5, 10, 20]:
        future_returns = []
        for i, ns in enumerate(net_scores):
            if abs(ns - cur_net) > margin:
                continue
            if i + horizon >= len(dates):
                continue
            cur_date = dates[i]
            fut_date = dates[min(i + horizon, len(dates) - 1)]
            cur_close = close_map.get(cur_date)
            fut_close = close_map.get(fut_date)
            if cur_close and fut_close and cur_close > 0:
                ret = (fut_close - cur_close) / cur_close * 100
                future_returns.append(ret)
        if future_returns:
            arr = np.array(future_returns)
            results[f'{horizon}d'] = {
                'avg_return': round(float(arr.mean()), 2),
                'median_return': round(float(np.median(arr)), 2),
                'up_ratio': round(float((arr > 0).mean()) * 100, 1),
                'sample_count': len(arr),
            }

    if '10d' in results:
        up_ratio = results['10d']['up_ratio']
        if up_ratio >= 60:
            direction = '상승 우세'
        elif up_ratio <= 40:
            direction = '하락 우세'
        else:
            direction = '방향 불명'
    else:
        direction = '데이터 부족'

    all_net = np.array(net_scores)
    percentile = round(float((all_net < cur_net).mean()) * 100, 1)

    return {
        'current_net_score': cur_net,
        'net_score_percentile': percentile,
        'direction': direction,
        'horizon_stats': results,
        'margin': margin,
    }


def precompute_direction(region: str) -> bool:
    """스케줄러용 — direction 페이로드를 app_cache 에 적재.
    매번 클릭마다 numpy 루프 돌던 것을 1회/일 cron 으로 격리."""
    payload = _compute_direction_payload(region)
    if not payload:
        return False
    upsert_app_cache(_direction_cache_key(region), payload)
    return True


@router.get('/direction')
def get_direction(region: str = Query('us')):
    """현재 net_score 기반 방향성 분석. app_cache 우선, miss 시 라이브 폴백.

    과거에 비슷한 net_score 구간이었을 때 5/10/20일 후 실제 수익률 통계를 반환.
    """
    region = _norm_region(region)
    cached = fetch_app_cache(_direction_cache_key(region))
    if cached and isinstance(cached, dict):
        return {**cached, 'cached': True}
    return _compute_direction_payload(region)


@router.get('/refresh')
def refresh_crash_surge():
    """수동으로 crash/surge 예측을 재실행한다.
    스케줄러가 실패했을 때 데이터를 복구하기 위한 엔드포인트."""
    global _refresh_running
    if _refresh_running:
        return {'status': 'already_running'}

    _refresh_running = True
    try:
        import numpy as np
        from collector.crash_surge_data import (
            fetch_crash_surge_light, compute_features,
            ALL_FEATURES, CORE_FEATURES, AUX_FEATURES,
        )
        from processor.feature3_crash_surge import (
            load_model as load_crash_surge_model, predict_crash_surge,
        )

        cs_model = load_crash_surge_model()
        if cs_model is None:
            return {'status': 'error', 'message': 'no model available'}

        raw = fetch_crash_surge_light()
        features = compute_features(raw['spy'], raw['fred'], raw['cboe'], raw['yahoo_macro'])
        feat_row = features[ALL_FEATURES].copy()
        feat_row = feat_row.ffill()
        feat_row = feat_row.dropna(subset=CORE_FEATURES)
        feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)
        feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)

        if len(feat_row) == 0:
            return {'status': 'error', 'message': 'no valid feature rows'}

        latest_row = feat_row.iloc[[-1]].values
        result = predict_crash_surge(latest_row, cs_model)
        upsert_crash_surge(result)

        return {'status': 'ok', 'date': result.get('date'),
                'crash_score': result.get('crash_score'),
                'surge_score': result.get('surge_score')}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
    finally:
        _refresh_running = False
