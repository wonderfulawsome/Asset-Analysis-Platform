"""부동산 데이터 가공 — Tier 1 지역 집계 + 법정동↔행정동 매핑.

기존 feature{N}_*.py 패턴을 따른다:
  - build_mapping(): 법정동↔행정동 매핑 테이블 생성 (노트북 03 이식)
  - compute_region_summary(): 지역 단위 Tier 1 집계 (노트북 04 EDA 로직 이식)
"""
import pandas as pd

from collector.real_estate_population import fetch_population, fetch_mapping_pairs


def build_mapping(sgg_cd: str, ref_ym: str) -> list[dict]:
    """시군구 코드(10자리) + 기준월 → (stdgCd, admmCd) 매핑 쌍 목록.

    fetch_population(lv=3)으로 읍면동 목록을 먼저 얻고,
    각 stdgCd에 fetch_mapping_pairs(lv=4)를 적용해 매핑 쌍 역추출.
    """
    # lv=3: 시군구 → 읍면동 목록 (stdgCd dedupe)
    items = fetch_population(sgg_cd, ref_ym)
    seen: dict[str, str] = {}
    for it in items:
        stdg = it.get("stdgCd")
        if stdg and stdg not in seen:
            seen[stdg] = stdg

    all_pairs: list[dict] = []
    for stdg_cd in seen:
        pairs = fetch_mapping_pairs(stdg_cd, ref_ym)
        for p in pairs:
            p["ref_ym"] = ref_ym  # DB 저장 시 기준월 필요
        all_pairs.extend(pairs)
    return all_pairs


def compute_region_summary(
    trades: list[dict],
    rents: list[dict],
    population: list[dict],
    mapping: list[dict],
    household: list[dict] | None = None,
    sgg_cd: str = "",
    stats_ym: str = "",
) -> list[dict]:
    """매매·전월세·인구·세대원수 데이터를 법정동별로 집계해 region_summary 레코드 목록 반환.

    반환값은 upsert_region_summary()에 바로 넘길 수 있는 list[dict].
    """
    if not trades and not rents:
        return []

    # ── 매매 집계 ────────────────────────────────────────────
    if trades:
        df_t = pd.DataFrame(trades)
        # DB에서 오는 deal_amount는 이미 int지만 API 직수신 시 문자열일 수 있어 방어 처리
        df_t["deal_amount"] = (
            df_t["deal_amount"].astype(str).str.replace(",", "").astype(float).astype(int)
        )
        df_t["exclu_use_ar"] = df_t["exclu_use_ar"].astype(float)
        df_t["pyeong"] = df_t["exclu_use_ar"] / 3.3058
        df_t["price_per_py"] = df_t["deal_amount"] / df_t["pyeong"]

        # stdg_cd 컬럼 확보 — DB 저장본은 stdg_cd, API 직수신은 sgg_cd+umd_cd 합성 필요
        if "stdg_cd" not in df_t.columns:
            df_t["stdg_cd"] = df_t["sgg_cd"].str.zfill(5) + df_t["umd_cd"].str.zfill(5)

        trade_agg = (
            df_t.groupby(["stdg_cd"])
            .agg(
                stdg_nm=("umd_nm", "first"),
                trade_count=("deal_amount", "size"),
                avg_price=("deal_amount", "mean"),
                median_price=("deal_amount", "median"),
                median_price_per_py=("price_per_py", "median"),
            )
            .reset_index()
        )
    else:
        trade_agg = pd.DataFrame(
            columns=["stdg_cd", "stdg_nm", "trade_count", "avg_price",
                     "median_price", "median_price_per_py"]
        )

    # ── 전월세 집계 ───────────────────────────────────────────
    if rents:
        df_r = pd.DataFrame(rents)
        df_r["deposit"] = (
            df_r["deposit"].astype(str).str.replace(",", "").astype(float).astype(int)
        )
        df_r["monthly_rent"] = df_r["monthly_rent"].astype(int)
        # monthly_rent == 0 이면 전세, 양수면 월세
        df_r["is_jeonse"] = df_r["monthly_rent"] == 0

        rent_agg = (
            df_r.groupby("sgg_cd")
            .agg(
                jeonse_count=("is_jeonse", "sum"),
                wolse_count=("is_jeonse", lambda x: (~x).sum()),
                avg_deposit=("deposit", "mean"),
            )
            .reset_index()
        )
    else:
        rent_agg = None

    # ── 인구 집계 ─────────────────────────────────────────────
    if population:
        df_p = pd.DataFrame(population)
        df_p["tot_nmpr_cnt"] = pd.to_numeric(df_p["tot_nmpr_cnt"], errors="coerce").fillna(0).astype(int)
        pop_agg = df_p[["stdg_cd", "tot_nmpr_cnt"]].copy()
        pop_agg = pop_agg.rename(columns={"tot_nmpr_cnt": "population"})
    else:
        pop_agg = None

    # ── 1인가구 비율 — 세대원수(행정동) + 매핑 → 법정동 가중합 ─
    # 한 법정동이 여러 행정동에 걸칠 수 있어 단순 평균이 아닌 세대수 가중합으로 재집계
    solo_agg = None
    if household and mapping:
        df_hh = pd.DataFrame(household)
        df_map = pd.DataFrame(mapping)
        df_hh["hh_1"] = pd.to_numeric(df_hh["hh_1"], errors="coerce").fillna(0).astype(int)
        df_hh["tot_hh_cnt"] = pd.to_numeric(df_hh["tot_hh_cnt"], errors="coerce").fillna(0).astype(int)
        hh_mapped = df_hh.merge(df_map[["stdg_cd", "admm_cd"]], on="admm_cd", how="inner")
        grp = (
            hh_mapped.groupby("stdg_cd")
            .agg(tot_hh=("tot_hh_cnt", "sum"), solo_cnt=("hh_1", "sum"))
            .reset_index()
        )
        grp["solo_rate"] = grp["solo_cnt"] / grp["tot_hh"].replace(0, float("nan"))
        solo_agg = grp[["stdg_cd", "solo_rate"]]

    # ── 조인 ──────────────────────────────────────────────────
    result = trade_agg.copy()
    if pop_agg is not None:
        result = result.merge(pop_agg, on="stdg_cd", how="left")
    if solo_agg is not None:
        result = result.merge(solo_agg, on="stdg_cd", how="left")

    result["sgg_cd"] = sgg_cd
    result["stats_ym"] = stats_ym

    # 전월세는 시군구 단위 집계라 모든 법정동 행에 동일 값 붙임
    if rent_agg is not None and not rent_agg.empty:
        row = rent_agg.iloc[0]
        result["jeonse_count"] = int(row.get("jeonse_count", 0))
        result["wolse_count"] = int(row.get("wolse_count", 0))
        result["avg_deposit"] = int(row.get("avg_deposit", 0))

    # int 반올림
    for col in ("avg_price", "median_price", "avg_deposit"):
        if col in result.columns:
            result[col] = result[col].round(0).astype("Int64")

    return result.where(pd.notna(result), other=None).to_dict(orient="records")
