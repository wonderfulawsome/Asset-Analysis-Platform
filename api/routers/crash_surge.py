from fastapi import APIRouter
from database.repositories import fetch_crash_surge_current, fetch_crash_surge_history, fetch_crash_surge_all, fetch_macro_closes

router = APIRouter()


@router.get('/current')
def get_current():
    """최신 폭락/급등 전조 신호 조회."""
    return fetch_crash_surge_current()


@router.get('/history')
def get_history(days: int = 30):
    """최근 N일 폭락/급등 전조 히스토리."""
    return fetch_crash_surge_history(days)


@router.get('/direction')
def get_direction():
    """현재 net_score 기반 방향성 분석.

    과거에 비슷한 net_score 구간이었을 때 5/10/20일 후 실제 수익률 통계를 반환.
    """
    import numpy as np                                  # 수치 계산용

    # 최신 결과 조회
    current = fetch_crash_surge_current()               # 오늘의 crash/surge 결과
    if not current or current.get('net_score') is None:
        return None

    # 전체 히스토리 조회
    all_data = fetch_crash_surge_all()                  # 전체 기간 데이터
    if not all_data or len(all_data) < 30:
        return {'current_net_score': current.get('net_score'), 'message': '백필 데이터 부족'}

    # 날짜순 정렬 (오름차순)
    all_data.sort(key=lambda x: x['date'])              # 날짜 오름차순 정렬

    # net_score와 날짜 추출
    dates = [r['date'] for r in all_data]               # 날짜 리스트
    net_scores = [r.get('net_score', 0) or 0 for r in all_data]  # net_score 리스트

    # SPY 종가를 macro_raw에서 가져옴 (crash_surge_result에는 없으므로)
    macro_rows = fetch_macro_closes()                    # 전체 SPY 종가 조회 (방향성 분석용)
    if not macro_rows:
        return {'current_net_score': current.get('net_score'), 'message': 'macro 데이터 부족'}

    # macro_raw를 날짜 → 종가 딕셔너리로 변환
    close_map = {r['date']: r.get('sp500_close') for r in macro_rows if r.get('sp500_close')}

    # 현재 net_score 기준 ±5 범위 구간 설정
    cur_net = current.get('net_score', 0)               # 오늘의 net_score
    margin = 7.0                                        # ±7 범위로 유사 구간 탐색

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

    return {
        'current_net_score': cur_net,                    # 현재 순방향 점수
        'direction': direction,                          # 방향 판정
        'horizon_stats': results,                        # 5/10/20일 통계
        'margin': margin,                                # 탐색 범위
    }
