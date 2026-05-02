"""수도권 신규 LAWD_CD × N개월 부동산 데이터 backfill.

대상: 인천 10 + 경기 42 (단일 25 + 일반구 17) = **52개 LAWD_CD** (서울 25는 제외 — 이미 보유)
출처: scheduler/job.py Step 9 와 동일 로직, 단일 시군구·다월 backfill 버전.

호출량 (months=24, hh_months=3):
- MOLIT 매매·전월세: 52 × 24 × 2 = 2,496회
- MOIS 인구·매핑: 52 × 24 × 2 = 2,496회
- MOIS 세대원수: 52 × 3 × ~20동 ≈ 3,120회 (최근 3개월만 — solo_rate 변동 작음)
- 합계 약 8,000회. data.go.kr 일일 quota 1만 이내. ~25~30분 (0.4s 간격).

사용법:
    python scripts/backfill_metro.py [--months 24] [--hh-months 3] [--sleep 0.4] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# 수도권 전체 LAWD_CD — 서울 25 + 인천 10 + 경기 42 = 77
# (역사적 변수명 유지. 서울은 추후 추가됨 — 매월 1ym 누적 외 backfill 필요)
METRO_NEW_LAWD_CDS: list[str] = [
    # 서울 (11) 25
    "11110", "11140", "11170", "11200", "11215",
    "11230", "11260", "11290", "11305", "11320",
    "11350", "11380", "11410", "11440", "11470",
    "11500", "11530", "11545", "11560", "11590",
    "11620", "11650", "11680", "11710", "11740",
    # 인천 (28) 10
    "28110", "28140", "28177", "28185", "28200",
    "28237", "28245", "28260", "28710", "28720",
    # 경기 (41) — 단일 시·군 25
    "41150", "41194", "41210", "41220", "41250",
    "41290", "41310", "41360", "41370", "41390",
    "41410", "41430", "41450", "41480", "41500",
    "41550", "41570", "41590", "41610", "41630",
    "41650", "41670", "41800", "41820", "41830",
    # 경기 일반구 17 (수원4·성남3·안양2·안산2·고양3·용인3)
    "41111", "41113", "41115", "41117",
    "41131", "41133", "41135",
    "41171", "41173",
    "41271", "41273",
    "41281", "41285", "41287",
    "41461", "41463", "41465",
]


def list_yms(months: int) -> list[str]:
    """최근 N개월 YM (오래된 → 최신). 기준: 전월(MOIS lag)."""
    today = datetime.date.today()
    cur = today.replace(day=1) - datetime.timedelta(days=1)
    yms = []
    for _ in range(months):
        yms.append(cur.strftime("%Y%m"))
        cur = cur.replace(day=1) - datetime.timedelta(days=1)
    yms.reverse()
    return yms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=24, help="기본 24개월 (매매·전월세·인구·매핑)")
    ap.add_argument("--hh-months", type=int, default=3, help="세대원수만 최근 N개월 (default 3)")
    ap.add_argument("--sleep", type=float, default=0.4, help="호출 간 대기 (초)")
    ap.add_argument("--dry-run", action="store_true", help="대상만 출력, fetch/upsert 안 함")
    ap.add_argument("--start-from", default=None, help="특정 LAWD_CD 부터 재개 (예: 41271)")
    ap.add_argument("--max-minutes", type=int, default=0, help="0=무제한. N분 경과 시 현재 sgg 끝내고 종료 (분할 실행용)")
    args = ap.parse_args()

    yms = list_yms(args.months)
    print(f"[backfill_metro] 대상 LAWD_CD {len(METRO_NEW_LAWD_CDS)}개 × {args.months}개월 ({yms[0]} ~ {yms[-1]})")
    print(f"[backfill_metro] 세대원수 = 최근 {args.hh_months}개월만 ({yms[-args.hh_months:]})")
    print(f"[backfill_metro] 호출 간격 {args.sleep}s, dry-run={args.dry_run}")

    if args.dry_run:
        print("\n[dry-run] 처음 5개:", METRO_NEW_LAWD_CDS[:5])
        return 0

    # 지연 import — dry-run 시 DB 접속 회피
    from collector.real_estate_trade import fetch_trades, fetch_rents
    from collector.real_estate_population import fetch_population, fetch_household_by_size
    from processor.feature5_real_estate import build_mapping, compute_region_summary
    from processor.feature6_buy_signal import compute_buy_signal
    from database.repositories import (
        upsert_re_trades, upsert_re_rents, upsert_mois_population,
        upsert_mois_household, upsert_stdg_admm_mapping, upsert_region_summary,
        upsert_buy_signal, fetch_macro_rate_kr, fetch_region_timeseries,
        fetch_region_migration,
    )
    from scheduler.job import (
        _re_norm_trades, _re_norm_rents, _re_norm_population,
        _re_norm_household, _re_norm_mapping,
    )

    rate_ts = fetch_macro_rate_kr(months=args.months) or []

    started = args.start_from is None
    t0 = time.time()
    for i, sgg in enumerate(METRO_NEW_LAWD_CDS, 1):
        if not started:
            if sgg == args.start_from:
                started = True
            else:
                continue
        # 시간 제한 체크 (매 sgg 시작 전 — 진행 중 sgg 는 안 끊고 다음 sgg 부터 stop)
        elapsed = time.time() - t0
        if args.max_minutes > 0 and elapsed >= args.max_minutes * 60:
            print(f"\n[--max-minutes {args.max_minutes} 도달, {elapsed:.0f}s 경과] "
                  f"다음 회차 명령: --start-from {sgg}", flush=True)
            return 0
        sgg_10 = sgg + "00000"
        print(f"\n[{i}/{len(METRO_NEW_LAWD_CDS)}] LAWD_CD {sgg} ({elapsed:.0f}s 경과)", flush=True)

        # mapping 캐시 — sgg 당 1회만 fetch (행정구역 코드는 1년 단위 변경, 12mo 안에서 무시).
        # 동수 × 12 ym 호출 → 동수 × 1 호출로 감소 (sgg 당 mapping 단계 ~5분 → ~30초).
        sgg_mapping = None

        for ym in yms:
            try:
                trades = _re_norm_trades(fetch_trades(sgg, ym), sgg, ym)
                upsert_re_trades(trades)
                time.sleep(args.sleep)

                rents = _re_norm_rents(fetch_rents(sgg, ym), sgg, ym)
                upsert_re_rents(rents)
                time.sleep(args.sleep)

                pop = _re_norm_population(fetch_population(sgg_10, ym), ym)
                upsert_mois_population(pop)
                time.sleep(args.sleep)

                if sgg_mapping is None:
                    sgg_mapping = _re_norm_mapping(build_mapping(sgg_10, ym))
                    upsert_stdg_admm_mapping(sgg_mapping)
                mapping = sgg_mapping  # 모든 ym 의 region_summary 에 같은 mapping 재사용

                household: list[dict] = []
                if args.hh_months > 0 and ym in yms[-args.hh_months:]:
                    hh_seen: set[tuple] = set()
                    admm_cds = list({m["admm_cd"] for m in mapping if m.get("admm_cd")})
                    for admm in admm_cds:
                        try:
                            for row in _re_norm_household(fetch_household_by_size(admm, ym), ym):
                                k = (row["stats_ym"], row["admm_cd"])
                                if k in hh_seen:
                                    continue
                                hh_seen.add(k)
                                household.append(row)
                        except Exception as e_hh:
                            print(f"     [{ym}] household {admm} 실패: {e_hh}")
                        time.sleep(args.sleep)
                    upsert_mois_household(household)

                summary = compute_region_summary(
                    trades=trades, rents=rents, population=pop, mapping=mapping,
                    household=household or None, sgg_cd=sgg, stats_ym=ym,
                )
                # 안전망: 동일 batch 안 (stdg_cd, stats_ym) 중복 시 ON CONFLICT 21000 발생 → 1차 dedupe
                seen_sum: set[tuple] = set()
                summary_dedup = []
                for row in summary or []:
                    key = (row.get("stdg_cd"), row.get("stats_ym"))
                    if key in seen_sum:
                        continue
                    seen_sum.add(key)
                    summary_dedup.append(row)
                upsert_region_summary(summary_dedup)
                print(f"   [{ym}] trades={len(trades)} rents={len(rents)} pop={len(pop)} hh={len(household)} sum={len(summary_dedup)}", flush=True)
            except Exception as e:
                # 401(quota throttle) 일 때만 60s 회복 대기, 일반 timeout/네트워크 오류는 5s
                msg = str(e).lower()
                wait = 60 if ("401" in msg or "quota" in msg or "throttle" in msg) else 5
                print(f"   [{ym}] !! 실패 ({wait}s 대기 후 다음 ym): {e}", flush=True)
                time.sleep(wait)

        # 시군구별 backfill 끝 → 매수 시그널 재계산 (compute_buy_signal 은 시계열 보고 산출)
        try:
            ts = fetch_region_timeseries(sgg)
            flow_ts = fetch_region_migration(sgg)
            signal_rec = compute_buy_signal(ts, rate_ts=rate_ts, flow_ts=flow_ts)
            if signal_rec:
                signal_rec["sgg_cd"] = sgg
                # compute_buy_signal 가 t-1 기준 stats_ym 을 정확히 set 하므로 외부에서 안 덮음
                # (값 누락 시에만 안전망으로 yms[-1] 사용)
                if not signal_rec.get("stats_ym"):
                    signal_rec["stats_ym"] = yms[-1]
                upsert_buy_signal(signal_rec)
                print(f"   ✓ signal: {signal_rec.get('signal')} (score={signal_rec.get('score')})")
        except Exception as e:
            print(f"   signal 실패: {e}")

    print(f"\n[완료] 총 소요 {(time.time()-t0)/60:.1f}분")
    return 0


if __name__ == "__main__":
    sys.exit(main())
