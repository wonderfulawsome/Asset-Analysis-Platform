-- 2026-04-30 — market_regime 제약 보정
--
-- 직전 마이그레이션에서 market_regime UNIQUE 를 (region, date) 로 만들었는데,
-- 이 테이블은 sp500/ndx/sox 3개 인덱스가 같은 날짜에 들어가야 하므로
-- (region, date, index_name) 합성 키로 다시 잡아야 함.
--
-- ⚠️ Supabase SQL Editor 에서 1회 실행. 재실행 안전.

BEGIN;

-- (region, date) 그룹 안에서 index_name 별 중복 dedupe
-- (직전 마이그레이션의 dedupe 로 이미 1행만 남았다면 영향 없음)
DELETE FROM market_regime WHERE id NOT IN (
  SELECT MAX(id) FROM market_regime GROUP BY region, date, index_name
);

-- 직전에 잘못 잡은 (region, date) 제약 제거
ALTER TABLE market_regime DROP CONSTRAINT IF EXISTS market_regime_region_date_key;

-- 올바른 (region, date, index_name) 제약 추가
ALTER TABLE market_regime DROP CONSTRAINT IF EXISTS market_regime_region_date_index_name_key;
ALTER TABLE market_regime ADD CONSTRAINT market_regime_region_date_index_name_key UNIQUE (region, date, index_name);

COMMIT;

-- 검증
-- SELECT region, index_name, count(*) FROM market_regime GROUP BY region, index_name ORDER BY region, index_name;
-- → us|sp500, us|ndx, us|sox 각각 N건씩 정상
