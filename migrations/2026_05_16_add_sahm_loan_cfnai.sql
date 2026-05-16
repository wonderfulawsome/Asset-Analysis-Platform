-- 2026-05-16: sector_macro_raw 에 leading indicator 3종 + 기존 2026-05-13 누락분(unrate/hy_oas/vix) 컬럼 추가
-- 회복→둔화 보수화 목적 (사용자 결정)
-- SAHMREALTIME: Sahm Rule 실시간 침체신호 (>=0.5 침체 진입)
-- DRTSCILM:     은행 대출기준 강화 % (분기, 신용경색 leading)
-- CFNAI:        시카고 연준 국가활동지수 (85개 지표 종합 coincident)

ALTER TABLE sector_macro_raw
    ADD COLUMN IF NOT EXISTS unrate       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hy_oas       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS vix          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS sahm         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS loan_tighten DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS cfnai        DOUBLE PRECISION;
