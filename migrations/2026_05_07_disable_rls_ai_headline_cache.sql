-- 2026-05-07 — ai_headline_cache RLS 비활성화
--
-- 문제:
-- 2026-05-03 add_ai_headline_cache 마이그레이션에서 테이블 생성 후 RLS 정책 미설정.
-- Supabase 는 신규 테이블에 RLS 를 기본 활성화하므로 anon 키 (스케줄러 + API
-- 백엔드가 사용) 의 INSERT/UPDATE 가 SQLSTATE 42501 (RLS 위반) 으로 차단.
-- 결과: precompute_home_headline 이 LLM 호출엔 성공하지만 upsert 단계에서 실패 →
-- ai_headline_cache 가 0 rows 상태로 유지 → endpoint 가 cache_miss 로 "해설 서비스
-- 개선중." 만 반환.
--
-- 해결:
-- ai_headline_cache 는 서버측 LLM 캐시이지 사용자별 데이터가 아니므로 RLS 불필요.
-- 기존 app_cache 와 동일하게 RLS 비활성화.

ALTER TABLE ai_headline_cache DISABLE ROW LEVEL SECURITY;

-- 검증:
-- SELECT relname, relrowsecurity
--   FROM pg_class
--  WHERE relname='ai_headline_cache';
-- → relrowsecurity = false 기대
