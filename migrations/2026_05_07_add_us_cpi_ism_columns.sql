-- 2026-05-07 — US 섹터 매크로에 CPI / ISM PMI 추가
--
-- collector/sector_macro.py 가 FRED 에서 다음 두 시리즈를 추가 수집함:
--   CPIAUCSL → cpi_yoy   (전년대비 변화율, %, HMM 피처에 포함)
--   NAPM     → ism_pmi   (FRED 미지원 시 skip, NULL 허용, 참고/표시용)
--
-- 기존 sector_macro_raw 테이블에 sparse 컬럼으로 추가. region='us' 행은 채워지고
-- region='kr' 행은 NULL 유지 — UNIQUE(region,date) 재사용, repository 시그니처 무변경.

BEGIN;

ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS cpi_yoy   DOUBLE PRECISION;
ALTER TABLE sector_macro_raw ADD COLUMN IF NOT EXISTS ism_pmi   DOUBLE PRECISION;

COMMIT;

-- 검증:
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='sector_macro_raw' AND column_name IN ('cpi_yoy','ism_pmi');
-- → 2행 기대
--
-- 다음 스케줄러 cycle 후 채워졌는지 확인:
-- SELECT date, cpi_yoy, ism_pmi FROM sector_macro_raw
--  WHERE region='us' ORDER BY date DESC LIMIT 6;
