-- 5탭 AI 해설 (fundamental/signal/sector/sector-val/sector-mom) 캐시.
--
-- 기존: in-memory _explain_cache (TTL 만료/재시작 시 LLM 즉석 호출 1~3초 → 사용자 체감 느림)
-- 변경: 스케줄러가 tab × lang × region 조합 미리 생성 → endpoint 즉시 응답 (memory → DB)
--
-- 5 tab × 2 lang × 2 region = 최대 20 entry. 'sector-mom' 은 region 무관 (전역) 이라 더 적음.

CREATE TABLE IF NOT EXISTS ai_explain_cache (
    id BIGSERIAL PRIMARY KEY,
    tab TEXT NOT NULL,                       -- 'fundamental' | 'signal' | 'sector' | 'sector-val' | 'sector-mom'
    lang TEXT NOT NULL,                      -- 'ko' | 'en'
    region TEXT NOT NULL,                    -- 'us' | 'kr'  (sector-mom 은 'us' 로 통일)
    explanation TEXT NOT NULL,               -- LLM 출력 (정리된 텍스트)
    generated_at TEXT,                       -- KST 시간 문자열
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT ai_explain_cache_tab_lang_region_unique UNIQUE (tab, lang, region)
);

CREATE INDEX IF NOT EXISTS ai_explain_cache_lookup_idx
    ON ai_explain_cache (tab, lang, region);
