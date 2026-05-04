"""KR 거시 12종 + derived 2종 통합 aggregator — sector cycle (5번째 탭) 전용.

US sector_macro.py 의 KR 등가. 차이:
- 데이터 소스 2개 혼합: ECOS (5종) + KOSIS (4종) + ECOS 시장금리 (3종 derived 활용)
- 분기 데이터 (GDP, 가계소득) 는 ffill(limit=2) 로 분기 첫달 → 다음 두 달 채움
- US 와 같은 (date, kr_*_yoy, ...) wide DataFrame 형식으로 반환

Returns DataFrame columns:
  kr_indpro_yoy, kr_yield_spread, kr_credit_spread, kr_unemp_yoy, kr_unemp_rate,
  kr_permit_yoy, kr_retail_yoy, kr_capex_yoy, kr_income_yoy,
  kr_cpi_yoy, kr_gdp_yoy, kr_m2_yoy,
  kr_indpro_chg3m, kr_capex_yoy_chg3m  (derived)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd


def _ecos_series_monthly(metric: str, months: int) -> pd.Series:
    """ECOS 단일 metric → MS 월초 인덱스 Series. 실패 시 빈 Series."""
    from collector.ecos_macro import fetch_ecos_series, SECTOR_MACRO_SPECS, RATE_SPECS

    spec = SECTOR_MACRO_SPECS.get(metric) or RATE_SPECS.get(metric)
    if not spec:
        return pd.Series(dtype=float)

    today = date.today()
    cycle = spec["cycle"]
    if cycle == "D":
        from_t = (today - timedelta(days=months * 31 + 30)).strftime("%Y%m%d")
        to_t = today.strftime("%Y%m%d")
    elif cycle == "M":
        m = today.month - months
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        from_t = f"{y:04d}{m:02d}"
        to_t = today.strftime("%Y%m")
    elif cycle == "Q":
        # Q 주기: from/to 모두 'YYYYQ#' 형식 (ECOS 가 YYYYMM 받으면 ERROR-101)
        q_now = (today.month - 1) // 3 + 1
        n_quarters = max(1, months // 3 + 1)
        fy, fq = today.year, q_now
        for _ in range(n_quarters):
            fq -= 1
            if fq <= 0:
                fq += 4
                fy -= 1
        from_t = f"{fy}Q{fq}"
        to_t = f"{today.year}Q{q_now}"
    else:
        from_t = ""
        to_t = today.strftime("%Y")

    try:
        rows = fetch_ecos_series(metric, from_t, to_t)
    except Exception as e:
        print(f"[sector_macro_kr] ECOS {metric} 실패: {e}")
        return pd.Series(dtype=float)
    if not rows:
        return pd.Series(dtype=float)

    s = pd.Series([r["value"] for r in rows],
                  index=pd.to_datetime([r["date"] for r in rows])).sort_index()
    # 분기 데이터: 각 분기 첫달 1일에 값, 그 외엔 NaN. 월별 resample('MS').last() 후 ffill(2).
    if cycle == "Q":
        s = s.resample("MS").last().ffill(limit=2)
    else:
        s = s.resample("MS").last()
    return s.dropna()


def _kosis_series_monthly(metric: str, months: int) -> pd.Series:
    """KOSIS 단일 metric → MS 월초 인덱스 Series. 실패 시 빈 Series."""
    from collector.kosis_macro import fetch_kosis_macro_series

    try:
        rows = fetch_kosis_macro_series(metric, months=months)
    except Exception as e:
        print(f"[sector_macro_kr] KOSIS {metric} 실패: {e}")
        return pd.Series(dtype=float)
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series([r["value"] for r in rows],
                  index=pd.to_datetime([r["date"] for r in rows])).sort_index()
    return s.resample("MS").last().dropna()


def _yoy(s: pd.Series) -> pd.Series:
    """YoY 변화율 (%) — 12개월 전 대비."""
    if s.empty:
        return s
    return (s.pct_change(12) * 100).dropna()


def _kr_rate_monthly(key: str, months: int) -> pd.Series:
    """KR 일별 시장금리 → 월말 last. ECOS kr_10y_daily/kr_3y_daily/kr_corp_aa3y."""
    s = _ecos_series_monthly(key, months)
    return s


def fetch_sector_macro_kr(months: int = 240) -> pd.DataFrame:
    """KR 12 거시 + 2 derived → MS 인덱스 wide DataFrame.

    months=240 → 20년치. 회사채/주요 KOSIS 시리즈 시작점이 2003 전후라 실제 dropna 후 ~270개월.
    """
    print(f"[sector_macro_kr] {months}개월 KR 거시 12종 수집 시작...")

    # ── ECOS 7종 (CPI/GDP/실업률/M2/광공업/소매/설비투자) ──
    # 2026-05-04 검증: 모든 통계표 / 항목 코드는 ECOS StatisticTableList + StatisticItemList sweep
    # 결과로 확정. 광공업·소매·설비투자도 ECOS 에 있어 KOSIS 없이 충당.
    print("  ① ECOS — CPI/GDP/실업률/M2/광공업/소매/설비투자...")
    cpi = _ecos_series_monthly("kr_cpi", months)
    gdp = _ecos_series_monthly("kr_gdp", months)              # 분기 → ffill(2)
    unemp_rate = _ecos_series_monthly("kr_unemp_rate", months)
    m2 = _ecos_series_monthly("kr_m2", months)
    indpro = _ecos_series_monthly("kr_indpro", months)
    retail = _ecos_series_monthly("kr_retail", months)
    capex = _ecos_series_monthly("kr_capex", months)

    # ── 건축허가 (ECOS 901Y105 주택건설인허가실적 전국) ──
    permit = _ecos_series_monthly("kr_permit", months)
    # 가계소득 — ECOS 에 적합한 분기 통계표 없음 (KOSIS 가계동향 별도 검증 필요).
    # 일단 빈 Series → kr_income_yoy NaN 컬럼, feature2 의 non_empty subset 이 자동 제외.
    income = pd.Series(dtype=float)

    # ── ECOS 시장금리 (kr_yield_spread, kr_credit_spread derived) ──
    print("  ③ ECOS 시장금리 — 10Y/3Y/회사채...")
    kr10 = _kr_rate_monthly("kr_10y_daily", months)
    kr3 = _kr_rate_monthly("kr_3y_daily", months)
    corp = _kr_rate_monthly("kr_corp_aa3y", months)
    yield_spread = (kr10 - kr3).dropna() if (not kr10.empty and not kr3.empty) else pd.Series(dtype=float)
    credit_spread = (corp - kr3).dropna() if (not corp.empty and not kr3.empty) else pd.Series(dtype=float)

    # ── YoY 변환 ──
    df = pd.DataFrame({
        "kr_indpro_yoy":   _yoy(indpro),
        "kr_yield_spread": yield_spread,        # raw level (이미 % 단위)
        "kr_credit_spread": credit_spread,       # raw level
        "kr_unemp_yoy":    _yoy(unemp_rate),    # 실업률 YoY 변화율
        "kr_unemp_rate":   unemp_rate,          # raw level
        "kr_permit_yoy":   _yoy(permit),
        "kr_retail_yoy":   _yoy(retail),
        "kr_capex_yoy":    _yoy(capex),
        "kr_income_yoy":   _yoy(income),
        "kr_cpi_yoy":      _yoy(cpi),
        "kr_gdp_yoy":      _yoy(gdp),
        "kr_m2_yoy":       _yoy(m2),
    })

    # MS 정렬 + 지연 지표 최대 3개월 ffill (월별 발표 시점 차이 보정)
    df = df.sort_index().ffill(limit=3)

    # 12 컬럼 모두 NaN 인 초기 행 제거 (각 시리즈 시작점 차이로 누적)
    # — feature2_sector_cycle 의 dropna 정책이 FEATURE_COLS 기준으로 변경됐으므로
    #   여기서 부분 NaN 행은 유지해도 됨. 하지만 모든 컬럼 NaN 인 행은 의미 없어 제거.
    df = df.dropna(how="all")

    # ── derived 2종: 3개월 변화량 ──
    if "kr_indpro_yoy" in df.columns:
        df["kr_indpro_chg3m"] = df["kr_indpro_yoy"].diff(3)
    if "kr_capex_yoy" in df.columns:
        df["kr_capex_yoy_chg3m"] = df["kr_capex_yoy"].diff(3)

    df.index.name = "date"
    if not df.empty:
        non_nan_cols = [c for c in df.columns if df[c].notna().any()]
        print(f"[sector_macro_kr] 수집 완료: {df.shape[0]}행 × {df.shape[1]}컬럼 "
              f"({df.index[0].date()} ~ {df.index[-1].date()}), "
              f"non-NaN 컬럼 {len(non_nan_cols)}/{df.shape[1]}")
    else:
        print("[sector_macro_kr] 수집 결과 0행 — 모든 시리즈 실패")
    return df


def to_sector_macro_kr_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → upsert_sector_macro 입력 형식 (region='kr')."""
    KR_COLS = [
        "kr_indpro_yoy", "kr_yield_spread", "kr_credit_spread",
        "kr_unemp_yoy", "kr_unemp_rate",
        "kr_permit_yoy", "kr_retail_yoy", "kr_capex_yoy", "kr_income_yoy",
        "kr_cpi_yoy", "kr_gdp_yoy", "kr_m2_yoy",
        "kr_indpro_chg3m", "kr_capex_yoy_chg3m",
    ]
    records = []
    for d, row in df.iterrows():
        rec = {"date": str(d.date())}
        for col in KR_COLS:
            if col in df.columns:
                v = row[col]
                rec[col] = round(float(v), 4) if pd.notna(v) else None
            else:
                rec[col] = None
        records.append(rec)
    return records


if __name__ == "__main__":
    # 수동 검증: python -m collector.sector_macro_kr
    df = fetch_sector_macro_kr(months=60)
    print(df.tail())
    print(f"\n총 {len(df)}행 × {df.shape[1]}컬럼")
