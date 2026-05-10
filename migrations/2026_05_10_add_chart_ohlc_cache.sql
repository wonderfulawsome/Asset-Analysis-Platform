-- 2026-05-10: chart_ohlc_cache — AI 차트 캔들스틱 OHLC 시계열 통째 적재.
-- 기존 인메모리 캐시는 프로세스 단위라 재배포 시 증발. 28 ticker × 3 interval
-- (1d/1wk/1mo) = 84 entry 를 매일 cron 1회 yfinance/pykrx 외부 API 로 fetch →
-- 본 테이블 적재. /api/chart/ohlc 는 DB select 1회로 응답 (외부 API 0회).
--
-- 컬럼:
--   ticker      — 'SPY' / '069500' 등
--   interval    — '1d' | '1wk' | '1mo'
--   payload     — {ticker, interval, candles: [{d,o,h,l,c,v}, ...]}
--   updated_at  — 마지막 갱신 시각
-- PK = (ticker, interval) 로 매일 cron 시 upsert.

CREATE TABLE IF NOT EXISTS chart_ohlc_cache (
    ticker TEXT NOT NULL,
    interval TEXT NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, interval)
);

CREATE INDEX IF NOT EXISTS idx_chart_ohlc_cache_ticker_interval
    ON chart_ohlc_cache(ticker, interval);

ALTER TABLE chart_ohlc_cache DISABLE ROW LEVEL SECURITY;
