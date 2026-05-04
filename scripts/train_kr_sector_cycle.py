"""KR Sector Cycle (HMM 4-state 경기국면) 1회 학습 + 1행 적재.

사용:
    python -m scripts.train_kr_sector_cycle              # 240개월 (20년) 학습 + 오늘 1행
    python -m scripts.train_kr_sector_cycle --months 120 # 10년치 학습

처리 흐름:
1. collector/sector_macro_kr.fetch_sector_macro_kr(months) — KR 거시 12종 + derived 2 (~270개월)
2. collector/sector_etf_kr.fetch_sector_etf_returns_kr(macro_start) — KR 10 sector + 8 holding 월별 수익률
3. processor/feature2_sector_cycle.run_sector_cycle(macro, sector_ret, holding_ret, region='kr')
4. database/repositories.upsert_sector_macro(records, region='kr')
5. database/repositories.upsert_sector_cycle(result, region='kr')

US 측 sector cycle 은 매번 학습+추론 (.pkl 미저장) — KR 도 같은 정책 (월별 데이터라 비용 작음).
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description='KR Sector Cycle 학습 + 적재')
    parser.add_argument('--months', type=int, default=240,
                        help='수집 기간 (months). 기본 240 (20년) — 회사채/KOSIS 시작점 고려해도 충분.')
    args = parser.parse_args()

    print('═══════════════════════════════════════════════════')
    print('  KR Sector Cycle (HMM 경기국면) — 학습 + 적재')
    print('═══════════════════════════════════════════════════')

    # 1) KR 거시 12종 + derived 수집
    print('\n[KR-Train] ① 거시 12종 수집...')
    try:
        from collector.sector_macro_kr import fetch_sector_macro_kr, to_sector_macro_kr_records
    except Exception as e:
        print(f'[FATAL] sector_macro_kr import 실패: {e}')
        return 1

    macro = fetch_sector_macro_kr(months=args.months)
    if macro is None or macro.empty:
        print('[FATAL] KR 거시 데이터 0행 — ECOS/KOSIS API 키 또는 통계표 코드 확인 필요')
        return 1
    macro_start = str(macro.index[0].date())

    # 2) sector_macro_raw 적재 (region='kr')
    print('\n[KR-Train] ② sector_macro_raw upsert (region=kr)...')
    try:
        from database.repositories import upsert_sector_macro
        records = to_sector_macro_kr_records(macro)
        if records:
            CHUNK = 200
            for i in range(0, len(records), CHUNK):
                upsert_sector_macro(records[i:i + CHUNK], region='kr')
            print(f'  {len(records)}건 upsert')
    except Exception as e:
        print(f'[KR-Train] sector_macro 적재 실패 (계속 진행): {e}')
        traceback.print_exc()

    # 3) KR sector ETF + holding 월별 수익률
    print('\n[KR-Train] ③ KR sector ETF + holding 월별 수익률...')
    try:
        from collector.sector_etf_kr import fetch_sector_etf_returns_kr
        sector_ret, holding_ret = fetch_sector_etf_returns_kr(macro_start)
    except Exception as e:
        print(f'[FATAL] sector ETF returns 실패: {e}')
        traceback.print_exc()
        return 1

    if sector_ret.empty:
        print('[FATAL] sector_ret 빈 DataFrame — sector_cycle 학습 불가')
        return 1

    # 4) HMM 학습 + 추론
    print('\n[KR-Train] ④ HMM 4-state 학습 + 오늘 phase 추론...')
    try:
        from processor.feature2_sector_cycle import run_sector_cycle
        result = run_sector_cycle(macro, sector_ret, holding_ret, region='kr')
    except Exception as e:
        print(f'[FATAL] HMM 학습 실패: {e}')
        traceback.print_exc()
        return 1

    if not result:
        print('[FATAL] sector_cycle 결과 빈 dict')
        return 1

    # 5) sector_cycle_result 적재 (region='kr')
    print('\n[KR-Train] ⑤ sector_cycle_result upsert (region=kr)...')
    try:
        from database.repositories import upsert_sector_cycle
        upsert_sector_cycle(result, region='kr')
    except Exception as e:
        print(f'[FATAL] sector_cycle 적재 실패: {e}')
        traceback.print_exc()
        return 1

    # 6) 선택: sector_valuation 5년 backfill
    print('\n[KR-Train] ⑥ sector_valuation 5년 backfill (선택 — 비활성 default)...')
    try:
        from processor.sector_valuation_kr_backfill import backfill_sector_valuations_kr
        n = backfill_sector_valuations_kr(months=60)
        print(f'  {n}건 valuation backfill')
    except Exception as e:
        print(f'  valuation backfill 실패 (skip): {e}')

    print('═══════════════════════════════════════════════════')
    print(f'  완료: {result["date"]} → {result["phase_emoji"]} {result["phase_name"]}')
    print(f'  Top3: {result["top3_sectors"]}')
    print('═══════════════════════════════════════════════════')
    return 0


if __name__ == '__main__':
    sys.exit(main())
