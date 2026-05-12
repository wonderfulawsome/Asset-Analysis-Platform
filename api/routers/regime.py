import json as _json
from fastapi import APIRouter, Query
from database.repositories import fetch_noise_regime_current, fetch_noise_regime_history

router = APIRouter()


def _norm_region(region: str) -> str:
    """region 파라미터 정규화 — 'us' 또는 'kr' 만 허용, 그 외는 'us' 폴백."""
    return region if region in ('us', 'kr') else 'us'


@router.get('/current')
def get_current(region: str = Query('us')):
    """현재 Noise vs Signal 국면 (단일 객체 반환)."""
    return fetch_noise_regime_current(region=_norm_region(region))


@router.get('/history')
def get_history(days: int = 30, region: str = Query('us')):
    """최근 N일 국면 히스토리."""
    return fetch_noise_regime_history(days, region=_norm_region(region))


@router.get('/fundamental-gap')
def get_fundamental_gap(region: str = Query('us'), days: int = Query(2520, ge=30, le=4000)):
    """fundamental_gap 시계열 + 오늘의 10년 분포 내 상위 N%.

    펀더멘털 갭 = log(P_t/P_{t-12}) - log(E_t/E_{t-12}). 양수=가격이 이익을 추월,
    0 근처=반영, 음수=가격이 이익을 따라가지 못함. 노이즈 8피처 중 하나 (feature_values JSONB).

    Returns:
        {
          'region': 'us'|'kr',
          'current': {'date', 'value', 'top_pct', 'top_abs_pct', 'sign'},
          'series': [{'date', 'value'}, ...]   # 일별 (forward-filled monthly value)
          'stats': {'min','max','mean','median'}
        }
    """
    import numpy as np
    region = _norm_region(region)
    rows = fetch_noise_regime_history(days=days, region=region)
    series = []
    for r in rows:
        fv = r.get('feature_values')
        if isinstance(fv, str):
            try:
                fv = _json.loads(fv)
            except Exception:
                continue
        if not isinstance(fv, dict):
            continue
        v = fv.get('fundamental_gap')
        if v is None:
            continue
        try:
            vf = float(v)
        except (TypeError, ValueError):
            continue
        # 옛 PER 평탄 fallback 산물 (E ∝ P → log diff = exact 0) 필터.
        # 부동소수 정밀도로 ±1e-6 까지는 fallback 판정. 실데이터는 보통 ±0.001 이상.
        if abs(vf) < 1e-6:
            continue
        series.append({'date': r['date'], 'value': vf})

    if not series:
        return {'region': region, 'current': None, 'series': [], 'stats': None}

    # rows 는 DB 에서 DESC 로 받음 → 차트용 ASC 정렬, current = 가장 최근.
    series.sort(key=lambda s: s['date'])
    values = np.array([s['value'] for s in series])
    cur = series[-1]
    cv = cur['value']
    # percentile 계산: 최근 2년 (거품 시기) 제외한 baseline 기준.
    # 이유: KR KOSPI 가 2024 중반부터 급등 — panel 후반 2년이 거의 모두 거품 영역.
    # 그 2년을 baseline 에 포함시키면 평균이 위로 끌어올려져 "오늘 +0.82" 가
    # 상위 41% 같은 둔감한 값으로 보이게 됨. 24개월 제외 시 상위 4% (직관 일치).
    import datetime as _dt
    try:
        last_date = _dt.date.fromisoformat(cur['date'])
        cutoff = (last_date - _dt.timedelta(days=730)).isoformat()
        baseline_vals = np.array([s['value'] for s in series if s['date'] < cutoff])
    except Exception:
        baseline_vals = values
    if len(baseline_vals) < 60:                     # 너무 짧으면 전체 사용
        baseline_vals = values
        baseline_window = 'all'
    else:
        baseline_window = 'pre-2y'
    top_pct = float((baseline_vals > cv).mean() * 100)
    top_abs_pct = float((np.abs(baseline_vals) > abs(cv)).mean() * 100)
    sign = 'bubble' if cv > 0 else ('compress' if cv < 0 else 'neutral')

    return {
        'region': region,
        'current': {
            'date': cur['date'],
            'value': round(cv, 4),
            'top_pct': round(top_pct, 1),
            'top_abs_pct': round(top_abs_pct, 1),
            'sign': sign,
            'baseline_window': baseline_window,         # 'pre-1y' (최근 1년 제외) | 'all'
            'baseline_n': int(len(baseline_vals)),
        },
        'series': series,
        'stats': {
            'min': round(float(values.min()), 4),
            'max': round(float(values.max()), 4),
            'mean': round(float(values.mean()), 4),
            'median': round(float(np.median(values)), 4),
            'count': int(len(values)),
            # baseline (percentile 기준) 통계
            'baseline_mean': round(float(baseline_vals.mean()), 4),
            'baseline_median': round(float(np.median(baseline_vals)), 4),
        },
    }


@router.get('/score-distribution')
def get_score_distribution(region: str = Query('us')):
    """시장 이성 점수(noise_score 컬럼) 전체 분포 통계 (게이지 기준점 튜닝용).

    부호 컨벤션 (2026-04-29~): 양수 = 이성, 음수 = 감정.
    """
    import numpy as np

    records = fetch_noise_regime_history(days=1000, region=_norm_region(region))
    scores = [r['noise_score'] for r in records
              if r.get('noise_score') is not None]

    if not scores:
        return {'error': 'no data'}

    arr = np.array(scores)

    # 국면별 분류
    by_regime = {}
    for r in records:
        ns = r.get('noise_score')
        name = r.get('regime_name')
        if ns is not None and name:
            by_regime.setdefault(name, []).append(ns)

    regime_stats = {}
    for name, vals in by_regime.items():
        a = np.array(vals)
        regime_stats[name] = {
            'count': len(a),
            'min': round(float(a.min()), 4),
            'max': round(float(a.max()), 4),
            'mean': round(float(a.mean()), 4),
            'median': round(float(np.median(a)), 4),
        }

    percentiles = {}
    for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        percentiles[f'P{p:02d}'] = round(float(np.percentile(arr, p)), 4)

    # 히스토그램 (0.5 간격)
    lo = float(int(arr.min()) - 1)
    hi = float(int(arr.max()) + 2)
    bins = np.arange(lo, hi + 0.5, 0.5)
    hist, edges = np.histogram(arr, bins=bins)
    histogram = [{'range': f'[{edges[i]:.1f}, {edges[i+1]:.1f})', 'count': int(hist[i])}
                 for i in range(len(hist)) if hist[i] > 0]

    return {
        'total_count': len(arr),
        'min': round(float(arr.min()), 4),
        'max': round(float(arr.max()), 4),
        'mean': round(float(arr.mean()), 4),
        'median': round(float(np.median(arr)), 4),
        'std': round(float(arr.std()), 4),
        'percentiles': percentiles,
        'by_regime': regime_stats,
        'histogram': histogram,
        'current_config': {'gauge_min': -10, 'gauge_mid': 0, 'gauge_max': 5},
        'all_scores': [{'date': r['date'], 'score': r['noise_score'], 'regime': r.get('regime_name')}
                       for r in records if r.get('noise_score') is not None],
    }
