-- ============================================================
-- Passive 앱 - Supabase 테이블 생성 SQL
-- SQL Editor에 붙여넣고 실행하세요.
-- ============================================================

-- 1. 거시 지표 원본 테이블
CREATE TABLE IF NOT EXISTS macro_raw (
    id           BIGSERIAL PRIMARY KEY,
    date         DATE NOT NULL UNIQUE,
    sp500_close  DOUBLE PRECISION,
    sp500_return DOUBLE PRECISION,
    sp500_vol20  DOUBLE PRECISION,
    vix          DOUBLE PRECISION,
    tnx          DOUBLE PRECISION,
    yield_spread DOUBLE PRECISION,
    dxy_return   DOUBLE PRECISION,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 2. HMM 시장 국면 결과 테이블
CREATE TABLE IF NOT EXISTS market_regime (
    id             BIGSERIAL PRIMARY KEY,
    date           DATE NOT NULL UNIQUE,
    regime_id      INTEGER,
    regime_name    TEXT,
    regime_emoji   TEXT,
    probabilities  JSONB,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- updated_at 자동 갱신 트리거
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER market_regime_updated_at
    BEFORE UPDATE ON market_regime
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 3. CNN Fear & Greed Index 원본 테이블
CREATE TABLE IF NOT EXISTS fear_greed_raw (
    id         BIGSERIAL PRIMARY KEY,
    date       DATE NOT NULL UNIQUE,
    score      DOUBLE PRECISION,
    rating     TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 1. index_name 컬럼 추가
ALTER TABLE market_regime ADD COLUMN index_name TEXT NOT NULL DEFAULT 'sp500';

-- 2. 기존 unique 제약 삭제 (제약 이름은 다를 수 있음)
ALTER TABLE market_regime DROP CONSTRAINT market_regime_date_key;

-- 3. (date, index_name) 복합 unique 제약 추가
ALTER TABLE market_regime ADD CONSTRAINT market_regime_date_index_key UNIQUE (date, index_name);

-- 4. ETF 가격 및 등락률 테이블
CREATE TABLE IF NOT EXISTS index_price_raw (
    id          BIGSERIAL PRIMARY KEY,
    date        DATE NOT NULL,
    ticker      TEXT NOT NULL,
    close       DOUBLE PRECISION,
    change_pct  DOUBLE PRECISION,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, ticker)
);

-- 5. 섹터 매크로 지표 원본 테이블 (FRED 8개 지표 + 파생 2개)
CREATE TABLE IF NOT EXISTS sector_macro_raw (
    id               BIGSERIAL PRIMARY KEY,
    date             DATE NOT NULL UNIQUE,
    pmi              DOUBLE PRECISION,
    yield_spread     DOUBLE PRECISION,
    anfci            DOUBLE PRECISION,
    icsa_yoy         DOUBLE PRECISION,
    permit_yoy       DOUBLE PRECISION,
    real_retail_yoy  DOUBLE PRECISION,
    capex_yoy        DOUBLE PRECISION,
    real_income_yoy  DOUBLE PRECISION,
    pmi_chg3m        DOUBLE PRECISION,
    capex_yoy_chg3m  DOUBLE PRECISION,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- 6. 섹터 경기국면 분석 결과 테이블
CREATE TABLE IF NOT EXISTS sector_cycle_result (
    id                  BIGSERIAL PRIMARY KEY,
    date                DATE NOT NULL UNIQUE,
    current_phase       INTEGER,
    phase_name          TEXT,
    phase_emoji         TEXT,
    probabilities       JSONB,
    phase_sector_perf   JSONB,
    phase_holding_perf  JSONB,
    top3_sectors        JSONB,
    macro_snapshot      JSONB,
    train_acc           DOUBLE PRECISION,
    test_acc            DOUBLE PRECISION,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER sector_cycle_result_updated_at
    BEFORE UPDATE ON sector_cycle_result
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 7. Noise vs Signal HMM 국면 결과 테이블
CREATE TABLE IF NOT EXISTS noise_regime (
    id             BIGSERIAL PRIMARY KEY,
    date           DATE NOT NULL UNIQUE,
    regime_id      INTEGER,
    regime_name    TEXT,
    regime_emoji   TEXT,
    noise_score    DOUBLE PRECISION,
    probabilities  JSONB,
    updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER noise_regime_updated_at
    BEFORE UPDATE ON noise_regime
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 8. XGBoost 폭락/급등 전조 결과 테이블
CREATE TABLE IF NOT EXISTS crash_surge_result (
    id           BIGSERIAL PRIMARY KEY,
    date         DATE NOT NULL UNIQUE,
    crash_score  DOUBLE PRECISION,
    crash_grade  TEXT,
    surge_score  DOUBLE PRECISION,
    surge_grade  TEXT,
    crash_raw    DOUBLE PRECISION,
    surge_raw    DOUBLE PRECISION,
    macro_f1     DOUBLE PRECISION,
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER crash_surge_result_updated_at
    BEFORE UPDATE ON crash_surge_result
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 9. SHAP/피처 설명용 JSONB 컬럼 추가
ALTER TABLE crash_surge_result ADD COLUMN IF NOT EXISTS shap_values JSONB;
ALTER TABLE crash_surge_result ADD COLUMN IF NOT EXISTS feature_importance JSONB;

ALTER TABLE noise_regime ADD COLUMN IF NOT EXISTS feature_contributions JSONB;
ALTER TABLE noise_regime ADD COLUMN IF NOT EXISTS feature_values JSONB;

-- 10. 사용자 방문 추적 테이블
CREATE TABLE IF NOT EXISTS user_visit (
    id           BIGSERIAL PRIMARY KEY,
    user_hash    TEXT NOT NULL,
    visit_date   DATE NOT NULL DEFAULT CURRENT_DATE,
    is_new       BOOLEAN DEFAULT FALSE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_hash, visit_date)
);

-- 사용자 최초 등장 여부를 빠르게 확인하기 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_user_visit_hash ON user_visit (user_hash);
CREATE INDEX IF NOT EXISTS idx_user_visit_date ON user_visit (visit_date);