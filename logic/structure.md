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
│   ├─ ecos_macro.py           ★ 한국은행 ECOS (기준금리·주담대)
│   ├─ kosis_migration.py      ★ 통계청 KOSIS (인구이동)
│   └─ sector_valuation.py     ★ yfinance Ticker.info — 11개 섹터 ETF PER/PBR
├─ processor/
│   ├─ feature1_regime.py      HMM 학습·예측
│   ├─ feature2_sector_cycle.py 섹터 경기국면
│   ├─ feature3_crash_surge.py XGBoost 폭락/급등
│   ├─ feature4_chart_predict.py 앙상블 ETF 예측
│   ├─ feature5_real_estate.py ★ 매핑 + 지역 집계
│   ├─ feature6_buy_signal.py  ★ 매수/관망/주의 시그널
│   └─ feature7_sector_momentum.py ★ 섹터 1주·1개월 일별 누적수익률 + 1주 기준 랭킹
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
│   └─ upload_dim.py
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
- `crash_surge` — XGBoost 폭락/급등 결과
- `fear_greed_raw` — CNN F&G 일별
- `index_price_raw` — ETF 가격
- `sector_macro_raw` — FRED 섹터 매크로
- `sector_cycle_result` — 섹터 경기국면
- `chart_predict` — 앙상블 ETF 30일 예측
- `sector_valuation` ★ — 11개 섹터 ETF PER/PBR 일별 (date+ticker UNIQUE)

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
