"""수도권 52 LAWD_CD 의 buy_signal 만 일괄 재산출.

backfill 끝났는데 signal 만 NULL 에러로 누락된 경우 사용.
DB 시계열만 사용 — 외부 API 호출 0회. ~5분 소요.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backfill_metro import METRO_NEW_LAWD_CDS


def main() -> int:
    from processor.feature6_buy_signal import compute_buy_signal
    from database.repositories import (
        fetch_macro_rate_kr, fetch_region_timeseries, fetch_region_migration,
        upsert_buy_signal,
    )

    rate_ts = fetch_macro_rate_kr(months=24) or []
    print(f"[recompute] 수도권 신규 {len(METRO_NEW_LAWD_CDS)} LAWD_CD 의 buy_signal 재산출")
    t0 = time.time()
    ok, fail = 0, 0
    for i, sgg in enumerate(METRO_NEW_LAWD_CDS, 1):
        try:
            ts = fetch_region_timeseries(sgg)
            if not ts or len(ts) < 2:
                print(f"  [{i:>2}/{len(METRO_NEW_LAWD_CDS)}] {sgg}: ts 부족 (n={len(ts) if ts else 0}) skip")
                continue
            flow_ts = fetch_region_migration(sgg)
            signal_rec = compute_buy_signal(ts, rate_ts=rate_ts, flow_ts=flow_ts)
            if not signal_rec:
                print(f"  [{i:>2}/{len(METRO_NEW_LAWD_CDS)}] {sgg}: signal None")
                continue
            signal_rec["sgg_cd"] = sgg
            # compute_buy_signal 가 stats_ym 을 None 으로 set 하는 경우 있음 → 강제 덮어쓰기
            signal_rec["stats_ym"] = ts[-1].get("ym") or ts[-1].get("stats_ym")
            if not signal_rec["stats_ym"]:
                print(f"  [{i:>2}/{len(METRO_NEW_LAWD_CDS)}] {sgg}: ts 마지막에 ym 없음 skip")
                fail += 1
                continue
            upsert_buy_signal(signal_rec)
            print(f"  [{i:>2}/{len(METRO_NEW_LAWD_CDS)}] {sgg}: ✓ {signal_rec.get('signal')} score={signal_rec.get('score')} ym={signal_rec['stats_ym']}", flush=True)
            ok += 1
        except Exception as e:
            print(f"  [{i:>2}/{len(METRO_NEW_LAWD_CDS)}] {sgg}: !! {e}", flush=True)
            fail += 1
    print(f"\n[완료] 성공 {ok} / 실패 {fail} / 총 {len(METRO_NEW_LAWD_CDS)}, 소요 {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
