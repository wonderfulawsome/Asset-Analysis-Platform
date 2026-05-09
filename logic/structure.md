# Passive Financial — 시스템 구조·로직 전체 문서

> 본 문서는 코드 변경이 있을 때마다 갱신한다. update.py 는 시간순 변경 이력, 본 문서는 "현재 시점의 시스템 청사진".

## 1. 개요

기존 **주식·ETF 분석 시스템(Passive)** 에 **부동산 분석 시스템** 을 통합한 단일 FastAPI 앱.
- 하나의 도메인에서 `/stocks`, `/realestate` 두 SPA를 서빙
- 모든 데이터는 Supabase Postgres에 적재
- APScheduler로 주기적 데이터 수집·가공·LLM 호출

### 1.1 도메인 아키텍처

```
┌────────────────────────────────────────────────────────────┐
│  외부 API (data.go.kr · ECOS · KOSIS · Kakao · FRED · 등)   │
└────────────────────────────────────────────────────────────┘
            ↓ collector/*.py (HTTP fetch + 정규화)
┌────────────────────────────────────────────────────────────┐
│  Supabase Postgres (raw + 가공 테이블 ~20종)                 │
└────────────────────────────────────────────────────────────┘
            ↓ processor/feature{N}_*.py (집계·신호 산출)
            ↓ scheduler/job.py (전체 파이프라인 오케스트레이션)
            ↓ database/repositories.py (모든 upsert/fetch)
┌────────────────────────────────────────────────────────────┐
│  FastAPI (api/app.py + api/routers/*.py)                    │
│   /stocks    → templates/stocks.html (Jinja2 + jQuery 앱)    │
│   /realestate → static/realestate/index.html (Vite + React)  │
└────────────────────────────────────────────────────────────┘
            ↓ apiFetch (frontend-realestate/src/api/client.ts)
┌────────────────────────────────────────────────────────────┐
│  React SPA (KakaoMap 폴리곤 + 법정동 상세 + AI 카드)          │
└────────────────────────────────────────────────────────────┘
```

---

## 2. 디렉토리 구조

```
Passive-Financial-Data-Analysis/
├─ api/
│   ├─ app.py                  ← FastAPI 진입점, 모든 라우터 include, lifespan에 스케줄러
│   └─ routers/
│       ├─ regime.py           시장 국면 (HMM)
│       ├─ macro.py            거시 지표
│       ├─ sector_cycle.py     섹터 경기국면
│       ├─ crash_surge.py      폭락/급등 전조 (XGBoost)
│       ├─ noise_regime.py     Noise vs Signal HMM
│       ├─ chart.py            앙상블 ETF 30일 예측
│       ├─ index_feed.py       ETF 가격 피드
│       ├─ market_summary.py   GPT/Groq 일일 마켓 요약
│       ├─ sector_cycle.py     섹터 경기국면 + ★ /valuation /momentum
│       └─ real_estate.py      ★ 부동산 — 14개 엔드포인트
├─ collector/
│   ├─ market_data.py          Yahoo Finance + macro
│   ├─ noise_regime_data.py    Shiller + FRED
│   ├─ sector_macro.py         FRED 섹터 매크로
│   ├─ sector_etf.py           ETF returns
│   ├─ index_price.py          ETF prices
│   ├─ fear_greed.py           CNN F&G 스크래핑
│   ├─ crash_surge_data.py     XGBoost용 raw + light
│   ├─ real_estate_trade.py    ★ MOLIT 매매·전월세
│   ├─ real_estate_population.py ★ MOIS 인구·세대원수·매핑
│   ├─ real_estate_geocode.py  ★ Kakao 로컬 (지오코딩)
│   ├─ ecos_macro.py           ★ 한국은행 ECOS (RATE_SPECS 6 + SECTOR_MACRO_SPECS 5, Q cycle 지원)
│   ├─ kosis_migration.py      ★ 통계청 KOSIS (인구이동)
│   ├─ kosis_macro.py          ★ 통계청 KOSIS 거시 4종 (광공업/소매/설비/건축)
│   ├─ sector_macro_kr.py      ★ KR 거시 12 + derived 2 통합 aggregator (ECOS+KOSIS)
│   ├─ sector_etf_kr.py        ★ KODEX/TIGER 10 sector + 8 holding returns + PER/PBR fallback
│   └─ sector_valuation.py     ★ yfinance Ticker.info — 11개 섹터 ETF PER/PBR
├─ processor/
│   ├─ feature1_regime.py      HMM 학습·예측
│   ├─ feature2_sector_cycle.py 섹터 경기국면
│   ├─ feature3_crash_surge.py XGBoost 폭락/급등
│   ├─ feature4_chart_predict.py 앙상블 ETF 예측
│   ├─ feature5_real_estate.py ★ 매핑 + 지역 집계
│   ├─ feature6_buy_signal.py  ★ 매수/관망/주의 시그널
│   ├─ feature7_sector_momentum.py ★ 섹터 1주·1개월 일별 누적수익률 + 1주 기준 랭킹
│   └─ sector_valuation_kr_backfill.py ★ KR sector PER/PBR proxy 60개월 backfill
├─ database/
│   ├─ supabase_client.py      threading.local() 싱글톤
│   └─ repositories.py         ★ 모든 테이블 upsert/fetch (단일 파일)
├─ scheduler/
│   └─ job.py                  ★ run_pipeline(light) — Step 1~9
├─ templates/
│   ├─ landing.html            / (주식/부동산 2버튼)
│   ├─ stocks.html             /stocks (jQuery)
│   └─ stats.html              /stats (공개 통계)
├─ static/
│   ├─ js/{main,chart,sector,i18n,home}.js  주식 화면 + ★ home.js (홈 라우터)
│   ├─ css/{main,home}.css                  ★ home.css 신규
│   ├─ img/                    주식 화면 자산
│   └─ realestate/             ★ Vite 빌드 산출물 (index.html + assets/ + geojson/)
├─ frontend-realestate/        ★ Vite + React + TS + Tailwind
│   ├─ public/geojson/{seoul-sgg,metro-sgg}.geojson  서울 25구(149KB) + 수도권 79폴리곤(70KB) — properties.sgg_cd 5자리 행안부 코드
│   ├─ src/
│   │   ├─ App.tsx             라우터
│   │   ├─ main.tsx
│   │   ├─ vite-env.d.ts       import.meta.env 타입
│   │   ├─ screens/            MapScreen / RegionDetail / StdgDetail / ComplexDetail / ComplexCompare / Ranking
│   │   ├─ components/         KakaoMap / NavBar / SignalCard / AiInsightCard /
│   │   │                      BottomBar / TimeSeriesChart / MetricGrid / MobileLayout / BottomSheet /
│   │   │                      ★ Bloomberg Terminal 재설계 (update.py [83]):
│   │   │                      TickerBar (KOSPI+BASE 60s polling) / TerminalSection (오렌지 ▓ 헤더) /
│   │   │                      TerminalMetric (LABEL/VALUE) / RegionCodeHeader (▓ RGN {code}) /
│   │   │                      SignalCounters (BUY/HOLD/WATCH) / ScoreBox (큰 SCORE/BUY + 5-cell) /
│   │   │                      MiniChart (콤팩트 strip)
│   │   ├─ store/mapStore.ts   Zustand
│   │   ├─ api/                client.ts + endpoints.ts
│   │   ├─ types/api.ts
│   │   ├─ lib/color.ts        ★ 변화율→색상 + 가격 포맷터 공용
│   │   └─ styles/globals.css
│   ├─ vite.config.ts          base="/static/realestate/", outDir="../static/realestate"
│   ├─ tsconfig.json, tailwind.config.ts, postcss.config.js
│   └─ package.json
├─ scripts/
│   ├─ build_frontend.sh        npm install + vite build
│   ├─ build_metro_geojson.py   ★ southkorea-maps → 수도권 metro-sgg.geojson 변환 (이름→행안부 LAWD_CD 매핑)
│   ├─ backfill_metro.py        ★ 수도권 77 LAWD_CD × N개월 backfill — 부천(41194)은 41192/41196 / 화성(41590)은 41591/41593/41595/41597 합산 (mapping/pop/trade/rent), --only/--start-from 분할 실행
│   ├─ flip_noise_score_sign.py noise_score 부호 일괄 반전 (1회성)
│   ├─ train_kr_sector_cycle.py ★ KR Sector Cycle (HMM 4-state) 1회 학습 + sector_macro/cycle/valuation 적재
│   ├─ sync_ui_design.sh        ★ 본 → "/root/UI 디자인" 단방향 프론트 미러 (rsync --delete, node_modules 제외)
│   └─ upload_dim.py
├─ .claude/
│   └─ settings.json            schema 키만 (hook 없음 — [98] 에서 자동 sync 해제)
├─ models/                     pkl 학습 모델 (HMM, XGBoost, ensemble)
├─ supabase_tables.sql         전체 DDL (~20 테이블)
├─ Dockerfile                  multi-stage (Node build → Python serve)
├─ .dockerignore               node_modules, data, notebooks 등 제외
├─ requirements.txt
├─ .env                        모든 API 키 (8종)
├─ CLAUDE.md                   ★ 작업 규칙 (update.py 자동 갱신)
├─ logic/structure.md          ★ 본 문서
└─ update.py                   변경 이력 ([1]~[N])
```

---

## 3. Supabase 테이블 (전체)

### 3.1 주식·거시 (기존)
- `macro_raw` — 거시지표 일별
- `market_regime` — HMM 시장 국면 (sp500/kospi)
- `noise_regime` — Noise vs Signal HMM
- `crash_surge` — XGBoost 폭락/급등 결과 (US 44 피처 / KR 24 피처, region 컬럼)
- `fear_greed_raw` — CNN F&G 일별
- `index_price_raw` — ETF 가격
- `sector_macro_raw` — FRED 섹터 매크로
- `sector_cycle_result` — 섹터 경기국면
- `chart_predict` — 앙상블 ETF 30일 예측
- `sector_valuation` ★ — 11개 섹터 ETF PER/PBR 일별 (date+ticker UNIQUE)
- `ai_headline_cache` ★ — 홈 화면 LLM 헤드라인 캐시 (region+lang UNIQUE) — 스케줄러 미리 생성

### 3.2 부동산 원천 (★ 신규)

| 테이블 | UNIQUE | 단위 | 의미 |
|---|---|---|---|
| `real_estate_trade_raw` | (apt_seq, deal_date, floor, exclu_use_ar) | 거래 1건 | MOLIT 매매 실거래가 |
| `real_estate_rent_raw` | + (deposit, monthly_rent) | 거래 1건 | MOLIT 전월세 |
| `mois_population` | (stats_ym, stdg_cd) | 법정동·월 | 인구·세대수·성비 |
| `mois_household_by_size` | (stats_ym, admm_cd) | 행정동·월 | 1~10인 세대수 + solo_rate |
| `stdg_admm_mapping` | (ref_ym, stdg_cd, admm_cd) | 매핑 | 법정동↔행정동 (지오코딩 캐시 포함) |
| `geo_stdg` | (stdg_cd) | 법정동 | 카카오 지오코딩 결과 (lat, lng) |

### 3.3 부동산 가공 결과 (★)
- `region_summary` UNIQUE (stdg_cd, stats_ym) — 법정동 단위 월별 집계
  - `trade_count`, `avg_price`, `median_price`, `median_price_per_py`
  - `jeonse_count`, `wolse_count`, `avg_deposit`
  - `population`, `solo_rate`
- `buy_signal_result` UNIQUE (sgg_cd, stats_ym) — 시그널·점수
  - `signal` ('매수'/'관망'/'주의'), `score`
  - `trade_score`, `price_score`, `pop_score`, `rate_score`(B), `flow_score`(C)
  - `feature_breakdown` JSONB, `narrative` TEXT(D)

### 3.4 거시 보조 (★)
- `macro_rate_kr` UNIQUE (date) — ECOS 시계열 (base_rate, mortgage_rate, mortgage_balance)
- `region_migration` UNIQUE (sgg_cd, stats_ym) — KOSIS 시군구 인구이동

---

## 4. 외부 API 카탈로그

### 4.1 부동산 거래 — 국토부 (data.go.kr `1613000`)
- **MOLIT 매매**: `RTMSDataSvcAptTradeDev` — 가용 2006-01~, 응답 XML camelCase
- **MOLIT 전월세**: `RTMSDataSvcAptRent` — 가용 2011-01~, 응답 XML (road 필드만 lowercase)
- 호출 단위: `LAWD_CD`(시군구 5자리) × `DEAL_YMD`(YYYYMM)
- 페이지네이션: `pageNo` + `numOfRows`(최대 1000)
- **resultCode "000" = 정상**, "003"=NODATA(빈 결과로 흡수)
- ⚠️ 동시 호출 시 **401 Unauthorized = quota throttle**. 호출 간격 0.3s+ + 401 발생 시 60s+ 회복 대기 필수

### 4.2 인구·매핑 — 행안부 (data.go.kr `1741000`)
- **인구**: `stdgPpltnHhStus/selectStdgPpltnHhStus` — `stdgCd`+`lv`+`regSeCd`
- **세대원수**: `admmHsmbHh/selectAdmmHsmbHh` — `admmCd`+`lv`
- **lv 의미**: 1=전국, 2=시도, 3=시군구, 4=읍면동/통반
- **stdgCd 10자리 = sgg(2)+sgg(3)+umd(5)**. 시군구 레벨은 뒤 5자리 0
- **resultCode "0" = 정상**, "3"=NODATA, "10"=INVALID_PARAMETER
- ⚠️ **2022-10부터만 가용 (3.5년 max)** — 더 이전 ym 호출 시 resultCode 10 에러
- ⚠️ 응답 XML root 는 대문자 `Response` (MOLIT 은 소문자 `response`)
- ⚠️ MOIS lv=4 reverse-extraction trick: 별도 매핑 API 없어 인구 API에 lv=4 호출하면 admmCd 부산물로 노출됨 → fetch_mapping_pairs

### 4.3 한국은행 ECOS
- 엔드포인트: `https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/{start}/{end}/{table}/{cycle}/{from}/{to}/{item}`
- REST path 형식 (query string 아님). cycle: D/M/Q/A
- 통계표 + 항목 검증된 코드 (StatisticItemList 직접 조회):
  - `722Y001/0101000`(M) = 기준금리
  - `121Y006/BECBLA0302`(M) = 주담대 신규취급 가중평균
  - `151Y005/11110A0`(M) = 예금은행 주담대 잔액
- 에러 응답: `{"RESULT": {"CODE": "INFO-200", "MESSAGE": "데이터 없음"}}`
- 1-2개월 lag (당월 미발표)

### 4.4 통계청 KOSIS
- 엔드포인트: `https://kosis.kr/openapi/Param/statisticsParameterData.do`
- 인구이동 통계표 `DT_1B26001` (시군구/성/연령(5세)별 이동자수)
- 분류: `objL1`=시군구, `objL2`=성별('0'=계), `objL3`=연령('000'=계)
- 항목 `itmId`: T10=전입, T20=전출, T25=순이동 (한 번에 `T10+T20+T25` 호출)
- ⚠️ **40,000셀/호출 한도** — 시군구 100개씩 chunk 호출

### 4.5 Kakao 로컬
- 지오코딩: `https://dapi.kakao.com/v2/local/search/address.json` (Authorization: `KakaoAK {REST_KEY}`)
- ⚠️ **응답 좌표 = (y=lat, x=lng) 순서 반대**
- ⚠️ **JS SDK 키는 도메인 화이트리스트** 등록 필수 (developers.kakao.com → 앱 설정 → 플랫폼 키 → JS SDK 도메인)

---

## 5. Collector 모듈 (각 함수 시그니처)

> 5.1~5.5 는 **호출자가 쓰는 공개 API** 만 적는다. 실제 동작은 5.0 의 공통 내부 헬퍼 4단을 거친다.

### 5.0 공통 내부 패턴 (모든 collector 공통)
각 파일은 `fetch_xxx()` 공개 함수 안에서 다음 4단 헬퍼를 호출한다 (`_` 접두사 = private).

```python
# collector/real_estate_trade.py 정의
_fetch_page(url, params)        # MOLIT 1페이지 HTTP GET (타임아웃·재시도 포함, XML text 반환)
_fetch_all(url, base_params)    # numOfRows/pageNo 루프로 MOLIT 전체 페이지를 누적 수집
_parse_molit_response(xml)      # MOLIT XML→dict 파싱 + resultCode "000" 검증, "003"=NODATA는 빈 결과로 흡수
_normalize_items(items_raw)     # xmltodict 단/복수 함정(item이 1개면 dict, 다수면 list) 흡수 → 항상 list[dict]

# collector/real_estate_population.py 정의 (MOIS 변형, 동일 4단)
_fetch_page_mois(url, params)        # MOIS 1페이지 HTTP GET (타임아웃·재시도)
_fetch_all_mois(url, base_params)    # numOfRows/pageNo 루프로 MOIS 전체 페이지 수집
_parse_mois_response(xml)            # MOIS XML→dict + resultCode "0" 검증, "3"=NODATA → 빈 결과
_normalize_items(items_raw)          # xmltodict 단/복수 함정 흡수 → 항상 list[dict]
```

호출 흐름 (real_estate_trade 예):
```
fetch_trades(sgg_cd, ym)
  └─ _fetch_all(url, params)
       └─ _fetch_page(url, params)        # 페이지마다 호출
            └─ _parse_molit_response(xml) # resultCode "0"/"000" 검증
                 └─ _normalize_items(...)  # 단일 dict도 [dict]로 통일
```

- 행안부(MOIS) 쪽은 동일 4단을 `_fetch_all_mois / _fetch_page_mois / _parse_mois_response / _normalize_items` 로 명명
- ECOS·KOSIS·Kakao 는 JSON 응답이라 `_parse_*_response` 없이 `requests` + dict 추출만
- FRED·Yahoo 류는 `_fetch_fred / _fetch_yahoo_*` 로 fetch만 하고, 정규화는 호출자(`fetch_xxx`)가 직접 pandas 로 처리

### 5.1 `collector/real_estate_trade.py`
```python
fetch_trades(sgg_cd: str, deal_ym: str) -> list[dict]   # 시군구·월 단위 MOLIT 매매 실거래가 전건 fetch
fetch_rents(sgg_cd: str, deal_ym: str) -> list[dict]    # 시군구·월 단위 MOLIT 전월세 실거래가 전건 fetch
# 응답: camelCase dict 리스트 (aptNm, aptSeq, dealAmount, excluUseAr, ...)
```

### 5.2 `collector/real_estate_population.py`
```python
fetch_population(stdg_cd: str, ym: str) -> list[dict]          # 시군구(lv=3) 인구·세대수·성비 월별 fetch
fetch_household_by_size(admm_cd: str, ym: str) -> list[dict]   # 행정동(lv=4) 1~10인 세대원수 분포 fetch
fetch_mapping_pairs(stdg_cd: str, ym: str) -> list[dict]       # 인구 API에 lv=4 호출해 admmCd 부산물로 법정동↔행정동 매핑 추출
fetch_all_sgg_codes(ym: str) -> list[str]                      # lv=1→lv=2 두 단계 호출로 전국 시군구 5자리 코드 수집
```

### 5.3 `collector/real_estate_geocode.py`
```python
geocode(address: str) -> dict | None                        # Kakao 로컬 API로 주소 1건을 (lat, lng)으로 변환 (실패 시 None)
batch_geocode(addresses: list[str]) -> list[dict | None]    # 주소 리스트를 순차 지오코딩 (rate-limit·실패 None 흡수)
```

### 5.4 `collector/ecos_macro.py`
```python
SPECS = {
  "base_rate":        {"table": "722Y001", "item": "0101000",    "cycle": "M"},
  "mortgage_rate":    {"table": "121Y006", "item": "BECBLA0302", "cycle": "M"},
  "mortgage_balance": {"table": "151Y005", "item": "11110A0",    "cycle": "M"},
}
fetch_ecos_series(metric: str, from_ym: str, to_ym: str) -> list[dict]   # SPECS의 단일 지표(table+item)를 ECOS REST path로 호출 → 시계열 list 반환
fetch_macro_rate_kr(months: int = 24) -> list[dict]                       # 3지표를 fetch_ecos_series로 받아 date 기준 wide-format으로 합쳐 반환
```

### 5.5 `collector/kosis_migration.py`
```python
fetch_kosis_migration(sgg_cds: list[str], months: int = 12) -> list[dict]   # KOSIS DT_1B26001 시군구 전입·전출·순이동 fetch (40,000셀 한도 회피용 100구씩 chunk)
```

---

## 6. Processor 모듈

### 6.1 `processor/feature5_real_estate.py`
```python
build_mapping(sgg_cd: str, ref_ym: str) -> list[dict]   # 시군구의 법정동↔행정동 매핑 한 벌을 MOIS lv=3·lv=4 호출로 구축
# lv=3으로 시군구→법정동 목록 → 각 stdgCd에 lv=4 매핑 호출 (reverse extract)

compute_region_summary(trades, rents, population, mapping, household, sgg_cd, stats_ym) -> list[dict]   # raw 입력 5종을 받아 법정동 단위 region_summary 행 리스트 산출
# 매매 평단가·중위 계산 → 법정동별 그룹핑
# 1인가구 비율: 행정동 세대원수 → 매핑으로 법정동 가중합
```

### 6.2 `processor/feature6_buy_signal.py`
```python
compute_buy_signal(ts: list[dict], rate_ts=None, flow_ts=None) -> dict | None   # 시군구 시계열·금리·인구이동을 합쳐 매수/관망/주의 시그널 dict 산출
# ts: region_summary 시계열 (ym, trade_count, median_price_per_py, population)
# 점수화:
#   trade_score = clamp(trade_chg * 100, -30, 30)
#   price_score = clamp(price_mom * 200, -30, 30)
#   pop_score   = clamp(pop_chg * 500, -20, 20)
#   rate_score (B) = clamp(base_drop*25 - mort_chg*1000, -25, 25)
#   flow_score (C) = clamp(net_flow / 100, -20, 20)
# 임계: total >= +15 = 매수, <= -15 = 주의, else 관망
```

---

## 7. Repository 함수 (database/repositories.py)

부동산 관련 (~20개):
```python
# 원천
upsert_re_trades(records)            # MOLIT 매매 정규화 행을 real_estate_trade_raw에 batch upsert (UNIQUE 4키 충돌 시 갱신)
fetch_re_trades(sgg_cd, ym)          # 시군구·월의 매매 raw 행 전건 조회
upsert_re_rents(records)             # MOLIT 전월세 정규화 행을 real_estate_rent_raw에 upsert (deposit·monthly_rent 추가 키)
fetch_re_rents(sgg_cd, ym)           # 시군구·월의 전월세 raw 행 전건 조회
upsert_mois_population(records)      # MOIS 인구·세대수 행을 mois_population에 upsert
fetch_mois_population(sgg_cd, ym)    # 시군구의 해당 월 법정동 인구 행 조회
upsert_mois_household(records)       # MOIS 행정동 1~10인 세대원수 행을 mois_household_by_size에 upsert
fetch_mois_household(sgg_cd, ym)     # 시군구의 해당 월 행정동 세대원수 행 조회
upsert_stdg_admm_mapping(records)    # 법정동↔행정동 매핑(+선택적 좌표) 캐시 upsert
fetch_stdg_admm_mapping(sgg_cd, ref_ym)   # 시군구·기준월의 매핑 행 조회
upsert_geo_stdg(records)             # 법정동 카카오 지오코딩 결과(lat·lng) upsert
fetch_geo_stdg(sgg_cd)               # 시군구 내 모든 법정동 좌표 조회

# 가공
upsert_region_summary(records)                     # 법정동 단위 월별 집계 행 batch upsert (UNIQUE: stdg_cd+stats_ym)
fetch_region_summary(sgg_cd, ym)                   # 시군구의 해당 월 법정동 집계 리스트
fetch_region_timeseries(sgg_cd)                    # 시군구 단위 12M 시계열 (월별 합산/평균)
fetch_region_by_stdg_cd(stdg_cd, ym)               # 단일 법정동·월의 region_summary 1행
fetch_region_timeseries_by_stdg(stdg_cd, months=12)   # 단일 법정동의 최근 N개월 시계열
fetch_complex_summary_by_stdg(stdg_cd, ym, top=10)    # 법정동 내 apt_seq별 거래 그룹 TOP-N (단지 카드용)
fetch_complex_compare(apt_seqs, months=12)            # 여러 단지의 평단가·거래량·전세가율 시계열 묶음 (비교 화면용)

# 시그널
upsert_buy_signal(record)             # 시군구·월의 매수 시그널 1행 upsert (점수·narrative 포함)
fetch_buy_signal(sgg_cd, ym=None)     # 시군구의 특정 월(또는 최신) 시그널 1행 조회
fetch_buy_signal_history(sgg_cd)      # 시군구의 시그널 시계열 (ym 오름차순)

# 거시
upsert_macro_rate_kr(records)        # ECOS 3지표 wide rollup 일/월 행 upsert (UNIQUE: date)
fetch_macro_rate_kr(months=24)       # 최근 N개월 거시 금리 시계열 조회
upsert_region_migration(records)     # KOSIS 시군구 인구이동(전입·전출·순이동) 월별 upsert
fetch_region_migration(sgg_cd)       # 시군구의 인구이동 시계열 조회
```

---

## 8. API 엔드포인트 (api/routers/real_estate.py)

```
GET /api/realestate/config                          # KAKAO_JS_KEY (프론트 SDK용)

# 원천 데이터
GET /api/realestate/trades?sgg_cd=&ym=
GET /api/realestate/rents?sgg_cd=&ym=
GET /api/realestate/population?sgg_cd=&ym=
GET /api/realestate/household?sgg_cd=&ym=
GET /api/realestate/mapping?sgg_cd=&ref_ym=
GET /api/realestate/geo?sgg_cd=

# 가공·집계
GET /api/realestate/summary?sgg_cd=&ym=             # 시군구의 법정동 리스트
GET /api/realestate/timeseries?sgg_cd=              # 시군구 12M 차트
GET /api/realestate/sgg-overview?ym=                # 지도 폴리곤 색칠용 (전국)
GET /api/realestate/stdg-detail?stdg_cd=&ym=        # 법정동 상세 통합 응답
GET /api/realestate/complex-compare?apt_seqs=A,B&months=  # 단지 비교 (최대 4개)

# 시그널·거시
GET /api/realestate/signal?sgg_cd=&ym=
GET /api/realestate/signal/history?sgg_cd=
GET /api/realestate/macro-rate?months=
GET /api/realestate/migration?sgg_cd=
```

기본값:
- `ym` 미지정 시 `_default_ym()` = **전월 YYYYMM** (MOIS lag 대응)

---

## 9. Scheduler (scheduler/job.py — `run_pipeline(light)`)

```
Step 1: macro_raw 수집·저장 (FRED)
Step 2: macro_raw upsert
Step 3: Noise vs Signal HMM (전체 모드만)
  Step 3f: 백필
Step 4: Fear & Greed + PUT/CALL
Step 5: ETF 가격 (31개)
  Step 5b: 경량 모드 crash/surge 실시간 예측
  Step 5c: 경량 모드 Noise HMM 실시간 예측
Step 6: 섹터 경기국면 (XGBoost)
Step 7: 폭락/급등 전조 (XGBoost)
  Step 7b: 백필
Step 8: 앙상블 ETF 30일 예측
Step 8b: ★ ECOS 거시지표 (24개월)
Step 9: ★ 부동산 — re_ym = 전월
  - fetch_all_sgg_codes() → 전국 ~245구
  - KOSIS 인구이동 한 번에
  - 시군구 루프:
      MOLIT 매매·전월세 fetch + 정규화 + dedupe + upsert
      MOIS 인구·매핑·세대원수 fetch + 누적 dedupe + upsert
      compute_region_summary → upsert
      compute_buy_signal(ts, rate_ts, flow_ts) → upsert
      신규 법정동만 batch_geocode → upsert_geo_stdg
```

스케줄: lifespan에서 `BackgroundScheduler` 등록
- 경량(light=True): 10분마다
- 전체(light=False): 3시간마다

---

## 10. 정규화 헬퍼 (scheduler/job.py)

API 응답(camelCase, 값=str) → DB 스키마(snake_case, typed) 변환:

```python
_re_norm_trades(items, sgg_cd, deal_ym)       # MOLIT 매매 raw → DB 스키마 dict + UNIQUE 4키 기준 in-batch dedupe
_re_norm_rents(items, sgg_cd, deal_ym)        # MOLIT 전월세 raw → DB 스키마 dict + UNIQUE 6키(매매4 + deposit/monthly_rent) dedupe
_re_norm_population(items, stats_ym)          # MOIS 인구 raw → mois_population 행 (stdg_cd, 인구·세대수·성비 typed)
_re_norm_household(items, stats_ym)           # MOIS 세대원수 raw → 행정동별 hhNmprCnt7~10 합산해 hh_7plus, solo_rate 산출
_re_norm_mapping(pairs)                       # lv=4 reverse-extract pair → stdg_admm_mapping 행 정규화
```

각 함수 내부 dedupe 외에 호출자(Step 9) 측에서도 누적 dedupe 필요 (특히 household — MOIS가 상위 admm 호출 시 하위까지 포함 반환).

---

## 11. 프론트엔드 (frontend-realestate/)

### 11.1 빌드·서빙
- Vite `base="/static/realestate/"`, `outDir="../static/realestate"`
- FastAPI: `/realestate/*` 모든 경로 → `FileResponse('static/realestate/index.html')` (React Router catch-all)
- `public/` 디렉토리 정적 자산 자동 복사 (geojson 포함)

### 11.2 라우트 (src/App.tsx)
```
/                       → MapScreen (지도 폴리곤)
/region/:sggCd          → RegionDetailScreen (시군구 + 법정동 리스트)
/stdg/:stdgCd           → StdgDetailScreen (법정동 상세 + 비교 모드)
/compare?seqs=A,B&sgg=  → ComplexCompareScreen (단지 2~4개 overlay 비교)
/complex/:aptSeq        → ComplexDetailScreen (단지 거래 이력)
/search /favorite /menu → Placeholder (탭바)
```

### 11.3 화면 구성

**MapScreen**
- KakaoMap 폴리곤(서울 25구, public/geojson/seoul-sgg.geojson)
- 색상: `lib/color.ts` `changePctColor(change_pct_3m)` (5단계 빨강→파랑)
- 폴리곤 클릭 → BottomBar 슬라이드 인 → 클릭 → `/stdg/:topStdgCd`
- 상단 검색바 (placeholder, 클릭 시 /search)
- 상단 색상 범례

**StdgDetailScreen**
1. NavBar (큰 동명 + 업데이트 월)
2. 헤더 배지 (상승/보합/하락 — change_pct_3m + signal 조합)
3. AiInsightCard (룰베이스 placeholder, narrative 채워지면 우선 사용)
4. 메트릭 4칸 (평균 매매가 / 거래량 3M / 전세가율 / 순이동)
5. 12M 평단가 추이 차트 (TimeSeriesChart)
6. 동 내 단지 TOP 10 (apt_seq 클릭 → /complex)

**RegionDetailScreen** (시군구 — 보조)
- 시그널 카드 + 메트릭 4칸 + 시계열 차트 4종 + 법정동 순위 리스트

**ComplexDetailScreen**
- /trades?sgg_cd= 페치 후 클라이언트에서 apt_seq 필터
- 거래 테이블

**ComplexCompareScreen** (단지 비교 — 나란히 보기)
- StdgDetailScreen 의 단지 리스트에서 "비교" 토글 → 카드에 체크박스 → 2~4개 선택 → 플로팅 버튼 → /compare 이동
- 상단 단지 카드 (시리즈 색 indicator + 단지명·연식)
- 3종 MultiSeriesChart overlay: 평단가 / 거래량 / 전세가율
- MultiSeriesChart 는 SVG 직조, 시리즈마다 다른 색 (SERIES_COLORS 4가지)
- 단지 카드 클릭 시 /complex/:apt_seq 이동

### 11.4 공용 유틸 (src/lib/color.ts)
```typescript
changePctColor(pct: number | null): string   // 변화율(%)을 5단계 빨강↔파랑 폴리곤 fill 컬러로 매핑 (null=회색)
changePctTextColor(pct): string              // 변화율 부호별 텍스트 색 클래스 반환 (양수 red / 음수 blue / null gray)
formatPrice(man: number | null): string      // 만원 단위 정수를 "X.X억"(≥10000만) 또는 "X,XXX만" 라벨로 포맷
```

### 11.5 데이터 흐름
```
브라우저 → /api/realestate/sgg-overview        # 25구 변화율
        → /static/realestate/geojson/seoul-sgg.geojson  # 폴리곤 좌표
        → name 매칭 → KakaoMap polygons prop
        → 폴리곤 클릭 → BottomBar 표시 (sgg_nm + top_stdg_nm + 평단가 + 변화율)
        → 바 클릭 → /stdg/:topStdgCd
        → /api/realestate/stdg-detail
        → StdgDetailScreen 렌더
```

---

## 12. 매수 시그널 알고리즘 (상세)

### 12.1 점수 산출 (compute_buy_signal)

**Step A — 부동산 3변수**
```
trade_chg  = (latest.trade_count - mean(prev_trades)) / mean(prev_trades)
price_mom  = (latest.median_price_per_py - prev.median_price_per_py) / prev.median_price_per_py
pop_chg    = (latest.population - prev.population) / prev.population

trade_score = clamp(trade_chg * 100, -30, 30)
price_score = clamp(price_mom * 200, -30, 30)
pop_score   = clamp(pop_chg * 500, -20, 20)
```

**Step B — ECOS 금리**
```
window = 최근 12개월 ECOS rate_ts (target_ym 까지)
base_drop  = (max_12m - now) / max_12m       # 0~1, 클수록 매수 우호
mort_mom   = (now - prev) / prev              # 음수=하락=우호
rate_score = clamp(base_drop * 25 - mort_mom * 1000, -25, 25)
```

**Step C — KOSIS 인구이동**
```
target 월의 net_flow (전입-전출)
flow_score = clamp(net_flow / 100, -20, 20)   # 1000명 = ±10점
```

**Step D — LLM 해설 (미구현)**
- `_groq_call(system, user)` 으로 narrative 생성, `narrative` 컬럼 채움
- 룰베이스 placeholder 는 frontend AiInsightCard 가 자체 생성

### 12.2 분류
```
total = trade + price + pop + (rate or 0) + (flow or 0)
total >= +15 → 매수
total <= -15 → 주의
else         → 관망
```

### 12.3 호출 흐름 (scheduler/job.py Step 9)
```python
ts      = fetch_region_timeseries(sgg_cd)        # 법정동 단위 시계열
rate_ts = fetch_macro_rate_kr(months=24)         # 한 번 fetch, 모든 시군구 재사용
flow_ts = fetch_region_migration(sgg_cd)
signal  = compute_buy_signal(ts, rate_ts=rate_ts, flow_ts=flow_ts)
upsert_buy_signal({**signal, 'sgg_cd': sgg_cd})
```

---

## 13. 운영 노트

### 13.1 환경 변수 (.env)
```
SUPABASE_URL=https://xxx.supabase.co     # 끝에 /rest/v1/ 붙이면 안 됨!
SUPABASE_KEY=sb_secret_xxx                # service_role (anon X)
DATA_GO_KR_KEY                            # MOLIT + MOIS 공용 (64자)
KAKAO_REST_KEY                            # 백엔드 지오코딩 (32자)
KAKAO_JS_KEY                              # 프론트 SDK (32자)
ECOS_API_KEY                              # 한국은행 (20자)
KOSIS_API_KEY                             # 통계청 (44자)
GROQ_API_KEY                              # LLM (Step D, market_summary 등)
RUN_SCHEDULER=true                        # false=스케줄러 비활성
```

### 13.2 WSL2 DNS 안정화
```
/etc/wsl.conf:
  [network]
  generateResolvConf = false

/etc/resolv.conf:
  nameserver 1.1.1.1
  nameserver 8.8.8.8
```

### 13.3 data.go.kr 401 quota 대응
- 단발 호출: 정상 (200)
- 연속 대량 호출: 401 Unauthorized (분당/일일 throttle)
- 대응: 호출 간 0.3s+ sleep, 401 발생 시 60s+ 회복 대기

### 13.4 Supabase 제약
- 무료 티어 1GB
- supabase-py 는 DDL 미지원 (CREATE TABLE은 SQL Editor 수동)
- upsert 시 같은 batch 안 unique key 중복 → 21000 에러 (반드시 사전 dedupe)
- 새 키 포맷 `sb_secret_xxx` 41자 — JWT 200+자 아님

### 13.5 카카오맵 도메인 등록
- developers.kakao.com → 내 앱 → "앱 설정 > 플랫폼 키" → JavaScript 키 → "JavaScript SDK 도메인" 에 `http://localhost:8000` 등 추가
- 미등록 시 SDK 로드 자체가 401 (script.onerror)

---

## 14. 알려진 한계·제약

| 항목 | 한계 | 사유 |
|---|---|---|
| MOIS 인구·세대원수 | 2022-10부터만 (3.5년) | 행안부 OpenAPI 시작 시점 |
| MOLIT 호출 속도 | 분당 ~200 (0.3s 간격) | data.go.kr quota |
| 폴리곤 지도 | 서울 25구만 | GeoJSON 파일 미준비 (전국 가능, 파일 크기 증가) |
| AI 해설 | 룰베이스 placeholder | Step D `_groq_call` 통합 미완 |
| 단지 적정가 비교 (유사단지 벤치마크) | 미구현 | 평형·연식 필터 기반 분포 분석 별도 endpoint 필요 |
| 동영상·VR 매물 | 미구현 | 별도 데이터 소스 |
| 법정동 단위 시그널 | 시군구만 | buy_signal 시군구 단위 — 법정동도 가능하나 더미 인구만 차이 |

---

## 15. 향후 확장 포인트

### 15.1 데이터
- 건축HUB API (입주 예정 물량·미분양·허가)
- 공동주택 단지 정보 (K-Apt) — 관리비·세대수
- 상권·유동인구 (서울열린데이터)
- 학교알리미 (학군)
- 지하철역 좌표·운행정보
- 전국 시군구·법정동 GeoJSON 확장

### 15.2 기능
- **Step D LLM 해설**: `_groq_call` 재사용해 narrative 채움 (`api/routers/market_summary.py:_groq_call` 패턴)
- **단지 적정가 비교**: `/api/realestate/complex/benchmark` — 평형·연식·시군구 필터로 유사 단지 평단가 분포
- **상세 페이지 전월세 흐름·평형별 가격·거래량 변화**: `/trades?ym=` 여러 월 호출 또는 시계열 endpoint 추가
- **알림 (시그널 매수 전환)**: 사용자 favorite 시군구의 signal 변화 push
- **시장 밸류 composite z (적용 완료, 2026-04-29)**: `collector/valuation_signal.py` 가 `z_comp = 0.4·z_ERP(5Y) + 0.3·z_VIX(5Y) + 0.3·z_DD60(5Y)` 산출 → `valuation_signal` 테이블에 6개 컬럼(vix/dd_60d/z_erp/z_vix/z_dd/z_comp) 추가. `/api/macro/valuation-signal` 응답에 `baselines_5y={erp,vix,dd,weights}` + 각 행 `z_*` 포함. 부호 컨벤션: 양수=저평가/공포 (DD 부호 반전). Baseline 캐시: `models/valuation_baselines.json` (TTL 90일). 한계: mild 충격은 max +0.84σ 가 천장 — 임계 완화 / EWMA / VIX intraday high 가 후보.
- **KR 등가 (적용 완료, 2026-05-02 ~ 05-03)**: `collector/valuation_signal_kr.py` (KOSPI PER + KR 10Y + VKOSPI + DD60), `collector/noise_regime_data_kr.py` (KOSPI Shiller-like). 데이터 소스 3-tier: pykrx → FDR → yfinance(.KS). KR 10Y/3Y/회사채는 ECOS API 1차. PER 동적 fallback (2026-05-03): pykrx 성공 시 `models/valuation_baselines_kr.json#last_known_per` 자동 캐싱, 실패 시 캐시 → 없으면 14.0. valuation_signal_kr 와 noise_regime_data_kr 가 같은 캐시 공유. Baseline JSON: `models/valuation_baselines_kr.json` (TTL 90일). 펀더멘털 탭 KR 모드: 게이지 범위 -25~+5 (US -10~+5 vs KR 깊은 분포), 카드 제목 region 분기 ('Noise vs Signal' ↔ '시장 이성 점수'), gap-ticks 중복 제거 — `static/js/main.js loadRegime`, `templates/stocks.html#nr-card-title`.
- **HMM 6-feature KR 재정의 (2026-05-03)**: `processor/feature1_regime.py` 가 region 별 다른 feature set + 가중치 사용. `FEATURE_NAMES` (US 8: fundamental_gap·erp_zscore·residual_corr·dispersion·amihud·vix_term·hy_spread·realized_vol) ↔ `FEATURE_NAMES_KR` (KR 6: erp_zscore·residual_corr·dispersion·amihud·hy_spread·realized_vol). KR 은 PER 시계열 부재로 fundamental_gap 가 12M log P/E diff cancel 로 0 평탄, VKOSPI 단일값으로 vix_term 가 1.0 평탄 → 두 피처 제외. 가중치 재배분: vix_term 2.0 → realized_vol 흡수해 4.0, |fundamental_gap| 0.5 → |erp_zscore| 흡수해 0.5. US 합 7.8 vs KR 합 7.5. `_feature_names(region)`/`_noise_weights(region)`/`_weights_for_features(feat_names)` 헬퍼, model bundle 에 `feature_names` 키 저장 (구버전 호환: `model.means_.shape[1]` 으로 8/6 추정). `train_hmm` 에서 region 의 feature subset 만 학습, `predict_regime`/`backfill_noise_regime` 가 `feat_names` 길이로 vector 차원 자동. 프론트 (`feature_contributions`/`feature_values` list/dict 순회) 자동 적응. 사용자가 `python scripts/train_kr_hmm.py` 재실행 시 6-feature 모델로 자동 교체.

### 15.3 인프라
- Supabase 유료 전환 (1GB 초과 시)
- Railway 또는 Vercel 배포 (Dockerfile 사용)
- 카카오 JS 키 production 도메인 추가 등록
- 전국 GeoJSON 시군구 (250개) + 법정동 (~15,000) 정적 자산화

---

## 16. CI/CD·배포

### 16.1 Dockerfile (multi-stage)
```
Stage 1: node:20-slim → npm install → npm run build (frontend-realestate)
Stage 2: python:3.11-slim
  + libgomp1 (xgboost/catboost 런타임)
  + ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
  + pip install -r requirements.txt
  + COPY . . (.dockerignore 로 node_modules·data·notebooks·models/*.pkl 제외)
  + COPY --from=frontend-builder /project/static/realestate static/realestate
  CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}
```

### 16.2 Railway
- `railway.json` builder=DOCKERFILE
- `RUN_SCHEDULER=true` (단일 서비스 운영)
- 또는 `RUN_SCHEDULER=false` 로 웹/스케줄러 분리

---

## 17. 변경 이력

상세 시간순 이력은 `update.py [1]~[N]` 참조. 본 문서는 현재 시점 청사진.

마지막 갱신 시점: 2026-05-03 (화성시(41590) backfill — MOLIT 가 41590 0건 반환, 옛 일반구 4코드(41591 새솔/41593 기안/41595 반정/41597 산척·동탄) 합산 후 sgg_cd=41590 normalize. backfill_metro.py 부천 분기 옆에 elif sgg=='41590' 추가, 5 LAWD_CD × 12 ym 20.7분, region_summary 30~35 stdg/월 (1585 trades 202603), buy_signal 매수(39.3), top_stdg=송동(평단가 1811만/평). app_cache 3종(sgg_overview·region_detail:41590·ranking) 즉시 재계산. update.py [85])

마지막 갱신 시점: 2026-05-03 (KR HMM 6-feature 재정의 — fundamental_gap·vix_term 제거, |erp_zscore| 0.3→0.5 + realized_vol 2.0→4.0 흡수. processor/feature1_regime.py 에 FEATURE_NAMES_KR + NOISE_WEIGHTS_US/KR + _feature_names/_noise_weights/_weights_for_features 헬퍼, train_hmm 에서 features_df subset 후 학습, model bundle 에 feature_names 키 저장. load_model 구버전 호환 (means_.shape[1] 으로 추정), predict/backfill 가 feat_names 길이로 차원 자동. 프론트 자동 적응 (feature_contributions/feature_values 순회). 사용자가 train_kr_hmm.py 재실행 시 6-feature 모델로 교체. update.py [86])

마지막 갱신 시점: 2026-05-03 (홈 AI 헤드라인 DB 캐시 — 사용자 보고 KR 홈탭 "오늘의 종합판단" 로딩 느림. 기존 in-memory _headline_cache (TTL 만료 시 LLM 즉석 호출, 재시작 시 증발) → migrations/2026_05_03_add_ai_headline_cache.sql 추가 (region+lang UNIQUE), repositories upsert/fetch_ai_headline, market_summary 에 _generate_home_headline 헬퍼 추출 + precompute_home_headline 신규 + endpoint 3단 fallback (메모리→DB→LLM 즉석). scheduler/job_kr.py 6번째 step + scheduler/job.py Step 10 에서 ko/en × region 미리 생성. Noise 추이 차트 dot 제거 (renderLineChart) — 라인 + 그라데이션만, mousemove 로 가까운 점 hover. main.js?v=125. update.py [87][88]. 사용자 액션: Supabase SQL Editor 에서 마이그 실행 후 다음 스케줄에 캐시 채워짐)

마지막 갱신 시점: 2026-05-03 (Noise 추이 차트 Y축 절대 범위 고정 — 사용자 보고 게이지(좌측 감정)와 라인차트(위쪽 이성적 라벨) 가 같은 score (-13.4) 를 시각적으로 모순되게 표시. renderLineChart 에 yFixedMin/yFixedMax 옵션 추가, loadNoiseChart 에서 region 따라 KR -25~+5 / US -10~+5 (게이지 G_LO/G_HI 와 일치) 전달. 0 기준선이 차트 위쪽에 명확히 보이고 "이성적" 라벨 = 양수 영역, "감정적" 라벨 = 음수 영역으로 절대 의미 회복. main.js?v=126, update.py [89])

마지막 갱신 시점: 2026-05-03 (KR 신호탭 — Crash/Surge XGBoost KR 24-feature 구현. collector/crash_surge_data_kr.py 신규 (KOSPI 7 + 변동성 4 + VKOSPI 3 + 회사채 AA-3Y 스프레드 3 + KR 금리 2 + 외국인 순매수 2 + USDKRW/WTI 2 + 거래대금 z 1). processor/feature3_crash_surge.py 에 _model_path/_feature_names_for_region/load_crash_surge_model 헬퍼 + train/predict/backfill region 인자 + bundle 에 region/feature_names 키 + 구버전 호환 (means_.shape 추정). scripts/train_kr_crash_surge.py 신규 (--start 2010 --trials 50). scheduler/job_kr.py Step 7 (load_crash_surge_model('kr') 있으면 light fetch → predict → upsert). home.js KR_SUPPORTED_TILES 에 'signal' 추가. 라벨링 동일 (±10%/20일 forward) — 모델 명명만 "20일 상승/하락 예측" 으로 직관화. home.js?v=29, update.py [90]. 사용자 액션: python -m scripts.train_kr_crash_surge 1회 실행 후 신호탭 자동 활성화)

마지막 갱신 시점: 2026-05-04 (5탭 AI 해설 DB 캐시 — 사용자 보고 5번 탭 진입 시 ai-explain endpoint LLM 즉석 호출 1~3초로 느림. [88] 의 home-headline 패턴을 5탭 AI 해설에 미러링: migrations/2026_05_04_add_ai_explain_cache.sql 신규 (tab+lang+region UNIQUE), repositories.upsert_ai_explain/fetch_ai_explain 추가, market_summary._generate_ai_explain helper + precompute_ai_explain + endpoint 3-tier (memory → DB → LLM 즉석). scheduler/job_kr.py Step 10 (KR × (fundamental/signal/sector) × (ko/en) = 6 entry), scheduler/job.py Step 11 (US × 5탭 × (ko/en) = 10 entry, sector-val/sector-mom 포함). 사용자 액션: 마이그 실행 + 다음 스케줄 사이클 자동 적재. update.py [93])

마지막 갱신 시점: 2026-05-04 (KR 거시경제 탭 — 5번째 탭 'tab-sector' (라벨 "거시경제") 의 미국 구조 (거시 8 → HMM 4-state 경기국면 → 섹터 회전) 를 KR 로 1:1 포팅. migrations 에 sector_macro_raw KR 14 컬럼 ALTER (sparse, 같은 UNIQUE 재사용). collector/ecos_macro.py SPECS 분리 (RATE_SPECS / SECTOR_MACRO_SPECS — fetch_macro_rate_kr 호출 폭증 방지) + Q cycle 변환 + 7종 추가 (CPI/GDP/실업률/M2/광공업/소매/설비투자, ECOS 정확한 코드 검증 완료). collector/kosis_macro.py 신규 (건축허가만 — 4종 중 3개는 ECOS 로 충당). collector/sector_macro_kr.py 신규 (ECOS+KOSIS 통합 aggregator, 분기 데이터 ffill(2)). collector/sector_etf_kr.py 에 ALL_HOLDINGS_KR + fetch_sector_etf_returns_kr + fetch_sector_etf_per_pbr_kr 1차 fallback (KOSPI 시장 평균 동일 적용 — Stage 2 가중평균은 별도 PR). processor/feature2_sector_cycle.py region 분기 (FEATURE_COLS_US/_KR + run_sector_cycle(..., region) + _map_states_to_phases 인덱스 동적 조회) + dropna 정책 변경 (non_empty subset + FEATURE_COLS 만 dropna + sector_ret left join — KR 단상장 ETF/일부 ECOS 무효 시리즈 학습 데이터 0행 만드는 사고 방지, US 도 안전화). processor/sector_valuation_kr_backfill.py 신규. scripts/train_kr_sector_cycle.py 신규. scheduler/job_kr.py Step 8/9 (sector_macro+cycle+valuation). database/repositories.py fetch_sector_macro_history select 26 컬럼 확장. static/js/sector.js _isKr/_MACRO_KEYS_KR/_SECTOR_KEYS_KR/formatMacroValue 분기 + MACRO_GOOD_HIGH/MACRO_NEUTRAL KR 14 추가. static/js/i18n.js 44 항목 (KR 22 ko/en). update.py [91][92]. Production 1차 검증 OK: 2026-04-01 → 🍂 둔화 (99.9%), Top3 [139260 IT, 091160 반도체, 341850 리츠]. 가용 매크로 10/14, kr_permit/kr_income 만 NaN. 사용자 액션: 마이그 실행 → python -m scripts.train_kr_sector_cycle 1회 → 다음 KST 16:00 부터 자동)

마지막 갱신 시점: 2026-05-04 (KR 섹터 밸류에이션 PDF 가중평균 — 사용자 결정 PDF 가중평균 + 주 1회 holdings 캐시. collector/etf_holdings_kr.py 신규 (pykrx.get_etf_portfolio_deposit_file 호출 캐시 TTL 7일, models/etf_holdings_kr.json). collector/sector_etf_kr.py 의 fetch_sector_etf_per_pbr_kr 교체: holdings 로드 + pykrx.get_market_fundamental(KOSPI/KOSDAQ) 1회 fetch 로 전체 종목 PER/PBR + 비중 가중평균 (적자 per≤0 제외 후 재정규화) + coverage<50% 시 KOSPI 평균 fallback. home.js KR_SUPPORTED_TILES 에 'sector-val' 추가. _weighted_avg unit test (50/30/20 비중, 부재 종목 1개 → cov=80%) 통과. home.js?v=31. 사용자 액션: 다음 KR 스케줄 cycle 부터 자동 (홈 'sector-val' 타일 활성))

마지막 갱신 시점: 2026-05-04 (region 토글 임시 숨김 + AI 해설 에러 멘트 통일 [95] — 사용자 요청 2건. (1) KR 미완성 상태라 헤더 US/KR 토글 임시 숨김: templates/stocks.html btn-region 에 style="display:none", static/js/region.js 에 _FORCE_US_ONLY flag → getRegion() 강제 'us' 반환 (localStorage 'kr' 잔여 무시). 복원은 두 줄만 변경. region.js v=4. (2) Groq 토큰 소진 등 AI 해설 모든 실패 케이스를 "해설 서비스 개선중." (en: "Commentary service is being improved.") 으로 통일: market_summary._EXPLAIN_ERR 의 no_data/no_service/fail 3종 동일, i18n 'ai.explainError' (frontend catch) 도 동일. i18n.js v=6. update.py [95])

마지막 갱신 시점: 2026-05-04 (KR 섹터 모멘텀 sector-mom 별 탭 KR 포팅 [94] — 미국 11종 SPDR → KR 10종 KODEX/TIGER 분기. processor/feature7_sector_momentum.py: _ticker_map_for_region helper 신규 + compute_sector_momentum(region='us') 시그니처 + DB query .eq('region', region) 필터 + 반환 dict 'region' 필드. api/routers/sector_cycle.py: get_momentum(region: str = Query('us')) + _momentum_cache region 별 dict 분리 (us 캐시가 kr 응답 덮어쓰는 버그 방지). api/routers/market_summary.py: _build_explain_text('sector-mom') 의 compute_sector_momentum 호출에 region=region 인자 추가. static/js/home.js: SECTOR_KR dict KR 10 ticker 한글 매핑 추가 (139260=IT 등) + KR_SUPPORTED_TILES 에 'sector-mom' 추가. scheduler/job_kr.py Step 10 ai-explain 탭 리스트에 'sector-mom' 추가 (KR × 4탭 × 2lang = 8 entry). templates/stocks.html home.js v=31 → v=32. 5 파일 ~55 LOC. update.py [94])

마지막 갱신 시점: 2026-05-05 (홈 헤드라인 에러 멘트 통일 [97] — 사용자 보고: [95] 적용 후에도 홈 화면 "오늘의 종합 판단" 카드가 "AI 요약을 생성할 수 없습니다." 표시 (별도 dict _ERR_MSGS, [95] 의 _EXPLAIN_ERR 와 분리). market_summary.py:_ERR_MSGS 의 ko/en × no_data/no_service/fail 6개 항목을 모두 "해설 서비스 개선중." / "Commentary service is being improved." 로 통일. 캐시 hit 인 정상 헤드라인은 그대로, 토큰 소진 후 만료된 호출만 새 멘트. update.py [97])

마지막 갱신 시점: 2026-05-05 (UI 디자인 워크스페이스 분리 + Stop hook 자동 미러 [96] — 디자인 시안 작업을 본 레포와 격리된 별도 폴더("/root/UI 디자인")에서 진행. 본→디자인 단방향 미러 자동화. (1) scripts/sync_ui_design.sh 신규: rsync -a --delete 로 static/templates/frontend-realestate 미러, node_modules/dist/.next 제외, 약 3.2MB 규모(node_modules 96MB 제외). (2) .claude/settings.json 신규: Stop hook (matcher="", command=bash sync_ui_design.sh, timeout 30s, statusMessage "UI 디자인 폴더 동기화 중...") — Claude Code 매 턴 종료 시 자동 실행. (3) /root/UI 디자인/CLAUDE.md 신규: 단방향 미러 규약·시안 확정 후 본 레포에 사람이 옮기는 워크플로우·node_modules 심링크 가이드. 양방향 sync 는 충돌 위험으로 배제 (사용자 결정). 백엔드(api/processor/scheduler/models/database/scripts/notebooks/logic) 는 미러 대상 아님 — 디자인 폴더는 프론트만. settings.json 이 세션 시작 시점에 부재했으므로 watcher 가 즉시 인지하지 못할 수 있음 → /hooks 한 번 열거나 Claude Code 재시작 시 활성화. update.py [96])

마지막 갱신 시점: 2026-05-05 (AI 해설 프롬프트 — "단순 나열" → "메커니즘 한 줄" [100] — 사용자 피드백 "각 모델에 영향을 미치는 요인을 단순히 말해주는게 아니라 왜 그 요인이 모델 결과에 그 영향을 미치는지 단순요약". market_summary._EXPLAIN_PROMPTS 5탭 × ko/en 모두 수정: "단순 나열 X — 왜 그 요인이 [방향]에 작용하는지 메커니즘 한 줄 (예: 'VIX↑=공포 확대→이성 약화')". 예시 가이드 5종 (fundamental/signal/sector/sector-val/sector-mom) 명시. 길이 ≤160/180자 (KR), ≤200/220자 (EN). max_tokens 150 그대로. 적용 시점: ai_explain_cache 의 옛 캐시는 다음 KST 16:00 (KR) / 09:00 (US) 자동 갱신, 즉시 원하면 DELETE FROM ai_explain_cache. update.py [100])

마지막 갱신 시점: 2026-05-05 (디자인 전용 호스트 서버 (port 8001) + STATIC/TEMPLATES env [99] — 사용자 명시 "디자인 전용으로 따른 호스트 서버 사용하길 원함" → api/app.py 3곳 수정: _STATIC_DIR=os.getenv('STATIC_DIR', 'static') / _TEMPLATES_DIR=os.getenv('TEMPLATES_DIR', 'templates') 추가, StaticFiles directory + Jinja2Templates directory + realestate SPA FileResponse + tiktok verify file_path 4군데 모두 env 변수 사용. env 미지정 시 기본값 'static'/'templates' 라 production 동작 동일. 디자인 서버 명령: cd 본 레포 + RUN_SCHEDULER=false + STATIC_DIR/TEMPLATES_DIR='/root/UI 디자인/static·templates' + uvicorn --port 8001 --reload-dir '/root/UI 디자인/static' --reload-dir '/root/UI 디자인/templates'. cwd=본 레포라 .env/models/catboost_info/Supabase 의존성 그대로, 화면 자원만 디자인 폴더로 분기. 두 서버 동시 운영: 8000(production) + 8001(디자인 hot reload). 워크플로우: 디자인 변경 → 8001 즉시 확인 → "본폴더에도 넣어" → 8000 reload. 검증: 한글 경로 watch OK, /stocks 200, 백엔드 startup complete. update.py [99])

마지막 갱신 시점: 2026-05-06 (region.js 로컬 노출 — wrapper 까지 풀기 [102] — [101] 의 새 마크업 wrapper(.region-toggle-bar) 도 inline display:none 이라 사용자가 직접 만든 hostname 자동 감지 로직(_IS_LOCAL_DEV → btn-region inline display 무력화)이 wrapper 까지는 안 풀어 localhost 에서 토글이 가려진 채. region.js 의 DOMContentLoaded 핸들러에서 _IS_LOCAL_DEV 분기 시 querySelector('.region-toggle-bar').style.display='' 도 추가. region.js?v=5→v=6 cache-bust. production(dinsightlab.com) 에선 _IS_LOCAL_DEV=false 라 wrapper/btn 모두 안 풀려 KR 가림 정책 [95] 그대로. update.py [102])

마지막 갱신 시점: 2026-05-07 (DART 기반 KOSPI 시장 PER/PBR 시총가중 fallback [102] — valuation_signal_kr 의 PER fallback 이 pykrx 차단 시 항상 _HARD_FALLBACK_PER=14.0 (장기 평균) 사용 → ERP 항상 양수 편향 ("저평가" 시그널 고정). DART API 로 시총가중 시장 PER 산출. dart_fundamentals.py 에 _market_cap_yf (yfinance .KS/.KQ marketCap fallback) + compute_kospi_market_per_dart (default 25 종목 = noise_regime ALL_STOCKS_KR proxy, 시총 가중평균 σcap/σni, 24h 캐시) 추가. dotenv 자동 로드 추가. valuation_signal_kr.py PER fallback 체인 2곳 (today + backfill): pykrx → DART → 캐시 → 14.0 (3단→4단). 검증: PER 24.82/PBR 3.06 (cov 84%, n_per=20/25) 산출 OK, valuation_signal today=spy_per:24.82 / ERP:0.001 / z_erp:-1.27 / label:'다소 저평가' (이전 14.0 fallback 시 label 항상 '명확한 저평가' 편향). update.py [102])

마지막 갱신 시점: 2026-05-07 (DART KOSPI 시장 PER/PBR KOSPI200 확장 [103] — [102] 의 25종목 proxy 를 실제 KOSPI200 시총가중으로 확장. collector/dart_fundamentals.py: _fetch_kospi200_codes(pykrx get_index_portfolio_deposit_file('1028'), 실패 시 25종목 proxy), _market_caps_pykrx(pykrx get_market_cap_by_ticker 최근 거래일 14일 lookback), compute_kospi_market_per_dart default universe=KOSPI200 + pykrx 시총 우선/yfinance 누락분 보강, cache key kospi200_market_per 로 분리. valuation_signal_kr.py 로그/주석 KOSPI200 정정. sector_etf_kr.py 시장 PER/PBR fallback 도 pykrx 실패 시 DART KOSPI200 결과 사용 후 last_known_per/14.0 로 내려가도록 연결. 검증: venv py_compile + callable import check OK. update.py [103])

마지막 갱신 시점: 2026-05-07 (KR 섹터 밸류에이션 표 빈칸 보정 [104] — 사용자 스크린샷: 국내주식 섹터 밸류에이션 표의 10Y 평균/현재가 전부 '-'. api/routers/sector_cycle.py compute_valuation_payload 에 KR null PER/PBR 보정 추가: 최신 sector_valuation row 의 per/pbr 이 비면 valuation_signal_kr last_known_per→14.0, pbr 1.0 fallback 으로 현재값 채움. 평균 표시 기준 분리: HIST_MIN_N=5 는 z-score/%diff 색상 판단용 유지, MEAN_MIN_N=1 로 히스토리 1개라도 10Y 평균 칸은 현재까지 누적 평균 표시. app_cache 가 모든 row per/per_mean null 인 불완전 payload 면 캐시 반환 대신 DB 최신 row 로 재구성 후 upsert. static/js/home.js 는 withRegion('/api/sector-cycle/valuation') 명시, templates/stocks.html home.js v=40→41. 검증: sector_cycle py_compile OK. update.py [104])

마지막 갱신 시점: 2026-05-07 (KR 섹터 밸류에이션 동일 PER 문제 수정 [105] — [104] 의 null PER 일괄 fallback 으로 모든 섹터가 last_known_per=24.8배 동일 표시. 원인: models/etf_holdings_kr.json 10개 ETF holdings 가 전부 빈 배열(KRX PDF fetch 실패 캐시). collector/etf_holdings_kr.py: 모든 ETF holdings 가 빈 캐시는 fresh 로 보지 않음 + KRX PDF 실패 시 ETF별 대표 구성종목 fallback(IT/반도체/은행/자동차/철강/에너지화학/필수소비재/헬스케어/게임/리츠). collector/sector_etf_kr.py: coverage<50% 여도 PER 산출 가능하면 섹터별 PER 유지, PER 이 전혀 없을 때만 KOSPI 시장 PER fallback. api/routers/sector_cycle.py: PER null→last_known_per 일괄 보정 제거. 검증: venv py_compile OK, 대표 holdings weight 합계 100. update.py [105])

마지막 갱신 시점: 2026-05-07 (KR sector_valuation DART None PER crash fix [106] — 사용자 `python -m scheduler.job_kr` 실행 중 `[sector_valuation_kr] DART PER/PBR 40 종목 산출` 후 `_weighted_avg` 에서 `float * NoneType` crash. 원인: DART metrics 에 적자/순이익 부재 종목은 {'per': None, 'pbr': 값} 가능하지만 기존 코드는 key 존재만 보고 곱셈. collector/sector_etf_kr.py _weighted_avg 에 value None/float 변환 실패/<=0 skip 추가. 일부 구성종목만 PER/PBR 산출되어도 valid 비중 기준으로 섹터별 가중평균 계산. 검증: py_compile OK, synthetic test A per=None/B per=20 → (20.0, 0.5). update.py [106])

마지막 갱신 시점: 2026-05-07 (KR sector valuation cache 를 LLM quota 실패와 분리 [107] — 사용자 재실행에서 sector_valuation 10건 DB upsert 는 성공했지만 Step 10 precompute_ai_summary 가 Groq 429 로 예외 → 같은 try 블록의 precompute_valuation/precompute_momentum 미실행, app_cache 가 오래된 동일 24.8배 payload 유지 가능. scheduler/job_kr.py Step 10 을 ai-summary(LLM) 와 sector valuation/momentum(non-LLM) try 로 분리. api/routers/sector_cycle.py _valuation_payload_incomplete(payload, region) 에 KR per 값이 모두 동일한 degenerate cache 무효화 로직 추가. endpoint 가 오래된 동일 PER cache 를 만나면 DB 최신 row 로 재구성 후 upsert. 검증: py_compile OK. update.py [107])

마지막 갱신 시점: 2026-05-08 (이상 탐지 탭 UX 리워드 — "평소 이탈도" 프레이밍 [117] — 사용자 피드백 "98.4% / 최상위 5% / 드문 영역 / D² / Σ⁻¹ 수식 노출이 직관성 부족 + 사용자가 자동으로 '위험' 으로 해석". 알고리즘·데이터·API 변동 0, 사용자 노출 문구만 일상어 + 살짝 전문 톤 ("시장 평소 이탈도", "과거 10년 기준 위치", "평소와의 거리", "비교 일수", "평소와 다름") 으로 통일. 수정: static/js/i18n.js 의 KO/EN 키 7종 (tab.signal, an.cardLabel/chartLabel/contribsLabel/disclaimer, tile.anomaly/anomalySub) + static/js/anomaly.js percentileLabel 5단계 라벨 ("매우 평온/드문 영역" → "평소에 가까움/평소와 다름") + renderSummary 헤더·게이지·3 stat·하단 설명 (D² 수식 → "여러 시장 지표를 한 번에 비교해... 미래 방향을 예측하지 않습니다" 일상어 한 문단) + renderChart 범례 + renderContribs/renderKnn 안내문 학술용어 제거 + templates/stocks.html fallback 라벨 + anomaly.js?v=1→v=2 캐시 버스트. 자문 리스크 가드: "확률·가능성·매수·매도·위험" 단어 0, 강도 표현만 (방향성 0), 하단 disclaimer "과거 데이터 기준의 거리 측정이며, 미래 방향을 예측하지 않습니다" 가 유일한 의미 가드. update.py [117])

마지막 갱신 시점: 2026-05-08 (평소 이탈도 탭 카드 재배치 + k-NN 시기별 시장 이벤트 [118] — 사용자 요청 "시장 이상 탐지 카드 없애고 추이 차트를 맨 위로, 과거 같은 패턴을 2번째로, 그리고 그 시기 어떤 뉴스 있었는지 표시". (1) templates/stocks.html tab-signal main 재구성: an-summary 카드 통째로 제거, 카드 순서 차트 → k-NN → contributors → AI 해설 → 면책. anomaly.js?v=2→v=3 캐시 버스트. (2) static/js/anomaly.js: renderSummary 함수 + 호출 + an-summary 참조 모두 삭제 (dead code). loadAnomaly 의 카드 렌더 순서도 차트 → k-NN → contributors. 파일 헤더 "4개 카드 → 3개 카드". (3) MARKET_EVENTS_US 신규 const (인라인 사전, 20건 큐레이팅: 2015 위안화/2016 브렉시트/2018 Volmageddon/2020 코로나/2021 GME/2022 우크라·CPI 9.1%/2023 SVB·CS·이스라엘-하마스/2024 캐리트레이드 청산·트럼프 재선/2025 美 상호관세 등). findEvent(date) helper YYYY-MM-DD lex 비교. (4) renderKnn 행 레이아웃: 기존 [date / 거리][#N 가까움] → [date][#N · 거리] + 아래줄 📌 이벤트 라벨 (매칭 시) 또는 회색 이탤릭 "기록된 시장 이벤트 없음" (매칭 실패 시 거짓 라벨 금지). 자문 가드: 이벤트 라벨은 사건 사실만 ("리먼 파산", "코로나 팬데믹"), 결과/인과/예측 단어 0. 안내문 "📌 = 그 시기 주요 시장 이벤트 (사실 기록만, 결과 해석 없음)" 명시. 확장: 신규 이벤트는 MARKET_EVENTS_US 배열 push, KR region 활성 시 MARKET_EVENTS_KR + region 분기 추가, 외부 뉴스 API 통합 시 findEvent() 만 fetch 비동기로 교체. update.py [118])

마지막 갱신 시점: 2026-05-08 (한자 제거 + k-NN 다양화 윈도 30→90일 [121] — 사용자 피드백 "한자는 안나오게" + "각 이벤트 너무 따닥, 최소 3개월 차이". processor/feature_anomaly.py KNN_DIVERSITY_DAYS 30→90 (사용자 요청, 매칭 시점 간 최소 3개월 보장). static/js/anomaly.js MARKET_EVENTS_US 라벨 한자→한글 8건 (美→미국, 日→일본, 英→영국, 對中→중국, etc) + 신규 1건 (2024-04-25~05-15 "미국 FOMC 매파 보합·4월 고용 부진"). anomaly.js?v=5→v=6. 재계산: compute_today_anomaly DB upsert 후 매칭 변화 — Before(30일): 2025-02/2024-12/2024-11 (모두 4개월 안짝 클러스터) → After(90일): 2025-02-06 (관세) / 2024-05-03 (FOMC·NFP) / 2022-02-08 (연준·우크라) (~280일/~815일 spread). 한자 grep (ord 0x4E00~0x9FFF) 0건 확인. update.py [121])

마지막 갱신 시점: 2026-05-08 (k-NN 방향 일치 매칭 [120] — 사용자 피드백 "지금 강세장인데 매칭은 다 인플레 stress 약세 이벤트". 원인: Mahalanobis 거리가 부호 무관(제곱) 이라 강세/약세 regime 무차별. 해결: 부호 일치 사전 필터 추가. processor/feature_anomaly.py 에 KNN_SIGN_AGREE_STRICT=6, RELAXED=5, NEUTRAL_TOL=0.3 상수 + _sign_agreement_counts(today_dev, past_devs, sigmas, tol) helper (z-score 변환 후 부호 비교, |z|<0.3 은 near-zero 로 자동 일치). _knn_diversified() 시그니처 확장 (mu/cov 추가) — 후보 필터: 부호 일치 ≥ STRICT (6/8) → 후보 < k*3 이면 RELAXED (5/8) → 그래도 부족하면 fallback (거리만). 두 호출 사이트 모두 mu/cov 전달. Before(거리만): 2022-02-08/2021-03-02/2021-05-07 (모두 인플레 stress). After(방향 일치): 2025-02-06/2024-12-23/2024-11-15 (트럼프 트레이드 시대, 사용자 강세장 인식과 같은 macro regime). MARKET_EVENTS_US +1 (2024-12-18~2025-01-03 "12월 FOMC 매파 dot plot·연말 변동성") → 3/3 라벨 매칭. anomaly.js?v=4→v=5. 의도된 비용: 진짜 극단 stress (2008/2020-03) 매칭은 fallback 발동 시에만 등장. update.py [120])

마지막 갱신 시점: 2026-05-08 (k-NN regime 클러스터 fix + 이벤트 사전 확장 [119] — 사용자 스크린샷: k-NN 매칭이 2026-01-27/28/29 3일 연속 모두 "기록된 시장 이벤트 없음". 원인: KNN_GAP_DAYS=90 이 시장 regime (보통 6개월+ 같은 패턴) 보다 짧아 cutoff 직후 연속일 클러스터가 top-K 차지. (1) processor/feature_anomaly.py: KNN_GAP_DAYS 90→365 (1년 — "역사적 유사 시점" 의미 보장), KNN_DIVERSITY_DAYS=30 신규 (픽 1개당 ±30일 윈도 마스크 — 같은 regime 클러스터 2건 이상 차단), _knn_diversified() helper 추가, compute_anomaly_timeseries / compute_today_anomaly 두 곳 모두 inline argsort[:K] → _knn_diversified 호출로 교체 (중복 제거). (2) static/js/anomaly.js MARKET_EVENTS_US +7건: 2025 트럼프 2기 (취임/관세 부과/Liberation Day/유예/이란 전쟁/관세 발효) + 2021-2022 평시 컨텍스트 (재오픈 rotation/CPI 4~5%/매파 회견·우크라 긴장). 즉시 재계산 (compute_today_anomaly + upsert) → DB today row 갱신, knn_dates = 2022-02-08/2021-03-02/2021-05-07 셋 다 새 이벤트 라벨 매칭. (3) templates/stocks.html anomaly.js?v=3→v=4 캐시 버스트. historical 행의 knn_dates 컬럼은 옛 gap=90 로직으로 채워져 있으나 화면은 fetch_anomaly_current(today 1행) 만 사용 → 노출 X, 다음 풀 백필 시 자연 갱신. update.py [119])

마지막 갱신 시점: 2026-05-06 (region 토글 디자인 재설계 [101] — 디자인 폴더에서 작업 후 본 레포 반영. (1) 헤더 우측 → 헤더 외부 별도 row 로 분리 (.region-toggle-bar wrapper, display:flex justify-content:center) — 모바일 480px 폭에서 좌측 'Passive' 로고와 가로 충돌 영구 해결. (2) 라벨 "미국주식/국내주식" → "미국 주식 / 국내 주식" (4글자 띄어쓰기), width 200px. (3) quiet baseline 위에 region 컬러 액센트: US 라이트 진한 네이비/다크 파스텔 블루, KR 라이트 진한 적갈/다크 파스텔 레드. 인디케이터에 위→아래 그라데이션 + 상단 inset highlight 로 입체감, hover 시 box-shadow 가 region 색으로 발광. cubic-bezier(0.22, 1, 0.36, 1) bounce 슬라이드. (4) region-indicator span 신규 (CSS 슬라이딩 배경). (5) main.css?v=110→111 cache-bust. 노출 정책: .region-toggle-bar 에 style="display:none;" 유지 ([95] KR 미완성 정책) + region.js _FORCE_US_ONLY=true 유지 — KR 화면 완성 시 두 곳만 풀면 즉시 활성. 디자인 서버 8001 에서 hot reload 확인 후 본 레포 8000 에 반영. update.py [101])

마지막 갱신 시점: 2026-05-05 (UI 디자인 워크플로우 재정의 — Stop hook 해제 [98] — 사용자 명시 "디자인(프론트) 를 그대로 본 폴더에서 클론해오는거야. 이후 디자인 변경점을 말하면 그 부분만 바꾸는거지" → [96] 의 자동 미러는 디자인 폴더 작업물을 매 턴 덮어쓰므로 의도와 충돌. .claude/settings.json 의 hooks.Stop 제거 (schema 키만 남김). scripts/sync_ui_design.sh 는 보존 — 사용자가 "sync 시켜" 요청 시 수동 호출용. /root/UI 디자인/CLAUDE.md 재작성 (자동 sync 없음 명시, 디자인 변경은 디자인 폴더에서 직접 / 본폴더 반영은 "이거 본폴더에도 넣어" 명시 요청 시에만 / sync_ui_design.sh 는 --delete 라 디자인 작업 중 실행 금지 경고). 동작: 본폴더 변경 → 사용자 "sync 시켜" → Claude rsync 실행. 디자인 변경 → 사용자 요청 → Claude 디자인 폴더 직접 수정. 매 턴 종료 시 아무 자동 동작 없음. update.py [98])

마지막 갱신 시점: 2026-05-09 (시황 AI 해설 4줄 형식 복원 + 매크로 영문 변수 18종 한국어 라벨 사전 합성 — 사용자 요청 (1) "시황 AI 해설을 기존(4줄 emoji+제목—내용) 처럼" + (2) "AI 해설에 영문 변수명 (pmi/yield_spread/anfci/icsa_yoy 등) 노출 안 되게 투자자 친화적 한국어로". api/routers/market_summary.py: (A) _SUMMARY_PROMPTS ko/en 형식 복원 — 2줄(📊 핵심 + 🔍 인사이트) → 4줄(시장 심리 ❄️ / 평소 이탈도 📊 / 펀더멘털 🧭 / 종합 🎯). 옛 "방향성/간극" 자리는 D² + 상위 N% 로 대체 (신호탭 폐기 일관성 유지), "종합" 라인은 행동 제안·방향 예측 단어 금지 명시. (B) _fallback_ai_summary 4줄 재작성 — fetch_fear_greed/fetch_anomaly_current/fetch_noise_regime_current/fetch_sector_cycle_latest 4 source 로 각 줄 합성, 데이터 결손 시 "수집 중" 표기. (C) _FEATURE_LABEL_KO/_EN 에 매크로 지표 18종 추가 (US 10: pmi/yield_spread/anfci/icsa_yoy/permit_yoy/real_retail_yoy/capex_yoy/real_income_yoy/pmi_chg3m/capex_yoy_chg3m, KR 8: kr_indpro_yoy/kr_yield_spread/kr_credit_spread/kr_unemp_rate/kr_permit_yoy/kr_retail_yoy/kr_capex_yoy/kr_cpi_yoy) — 라벨/의미/왜 영향 주는지 3-tuple. (D) _build_explain_text(tab='sector') 의 macro_snapshot 루프를 _ko_feature_why(k, lang) 호출로 교체 — LLM 입력 단계에서 "제조업 PMI(50 기준 확장/수축) — PMI 가 50 이상이면 일반적으로 ... 산입; 값: 50.21" 형식 사전 합성 → LLM 이 영문 snake_case 그대로 echo 하던 케이스 차단. (E) _fallback_ai_explain(tab='sector') 의 macro_str 도 _ko_feature 적용 — 화면에 "pmi 50.21" → "제조업 PMI(50 기준 확장/수축) 50.21" 노출. 알고리즘·DB 스키마·API 시그니처 변동 0. 검증: ast syntax OK. 옛 DB 캐시는 다음 요청에서 백그라운드(옵션 C) 가 새 형식으로 재적재 → 자연 갱신.

마지막 갱신 시점: 2026-05-09 (AI 시황·해설 cache miss 시 즉시 fallback + 백그라운드 LLM (옵션 C) — 사용자 보고 "AI 해설이 너무 느리게 나옴", Network 캡처에서 ai-summary 가 ~6초 (cache miss → on-demand Groq + Supabase 다회 왕복). 설계상 scheduler precompute 후 cache hit 가 정상이지만 적재 실패·TTL 만료 시 첫 요청이 LLM 비용 전부 짊어지는 구조. api/routers/market_summary.py 변경: (1) BackgroundTasks 임포트 추가. (2) 모듈 전역 _bg_running:set + _bg_lock:Lock 도입 — 동일 키 동시 LLM 실행 차단 (중복 비용·중복 upsert 방지). (3) _bg_generate_summary(lang, region) / _bg_generate_explain(tab, lang, region) 헬퍼 신규 — 각각 _generate_ai_summary / _generate_ai_explain 호출 후 app_cache or ai_explain_cache + in-memory 캐시 적재. 시작/종료 로그 + finally 에서 _bg_running 회수. (4) get_ai_summary 엔드포인트 시그니처에 background_tasks: BackgroundTasks 추가, cache miss 분기에서 *동기 LLM 호출 제거* + _fallback_ai_summary 즉시 응답 + background_tasks.add_task(_bg_generate_summary, ...) 등록. (5) get_ai_explain 동일 패턴 — cache miss 분기 fallback 즉시 + _bg_generate_explain dispatch. fallback 은 _explain_cache 에 *저장하지 않음* — 다음 요청이 BG 가 채운 in-memory 캐시 또는 DB 를 자연스럽게 hit. 결과: 첫 진입 사용자도 ~1초 내 응답 (fallback), 새로고침 1회 후부터 LLM 결과 노출. 동시 다중 요청에도 LLM 은 키당 1회만 실행. trade-off: 첫 로드 시 룰베이스 텍스트 (이미 3블록 구조 + 한국어 라벨 + 자문 가드 적용되어 충분히 자연스러움). 알고리즘·DB 스키마·precompute 로직 변동 0. 검증: ast syntax OK.

마지막 갱신 시점: 2026-05-09 (AI 해설 줄바꿈 미적용 root cause 수정 — 사용자 보고 "[1]/[2]/[3] 블록이 여전히 한 단락으로 합쳐 나옴" (스크린샷). 원인: 프론트 _formatExplainText (static/js/main.js line 512) 의 `text.replace(/\\s{2,}/g, ' ')` 가 \\n\\n 까지 단일 공백으로 합쳐버려 백엔드가 보낸 블록 분리 \\n\\n 가 화면에 닿기 전에 사라짐. 그 다음 line 518 의 `\\n → <br>` 변환은 이미 \\n 이 사라진 뒤라 효과 없음 ([N] 후처리 헬퍼는 정상 동작했으나 프론트 단계에서 무력화). 수정: (1) `\\s{2,}` → `[ \\t]{2,}` 로 교체 — 줄바꿈 보존, 공백·탭만 압축. (2) `\\n` → `<br>` 변환 직전에 `[1]/[2]/[3]` 마커 앞에 강제 \\n\\n 삽입 정규식 추가 (옛 캐시·후처리 누락 케이스 보강). templates/stocks.html main.js?v=134→v=135. 알고리즘·API·DB 변동 0, 단일 정규식 fix 로 전 탭 AI 해설 가독성 복구.

마지막 갱신 시점: 2026-05-09 (시황 탭 요약/프롬프트/입력 텍스트에서 옛 신호탭(crash/surge gap) 자취 제거 — 사용자 보고 "심리 라벨과 신호 간극 방향이 같은 *정렬 패턴* 처럼 신호 간극 표현이 나오는데 삭제된 신호탭 데이터 같음". api/routers/market_summary.py 4 군데 수정: (1) _build_indicator_text(): 시황 LLM 입력에서 fetch_crash_surge_current → fetch_anomaly_current. "하락 위험도/상승 기대도/간극" 줄 → "평소와의 거리(D²) — 10년 분포 내 상위 N%" 줄. (2) _build_home_indicator_text() 의 "[신호 탭]" 섹션 → "[이상 탐지 탭]" 으로 라벨 + crash/surge gap → D²/percentile_10y/percentile_90d 데이터로 교체. (3) _SUMMARY_PROMPTS ko/en — "신호 간극 +/-X" → "평소와의 거리 D²(상위 N%)"; 자문 가드에 "crash/surge·간극·상승 우위·하락 우위·신호 간극 단어 금지" 명시 추가. 인사이트 예시도 D² 기반으로 교체. (4) _fallback_ai_summary 전면 재작성: today.crash_surge.gap → fetch_anomaly_current 의 d2/percentile_10y. 인사이트 룰을 사실 기반 동반 이격/평소 영역 패턴으로 재정의 (탐욕+멀리 이격 → 교과서적 동반 이격 패턴, 평소 분포 중심 부근 → 심리가 차별 변수 등). "신호 간극" 단어 0건. 한자 0건. fetch_crash_surge_current/_history 임포트는 다른 코드 경로(crash_surge 디테일 패널 등) 가 여전히 사용하므로 유지. 알고리즘·DB·API 시그니처 변동 0. 검증: ast syntax OK, 로컬 endpoint probe 는 Windows TCP 좀비 소켓 누적으로 보류 — 재부팅 후 확인 필요.

마지막 갱신 시점: 2026-05-08 (PER 가중평균 빈 칸 fallback + AI 해설 [N] 마커 줄바꿈 후처리 — 사용자 보고 (1) "PER 가중평균 컬럼이 안 나옴" (2) "AI 해설이 한 줄에 합쳐서 나옴". (1) api/routers/sector_cycle.py compute_valuation_payload(): 오늘자 perw 가 None 일 때 perw_samples (history) 의 마지막 non-null 값으로 폴백. 일별 collector 가 trailingPE 수집에 실패해도 화면이 빈 칸이 아닌 직전 사용 가능 값을 표시. _valuation_payload_incomplete() 에 신규 stale 검출: vals 모두 per_weighted=None 이면서 일부 per_weighted_mean 만 있는 케이스 → 폴백 도입 후 재계산 유도. (2) api/routers/market_summary.py: _format_explain_blocks(text) helper 신규 — 정규식 [1-3] 마커 split + '\\n\\n' join 으로 LLM 출력의 [1]·[2]·[3] 마커 앞에 빈 줄을 강제 삽입 (idempotent). _generate_ai_explain 결과 + get_ai_explain endpoint 의 in-memory cache hit / DB cache hit 두 경로 모두에서 동일 후처리 적용. 옛 캐시도 응답 시점에 재포맷되어 즉시 반영. 알고리즘·DB 스키마·API 시그니처 변동 0. 검증: syntax check OK. 로컬 서버 verify 는 Windows TCP 스택 좀비 소켓 누적으로 신규 포트 바인딩 실패 (WinError 10014) — 재부팅 후 또는 배포 환경에서 동작 확인.

마지막 갱신 시점: 2026-05-08 (LLM 입력 단계에 변수명 한국어 라벨 + 의미 + 영향 메커니즘 사전 합성 — qwen LLM 이 'vix_term', 'amihud' 등 영문 snake_case 를 출력에 그대로 echo 하는 문제 해결. 사용자 보고 후 옵션 (a) 채택. api/routers/market_summary.py _build_explain_text(): (1) fundamental 탭 feature_contributions 루프를 "라벨·의미·왜 영향 주는지" 헤더 + `_ko_feature_why(name, lang)` 결과 + 기여도 형식으로 변경 (예: "  - 하이일드 스프레드(신용 위험 프리미엄) — 회사채 위험이 커지면 자금 경색을 시사해 시장 스트레스 신호로 산입됩니다; 기여도: +0.85"). feature_values 의 키도 _ko_feature 로 변환. (2) signal 탭 top_contributors 루프도 동일 패턴 적용. LLM 시스템 프롬프트는 그대로지만 *입력 데이터 자체* 가 이미 한국어 라벨/의미/영향 메커니즘을 담고 있어 LLM 이 번역 단계 없이 그대로 echo 만 하면 되므로 영문 변수명 출력 케이스 차단. 알고리즘·DB·API 시그니처 변동 0. fallback 은 이미 _ko_feature_why 사용 중이라 변동 없음.

마지막 갱신 시점: 2026-05-08 (거시경제 메인에 매크로 지표·10년 추세 노출 + sparkline log 스케일 — 사용자 요청 "거시경제 상세페이지의 매크로 지표/그래프를 로그 스케일로 + 거시경제 메인페이지로 나오도록". 거시경제 탭 (idx=4) = tab-sector. 상세페이지(클릭 후 열리는 패널)의 매크로 스냅샷·10년 sparkline 섹션을 메인에도 동일하게 노출. (1) templates/stocks.html tab-sector 의 sc-phase-card 직후에 신규 섹션 "매크로 지표 · 10년 추세" + sc-macro-main 컨테이너 추가. (2) static/js/sector.js: _renderSparkline 시그니처 확장 (..., opts={logScale:false}) — logScale=true 시 symlog (sign(x)*log1p(|x|)) y 변환으로 0/음수 안전 + 극단치 압축. (3) _renderMacroMain(d) 신규 — sc-macro-main 에 매크로 스냅샷 그리드 + /api/sector-cycle/macro-history fetch + 8 indicator log-scale sparkline 렌더, 우하단 안내 "y축 symlog 압축 (극단치 완화)". (4) loadSectorCycle 끝부분에 _renderMacroMain(d) 호출. (5) renderSectorDetail 의 기존 spark-* sparkline 도 logScale:true 로 통일. templates/stocks.html sector.js?v=7→v=8 캐시 버스트. 알고리즘·API·DB 변동 0, 백엔드 endpoint 재사용. 데이터: macro_snapshot (현재값), /api/sector-cycle/macro-history (10년 시계열) — region 별 8 키 세트 (US: pmi/yield_spread/anfci/icsa_yoy/permit_yoy/real_retail_yoy/capex_yoy/real_income_yoy, KR: kr_indpro_yoy/kr_yield_spread/kr_credit_spread/kr_unemp_rate/kr_permit_yoy/kr_retail_yoy/kr_capex_yoy/kr_cpi_yoy).

마지막 갱신 시점: 2026-05-08 (모든 AI 해설 3 블록 구조 (데이터 요약/변수 설명/인사이트) + 한자 금지 — 사용자 요청 "그 탭의 데이터를 모두 넣은 다음 요약 + 변수가 왜 모델에 영향 주는지 쉽고 간단히 + 그 토대로 인사이트 출력 + 항상 줄바꿈 + 한자 금지". api/routers/market_summary.py: (1) _FEATURE_LABEL_KO/_EN 13개 변수에 'why' 3번째 필드 추가 (왜 이 변수가 모델에 영향 주는지 한 줄). _ko_feature_why(name, lang) helper 신규. (2) _EXPLAIN_PROMPTS 5탭×2언어 — 출력 구조 [블록1 데이터 요약 + 한 줄 요약] [블록2 주요 변수 설명: 왜 영향 주는지] [블록3 교과서적 인사이트] 강제. 블록 사이 \\n\\n. 한자 절대 금지 명시. (3) _SUMMARY_PROMPTS ko/en 양쪽에 한자 금지 명시. (4) _fallback_ai_explain 5탭 모두 [데이터 요약]\\n\\n[주요 변수 설명]\\n\\n[인사이트] 형식으로 재작성: fundamental(레짐+점수+상위 기여+값+요약), signal(D²+10년/90일 위치+기여+유사 시점+요약), sector(국면+macro+섹터), sector-val(상위 양/음 deviation), sector-mom(상위/하위 랭크). _ko_feature_why 호출하여 변수마다 의미+영향 메커니즘 한 줄 자동 합성. (5) 코드 주석 line 126 "中" → "우선" 한글 치환. JS 변경 0 — 프론트 _formatExplainText 가 이미 \\n → <br> 변환. 검증: en signal endpoint "[Data] Anomaly Distance (D²): 10.627.\\nPosition: top 28.4% ...\\n\\n[Why these variables matter]\\n  - return dispersion(...) — ...\\n  - Amihud illiquidity(...) — ...\\n\\n[Insight] ..." 3 블록 구조 + 한자 없음 확인.

마지막 갱신 시점: 2026-05-08 (이상 탐지 탭 AI 해설을 anomaly 데이터로 교체 + 모든 탭 줄바꿈 — 사용자 보고 "이상치 탭 AI 해설이 삭제된 신호탭(crash/surge) 정보 가져옴". 원인: tab='signal' 의 _build_explain_text/_fallback_ai_explain 가 fetch_crash_surge_current 를 사용하던 잔재 (UI 는 [117]+ 에서 anomaly 차트로 교체됐으나 해설 빌더는 미동기화). api/routers/market_summary.py: (1) imports 에 fetch_anomaly_current 추가. (2) _build_explain_text(tab='signal') 전면 재작성 — fetch_anomaly_current 호출, D²/percentile_10y/percentile_90d/top_contributors/knn_dates 를 영문/한국어 라벨로 출력. crash_surge gap·shap 의존 0. (3) _fallback_ai_explain(tab='signal') 동일 anomaly 데이터로 교체 — D² + 상위 N% 위치 + 주된 기여 지표(_ko_feature 자동 한국어 변환) + 메커니즘. (4) 사용자 추가 요청 "각 AI 해설 가독성 좋게 줄바꿈": _EXPLAIN_PROMPTS 5탭×2언어에 원칙 4 추가 ("3 문장 = 3 줄, 각 문장 끝에 \\n"), 모든 _fallback_ai_explain 분기 (5탭) 를 \n 으로 줄 분리, _fallback_ai_summary 도 \n 분리 유지. 프론트 _formatExplainText (static/js/main.js line 518) 이미 \n → <br> 변환하므로 화면에서 줄바꿈 자동 렌더, JS 변경 0. 검증: GET /api/market-summary/ai-explain?tab=signal&lang=en 응답 "Anomaly Distance (D²) is 10.627, positioned at top 28.4% of the 10-year distribution.\nTop contributing indicators: return dispersion(cross-stock spread), Amihud illiquidity(execution impact cost) — ...\nState only — distance to 'usual', no direction inference." (3 줄, 한국어 라벨 변환).

마지막 갱신 시점: 2026-05-08 (AI 해설/시황 요약 — 영문 변수명 한국어 번역 + 인사이트 형식 + 한 줄 요약 — 사용자 요청 "시황 탭 한 줄 요약 + 인사이트, 펀더멘털 탭 영문(hy_spread/vix_term/erp_zscore 등) 직관적 한국어로 + 그 변수가 왜 영향 주는지 설명 포함, 모든 탭에 적용". api/routers/market_summary.py: (1) _SUMMARY_PROMPTS 4줄 브리핑 → *2줄* (📊 핵심 한 줄 + 🔍 인사이트 한 줄, 자문 가드 동일 유지). (2) _EXPLAIN_PROMPTS 5탭×2언어에 원칙 3 추가: 영문 snake_case 변수명을 *반드시* 한국어 자연어로 번역 + 한 줄 의미 (지표 의미·역할). 프롬프트 상단 주석에 8 regime 피처 매핑 명시 (hy_spread→하이일드 스프레드(신용 위험 프리미엄), vix_term→VIX 텀 구조, erp_zscore→주식 위험 프리미엄 z-score, fundamental_gap→펀더멘털 갭, residual_corr→잔차 상관, dispersion→종목 분산, amihud→유동성 비용, realized_vol→실현 변동성). (3) _FEATURE_LABEL_KO/_EN 모듈 dict 신규 (13개 변수 매핑) + _ko_feature(name, lang) helper. (4) _fallback_ai_summary 재구성 — 1줄 핵심 + 1줄 인사이트 (심리·간극 정렬/괴리 *교과서 패턴* 기반 인사이트 룰), 자문 가드 동일. (5) _fallback_ai_explain 5탭 모두 _ko_feature 호출하여 영문 변수명 자동 한국어 + 의미 변환 + "이 지표가 왜 산입되는지" 한 줄 추가, "유리/추천/매수·매도" 표현 모두 제거. 알고리즘·DB·API 시그니처 변동 0. ai_explain_cache/app_cache(ai_summary) DB 옛 캐시는 다음 scheduler precompute 또는 row 삭제 시점부터 신 출력으로 교체.

마지막 갱신 시점: 2026-05-08 (AI 해설 프롬프트 5탭×2언어 자문 리스크 강화 — 사용자 요청 "AI 해설 부분도 투자자문 리스크를 제외하도록 설명하도록 프롬프트를 변경". api/routers/market_summary.py 의 _EXPLAIN_PROMPTS dict (line 661) 전면 갱신: 모든 탭 (fundamental/signal/sector/sector-val/sector-mom) × 2언어 (ko/en) 에서 "매수/매도/추천/유리/불리/위험/안전/매수타이밍/상승전망/하락전망/예측/전망/기대/선반영/포트폴리오/목표가/수익률 보장" 단어 명시 금지 + 미래 방향성 추정("~할 것이다", "~로 이어질 가능성") 금지 + 과거·현재 사실 + 일반론적 메커니즘 (교과서 인과) 만 허용. fundamental: "유리/수혜→점수 산입 메커니즘만". signal (이상 탐지 탭 사용): "상승/하락 압력/우위" 단어 제거, "평소 분포 내 위치 + 기여 피처 메커니즘" 으로 재정의 (현재 backend 가 crash/surge 데이터로 빌드되지만 자문 가드는 일관). sector: "유리한 섹터→일반론적으로 함께 거론되는 섹터" 톤 변경. sector-val: 기존 가치판단 금지에 "방향 예측 X" 추가. sector-mom: "선반영/기대" 제거. 캐시 무효화 필요 — ai_explain_cache 테이블 기존 row 가 옛 프롬프트로 생성되어 있어 신규 프롬프트 적용은 (a) DB row 삭제 후 다음 scheduler precompute_ai_explain 또는 (b) on-demand 강제 재생성 시까지 지연. CLAUDE.md "투자자문 리스크 회피" 섹션 부합. 알고리즘·DB 스키마·라우터 시그니처 변동 0.)

마지막 갱신 시점: 2026-05-08 (이상 탐지 차트 범례 한 줄 정렬 — 사용자 요청 "빨간줄 처럼 강세장과 하락장이 같은줄에 있게". static/js/anomaly.js renderChart() 의 범례 div 에서 flex-wrap:wrap 제거 + white-space:nowrap + overflow-x:auto (좁은 화면 fallback), 라벨 단축: "평소와의 거리 (시계열)"→"평소와의 거리", "강세장 (50일선 위)"→"강세장", "하락장 (50일선 아래)"→"하락장" — 50일선 컨텍스트는 차트 색 띠 자체로 자명. 4개 항목 단일 행 정렬. templates/stocks.html anomaly.js?v=12→v=13.)

마지막 갱신 시점: 2026-05-08 (regime bands TDZ 버그 수정 — 직전 변경의 regime band 합성 블록이 const x = ... 정의보다 위에 위치하여 ReferenceError: Cannot access 'x' before initialization 발생, 사용자 화면 "로드 실패" 보고. static/js/anomaly.js renderChart() 에서 regime band 루프를 const x/const y 정의 이후로 이동, REGIME_BULL_FILL/REGIME_BEAR_FILL 색 상수만 그 위에 잔존 (사용 위치 무관). templates/stocks.html anomaly.js?v=11→v=12 캐시 버스트.)

마지막 갱신 시점: 2026-05-08 (이상 탐지 차트에 50일선 강세장/하락장 배경 음영 — 사용자 요청 "강세장/하락장 부분을 색을 칠하는식으로 표현, 50일선 기준". (1) api/routers/anomaly.py: REGIME_TICKERS={'us':'^GSPC','kr':'^KS11'} + REGIME_50_WINDOW=50 + _regime_50_dict(region, day_key) lru_cache(maxsize=4) 신규 — yfinance 로 12년치 종가 로드 → 50d SMA 비교 → ffill (휴장일 갭 직전 라벨 유지) → {YYYY-MM-DD: 1|0|None} dict, 캐시 키 (region, today.isoformat()) 로 일자 바뀌면 자동 갱신. get_history() 에서 호출하여 series 각 row 에 regime_50 필드 부착. (2) static/js/anomaly.js renderChart(): regime_50 ∈ {0,1} 인 연속 구간을 찾아 <rect> 배경 띠 합성 (강세장 #22c55e green / 하락장 #ef4444 red, opacity 0.10), defs 직후 + gridLines 이전에 렌더 (가장 뒤 레이어). 범례에 강세장(50일선 위) / 하락장(50일선 아래) 항목 2개 추가, flex-wrap 으로 모바일 폭 대응. (3) templates/stocks.html anomaly.js?v=10→v=11. yfinance 외부 의존은 _load_market_regime (200d, [122]) 이 이미 사용 중이라 신규 의존 없음. 자문 가드: 사실 표시 (50d SMA 위/아래), 매수/매도/방향 단어 0. CLAUDE.md 신규 규칙 — update.py 갱신 금지, structure.md 단독 운영.

마지막 갱신 시점: 2026-05-08 (이상 탐지 차트 상위 20% 실선 제거, 상위 10% 만 유지 [126] — 사용자 요청 "상위 10퍼만 표시하도록 다시 변경". static/js/anomaly.js renderChart(): [125] 에서 추가했던 ORANGE_TOP20=#fbbf24 amber 실선·라벨 블록 삭제, percentileOf helper 도 단일 p90 사용이라 인라인 (sortedVals[floor(N*0.9)]) 으로 단순화. 차트엔 상위 10% (#f97316 deeper orange) 가로 실선 + "상위 10%" 우상단 라벨만 남음. 범례 "· 상위 N%" 주황 span 강조 유지. templates/stocks.html anomaly.js?v=9→v=10. update.py [126])

마지막 갱신 시점: 2026-05-08 (상위% 라벨 위치 정리 + 상위 10/20% 경계 실선 [125] — 사용자 피드백 "차트 안 주황색 상위 29% 라벨 삭제 + 위쪽(범례) 상위 29% 만 주황색 + 실선으로 상위 10/20% 구간 표시". static/js/anomaly.js renderChart(): (1) [124] 의 차트 안 SVG <text> 라벨 제거 (annoX/annoY 변수도 함께 삭제). (2) 범례 텍스트 "오늘 (3.2 · 상위 29%)" 의 "· 상위 N%" 부분만 <span style="color:#f97316;font-weight:700"> 로 분리 — var(--sub) gray 안에서 주황만 강조. (3) 시계열 분포 기준 p90/p80 계산 (sortedVals + percentileOf helper) → 상위 10% 컷 (ORANGE_TOP10=#f97316 실선) + 상위 20% 컷 (ORANGE_TOP20=#fbbf24 실선) 차트 폭 가로지르며 그림, 우상단에 "상위 10%/20%" 라벨 (paint-order:stroke + stroke:#fff:3px 가독성). 렌더 순서: thresholdLines → circle (오늘 점이 라인 위에 덮임). 시계열 분포 기준이라 백엔드 percentile_10y 와 살짝 다를 수 있으나 사용자 노출 라벨은 백엔드값 단일 — 혼란 없음. templates/stocks.html anomaly.js?v=8→v=9. 알고리즘·API·DB 변동 0. update.py [125])

마지막 갱신 시점: 2026-05-08 (이상 탐지 차트 안 "상위 N%" 라벨 [124] — 사용자 요청 "상위 몇퍼센트인지도 그래프 안에 표시". static/js/anomaly.js renderChart() 에 오늘 점 옆 SVG <text> 추가: topPct = round(100 - percentile_10y), [0,100] clamp + finite check, 위치는 점 위쪽 9px (점이 상단 24px 안쪽이면 아래로 회피), text-anchor=end 로 점 좌측 6px 끝맺음, fill = percentileLabel().color (5단계 강도색), paint-order:stroke + stroke:#fff:3px 로 area gradient 위 가독성 보장. 범례 "오늘 (3.2)" → "오늘 (3.2 · 상위 12%)" 확장 (차트 안 라벨 + 범례 이중 노출). hasPct=false 면 라벨·범례 양쪽 미표시 (잘못된 0% 시각화 차단). templates/stocks.html anomaly.js?v=7→v=8. 알고리즘·API·DB 변동 0. 자문 리스크 가드: 상위% 는 사실 기록 (분포 위치), 매수/매도/방향 단어 0 — disclaimer 하 안전. update.py [124])

마지막 갱신 시점: 2026-05-08 (이상 탐지 탭 10년 추이 차트 y축 sqrt→log1p [123] — 사용자 피드백 "코로나 같은 부분이 너무 솟구쳐 있어서 다른 부분들이 차별성이 없어지는데 minmaxscaler를 활용하는건 어때?" → MinMaxScaler 는 선형 [0,1] 이라 비율 보존 = 같은 문제. 비선형 압축 필요. static/js/anomaly.js renderChart() yTransform Math.sqrt → Math.log1p (0 입력 안전, log(1+x)), y축 라벨 역변환 t*t → Math.expm1(t) (= exp(t)-1). 평시 D²≈10 / 코로나 피크 D²≈500 가정 시 sqrt 변환은 3.16 vs 22.36 (~7배 차이로 평시가 차트 ~14% 만 차지) → log1p 변환은 2.40 vs 6.22 (~2.6배 차이로 평시가 ~38% 차지), 평시 변동 가시화. templates/stocks.html anomaly.js?v=6→v=7. 알고리즘·API·DB 변동 0, 시각화 좌표 변환만 변경 — y축 눈금은 여전히 원래 D² 값으로 표시되어 사용자는 변환을 인지할 필요 없음, 자문 리스크 가드 무관. update.py [123])

마지막 갱신 시점: 2026-05-08 (k-NN 시장 regime (200d SMA) 사전 필터 [122] — 사용자 요청 "지금이 강세장이면 저 당시 비슷한 시장 리스트도 강세장이었던 시기로 나오게 하고싶은데". [120] 의 부호 일치 필터(8 피처 deviation 방향) 위에 명시적 가격 regime 게이팅 추가. processor/feature_anomaly.py: REGIME_MA_WINDOW=200, REGIME_TICKERS={'us':'^GSPC','kr':'^KS11'} 상수 + _load_market_regime(start,end,region) (yfinance 로 인덱스 종가 → 200영업일 SMA 비교 → 1/0/NaN Series, look-ahead 안전) + _filter_pool_by_regime(knn_pool, today_regime, regime_series, min_keep=KNN_K) (same regime 행만 남기되 < min_keep 이면 원본 반환 fallback). compute_anomaly_timeseries 는 panel 로드 후 regime_series 1회 pre-load, 루프 안에서 dt 별 today_regime → pool filter → _knn_diversified. compute_today_anomaly 는 knn_pool 결정 후 regime_series 로드 후 동일 처리. trade-off: 강세장 today 일 때 진짜 폭락 시점(2008-09/2020-03) 매칭 거의 불가 — 의도된 비용. yfinance 외부 의존은 _load_extras_yfinance 가 이미 사용 중이라 신규 의존 없음. JS 변경 없음 (anomaly.js 캐시 bump 불필요). 적용: 다음 scheduler 실행에서 latest anomaly_daily row 자연 갱신, 강제 갱신은 anomaly_daily 최근 date 1건 delete 후 재계산 또는 scripts/backfill_anomaly.py. update.py [122])

마지막 갱신 시점: 2026-05-09 (햄버거 메뉴 + About 가이드 페이지 골격(Stage A) — 사용자 요청 "메뉴탭 만들어 Passive 소개·사용법·지표·ML 모델 설명 넣고 싶다", AskUserQuestion 결정: 진입 위치=헤더 좌측 햄버거 / 콘텐츠 깊이=핵심 요약 / 모델 범위=전체. Stage A(골격)만 먼저 구현, 콘텐츠 채우기는 후속. (1) templates/stocks.html: app-header 첫 자식으로 #btn-menu (3-bar) 추가, top-accent 직후 #menu-backdrop + <aside id="menu-drawer"> (좌측 드로어, "About / 설정 / 면책 고지" 3 링크, About 만 활성, 나머지 disabled placeholder), main.css?v=112→113, i18n.js?v=7→8, 새 menu.js?v=1 로드. (2) static/js/menu.js 신규: btnMenu/btnClose/backdrop click + ESC + 메뉴 링크 클릭 시 closeDrawer, body.menu-open 으로 본문 스크롤 잠금. (3) static/css/main.css +약 200줄: .menu-btn(3-bar) / .menu-backdrop(opacity 0.42) / .menu-drawer(transform translateX, width min(78vw,320px), shadow) / .menu-link(disabled 회색) + .about-page(overflow auto) / .about-header(sticky top, glass) / .about-layout(grid 220px 1fr, 모바일 1fr) / .about-toc(sticky, 카드형) / .about-toc-link.active(accent) / .about-section(scroll-margin-top 80) / .about-placeholder(dashed border 회색). (4) templates/about.html 신규: 6개 섹션(intro/usage/metrics/models/sources/disclaimer) anchor + 좌측 sticky ToC + IntersectionObserver 스크롤스파이(rootMargin -30%/-60%, active 토글). 본문은 모두 .about-placeholder "(작성 예정)" 자리표시자. (5) api/app.py: @app.get('/about') 라우트 추가, templates.TemplateResponse('about.html'). (6) static/js/i18n.js: KO/EN 양쪽에 menu.* + about.* 키 22개 추가 (menu.title/about/settings/disclaimer, about.back/title/tocLabel/intro|usage|metrics|models|sources|disclaimer.{title,lead}, about.placeholder). update.py 갱신은 새 규칙(CLAUDE.md "## update.py 갱신 금지") 에 따라 생략. 검증: py_compile api/app.py OK, node --check menu.js / i18n.js OK. 후속(Stage B+): 각 섹션에 콘텐츠 카드(지표 10/모델 4/데이터 출처 9), 카드별 펼침 접힘, 자문 리스크 가드(매수·매도·타이밍 단어 0).)

마지막 갱신 시점: 2026-05-09 (페이지·탭·dwell 추적 + stats Top 페이지 카드 — 사용자 요청 "/stats 에서 사용자들이 어떤 페이지에 들어가는지도 알 수 있게". AskUserQuestion 결정: granularity=path+tab+dwell, 시각화=Top 페이지 수직 바 카드. (1) DB: migrations/2026_05_09_add_page_view.sql 신규 — page_view 테이블 (id BIGSERIAL, user_hash, visit_date DATE, visited_at TIMESTAMPTZ, path, tab nullable, dwell_ms nullable) + 3개 인덱스 + RLS disable. user_visit 와 별개 — user_visit 는 일자별 1행, page_view 는 진입/탭전환/이탈마다 누적. (2) database/repositories.py: track_page_view(user_hash, visit_date, path, tab, dwell_ms) INSERT + fetch_page_stats(date) 집계 함수 신규. 집계 결과 by_path / by_tab 두 단위 모두 반환 (views, unique_users, avg_dwell_ms). (3) api/routers/tracking.py: POST /api/tracking/page (PageViewRequest body) + GET /api/tracking/pages?d=YYYY-MM-DD 신규. (4) static/js/main.js: TAB_NAME_BY_IDX 매핑 (0=ai-chart/1=market/2=fundamental/3=signal/4=sector) + _pageView 모듈 상태 + _sendPageView (sendBeacon 우선, fetch keepalive fallback) + flushPageView (dwell_ms 계산 후 전송) + beginPageView (직전 flush + 새 시작 시각 + 진입 1건 dwell_ms=null 기록) + visibilitychange/pagehide/beforeunload 자동 flush + window.recordTabSwitch hook. switchTab() 시작부에 recordTabSwitch(idx) 추가. 부팅 IIFE 의 trackVisit() 직후 beginPageView('ai-chart') 호출. (5) templates/stats.html: "Top 페이지" 패널 신규 (panel-tag PAGE VIEWS), top-pages-list 컨테이너 + loadTopPages() 함수 — by_tab 상위 12건을 path·tab 라벨 + 수평 바 그라데이션 + views/unique/avg_dwell 3컬럼 테이블 형태로 렌더, fetchStats() 끝부분에서 호출. 알고리즘·기존 user_visit 동작 변동 0. 운영: production Supabase 에서 마이그레이션 SQL 1회 실행 필요. fire-and-forget 추적이라 실패해도 앱 동작 무관.

마지막 갱신 시점: 2026-05-09 (Stage A 후속 — splash 재진입 차단 + 메뉴 아이콘 미니멀 SVG 교체. (1) /about ← 뒤로 → /stocks 재진입 시 splash 가 다시 보이는 문제: templates/stocks.html <head> 인라인 가드 추가 — sessionStorage.getItem("splashShown") 이면 document.documentElement.classList.add("splash-skip"), main.css 에 html.splash-skip .splash{display:none !important} 로 페이지 페인트 전 즉시 숨김. static/js/main.js IIFE 진입부에서 skipSplash 플래그 산출 후 sessionStorage.setItem("splashShown","1"), skipSplash 면 즉시 safeDismiss() (데이터 로드 병렬). dismissSplash() 시그니처 +skipAnimation: 참이면 fade-out 클래스 / transitionend 우회하고 onEnd 즉시 실행. 첫 세션 진입은 기존대로 2200ms 최소 노출, 같은 세션 재진입은 즉시 본문 노출. sessionStorage 라 탭 닫으면 자동 초기화 — 새 세션 진입 시 정상 splash. (2) 메뉴 드로어 이모지 (📖 ⚙ 📜) → stroke=1.6 currentColor 미니멀 SVG: About=info circle(원+세로선+상단 dot), Settings=Lucide gear(원+12개 톱니 path), 면책=document(folder+folded corner+2 lines). main.css .menu-link-icon 을 inline-flex 22×22 컨테이너로 변경(svg 18×18), color: var(--sub) → hover 시 var(--text). main.css?v=113→114, main.js?v=133→134, about.html main.css?v=113→114 동기화. 검증: node --check main.js OK, /stocks /about 양쪽 200.)

마지막 갱신 시점: 2026-05-09 (부동산 랭킹 탭 빈 카드/None trade_count fix — 사용자 보고 "랭킹탭에 안나오는 화면". 원인: app_cache.sgg_overview / app_cache.ranking 둘 다 RLS 거부로 미적재 (cache write 실패: "new row violates row-level security policy" 로그). compute_ranking() 이 sgg_overview cache 를 읽고 빈 dict 면 그대로 진행해 overview_by_sgg={} → trade_count 전부 None + price_top5 빈 배열. fix: api/routers/real_estate.py compute_ranking() 의 sgg_overview 조회 직후 if not overview: compute_sgg_overview("") 폴백 호출 추가. region_summary 4000+행 페이지네이션 직접 계산 (~12s 첫 호출, 이후 cache hit 시도). try/except 로 cache 조회 실패도 폴백으로 흡수. 검증: 서버 재시작 (--reload-dir 에 api/processor/database 추가) 후 curl /api/realestate/ranking → trade_recovery_top5 5건 모두 trade_count non-null (416/245/178/16/556), price_top5 5건 (분당구+15.63
마지막 갱신 시점: 2026-05-09 (부동산 랭킹 탭 빈 카드/None trade_count fix — 사용자 보고 "랭킹탭에 안나오는 화면". 원인: app_cache.sgg_overview / app_cache.ranking 둘 다 RLS 거부로 미적재 (cache write 실패: "new row violates row-level security policy" 로그). compute_ranking() 이 sgg_overview cache 를 읽고 빈 dict 면 그대로 진행해 overview_by_sgg={} → trade_count 전부 None + price_top5 빈 배열. fix: api/routers/real_estate.py compute_ranking() 의 sgg_overview 조회 직후 if not overview: compute_sgg_overview("") 폴백 호출 추가. region_summary 4000+행 페이지네이션 직접 계산 (~12s 첫 호출, 이후 cache hit 시도). try/except 로 cache 조회 실패도 폴백으로 흡수. 검증: 서버 재시작 (--reload-dir 에 api/processor/database 추가) 후 curl /api/realestate/ranking → trade_recovery_top5 5건 모두 trade_count non-null (416/245/178/16/556), price_top5 5건 (분당구+15.63%/강북구+15.28%/강동구+14.74%/동작구+11.40%/구리시+11.24%). 추후 작업: app_cache RLS 정책 마이그레이션으로 upsert 허용 → latency 12s→0.)

마지막 갱신 시점: 2026-05-09 (부동산 지도 폴리곤 라벨 — 사용자 요청 "각 지역별로 시군구 + 동 이름을 경계면 중앙 위에 디자인에 어울리게 표시". (1) frontend-realestate/src/components/VWorldMap.tsx + KakaoMap.tsx: PolygonFeature 인터페이스에 subName?: string|null 필드 추가. 폴리곤 useEffect 에 라벨 렌더링 — 각 폴리곤의 가장 큰 ring 의 centroid 계산 후 L.marker(divIcon) (Kakao 는 CustomOverlay) 라벨 1개씩 추가, interactive:false 라 클릭은 폴리곤이 받음. 다크 터미널 톤 — 반투명 검정 배경(rgba 0.62), 오렌지 border(255,140,0,0.32), JetBrains Mono 10.5px, 시군구 #ffaa44 + 동 #888 분리 색상, text-shadow 로 타일 위 가독성. (2) LABEL_MIN_ZOOM=9 (Leaflet) / LABEL_MIN_LEVEL=10 (Kakao) 줌 토글 — 수도권 overview 시 자동 숨김. zoomend 이벤트로 동적 toggle. (3) MapScreen.tsx loadPolygons: subName=overview.top_stdg_nm (부천은 bucheon_sub_top[subKey].top_stdg_nm 우선). 검증: npm install + tsc&&vite build 통과 (TS narrowing 1건 fix), static/realestate/index-CEg3UZJw.js 새 번들 산출, /realestate 200. 추후: convex 가정 — concave 폴리곤은 centroid 가 외부 점이 될 수 있음, 정밀 polylabel 필요 시 별도 작업.)

마지막 갱신 시점: 2026-05-09 (부동산 지도 모바일 상단 카드 가시성 fix — 사용자 보고 "모바일에서는 상단에 해설 카드가 안나오는데". 원인: MapScreen.tsx 의 플로팅 상단 wrapper(검색·MARKET BRIEF·choropleth 캡션 3 패널) 가 Tailwind `z-10` (z-index:10) 인데 Leaflet 내장 panes(tilePane 200·overlayPane 400·markerPane 600·popupPane 700)가 더 높아 지도 콘텐츠에 덮임. fix: z-10 → z-[1000] 로 강제 — Leaflet panes 위 + FeatureCard zIndex:9000 아래 사이. pointer-events 정책(outer none + inner auto, 빈공간 click 폴리곤 pass-through) 그대로 유지. 검증: npm run build 통과, 새 번들 index-KVlEqQjd.js / index-hBwtPilN.css.)

마지막 갱신 시점: 2026-05-09 (거시경제 탭 sparkline 모바일 잘림 fix — 사용자 보고 "거시경제 탭에서 그래프가 짤리는데". 원인: static/js/sector.js _renderSparkline 의 SVG 가 width="160" 고정 → 360px 폭 모바일에서 1fr 1fr 그리드(160×2 + gap + padding ≈ 360px) 가 viewport 초과해 우측 칼럼(금리차/실업급여/실질소매판매/실질소득) 잘림. fix: viewBox 유지 + width="100%" + preserveAspectRatio="none" + vector-effect="non-scaling-stroke" — 좁은 viewport 에서 컨테이너 폭에 stretch 되, stroke 두께는 1.5px 일정. _renderSparkline 자체 수정이라 거시경제 메인 + 상세 페이지 두 호출 사이트 모두 적용. templates/stocks.html sector.js?v=8→v=9. node --check OK.)
