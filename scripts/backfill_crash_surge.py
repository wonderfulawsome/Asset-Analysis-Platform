"""폭락/급등 전조 히스토리 백필 스크립트

과거 10 거래일치 crash/surge 점수를 계산하여 DB에 저장합니다.
사용법: python -m scripts.backfill_crash_surge
"""

import sys
import os

# 프로젝트 루트를 sys.path에 추가 (모듈 임포트용)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.crash_surge_data import (
    fetch_crash_surge_raw, compute_features, compute_labels,
    prepare_datasets, ALL_FEATURES,
)
from processor.feature3_crash_surge import load_model, predict_crash_surge
from database.repositories import upsert_crash_surge


# 백필할 거래일 수
BACKFILL_DAYS = 10


def main():
    # 1) 기존 학습된 모델 로드
    print('[백필] 모델 로드...')
    model_bundle = load_model()
    if model_bundle is None:
        print('[백필] 저장된 모델이 없습니다. 먼저 파이프라인을 실행해주세요.')
        return

    # 2) 원시 데이터 수집 + 피처 계산
    print('[백필] 데이터 수집 + 피처 계산...')
    raw = fetch_crash_surge_raw()
    features = compute_features(raw['spy'], raw['fred'], raw['cboe'],
                               raw['yahoo_macro'])
    labels = compute_labels(raw['spy']['Close'])
    datasets = prepare_datasets(features, labels, raw['spy']['Close'])

    # 3) 전체 피처 DataFrame에서 마지막 N 거래일 추출
    df_full = datasets['df_full']
    # 마지막 BACKFILL_DAYS 행 (가장 오래된 날짜부터)
    recent = df_full.iloc[-BACKFILL_DAYS:]
    print(f'[백필] {len(recent)}일치 백필 시작: {recent.index[0].date()} ~ {recent.index[-1].date()}')

    # 4) 각 거래일에 대해 예측 + DB 저장
    for idx, row in recent.iterrows():
        # 해당 날짜의 피처 벡터 (1, 44) 형태로 변환
        X_row = row[ALL_FEATURES].values.reshape(1, -1)
        # 예측 실행
        result = predict_crash_surge(X_row, model_bundle)
        # 날짜를 해당 거래일로 오버라이드 (원래는 today()로 설정됨)
        result['date'] = str(idx.date())
        # DB 저장
        upsert_crash_surge(result)

    print(f'[백필] 완료! {len(recent)}일치 데이터가 DB에 저장되었습니다.')


if __name__ == '__main__':
    main()
