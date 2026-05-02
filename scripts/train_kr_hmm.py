"""KR Noise vs Signal HMM 1회성 학습 + 30일 백필 적재 스크립트.

사용:
    python -m scripts.train_kr_hmm                # 7년치 학습 + 60일 backfill
    python -m scripts.train_kr_hmm --years 5      # 5년치 학습
    python -m scripts.train_kr_hmm --backfill 90  # 90일 backfill

처리 흐름:
1. collector/noise_regime_data_kr.fetch_all_kr(years) — KOSPI 25종목 + macro
   (예상 5~10분, pykrx 25종목 5년치 fetch)
2. processor.feature1_regime.train_hmm(features, bundle, region='kr')
   → models/noise_hmm_kr.pkl 저장
3. backfill_noise_regime(bundle, model, days=N, region='kr')
   → repository.upsert_noise_regime(rec, region='kr') 로 적재
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description='KR HMM 학습 + 백필')
    parser.add_argument('--years', type=int, default=7, help='학습 데이터 기간 (years)')
    parser.add_argument('--backfill', type=int, default=60, help='backfill 일수')
    args = parser.parse_args()

    print('═══════════════════════════════════════════════════')
    print('  KR Noise vs Signal HMM — 학습 + 백필')
    print('═══════════════════════════════════════════════════')

    # 1) raw fetch + 8피처 산출
    from collector.noise_regime_data_kr import fetch_all_kr
    bundle = fetch_all_kr(years=args.years)
    if not bundle or 'features' not in bundle or len(bundle['features']) == 0:
        print('[FATAL] KR raw 데이터 수집 실패 또는 피처 0행')
        return 1

    feat_df = bundle['features']
    print(f'\n[KR-Train] 학습용 피처: {feat_df.shape}')
    print(f'  기간: {feat_df.index[0].date()} ~ {feat_df.index[-1].date()}')

    if len(feat_df) < 24:
        print(f'[FATAL] 피처 행 수 {len(feat_df)} < 24 — HMM 학습 불충분')
        return 1

    # 2) HMM 학습 + 모델 저장
    from processor.feature1_regime import train_hmm, backfill_noise_regime
    print('\n[KR-Train] HMM 학습 시작...')
    try:
        model_bundle = train_hmm(feat_df, monthly_bundle=bundle, region='kr')
    except Exception as e:
        print(f'[FATAL] HMM 학습 실패: {e}')
        traceback.print_exc()
        return 1

    # 3) 백필 — 최근 N일 KR noise_regime 결과 산출
    print(f'\n[KR-Train] 최근 {args.backfill}일 backfill 시작...')
    try:
        records = backfill_noise_regime(bundle, model_bundle, days=args.backfill, region='kr')
    except Exception as e:
        print(f'[FATAL] backfill 실패: {e}')
        traceback.print_exc()
        return 1

    if not records:
        print('[KR-Train] backfill 결과 0건 — DB 적재 건너뜀')
        return 0

    # 4) DB 에 region='kr' 로 upsert
    print(f'\n[KR-Train] DB 적재 ({len(records)}건)...')
    from database.repositories import upsert_noise_regime
    success = 0
    for rec in records:
        try:
            upsert_noise_regime(rec, region='kr')
            success += 1
        except Exception as e:
            print(f"  [skip {rec.get('date')}] {e}")

    print('═══════════════════════════════════════════════════')
    print(f'  완료: 학습 + {success}/{len(records)} 건 DB 적재')
    print(f'  모델: models/noise_hmm_kr.pkl')
    print('═══════════════════════════════════════════════════')
    return 0


if __name__ == '__main__':
    sys.exit(main())
