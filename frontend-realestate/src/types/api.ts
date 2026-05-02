// 백엔드(Supabase) 응답 타입 — 컬럼명이 snake_case 이므로 그대로 유지.
// FastAPI 라우터가 repositories 의 list[dict] 를 그대로 JSON 반환하기 때문에
// 프론트에서 camelCase 로 변환하지 않고 원본 키를 사용한다.

// GET /api/realestate/summary 의 한 법정동 레코드.
export interface RegionSummary {
  sgg_cd: string;
  stdg_cd: string;
  stdg_nm: string | null;
  stats_ym: string;
  trade_count: number | null;
  avg_price: number | null;          // 만원
  median_price: number | null;       // 만원
  median_price_per_py: number | null; // 만원/평
  jeonse_count: number | null;
  wolse_count: number | null;
  avg_deposit: number | null;        // 만원
  population: number | null;
  solo_rate: number | null;          // 0~1
}

// GET /api/realestate/trades 의 매매 실거래 레코드.
export interface Trade {
  sgg_cd: string;
  deal_ym: string;
  apt_nm: string | null;
  apt_seq: string | null;
  umd_nm: string | null;
  umd_cd: string | null;
  stdg_cd: string | null;
  deal_amount: number;               // 만원
  exclu_use_ar: number;              // m²
  floor: number | null;
  build_year: number | null;
  deal_date: string;                 // YYYY-MM-DD
  dealing_gbn: string | null;
  road_nm: string | null;
}

// GET /api/realestate/rents 의 전월세 실거래 레코드.
export interface Rent {
  sgg_cd: string;
  deal_ym: string;
  apt_nm: string | null;
  apt_seq: string | null;
  umd_nm: string | null;
  deposit: number;                   // 만원
  monthly_rent: number;              // 만원 (0이면 전세)
  exclu_use_ar: number;
  floor: number | null;
  deal_date: string;
  contract_type: string | null;
  road_nm: string | null;
}

// GET /api/realestate/population 의 법정동별 인구 레코드.
export interface Population {
  stats_ym: string;
  stdg_cd: string;
  stdg_nm: string | null;
  sgg_nm: string | null;
  tot_nmpr_cnt: number;
  hh_cnt: number;
  hh_nmpr: number;
  male_nmpr_cnt: number;
  feml_nmpr_cnt: number;
  male_feml_rate: number;
}

// GET /api/realestate/geo 의 법정동 좌표.
export interface GeoStdg {
  stdg_cd: string;
  lat: number | null;
  lng: number | null;
}

// GET /api/realestate/sgg-overview — 지도 폴리곤 색칠 + BottomBar 표기용
export interface SggOverview {
  sgg_cd: string;
  sgg_nm: string | null;
  stats_ym: string;
  median_price_per_py: number | null;
  change_pct_3m: number | null;        // 3개월 변화 (지도 폴리곤 색칠용)
  change_pct_1m: number | null;        // 1개월 변화 (FeatureCard 표시용)
  trade_count: number;
  top_stdg_cd: string | null;
  top_stdg_nm: string | null;
  // 부천(41194) 만 — 옛 일반구 sub-area (sosa/wonmi/ojeong) 별 top stdg.
  // geojson 폴리곤이 일반구 단위로 분할돼 있어 클릭한 폴리곤의 영역에 맞는 동을 따로 표시.
  bucheon_sub_top?: Record<string, {
    top_stdg_cd: string;
    top_stdg_nm: string | null;
    median_price_per_py: number;
    trade_count: number;
  }>;
}

// GET /api/realestate/stdg-detail — 법정동 상세 페이지 통합 응답
export interface ComplexSummary {
  apt_seq: string;
  apt_nm: string | null;
  build_year: number | null;
  trade_count: number;
  median_price_per_py: number;
}

export interface StdgDetail {
  summary: (RegionSummary & {
    change_pct_3m: number | null;
    trade_count_3m: number | null;
    jeonse_rate: number | null;
    net_flow: number | null;
  }) | null;
  timeseries: RegionSummary[];
  complexes: ComplexSummary[];
  signal: BuySignal | null;
}

// GET /api/realestate/complex-compare — 단지 비교용 (2~4개 동시)
export interface ComplexComparePoint {
  ym: string;
  median_price_per_py: number | null;
  trade_count: number;
  avg_sale: number | null;
  avg_jeonse: number | null;
  jeonse_rate: number | null;
}

export interface ComplexCompareItem {
  apt_seq: string;
  apt_nm: string | null;
  build_year: number | null;
  sgg_cd: string | null;
  umd_nm: string | null;
  timeseries: ComplexComparePoint[];
}

// GET /api/realestate/signal 의 매수 타이밍 시그널 1건.
export interface BuySignal {
  sgg_cd: string;
  stats_ym: string;
  signal: '매수' | '관망' | '주의';
  score: number;
  trade_score: number;
  price_score: number;
  pop_score: number;
  rate_score: number | null;     // Step B
  flow_score: number | null;     // Step C
  feature_breakdown: {
    trade_chg_pct: number;
    price_mom_pct: number;
    pop_chg_pct: number;
    // 지속성 (FeatureCard 요약 문장용)
    price_consec_months?: number;          // +N 연속 상승 / -N 연속 하락
    trade_consec_months?: number;
    trade_vs_long_ratio?: number | null;   // t-1 거래량 / 직전 12개월 평균 (1.0=동등)
    compare_n_months?: number;             // older 평균 산출 시 사용된 개월 수 (라벨용)
    // Step B (ECOS)
    base_rate?: number | null;
    base_rate_drop_pct?: number;
    mortgage_rate?: number | null;
    mortgage_rate_mom_pct?: number;
    // Step C (KOSIS)
    in_count?: number | null;
    out_count?: number | null;
    net_flow?: number;
  };
  narrative: string | null;      // Step D
}

// GET /api/realestate/timeseries 의 월별 시군구 rollup 배열 원소
export interface TimeseriesPoint {
  ym: string;                          // YYYYMM
  trade_count: number;
  jeonse_count: number;
  wolse_count: number;
  population: number;
  median_price_per_py: number | null;  // 만원/평 (구 평균)
  avg_deposit: number | null;          // 만원
  avg_price: number | null;            // 만원
  jeonse_rate: number | null;          // 0~1 (전세가율 = 보증금/매매)
}
