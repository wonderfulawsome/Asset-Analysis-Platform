-- 홈 화면 AI 헤드라인 — region+lang 별 1행씩 (스케줄러 미리 생성, endpoint 즉시 응답).
--
-- 기존: in-memory _headline_cache (TTL 만료 시 LLM 즉석 호출, 서버 재시작 시 증발)
-- 변경: 스케줄러가 KR/US × ko/en 4 조합 미리 생성 → 이 테이블 upsert → endpoint DB 조회만

CREATE TABLE IF NOT EXISTS ai_headline_cache (
    id BIGSERIAL PRIMARY KEY,
    region TEXT NOT NULL,                    -- 'us' | 'kr'
    lang TEXT NOT NULL,                      -- 'ko' | 'en'
    summary TEXT NOT NULL,                   -- LLM 출력 (최종 정리된 1~2 문장)
    generated_at TEXT,                       -- KST 시간 문자열 (frontend 표시용)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT ai_headline_cache_region_lang_unique UNIQUE (region, lang)
);

CREATE INDEX IF NOT EXISTS ai_headline_cache_region_lang_idx
    ON ai_headline_cache (region, lang);
