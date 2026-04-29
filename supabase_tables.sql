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


-- ============================================================
-- 부동산 테이블 (Asset-Analysis-Platform 통합)
-- ============================================================

-- 11. 국토부 매매 실거래 원본
CREATE TABLE IF NOT EXISTS real_estate_trade_raw (
    id              BIGSERIAL PRIMARY KEY,
    sgg_cd          TEXT NOT NULL,          -- 시군구 코드 5자리
    deal_ym         TEXT NOT NULL,          -- 수집 기준 연월 YYYYMM
    apt_nm          TEXT,
    apt_seq         TEXT,
    umd_nm          TEXT,                   -- 법정동명
    umd_cd          TEXT,                   -- 법정동 코드 5자리
    stdg_cd         TEXT,                   -- 법정동 코드 10자리 (sgg_cd + umd_cd)
    deal_amount     INTEGER,                -- 거래금액 (만원)
    exclu_use_ar    DOUBLE PRECISION,       -- 전용면적 m²
    floor           INTEGER,
    build_year      INTEGER,
    deal_date       DATE,
    dealing_gbn     TEXT,                   -- 중개거래/직거래
    road_nm         TEXT,
    lat             DOUBLE PRECISION,       -- 카카오 지오코딩 결과
    lng             DOUBLE PRECISION,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (apt_seq, deal_date, floor, exclu_use_ar)
);

CREATE INDEX IF NOT EXISTS idx_re_trade_sgg_ym   ON real_estate_trade_raw (sgg_cd, deal_ym);
CREATE INDEX IF NOT EXISTS idx_re_trade_stdg      ON real_estate_trade_raw (stdg_cd);
CREATE INDEX IF NOT EXISTS idx_re_trade_deal_date ON real_estate_trade_raw (deal_date);

-- 12. 국토부 전월세 실거래 원본
CREATE TABLE IF NOT EXISTS real_estate_rent_raw (
    id              BIGSERIAL PRIMARY KEY,
    sgg_cd          TEXT NOT NULL,
    deal_ym         TEXT NOT NULL,
    apt_nm          TEXT,
    apt_seq         TEXT,
    umd_nm          TEXT,
    deposit         INTEGER,                -- 보증금 (만원)
    monthly_rent    INTEGER,                -- 월세 (만원, 0이면 전세)
    exclu_use_ar    DOUBLE PRECISION,
    floor           INTEGER,
    deal_date       DATE,
    contract_type   TEXT,                   -- 신규/갱신
    road_nm         TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (apt_seq, deal_date, floor, exclu_use_ar, deposit, monthly_rent)
);

CREATE INDEX IF NOT EXISTS idx_re_rent_sgg_ym ON real_estate_rent_raw (sgg_cd, deal_ym);

-- 13. 행안부 법정동별 인구 원본
CREATE TABLE IF NOT EXISTS mois_population (
    id              BIGSERIAL PRIMARY KEY,
    stats_ym        TEXT NOT NULL,          -- YYYYMM
    stdg_cd         TEXT NOT NULL,          -- 법정동 코드 10자리
    stdg_nm         TEXT,
    sgg_nm          TEXT,
    tot_nmpr_cnt    INTEGER,                -- 총인구
    hh_cnt          INTEGER,                -- 총세대수
    hh_nmpr         DOUBLE PRECISION,       -- 세대당 인구
    male_nmpr_cnt   INTEGER,
    feml_nmpr_cnt   INTEGER,
    male_feml_rate  DOUBLE PRECISION,       -- 성비 (남/여)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (stats_ym, stdg_cd)
);

CREATE INDEX IF NOT EXISTS idx_mois_pop_ym ON mois_population (stats_ym);

-- 14. 행안부 행정동별 세대원수 분포 원본
CREATE TABLE IF NOT EXISTS mois_household_by_size (
    id              BIGSERIAL PRIMARY KEY,
    stats_ym        TEXT NOT NULL,
    admm_cd         TEXT NOT NULL,          -- 행정동 코드 10자리
    dong_nm         TEXT,
    sgg_nm          TEXT,
    tot_hh_cnt      INTEGER,
    hh_1            INTEGER,                -- 1인 가구수
    hh_2            INTEGER,
    hh_3            INTEGER,
    hh_4            INTEGER,
    hh_5            INTEGER,
    hh_6            INTEGER,
    hh_7plus        INTEGER,                -- 7인 이상 (hhNmprCnt7~10 합산)
    solo_rate       DOUBLE PRECISION,       -- 1인가구 비율 (hh_1 / tot_hh_cnt)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (stats_ym, admm_cd)
);

CREATE INDEX IF NOT EXISTS idx_mois_hh_ym ON mois_household_by_size (stats_ym);

-- 15. 법정동↔행정동 매핑 참조 테이블
CREATE TABLE IF NOT EXISTS stdg_admm_mapping (
    id          BIGSERIAL PRIMARY KEY,
    ref_ym      TEXT NOT NULL,              -- 매핑 기준 연월 YYYYMM
    stdg_cd     TEXT NOT NULL,             -- 법정동 코드 10자리
    stdg_nm     TEXT,
    admm_cd     TEXT NOT NULL,             -- 행정동 코드 10자리
    admm_nm     TEXT,
    ctpv_nm     TEXT,                      -- 시도명
    sgg_nm      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ref_ym, stdg_cd, admm_cd)
);

CREATE INDEX IF NOT EXISTS idx_mapping_stdg ON stdg_admm_mapping (stdg_cd);
CREATE INDEX IF NOT EXISTS idx_mapping_admm ON stdg_admm_mapping (admm_cd);

-- 16. 법정동 좌표 참조 테이블 (카카오 지오코딩 결과)
CREATE TABLE IF NOT EXISTS geo_stdg (
    id          BIGSERIAL PRIMARY KEY,
    stdg_cd     TEXT NOT NULL UNIQUE,
    stdg_nm     TEXT,
    sgg_nm      TEXT,
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 17. 지역 단위 Tier 1 집계 결과
CREATE TABLE IF NOT EXISTS region_summary (
    id                    BIGSERIAL PRIMARY KEY,
    sgg_cd                TEXT NOT NULL,
    stdg_cd               TEXT NOT NULL,
    stdg_nm               TEXT,
    stats_ym              TEXT NOT NULL,
    trade_count           INTEGER,
    avg_price             INTEGER,          -- 평균 거래가 (만원)
    median_price          INTEGER,          -- 중위 거래가 (만원)
    median_price_per_py   DOUBLE PRECISION, -- 중위 평단가 (만원/평)
    jeonse_count          INTEGER,
    wolse_count           INTEGER,
    avg_deposit           INTEGER,          -- 평균 전세 보증금 (만원)
    population            INTEGER,
    solo_rate             DOUBLE PRECISION,
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (stdg_cd, stats_ym)
);

CREATE TRIGGER region_summary_updated_at
    BEFORE UPDATE ON region_summary
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE INDEX IF NOT EXISTS idx_region_summary_sgg_ym ON region_summary (sgg_cd, stats_ym);

-- 18. 매수 타이밍 시그널 (Step A: 거래량·가격·인구 기반, B/C/D 컬럼은 향후 채움)
CREATE TABLE IF NOT EXISTS buy_signal_result (
    id                  BIGSERIAL PRIMARY KEY,
    sgg_cd              TEXT NOT NULL,
    stats_ym            TEXT NOT NULL,
    signal              TEXT NOT NULL,         -- 매수/관망/주의
    score               NUMERIC,
    trade_score         NUMERIC,
    price_score         NUMERIC,
    pop_score           NUMERIC,
    rate_score          NUMERIC,               -- Step B (ECOS 금리)
    flow_score          NUMERIC,               -- Step C (KOSIS 인구이동)
    feature_breakdown   JSONB,
    narrative           TEXT,                  -- Step D (LLM 해설)
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (sgg_cd, stats_ym)
);

CREATE INDEX IF NOT EXISTS idx_buy_signal_sgg_ym ON buy_signal_result (sgg_cd, stats_ym DESC);

-- 19. 한국은행 ECOS 거시 지표 (기준금리·주담대 금리·잔액)
-- 시계열 wide 형식: 한 행 = 한 날짜, 여러 지표를 컬럼으로 (Null 허용)
CREATE TABLE IF NOT EXISTS macro_rate_kr (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    base_rate       DOUBLE PRECISION,    -- 한국은행 기준금리 (%)
    mortgage_rate   DOUBLE PRECISION,    -- 예금은행 가계 주담대 가중평균 금리 (%, 신규 취급)
    mortgage_balance BIGINT,             -- 예금은행 주담대 잔액 (백만원)
    cycle           TEXT NOT NULL,       -- 'D' 일·'M' 월 (지표마다 상이라 mixed)
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_macro_rate_date ON macro_rate_kr (date DESC);

-- 20. 통계청 KOSIS 시군구 인구이동 (월별 전입·전출)
CREATE TABLE IF NOT EXISTS region_migration (
    id              BIGSERIAL PRIMARY KEY,
    sgg_cd          TEXT NOT NULL,       -- 시군구 코드 5자리
    stats_ym        TEXT NOT NULL,       -- YYYYMM
    in_count        INTEGER,             -- 전입자수
    out_count       INTEGER,             -- 전출자수
    net_flow        INTEGER,             -- in - out
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (sgg_cd, stats_ym)
);
CREATE INDEX IF NOT EXISTS idx_migration_sgg_ym ON region_migration (sgg_cd, stats_ym DESC);

-- 21. 섹터 밸류에이션 (PER/PBR 일별 스냅샷, 11개 GICS 섹터 ETF)
CREATE TABLE IF NOT EXISTS sector_valuation (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    ticker          TEXT NOT NULL,
    sector_name     TEXT,
    per             DOUBLE PRECISION,
    pbr             DOUBLE PRECISION,
    current_phase   INTEGER,        -- HMM 4상태 (회복=0/확장=1/둔화=2/침체=3)
    phase_name      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (date, ticker)
);
CREATE INDEX IF NOT EXISTS idx_sector_val_date ON sector_valuation (date DESC);


-- ── ERP + Composite Z (A1+C7) 일별 시그널 ──
-- ERP (Fed Model) + VIX + 60일 drawdown 합성 z-score. 라벨은 z_comp 기반.
CREATE TABLE IF NOT EXISTS valuation_signal (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    spy_per         DOUBLE PRECISION,         -- SPY trailing P/E
    earnings_yield  DOUBLE PRECISION,         -- 1 / SPY_per
    tnx_yield       DOUBLE PRECISION,         -- 10y treasury yield (^TNX / 100)
    erp             DOUBLE PRECISION,         -- earnings_yield - tnx_yield
    vix             DOUBLE PRECISION,         -- ^VIX close
    dd_60d          DOUBLE PRECISION,         -- SPY / max(SPY 60d) - 1 (음수)
    z_erp           DOUBLE PRECISION,         -- (erp - 5Y mean) / 5Y std
    z_vix           DOUBLE PRECISION,         -- (vix - 5Y mean) / 5Y std (양수=공포=저평가 신호)
    z_dd            DOUBLE PRECISION,         -- -(dd60 - 5Y mean) / 5Y std (양수=큰 drawdown)
    z_comp          DOUBLE PRECISION,         -- 0.4·z_erp + 0.3·z_vix + 0.3·z_dd
    label           TEXT,                     -- z_comp 기반: 명확한 저평가/다소 저평가/다소 고평가/명확한 고평가
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_valuation_signal_date ON valuation_signal (date DESC);
ALTER TABLE valuation_signal DISABLE ROW LEVEL SECURITY;

-- ── 마이그레이션 (기존 테이블이 이미 있으면 컬럼 추가) ──
ALTER TABLE valuation_signal
    ADD COLUMN IF NOT EXISTS vix     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dd_60d  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_erp   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_vix   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_dd    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_comp  DOUBLE PRECISION;