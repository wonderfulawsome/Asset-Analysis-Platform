-- 2026-05-10: chart_similarity_cache — AI 차트 유사 패턴 매칭 결과 통째 적재
-- 매일 1회 scheduler 가 28종(US 16 + KR 12) × 2 모드(shape/magnitude) = 56 entry 계산 → 적재.
-- 사용자 클릭 시 numpy 슬라이딩 윈도우 CPU 연산 0회, DB select 1회 만으로 즉시 응답.
-- chart_close_cache (raw close 시계열) 와 함께 운영. close 캐시는 라이브 폴백/실험용.
--
-- 컬럼:
--   ticker      — 'SPY' / '069500' 등
--   mode        — 'shape' (60일 모양 매칭) | 'magnitude' (126일 강도 매칭)
--   payload     — find_*_matches 응답 통째 (today_window, matches[], summary, ...)
--   updated_at  — 마지막 갱신 시각
-- PK = (ticker, mode) 로 매일 cron 시 upsert.

CREATE TABLE IF NOT EXISTS chart_similarity_cache (
    ticker TEXT NOT NULL,
    mode TEXT NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, mode)
);

CREATE INDEX IF NOT EXISTS idx_chart_similarity_cache_ticker_mode
    ON chart_similarity_cache(ticker, mode);

-- RLS 비활성화 (다른 캐시 테이블 정책과 동일)
ALTER TABLE chart_similarity_cache DISABLE ROW LEVEL SECURITY;
