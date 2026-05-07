-- 2026-05-08 — 부동산 관련 테이블 10개 RLS 비활성화
--
-- 문제:
-- 부동산 데이터 백필/스케줄러 upsert 시 'new row violates row-level security policy'
-- (SQLSTATE 42501) 로 차단. Supabase 는 신규 테이블에 RLS 를 기본 활성화하므로
-- anon 키 (스케줄러 + API 가 사용) 의 INSERT/UPDATE 가 모두 거부됨.
--
-- 해결:
-- 모든 부동산 테이블은 서버측 데이터 캐시이지 사용자별 권한이 필요 없음. ai_headline_cache,
-- anomaly_daily 와 동일한 패턴으로 RLS 비활성.

ALTER TABLE real_estate_trade_raw    DISABLE ROW LEVEL SECURITY;
ALTER TABLE real_estate_rent_raw     DISABLE ROW LEVEL SECURITY;
ALTER TABLE mois_population          DISABLE ROW LEVEL SECURITY;
ALTER TABLE mois_household_by_size   DISABLE ROW LEVEL SECURITY;
ALTER TABLE stdg_admm_mapping        DISABLE ROW LEVEL SECURITY;
ALTER TABLE geo_stdg                 DISABLE ROW LEVEL SECURITY;
ALTER TABLE region_summary           DISABLE ROW LEVEL SECURITY;
ALTER TABLE buy_signal_result        DISABLE ROW LEVEL SECURITY;
ALTER TABLE region_migration         DISABLE ROW LEVEL SECURITY;
ALTER TABLE macro_rate_kr            DISABLE ROW LEVEL SECURITY;

-- 검증:
-- SELECT relname, relrowsecurity
--   FROM pg_class
--  WHERE relname IN (
--      'real_estate_trade_raw','real_estate_rent_raw','mois_population',
--      'mois_household_by_size','stdg_admm_mapping','geo_stdg','region_summary',
--      'buy_signal_result','region_migration','macro_rate_kr'
--  )
--  ORDER BY relname;
-- → 10행 모두 relrowsecurity = false 기대
