-- 2026-05-09 — valuation_signal 에 z_per / z_trend / price_vs_ma200 컬럼 추가
--
-- 배경:
-- KR 시장 밸류 composite 가 0.4·z_ERP + 0.3·z_VKOSPI + 0.3·z_DD60 (단기 sentiment
-- 만) → "코스피 50%+ 급등인데 저평가" 오판 발생.
--
-- 해결:
-- collector/valuation_signal_kr.py 에 절대 valuation 앵커 2개 추가:
--   - z_per   = -(KOSPI PER - 15Y mean) / 15Y std    (PER 높음 → composite 음수)
--   - z_trend = -(close/MA200 - 1 - 5Y mean) / 5Y std (가격 추세 위 → composite 음수)
-- 새 가중치 W_PER 0.35 + W_TREND 0.25 + W_ERP 0.15 + W_VIX 0.10 + W_DD 0.15.
-- 이 컴포넌트 z 값을 DB 에 저장하려면 새 컬럼이 필요.
--
-- 적용:
ALTER TABLE valuation_signal
    ADD COLUMN IF NOT EXISTS z_per           DOUBLE PRECISION,    -- (KOSPI PER 15Y baseline 기준 z, 부호 반전 후)
    ADD COLUMN IF NOT EXISTS z_trend         DOUBLE PRECISION,    -- (close/MA200 5Y baseline 기준 z, 부호 반전 후)
    ADD COLUMN IF NOT EXISTS price_vs_ma200  DOUBLE PRECISION;    -- close / MA200 - 1 (raw)

-- 검증:
-- SELECT column_name FROM information_schema.columns
--  WHERE table_name='valuation_signal' AND column_name IN ('z_per','z_trend','price_vs_ma200');
-- → 3 rows 기대
--
-- 적용 후:
-- 다음 KR 스케줄러 cron (KST 16:00) 실행 시 새 컴포넌트 z 값 적재. 옛 row(z_per/
-- z_trend NULL) 는 그대로 유지 — frontend 가 NULL 인 컬럼은 0 또는 미표시.
