-- 2026-04-30 — 미국·한국 시장 분리 도입을 위한 region 컬럼 추가
--
-- 기존 모든 행은 'us' 로 태그.
-- KR 데이터가 들어오기 시작하면 region='kr' 로 적재됨.
-- API/Repository 는 region 파라미터를 받아 분기 (default='us' 로 하위호환).
--
-- ⚠️ Supabase SQL Editor 에서 1회 실행. 컬럼 추가 후 NOT NULL + default 적용.
-- 모든 ALTER 가 IF NOT EXISTS / IF EXISTS 패턴 + dedupe 선행이라 재실행 안전.

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 1. region 컬럼 추가 (모든 행 'us' 로 태그)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE noise_regime           ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE crash_surge_result     ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE sector_cycle_result    ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE sector_valuation       ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE valuation_signal       ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE chart_predict_result   ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE market_regime          ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE macro_raw              ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE sector_macro_raw       ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE index_price_raw        ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';
ALTER TABLE fear_greed_raw         ADD COLUMN IF NOT EXISTS region TEXT NOT NULL DEFAULT 'us';

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 2. (region, date) 또는 (region, date, ticker) 중복 제거
-- ─────────────────────────────────────────────────────────────────────────────
-- 같은 키 그룹에서 id 가 가장 큰 (=최신) 행만 남기고 나머지 삭제.
-- Supabase 의 모든 테이블은 BIGSERIAL id 가 있다고 가정.

-- (region, date) 단일 키 테이블들
DELETE FROM noise_regime WHERE id NOT IN (
  SELECT MAX(id) FROM noise_regime GROUP BY region, date
);
DELETE FROM crash_surge_result WHERE id NOT IN (
  SELECT MAX(id) FROM crash_surge_result GROUP BY region, date
);
DELETE FROM sector_cycle_result WHERE id NOT IN (
  SELECT MAX(id) FROM sector_cycle_result GROUP BY region, date
);
DELETE FROM valuation_signal WHERE id NOT IN (
  SELECT MAX(id) FROM valuation_signal GROUP BY region, date
);
DELETE FROM market_regime WHERE id NOT IN (
  SELECT MAX(id) FROM market_regime GROUP BY region, date
);
DELETE FROM macro_raw WHERE id NOT IN (
  SELECT MAX(id) FROM macro_raw GROUP BY region, date
);
DELETE FROM fear_greed_raw WHERE id NOT IN (
  SELECT MAX(id) FROM fear_greed_raw GROUP BY region, date
);
DELETE FROM sector_macro_raw WHERE id NOT IN (
  SELECT MAX(id) FROM sector_macro_raw GROUP BY region, date
);

-- (region, date, ticker) 합성 키 테이블들
DELETE FROM sector_valuation WHERE id NOT IN (
  SELECT MAX(id) FROM sector_valuation GROUP BY region, date, ticker
);
DELETE FROM index_price_raw WHERE id NOT IN (
  SELECT MAX(id) FROM index_price_raw GROUP BY region, date, ticker
);
DELETE FROM chart_predict_result WHERE id NOT IN (
  SELECT MAX(id) FROM chart_predict_result GROUP BY region, date, ticker
);

-- ─────────────────────────────────────────────────────────────────────────────
-- STEP 3. UNIQUE 제약을 (region, date) / (region, date, ticker) 로 교체
-- ─────────────────────────────────────────────────────────────────────────────

-- noise_regime
ALTER TABLE noise_regime DROP CONSTRAINT IF EXISTS noise_regime_date_key;
ALTER TABLE noise_regime DROP CONSTRAINT IF EXISTS noise_regime_pkey;
ALTER TABLE noise_regime DROP CONSTRAINT IF EXISTS noise_regime_region_date_key;
ALTER TABLE noise_regime ADD CONSTRAINT noise_regime_region_date_key UNIQUE (region, date);

-- crash_surge_result
ALTER TABLE crash_surge_result DROP CONSTRAINT IF EXISTS crash_surge_result_date_key;
ALTER TABLE crash_surge_result DROP CONSTRAINT IF EXISTS crash_surge_result_pkey;
ALTER TABLE crash_surge_result DROP CONSTRAINT IF EXISTS crash_surge_result_region_date_key;
ALTER TABLE crash_surge_result ADD CONSTRAINT crash_surge_result_region_date_key UNIQUE (region, date);

-- sector_cycle_result
ALTER TABLE sector_cycle_result DROP CONSTRAINT IF EXISTS sector_cycle_result_date_key;
ALTER TABLE sector_cycle_result DROP CONSTRAINT IF EXISTS sector_cycle_result_pkey;
ALTER TABLE sector_cycle_result DROP CONSTRAINT IF EXISTS sector_cycle_result_region_date_key;
ALTER TABLE sector_cycle_result ADD CONSTRAINT sector_cycle_result_region_date_key UNIQUE (region, date);

-- valuation_signal
ALTER TABLE valuation_signal DROP CONSTRAINT IF EXISTS valuation_signal_date_key;
ALTER TABLE valuation_signal DROP CONSTRAINT IF EXISTS valuation_signal_pkey;
ALTER TABLE valuation_signal DROP CONSTRAINT IF EXISTS valuation_signal_region_date_key;
ALTER TABLE valuation_signal ADD CONSTRAINT valuation_signal_region_date_key UNIQUE (region, date);

-- macro_raw
ALTER TABLE macro_raw DROP CONSTRAINT IF EXISTS macro_raw_date_key;
ALTER TABLE macro_raw DROP CONSTRAINT IF EXISTS macro_raw_pkey;
ALTER TABLE macro_raw DROP CONSTRAINT IF EXISTS macro_raw_region_date_key;
ALTER TABLE macro_raw ADD CONSTRAINT macro_raw_region_date_key UNIQUE (region, date);

-- market_regime
ALTER TABLE market_regime DROP CONSTRAINT IF EXISTS market_regime_date_key;
ALTER TABLE market_regime DROP CONSTRAINT IF EXISTS market_regime_pkey;
ALTER TABLE market_regime DROP CONSTRAINT IF EXISTS market_regime_region_date_key;
ALTER TABLE market_regime ADD CONSTRAINT market_regime_region_date_key UNIQUE (region, date);

-- fear_greed_raw
ALTER TABLE fear_greed_raw DROP CONSTRAINT IF EXISTS fear_greed_raw_date_key;
ALTER TABLE fear_greed_raw DROP CONSTRAINT IF EXISTS fear_greed_raw_pkey;
ALTER TABLE fear_greed_raw DROP CONSTRAINT IF EXISTS fear_greed_raw_region_date_key;
ALTER TABLE fear_greed_raw ADD CONSTRAINT fear_greed_raw_region_date_key UNIQUE (region, date);

-- sector_macro_raw
ALTER TABLE sector_macro_raw DROP CONSTRAINT IF EXISTS sector_macro_raw_date_key;
ALTER TABLE sector_macro_raw DROP CONSTRAINT IF EXISTS sector_macro_raw_pkey;
ALTER TABLE sector_macro_raw DROP CONSTRAINT IF EXISTS sector_macro_raw_region_date_key;
ALTER TABLE sector_macro_raw ADD CONSTRAINT sector_macro_raw_region_date_key UNIQUE (region, date);

-- (date+ticker) → (region, date, ticker)
ALTER TABLE sector_valuation DROP CONSTRAINT IF EXISTS sector_valuation_date_ticker_key;
ALTER TABLE sector_valuation DROP CONSTRAINT IF EXISTS sector_valuation_pkey;
ALTER TABLE sector_valuation DROP CONSTRAINT IF EXISTS sector_valuation_region_date_ticker_key;
ALTER TABLE sector_valuation ADD CONSTRAINT sector_valuation_region_date_ticker_key UNIQUE (region, date, ticker);

ALTER TABLE index_price_raw DROP CONSTRAINT IF EXISTS index_price_raw_date_ticker_key;
ALTER TABLE index_price_raw DROP CONSTRAINT IF EXISTS index_price_raw_pkey;
ALTER TABLE index_price_raw DROP CONSTRAINT IF EXISTS index_price_raw_region_date_ticker_key;
ALTER TABLE index_price_raw ADD CONSTRAINT index_price_raw_region_date_ticker_key UNIQUE (region, date, ticker);

ALTER TABLE chart_predict_result DROP CONSTRAINT IF EXISTS chart_predict_result_date_ticker_key;
ALTER TABLE chart_predict_result DROP CONSTRAINT IF EXISTS chart_predict_result_pkey;
ALTER TABLE chart_predict_result DROP CONSTRAINT IF EXISTS chart_predict_result_region_date_ticker_key;
ALTER TABLE chart_predict_result ADD CONSTRAINT chart_predict_result_region_date_ticker_key UNIQUE (region, date, ticker);

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- 검증 쿼리
-- ─────────────────────────────────────────────────────────────────────────────
-- SELECT region, count(*) FROM noise_regime GROUP BY region;
-- SELECT region, count(*) FROM market_regime GROUP BY region;
-- → 모든 기존 행은 'us' 로 태그됨, 중복 없음
