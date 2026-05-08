-- 2026-05-09: page_view 테이블 — 사용자 페이지·탭 단위 조회 추적
-- 기존 user_visit 은 사용자 일자별 1행만 기록 → 페이지·탭별 조회는 잡히지 않음.
-- 본 테이블은 페이지 진입 / 탭 전환 / 페이지 이탈마다 1행씩 누적.
--
-- 컬럼:
--   user_hash   — 익명 해시 (user_visit 와 동일 source)
--   visit_date  — KST 날짜 (집계용)
--   visited_at  — 진입 시각 (정밀)
--   path        — '/stocks' '/about' '/landing' '/stats' 등
--   tab         — '/stocks' 안의 SPA 탭 식별자. nullable (다른 페이지는 null).
--                 e.g. 'ai-chart', 'market', 'fundamental', 'signal', 'sector',
--                       'sector-val', 'sector-mom', 'market-valuation'
--   dwell_ms    — 머문 시간 (ms). 페이지 이탈 / 탭 전환 시 sendBeacon 으로 보냄. nullable.

CREATE TABLE IF NOT EXISTS page_view (
    id BIGSERIAL PRIMARY KEY,
    user_hash TEXT NOT NULL,
    visit_date DATE NOT NULL,
    visited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    path TEXT NOT NULL,
    tab TEXT,
    dwell_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_page_view_date_path ON page_view(visit_date, path);
CREATE INDEX IF NOT EXISTS idx_page_view_date_path_tab ON page_view(visit_date, path, tab);
CREATE INDEX IF NOT EXISTS idx_page_view_user ON page_view(user_hash);

-- RLS 비활성화 (기존 user_visit 와 동일 정책)
ALTER TABLE page_view DISABLE ROW LEVEL SECURITY;
