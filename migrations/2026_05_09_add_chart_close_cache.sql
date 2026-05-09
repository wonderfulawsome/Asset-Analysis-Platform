-- 2026-05-09: chart_close_cache 테이블 — AI 차트 유사 패턴 매칭용 종가 시계열 캐시
-- 매일 1회 scheduler 가 모든 ticker (US 16 + KR 12 = 28종) 의 close 를 적재.
-- 사용자 클릭 시 yfinance/pykrx 외부 API 대신 DB select 만 → 응답 1~3초 → ~200ms.
--
-- 컬럼:
--   ticker      — 'SPY' / '069500' 등
--   date        — 거래일 (KST 기준 YYYY-MM-DD)
--   close       — 수정 종가 (float)
--   updated_at  — 마지막 갱신 시각 (감사용)
-- PK = (ticker, date) 로 같은 날 중복 방지.

CREATE TABLE IF NOT EXISTS chart_close_cache (
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);

-- ticker 별 날짜 정렬 인덱스 (DB select 시 ORDER BY date)
CREATE INDEX IF NOT EXISTS idx_chart_close_cache_ticker_date
    ON chart_close_cache(ticker, date);

-- RLS 비활성화 (다른 추적·캐시 테이블 정책과 동일)
ALTER TABLE chart_close_cache DISABLE ROW LEVEL SECURITY;
