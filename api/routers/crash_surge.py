import threading
from fastapi import APIRouter, Query
from database.repositories import (
    fetch_crash_surge_current, fetch_crash_surge_history,
    fetch_crash_surge_all, fetch_macro_closes, upsert_crash_surge,
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


@router.get('/direction')
def get_direction(region: str = Query('us')):
    """현재 net_score 기반 방향성 분석.

    과거에 비슷한 net_score 구간이었을 때 5/10/20일 후 실제 수익률 통계를 반환.
    """
    import numpy as np                                  # 수치 계산용
    region = _norm_region(region)

    # 최신 결과 조회
    current = fetch_crash_surge_current(region=region)  # 오늘의 crash/surge 결과
    if not current or current.get('net_score') is None:
        return None

    # 캐시가 만료되었으면 DB에서 다시 로드 (region 별 캐시키 분리)
    now = time.time()                                    # 현재 시각
    cache_key = f'_dir_cache_{region}'
    if (_dir_cache.get(f'cs_data_{region}') is None
            or (now - _dir_cache.get(f'loaded_at_{region}', 0)) > _CACHE_TTL):
        _dir_cache[f'cs_data_{region}'] = fetch_crash_surge_all(region=region)
        _dir_cache[f'macro_data_{region}'] = fetch_macro_closes(region=region)
        _dir_cache[f'loaded_at_{region}'] = now
    _dir_cache['cs_data'] = _dir_cache[f'cs_data_{region}']
    _dir_cache['macro_data'] = _dir_cache[f'macro_data_{region}']
    _dir_cache['loaded_at'] = _dir_cache[f'loaded_at_{region}']

    all_data = _dir_cache['cs_data']                     # 캐시에서 가져옴
    if not all_data or len(all_data) < 30:
        return {'current_net_score': current.get('net_score'), 'message': '백필 데이터 부족'}

    # 날짜순 정렬 (오름차순)
    all_data.sort(key=lambda x: x['date'])              # 날짜 오름차순 정렬

    # net_score와 날짜 추출
    dates = [r['date'] for r in all_data]               # 날짜 리스트
    net_scores = [r.get('net_score', 0) or 0 for r in all_data]  # net_score 리스트

    # SPY 종가 (캐시에서 가져옴)
    macro_rows = _dir_cache['macro_data']                # 캐시된 macro 데이터
    if not macro_rows:
        return {'current_net_score': current.get('net_score'), 'message': 'macro 데이터 부족'}

    # macro_raw를 날짜 → 종가 딕셔너리로 변환
    close_map = {r['date']: r.get('sp500_close') for r in macro_rows if r.get('sp500_close')}

    # 현재 net_score 기준 ±5 범위 구간 설정
    cur_net = current.get('net_score', 0)               # 오늘의 net_score
    margin = 1.0                                        # ±1 범위로 유사 구간 탐색

    # 유사 구간에서의 미래 수익률 통계 계산
    results = {}                                         # 5/10/20일 후 결과
    for horizon in [5, 10, 20]:                          # 5일, 10일, 20일 후
        future_returns = []                              # 미래 수익률 리스트
        for i, ns in enumerate(net_scores):              # 전체 기간 순회
            # 현재와 비슷한 net_score 구간인지 확인
            if abs(ns - cur_net) > margin:               # 범위 밖이면 건너뜀
                continue
            # horizon일 후 날짜 찾기
            if i + horizon >= len(dates):                # 미래 데이터 없으면 건너뜀
                continue
            cur_date = dates[i]                          # 기준 날짜
            fut_date = dates[min(i + horizon, len(dates) - 1)]  # 미래 날짜
            cur_close = close_map.get(cur_date)          # 기준일 종가
            fut_close = close_map.get(fut_date)          # 미래일 종가
            if cur_close and fut_close and cur_close > 0:  # 종가가 유효할 때만
                ret = (fut_close - cur_close) / cur_close * 100  # 수익률 %
                future_returns.append(ret)

        if future_returns:                               # 유사 구간이 있으면
            arr = np.array(future_returns)               # numpy 배열로 변환
            results[f'{horizon}d'] = {
                'avg_return': round(float(arr.mean()), 2),     # 평균 수익률
                'median_return': round(float(np.median(arr)), 2),  # 중앙값 수익률
                'up_ratio': round(float((arr > 0).mean()) * 100, 1),  # 상승 비율 %
                'sample_count': len(arr),                # 유사 구간 횟수
            }

    # 방향 판정
    if '10d' in results:                                 # 10일 기준으로 판정
        up_ratio = results['10d']['up_ratio']            # 상승 비율
        if up_ratio >= 60:
            direction = '상승 우세'                       # 60% 이상이면 상승
        elif up_ratio <= 40:
            direction = '하락 우세'                       # 40% 이하면 하락
        else:
            direction = '방향 불명'                       # 그 사이는 불명
    else:
        direction = '데이터 부족'

    # 백분위 계산: 현재 net_score가 과거 대비 어느 위치인지
    all_net = np.array(net_scores)                       # 전체 net_score 배열
    percentile = round(float((all_net < cur_net).mean()) * 100, 1)  # 현재보다 낮은 비율

    return {
        'current_net_score': cur_net,                    # 현재 순방향 점수
        'net_score_percentile': percentile,              # 백분위 (0~100, 높을수록 상승 쪽)
        'direction': direction,                          # 방향 판정
        'horizon_stats': results,                        # 5/10/20일 통계
        'margin': margin,                                # 탐색 범위
    }


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
