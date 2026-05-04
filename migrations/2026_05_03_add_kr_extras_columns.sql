-- 2026-05-03 — KR 시황 보강 컬럼 추가 (원/달러 환율 + 외국인 순매수)
--
-- 시장 요약 카드의 "공포·탐욕" 과 "P/C" 자리가 KR 모드에서 미적재 였는데,
-- 그 자리를 한국 시장 시황에 더 직접적인 지표로 대체:
--   1) 원/달러 환율 (USDKRW) — 외국인 자금 흐름의 가장 직접적 신호
--   2) 외국인 KOSPI 5일 누적 순매수 (억 원) — 매수세/매도세 직접 측정
--
-- 두 컬럼은 기본 NULL — US 행은 영향 없음. KR 행에서만 채움.

BEGIN;

ALTER TABLE macro_raw ADD COLUMN IF NOT EXISTS usdkrw DOUBLE PRECISION;
ALTER TABLE macro_raw ADD COLUMN IF NOT EXISTS usdkrw_change_pct DOUBLE PRECISION;
ALTER TABLE macro_raw ADD COLUMN IF NOT EXISTS foreign_net_buy_1d DOUBLE PRECISION;
ALTER TABLE macro_raw ADD COLUMN IF NOT EXISTS foreign_net_buy_5d DOUBLE PRECISION;

COMMIT;

-- 검증
-- SELECT date, usdkrw, usdkrw_change_pct, foreign_net_buy_5d
--   FROM macro_raw WHERE region='kr' ORDER BY date DESC LIMIT 5;
