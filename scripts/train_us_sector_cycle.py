"""US Sector Cycle (HMM 6-state 경기국면) 1회 학습 + 1행 적재.

사용:
    python -m scripts.train_us_sector_cycle              # 기본 (sector_macro 전체)
    python -m scripts.train_us_sector_cycle --dry-run    # DB upsert 건너뛰고 결과만 출력

처리 흐름 (scheduler/job.py Step 6 와 동일):
1. collector/sector_macro.fetch_sector_macro() — FRED 15 시리즈 + 파생 2
2. database/repositories.upsert_sector_macro(records) — region='us'
3. collector/sector_etf.fetch_sector_etf_returns(macro_start)
4. processor/feature2_sector_cycle.run_sector_cycle(..., region='us')
5. database/repositories.upsert_sector_cycle(result, region='us')

KR 측 train_kr_sector_cycle.py 와 1:1 미러. 학습은 매번 (pkl 미저장).
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description='US Sector Cycle 학습 + 적재')
    parser.add_argument('--dry-run', action='store_true', help='DB upsert 건너뛰고 결과만 출력')
    args = parser.parse_args()

    print('═══════════════════════════════════════════════════')
    print('  US Sector Cycle (HMM 6-state 경기국면) — 학습 + 적재')
    print('═══════════════════════════════════════════════════')

    print('\n[US-Train] ① FRED 15 시리즈 + 파생 수집...')
    try:
        from collector.sector_macro import fetch_sector_macro, to_sector_macro_records
        macro = fetch_sector_macro()
    except Exception as e:
        print(f'[FATAL] sector_macro fetch 실패: {e}')
        traceback.print_exc()
        return 1
    if macro is None or macro.empty:
        print('[FATAL] sector_macro 빈 DataFrame')
        return 1
    macro_start = str(macro.index[0].date())
    print(f'  수집 완료: {macro.shape} ({macro_start} ~ {macro.index[-1].date()})')

    if not args.dry_run:
        print('\n[US-Train] ② sector_macro_raw upsert (region=us)...')
        try:
            from database.repositories import upsert_sector_macro
            records = to_sector_macro_records(macro)
            CHUNK = 200
            for i in range(0, len(records), CHUNK):
                upsert_sector_macro(records[i:i + CHUNK], region='us')
            print(f'  {len(records)}건 upsert')
        except Exception as e:
            print(f'[US-Train] sector_macro 적재 실패 (계속 진행): {e}')
            traceback.print_exc()
    else:
        print('\n[US-Train] ② sector_macro_raw upsert SKIP (dry-run)')

    print('\n[US-Train] ③ sector ETF + holding 월별 수익률...')
    try:
        from collector.sector_etf import fetch_sector_etf_returns
        sector_ret, holding_ret = fetch_sector_etf_returns(macro_start)
    except Exception as e:
        print(f'[FATAL] sector ETF returns 실패: {e}')
        traceback.print_exc()
        return 1
    if sector_ret.empty:
        print('[FATAL] sector_ret 빈 DataFrame')
        return 1

    print('\n[US-Train] ④ HMM 6-state 학습 + 오늘 phase 추론...')
    try:
        from processor.feature2_sector_cycle import run_sector_cycle
        result = run_sector_cycle(macro, sector_ret, holding_ret, region='us')
    except Exception as e:
        print(f'[FATAL] HMM 학습 실패: {e}')
        traceback.print_exc()
        return 1
    if not result:
        print('[FATAL] sector_cycle 결과 빈 dict')
        return 1

    if not args.dry_run:
        print('\n[US-Train] ⑤ sector_cycle_result upsert (region=us)...')
        try:
            from database.repositories import upsert_sector_cycle
            upsert_sector_cycle(result, region='us')
        except Exception as e:
            print(f'[FATAL] sector_cycle 적재 실패: {e}')
            traceback.print_exc()
            return 1
    else:
        print('\n[US-Train] ⑤ sector_cycle_result upsert SKIP (dry-run)')

    print('═══════════════════════════════════════════════════')
    print(f'  완료: {result["date"]} → {result["phase_emoji"]} {result["phase_name"]}')
    print(f'  확률 분포: {result.get("probabilities")}')
    print(f'  Top3: {result.get("top3_sectors")}')
    print('═══════════════════════════════════════════════════')
    return 0


if __name__ == '__main__':
    sys.exit(main())
