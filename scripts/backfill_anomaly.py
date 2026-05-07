"""시장 이상 탐지 (Anomaly Detection) 10년 백필.

신호 탭 교체용. noise_regime.feature_values (8개) + yfinance ^TNX/^IRX/^VIX 에서
yield_curve, vix_abs 추가 → 10 피처 → rolling 10년 μ, Σ → Mahalanobis D² 시계열.

사용:
    python -m scripts.backfill_anomaly                          # us, 가능한 전 구간
    python -m scripts.backfill_anomaly --region us
    python -m scripts.backfill_anomaly --dry-run                # DB 적재 없이 결과 통계만
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# repo 루트 path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

from processor.feature_anomaly import compute_anomaly_timeseries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--region', default='us', choices=['us', 'kr'])
    ap.add_argument('--dry-run', action='store_true', help='DB 적재 안 하고 통계만 출력')
    args = ap.parse_args()

    print(f'[Backfill] region={args.region} dry_run={args.dry_run}')
    t0 = time.time()
    df = compute_anomaly_timeseries(region=args.region)
    elapsed = time.time() - t0
    print(f'[Backfill] computed {len(df)} rows in {elapsed:.1f}s')

    if df.empty:
        print('[Backfill] 결과 비어있음 — noise_regime feature_values 또는 yfinance 데이터 부재 가능성.')
        sys.exit(1)

    # sanity check
    print()
    print('=== 통계 ===')
    print(f"  date range: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")
    print(f"  D² range  : {df['d2'].min():.2f} ~ {df['d2'].max():.2f}  (median {df['d2'].median():.2f})")
    valid_pct = df['percentile_10y'].dropna()
    if len(valid_pct):
        print(f"  pct_10y   : {valid_pct.min():.1f} ~ {valid_pct.max():.1f}  (median {valid_pct.median():.1f})")
    print(f"  n_history : {df['n_history'].min()} ~ {df['n_history'].max()}")

    print()
    print('=== 가장 이상한 5일 (D² 기준) ===')
    top5 = df.nlargest(5, 'd2')[['date', 'd2', 'percentile_10y', 'percentile_90d']]
    print(top5.to_string(index=False))

    print()
    print('=== 가장 평온한 5일 (D² 기준) ===')
    bot5 = df.nsmallest(5, 'd2')[['date', 'd2', 'percentile_10y', 'percentile_90d']]
    print(bot5.to_string(index=False))

    print()
    print('=== 최근 5일 ===')
    recent = df.tail(5)[['date', 'd2', 'percentile_10y', 'percentile_90d']]
    print(recent.to_string(index=False))

    if args.dry_run:
        print()
        print('[Backfill] dry-run — DB 적재 skip')
        return

    # DB 적재
    from database.repositories import upsert_anomaly_daily_bulk
    records = df.to_dict(orient='records')
    print()
    print(f'[Backfill] DB upsert {len(records)} rows ...')
    upsert_anomaly_daily_bulk(records, region=args.region)
    print('[Backfill] 완료')


if __name__ == '__main__':
    main()
