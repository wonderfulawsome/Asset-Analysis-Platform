"""KR Crash/Surge XGBoost 1회성 학습 + 백필 적재.

사용:
    python -m scripts.train_kr_crash_surge                # 2010~ 학습 + 60일 backfill
    python -m scripts.train_kr_crash_surge --start 2012-01-01
    python -m scripts.train_kr_crash_surge --backfill 90 --trials 30

처리 흐름:
1. collector/crash_surge_data_kr.fetch_crash_surge_raw_kr — KR raw fetch
2. compute_features_kr → 24 피처 DataFrame
3. compute_labels_kr → 3-class y (±10% / 20영업일 forward)
4. 시간순 split (train/calib/test/dev)
5. processor.feature3_crash_surge.train_crash_surge(region='kr')
   → models/crash_surge_xgb_kr.pkl 저장
6. backfill_crash_surge → repository.upsert_crash_surge(rec, region='kr')
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def _prepare_datasets_kr(features: pd.DataFrame, labels: pd.Series,
                         close: pd.Series, feat_names: list[str],
                         forward_window: int = 20) -> dict:
    """KR 24-feature 용 데이터셋 분할 — US prepare_datasets 패턴 그대로."""
    df_full = features[feat_names].copy()
    df_full['label'] = labels

    # NaN/inf 처리 — KR 24 피처 모두 핵심이라 dropna
    df_full = df_full.replace([np.inf, -np.inf], np.nan).dropna(subset=feat_names)
    df_full = df_full.dropna(subset=['label'])

    # 학습 가능 구간 (최근 forward_window 일 제외 — 미래 라벨 없음)
    if len(close) <= forward_window:
        raise ValueError(f'KOSPI close 데이터가 부족 ({len(close)} < {forward_window + 1})')
    cutoff = close.index[-forward_window - 1]
    df = df_full[df_full.index <= cutoff].copy()

    if len(df) == 0:
        raise ValueError('학습 가능 행 0건 (피처 dropna 후)')

    # 3-split — US 와 동일 비율
    holdout_days = min(504, len(df) - 100)        # 약 2년
    calib_days = min(1008, len(df) - holdout_days - 100)  # 약 4년

    if holdout_days < 50 or calib_days < 50:
        raise ValueError(f'데이터 부족 — total={len(df)}, holdout={holdout_days}, calib={calib_days}')

    test_df = df.iloc[-holdout_days:]
    calib_df = df.iloc[-(holdout_days + calib_days):-holdout_days]
    train_df = df.iloc[:-(holdout_days + calib_days)]
    dev_df = df.iloc[:-holdout_days]

    print(f'  [KR-CrashSurge] 학습: {len(train_df)}, 캘리브: {len(calib_df)}, '
          f'테스트: {len(test_df)}, 추론(df_full): {len(df_full)}')

    return {
        'df_full': df_full,
        'train': (train_df[feat_names].values, train_df['label'].values),
        'calib': (calib_df[feat_names].values, calib_df['label'].values),
        'test': (test_df[feat_names].values, test_df['label'].values),
        'dev': (dev_df[feat_names].values, dev_df['label'].values),
    }


def main():
    parser = argparse.ArgumentParser(description='KR Crash/Surge XGBoost 학습 + 백필')
    parser.add_argument('--start', type=str, default='2010-01-01',
                        help='학습 데이터 시작일 (YYYY-MM-DD). 기본 2010 — ECOS 회사채 안정 시점부터.')
    parser.add_argument('--backfill', type=int, default=60, help='backfill 일수 (기본 60)')
    parser.add_argument('--trials', type=int, default=50, help='Optuna trials (기본 50)')
    args = parser.parse_args()

    print('═══════════════════════════════════════════════════')
    print('  KR Crash/Surge XGBoost — 학습 + 백필')
    print('═══════════════════════════════════════════════════')

    # 1) Raw fetch + 피처/라벨
    from collector.crash_surge_data_kr import (
        fetch_crash_surge_raw_kr, compute_features_kr, compute_labels_kr, KR_FEATURES,
    )
    raw = fetch_crash_surge_raw_kr(start=args.start)
    if not raw or 'kospi' not in raw or raw['kospi'].empty:
        print('[FATAL] KOSPI raw 데이터 수집 실패')
        return 1

    feat_df = compute_features_kr(raw)
    if feat_df is None or feat_df.empty:
        print('[FATAL] 피처 산출 실패 또는 빈 DataFrame')
        return 1

    close = raw['kospi']['Close']
    labels = compute_labels_kr(close)

    print(f'\n[KR-CrashSurge] 피처: {feat_df.shape}, 라벨: {len(labels)}')
    print(f'  기간: {feat_df.index[0].date()} ~ {feat_df.index[-1].date()}')
    print(f'  라벨 분포: 0={int((labels==0).sum())}, 1(crash)={int((labels==1).sum())}, '
          f'2(surge)={int((labels==2).sum())}')

    if (labels == 1).sum() < 30 or (labels == 2).sum() < 30:
        print('[WARN] crash/surge 표본 30 미만 — 학습 부실 가능성. --start 더 일찍 또는 임계값 검토.')

    # 2) 데이터셋 분할
    try:
        ds = _prepare_datasets_kr(feat_df, labels, close, list(KR_FEATURES))
    except Exception as e:
        print(f'[FATAL] 데이터셋 분할 실패: {e}')
        traceback.print_exc()
        return 1

    # 3) 학습
    from processor.feature3_crash_surge import train_crash_surge, backfill_crash_surge
    print('\n[KR-CrashSurge] XGBoost 학습 시작...')
    try:
        bundle = train_crash_surge(
            X_train=ds['train'][0], y_train=ds['train'][1],
            X_calib=ds['calib'][0], y_calib=ds['calib'][1],
            X_test=ds['test'][0], y_test=ds['test'][1],
            X_dev=ds['dev'][0], y_dev=ds['dev'][1],
            X_full=ds['df_full'][list(KR_FEATURES)].values,
            n_trials=args.trials,
            region='kr',
        )
    except Exception as e:
        print(f'[FATAL] 학습 실패: {e}')
        traceback.print_exc()
        return 1

    # 4) 백필 — 최근 N일 KR crash_surge 결과 산출
    print(f'\n[KR-CrashSurge] 최근 {args.backfill}일 backfill 시작...')
    try:
        records_all = backfill_crash_surge(ds['df_full'], bundle)
    except Exception as e:
        print(f'[FATAL] backfill 실패: {e}')
        traceback.print_exc()
        return 1

    # 최근 N일만 잘라 DB 적재 (전체 백필은 학습 시점 분포 산출 보조용)
    records = records_all[-args.backfill:] if args.backfill < len(records_all) else records_all
    if not records:
        print('[KR-CrashSurge] backfill 결과 0건 — DB 적재 건너뜀')
        return 0

    # 5) DB 적재
    print(f'\n[KR-CrashSurge] DB 적재 ({len(records)}건)...')
    from database.repositories import upsert_crash_surge
    success = 0
    for rec in records:
        try:
            upsert_crash_surge(rec, region='kr')
            success += 1
        except Exception as e:
            print(f"  [skip {rec.get('date')}] {e}")

    print('═══════════════════════════════════════════════════')
    print(f'  완료: 학습 + {success}/{len(records)} 건 DB 적재')
    print(f'  모델: models/crash_surge_xgb_kr.pkl')
    print(f'  Macro F1 (test): {bundle.get("macro_f1", 0):.4f}')
    print('═══════════════════════════════════════════════════')
    return 0


if __name__ == '__main__':
    sys.exit(main())
