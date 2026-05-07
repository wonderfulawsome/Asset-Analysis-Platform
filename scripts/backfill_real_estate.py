"""부동산 데이터 일회성 백필 스크립트.

scheduler/job.py 의 Step 9 로직을 단발 실행용으로 추출. 신규 환경에서
production Supabase 에 부동산 데이터 채워넣을 때 또는 키 변경 후 빈 테이블
복구 시 사용.

사용:
    python -m scripts.backfill_real_estate                       # 전국 (오래 걸림)
    python -m scripts.backfill_real_estate --seoul-only          # 서울 25개 시군구만
    python -m scripts.backfill_real_estate --sgg 11200 11680     # 특정 시군구만
    python -m scripts.backfill_real_estate --ym 202602           # 특정 월 (default = 전월)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, '.env'))

from collector.real_estate_trade import fetch_trades, fetch_rents
from collector.real_estate_population import (
    fetch_population, fetch_household_by_size, fetch_all_sgg_codes,
)
from processor.feature5_real_estate import build_mapping, compute_region_summary
from database.repositories import (
    upsert_re_trades, upsert_re_rents, upsert_mois_population, upsert_mois_household,
    upsert_stdg_admm_mapping, upsert_region_summary,
)
from scheduler.job import (
    _re_norm_trades, _re_norm_rents, _re_norm_population, _re_norm_mapping,
    _re_norm_household,
)

# 서울 25 시군구 (가장 빠른 검증용)
SEOUL_SGG = [
    '11110','11140','11170','11200','11215','11230','11260','11290','11305',
    '11320','11350','11380','11410','11440','11470','11500','11530','11545',
    '11560','11590','11620','11650','11680','11710','11740',
]


def _default_ym() -> str:
    today = _dt.date.today()
    prev1 = today.replace(day=1) - _dt.timedelta(days=1)
    prev2 = prev1.replace(day=1) - _dt.timedelta(days=1)
    return prev2.strftime('%Y%m')


def backfill_one(sgg_cd: str, re_ym: str) -> dict:
    """한 시군구·한 월에 대해 6개 단계 모두 실행. 결과 카운트 dict 반환."""
    out: dict = {'sgg_cd': sgg_cd, 'ym': re_ym}

    raw_trades = fetch_trades(sgg_cd, re_ym)
    trades = _re_norm_trades(raw_trades, sgg_cd, re_ym)
    upsert_re_trades(trades)
    out['trades'] = len(trades)

    raw_rents = fetch_rents(sgg_cd, re_ym)
    rents = _re_norm_rents(raw_rents, sgg_cd, re_ym)
    upsert_re_rents(rents)
    out['rents'] = len(rents)

    sgg_cd_10 = sgg_cd + "00000"
    raw_pop = fetch_population(sgg_cd_10, re_ym)
    population = _re_norm_population(raw_pop, re_ym)
    upsert_mois_population(population)
    out['population'] = len(population)

    raw_mapping = build_mapping(sgg_cd_10, re_ym)
    mapping = _re_norm_mapping(raw_mapping)
    upsert_stdg_admm_mapping(mapping)
    out['mapping'] = len(mapping)

    # household — 매핑된 admm_cd 별로 호출 후 dedupe
    hh_seen: set[tuple] = set()
    household: list[dict] = []
    admm_cds = list({m["admm_cd"] for m in mapping if m.get("admm_cd")})
    for admm_cd in admm_cds:
        try:
            raw_hh = fetch_household_by_size(admm_cd, re_ym)
            for row in _re_norm_household(raw_hh, re_ym):
                k = (row["stats_ym"], row["admm_cd"])
                if k in hh_seen:
                    continue
                hh_seen.add(k)
                household.append(row)
        except Exception as e_hh:
            print(f'    [household] admm_cd={admm_cd} 실패: {e_hh}')
    upsert_mois_household(household)
    out['household'] = len(household)

    summary = compute_region_summary(
        trades=trades, rents=rents,
        population=population, mapping=mapping,
        household=household or None,
        sgg_cd=sgg_cd, stats_ym=re_ym,
    )
    upsert_region_summary(summary)
    out['summary'] = len(summary) if isinstance(summary, list) else 1

    return out


def main():
    ap = argparse.ArgumentParser()
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument('--sgg', nargs='+', default=None, help='시군구 코드 5자리 리스트')
    grp.add_argument('--seoul-only', action='store_true', help='서울 25개만')
    grp.add_argument('--all', action='store_true', help='전국 (~250개, 매우 오래 걸림)')
    ap.add_argument('--ym', default='', help='YYYYMM (default = 전월)')
    args = ap.parse_args()

    re_ym = args.ym or _default_ym()

    if args.sgg:
        sgg_list = args.sgg
    elif args.all:
        print('[Backfill] 전국 시군구 코드 동적 조회 중...')
        sgg_list = fetch_all_sgg_codes(re_ym)
    else:
        # default = seoul-only (안전한 검증용)
        sgg_list = SEOUL_SGG

    print(f'[Backfill] ym={re_ym}  sgg 수={len(sgg_list)}')
    print(f'[Backfill] sgg 샘플: {sgg_list[:5]}{"..." if len(sgg_list) > 5 else ""}')
    print()

    success, fail = 0, 0
    for i, sgg_cd in enumerate(sgg_list, 1):
        print(f'[{i}/{len(sgg_list)}] sgg_cd={sgg_cd} ...', flush=True)
        try:
            counts = backfill_one(sgg_cd, re_ym)
            print(f'  OK  trades={counts["trades"]} rents={counts["rents"]} '
                  f'pop={counts["population"]} mapping={counts["mapping"]} '
                  f'hh={counts["household"]} summary={counts["summary"]}')
            success += 1
        except Exception as e:
            print(f'  FAIL: {type(e).__name__}: {str(e)[:200]}')
            traceback.print_exc()
            fail += 1

    print()
    print(f'[Backfill] 완료 — 성공 {success} / 실패 {fail}')


if __name__ == '__main__':
    main()
