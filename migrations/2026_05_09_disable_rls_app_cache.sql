-- 2026-05-09 — app_cache RLS 비활성화
--
-- 문제:
-- 서버 로그에 다음 에러 반복:
--   [sgg-overview] cache write 실패: {'message': 'new row violates row-level security
--     policy for table "app_cache"', 'code': '42501', ...}
--   [emd-overview] cache write 실패: 동일
--   [ranking] cache write 실패: 동일
--
-- app_cache 는 사전 계산 결과(시군구·법정동 단위 매매가 변화율, 랭킹 TOP5 등)를
-- 적재해 endpoint cache lookup 으로 즉시 반환하기 위한 테이블. 그러나 anon 키로
-- INSERT/UPSERT 가 RLS 정책에 막혀 적재 실패. 매 요청 region_summary 4000+ row 를
-- 페이지네이션해 live compute (~10–15s 지연).
--
-- 해결:
-- app_cache 는 서버측 사전계산 캐시이지 사용자별 데이터가 아님 — RLS 불필요.
-- ai_headline_cache (2026_05_07_disable_rls_ai_headline_cache.sql) 와 동일 패턴으로
-- DISABLE.

ALTER TABLE app_cache DISABLE ROW LEVEL SECURITY;

-- 검증:
-- SELECT relname, relrowsecurity FROM pg_class WHERE relname='app_cache';
-- → relrowsecurity = false 기대
--
-- 적용 후 첫 endpoint 호출 (예: /api/realestate/sgg-overview) 은 여전히 ~12s
-- (live compute) 지만 그 결과가 app_cache 에 적재되어 다음 호출부터 < 100ms.
