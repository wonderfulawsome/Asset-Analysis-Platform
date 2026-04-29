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


@router.get('/score-distribution')
def get_score_distribution():
    """시장 이성 점수(noise_score 컬럼) 전체 분포 통계 (게이지 기준점 튜닝용).

    부호 컨벤션 (2026-04-29~): 양수 = 이성, 음수 = 감정.
    """
    import numpy as np

    records = fetch_noise_regime_history(days=1000)
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
