-- 2026-05-07 — 시장 이상 탐지 (Anomaly Detection) 일별 결과 테이블
--
-- 신호 탭 (crash_surge 기반) 을 교체하는 "이상 탐지" 기능의 핵심 데이터.
-- "오늘의 시장 좌표가 historical 분포에서 얼마나 떨어져 있나" 를 descriptive 하게 측정.
--
-- 알고리즘:
--   - 10개 피처 벡터 x_t 구성 (noise_regime 8개 + yield_curve + VIX 절대값)
--   - 10년 rolling [t-10y, t-1] 로 μ, Σ 추정 (look-ahead 방지)
--   - Mahalanobis D²(t) = (x_t - μ)' Σ^-1 (x_t - μ)  ← 단일 이상도 점수
--   - percentile_10y / percentile_90d = D²(t) 의 historical 시계열 내 백분위
--   - top_contributors = D² 분해 시 기여 상위 3개 피처
--   - knn_dates = pairwise Mahalanobis 거리로 가장 가까운 과거 K개 시점 (최근 90일 제외)
--
-- 자문 리스크 차단을 위해 "예측" 이 아닌 "관측" 만 저장. 라벨/UI 는 모두 descriptive.

CREATE TABLE IF NOT EXISTS anomaly_daily (
    id                  BIGSERIAL PRIMARY KEY,
    region              TEXT NOT NULL,                   -- 'us' | 'kr' (현재 us 만, 향후 kr 확장)
    date                DATE NOT NULL,
    d2                  DOUBLE PRECISION,                -- Mahalanobis 거리 제곱
    percentile_10y      DOUBLE PRECISION,                -- 0~100 (10년 historical 분포 내 백분위)
    percentile_90d      DOUBLE PRECISION,                -- 0~100 (최근 90일 분포 내 백분위)
    feature_vector      JSONB,                           -- {fundamental_gap: 0.42, erp_zscore: -1.1, ...}
    top_contributors    JSONB,                           -- [{name, contribution}, ...] D² 분해 상위 3개
    knn_dates           JSONB,                           -- [{date, distance}, ...] 가장 비슷했던 과거 K개
    n_history           INTEGER,                         -- μ, Σ 추정에 쓴 표본 수 (안정성 신호)
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT anomaly_daily_region_date_unique UNIQUE (region, date)
);

CREATE INDEX IF NOT EXISTS anomaly_daily_region_date_idx
    ON anomaly_daily (region, date DESC);

-- RLS 비활성 — 서버측 캐시성 데이터 (사용자별 권한 분리 불필요).
-- ai_headline_cache 에서 RLS 누락으로 anon upsert 차단됐던 사고 방지.
ALTER TABLE anomaly_daily DISABLE ROW LEVEL SECURITY;

-- updated_at 자동 갱신 트리거 (기존 update_updated_at 함수 재사용)
CREATE TRIGGER anomaly_daily_updated_at
    BEFORE UPDATE ON anomaly_daily
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 검증:
-- SELECT column_name, data_type FROM information_schema.columns
--  WHERE table_name='anomaly_daily' ORDER BY ordinal_position;
-- → 10 컬럼 (id, region, date, d2, pct_10y, pct_90d, feature_vector,
--             top_contributors, knn_dates, n_history, created_at, updated_at) 기대
--
-- 백필 후:
-- SELECT date, ROUND(d2::numeric, 2) AS d2,
--        ROUND(percentile_10y::numeric, 1) AS pct10y,
--        ROUND(percentile_90d::numeric, 1) AS pct90d
--   FROM anomaly_daily
--  WHERE region='us'
--  ORDER BY date DESC LIMIT 10;
