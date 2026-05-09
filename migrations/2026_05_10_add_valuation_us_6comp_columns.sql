-- 2026-05-10 — valuation_signal 에 US 6-component 전용 컬럼 추가
--
-- 배경:
-- US 시장 밸류 composite 가 3-component (0.4·z_ERP + 0.3·z_VIX + 0.3·z_DD60) 으로
-- short-term sentiment 만 반영해 Buffett indicator 230% / Shiller CAPE 40+ 같은
-- 구조적 고평가를 잡지 못함.
--
-- 해결:
-- collector/valuation_signal.py 를 6-component 으로 확장:
--   z_comp = 0.25·z_CAPE + 0.25·z_BUFFETT + 0.20·z_TREND
--          + 0.10·z_ERP  + 0.10·z_VIX     + 0.10·z_DD
-- z_trend / price_vs_ma200 는 KR 마이그레이션(2026-05-09) 에서 이미 추가됨.
-- 이 마이그레이션은 z_cape / z_buffett + 원시값 컬럼 (cape, buffett_ratio) 추가.
--
-- 적용:
ALTER TABLE valuation_signal
    ADD COLUMN IF NOT EXISTS z_cape         DOUBLE PRECISION,    -- (Shiller CAPE 15Y baseline 기준 z, 부호 반전 후)
    ADD COLUMN IF NOT EXISTS z_buffett      DOUBLE PRECISION,    -- (WILL5000PRFC/GDP 15Y baseline 기준 z, 부호 반전 후)
    ADD COLUMN IF NOT EXISTS cape           DOUBLE PRECISION,    -- Shiller CAPE 원시값 (today)
    ADD COLUMN IF NOT EXISTS buffett_ratio  DOUBLE PRECISION;    -- WILL5000PRFC/GDP 원시 비율

-- 검증:
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='valuation_signal'
--    AND column_name IN ('z_cape','z_buffett','cape','buffett_ratio');
-- → 4 rows 기대
--
-- 적용 후:
-- 다음 US 스케줄러 cron (NY 16:30) 실행 시 z_cape/z_buffett/cape/buffett_ratio
-- 적재. 옛 row 는 NULL 유지 — frontend 가 NULL 컬럼은 0 또는 미표시.
