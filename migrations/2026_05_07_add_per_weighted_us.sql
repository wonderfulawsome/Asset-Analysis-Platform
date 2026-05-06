-- US 섹터 밸류에이션에 가중평균 PER (절대값) 컬럼 추가.
-- 기존 `per` 컬럼 = fundamental_gap (ratio, US) 또는 ETF 가중평균 PER (KR) — 의미 충돌 분리.
-- 새 컬럼 `per_weighted` = ETF 보유종목 trailingPE × 비중 가중평균 (US/KR 공통 의미).

ALTER TABLE sector_valuation
  ADD COLUMN IF NOT EXISTS per_weighted DOUBLE PRECISION;

-- index 불필요 (date+ticker UNIQUE 이미 있음)
