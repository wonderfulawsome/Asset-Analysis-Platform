-- 2026-05-03 — KR 섹터 사이클(거시경제 탭) 14컬럼 추가
--
-- 5번째 탭 "거시경제" (tab-sector) 를 KR 모드에서 채우기 위한 KR 거시 12종 + derived 2종.
-- 같은 sector_macro_raw 테이블에 sparse 컬럼으로 추가 — UNIQUE(region,date) 재사용,
-- repository 시그니처 무변경. US 행은 KR 컬럼 NULL, KR 행은 US 컬럼 NULL.
--
-- 12 KR 거시 (US FRED 8 등가 + 추가 4종 CPI/GDP/M2/실업률):
--   kr_indpro_yoy        ← KOSIS 광공업생산지수 YoY (US INDPRO 등가)
--   kr_yield_spread      ← ECOS kr_10y - kr_3y (US T10Y3M 등가)
--   kr_credit_spread     ← ECOS kr_corp_aa3y - kr_3y (US ANFCI 대용)
--   kr_unemp_yoy         ← ECOS 실업률 YoY (US ICSA 대용)
--   kr_unemp_rate        ← ECOS 실업률 raw level (참고/snapshot)
--   kr_permit_yoy        ← KOSIS 건축허가 YoY (US PERMIT 등가)
--   kr_retail_yoy        ← KOSIS 소매판매액지수 YoY (US RRSFS 등가)
--   kr_capex_yoy         ← KOSIS 설비투자지수 YoY (US ANDENO 등가)
--   kr_income_yoy        ← ECOS 가계소득 YoY (US W875RX1 등가)
--   kr_cpi_yoy           ← ECOS CPI YoY (추가)
--   kr_gdp_yoy           ← ECOS 실질 GDP YoY (분기, ffill)
--   kr_m2_yoy            ← ECOS M2 광의통화 YoY (추가)
--
-- 2 derived:
--   kr_indpro_chg3m      ← kr_indpro_yoy.diff(3) (3개월 모멘텀)
--   kr_capex_yoy_chg3m   ← kr_capex_yoy.diff(3)

BEGIN;

ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_indpro_yoy        DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_yield_spread      DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_credit_spread     DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_unemp_yoy         DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_unemp_rate        DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_permit_yoy        DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_retail_yoy        DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_capex_yoy         DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_income_yoy        DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_cpi_yoy           DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_gdp_yoy           DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_m2_yoy            DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_indpro_chg3m      DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS kr_capex_yoy_chg3m   DOUBLE PRECISION;

COMMIT;

-- 검증:
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='sector_macro_raw' AND column_name LIKE 'kr_%'
--  ORDER BY column_name;
-- → 14행 기대
--
-- KR 행 채워진 후:
-- SELECT date, kr_indpro_yoy, kr_cpi_yoy, kr_gdp_yoy, kr_yield_spread
--   FROM sector_macro_raw WHERE region='kr' ORDER BY date DESC LIMIT 6;
