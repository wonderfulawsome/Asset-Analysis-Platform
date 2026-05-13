# KR 섹터 ETF 확장 설계 — 한국 특유 8개 섹터 추가

작성일: 2026-05-14
범위: A+B (섹터 밸류에이션 + 섹터 모멘텀 탭만)
접근: Approach A — 단일 dict 확장 + `listed_date` 필드

---

## 1. 배경 & 목표

현재 KR 섹터 ETF = 10개 (`collector/sector_etf_kr.py::SECTOR_ETF_KR`):
IT, 반도체, 게임산업, 은행, 에너지화학, 헬스케어, 자동차, 철강, 리츠, 필수소비재.

미국 SPDR 13개와 매핑 위주로 구성되어 *한국 시장 특유 색깔* (방산·2차전지·조선·바이오·미디어 등) 부재.

**목표:** 한국 특유 8개 섹터 추가 → 총 18개. 사용자가 한국 시장의 다양한 테마를 *섹터 밸류에이션* / *섹터 모멘텀* 탭에서 비교 가능.

**비목표:**
- 거시경제 HMM 사이클 학습 데이터에 신규 섹터 편입 X (학습 데이터 부족 우려)
- 펀더멘털 탭 직접 영향 X
- 미국 매핑(`us_proxy`) 보강 X (별도 작업)

---

## 2. 신규 섹터 8개

| Ticker | kr_name | en_name | us_proxy | listed_date |
|--------|---------|---------|----------|-------------|
| 401170 | K-방산 | Defense | ITA | 2024-04-30 |
| 305720 | 2차전지산업 | Battery | LIT | 2018-09-12 |
| 466920 | 조선해운 | Shipbuilding | SEA | 2023-09-15 |
| 244620 | 바이오 | Biotech | XBI | 2016-05-13 |
| 228810 | 미디어컨텐츠 | Media/Content | XLC | 2015-10-07 |
| 117700 | 건설 | Construction | ITB | 2009-10-30 |
| 098560 | 통신서비스 | Telecom | XLC | 2008-12-12 |
| 445290 | K-로봇액티브 | Robotics | BOTZ | 2023-03-21 |

상장일 기준 3년 미만: **401170, 466920, 445290** — 데이터 부족 라벨 표시.

us_proxy 는 LLM 입력용 *매크로 비교 hint*. 정확도 영향 작음 (단순 라벨링).

---

## 3. 데이터 구조 변경

### 3.1 SECTOR_ETF_KR dict 확장

`collector/sector_etf_kr.py::SECTOR_ETF_KR` 각 항목에 `listed_date: YYYY-MM-DD` 필드 추가. 기존 10개 + 신규 8개 = 18개. dict 순서 무관.

### 3.2 DB 스키마 변경 — `sector_valuation_kr` 테이블

신규 컬럼 2개:
- `lookback_days INT` — PER 평균 산출 시 실제 사용한 데이터 일수
- `data_sufficient BOOLEAN` — `lookback_days >= 756` (3년 ≈ 252×3) bool

migration 필요. ALTER TABLE 1회.

---

## 4. PER 5년 평균 산출 로직

`processor/sector_valuation_kr_backfill.py` 의 PER mean 산출 함수 수정:

```
1) ticker 별 가용 PER daily 시계열 fetch
2) days_available = len(시계열)
3) if days_available >= 1260 (5년): use last 5년 mean
   elif days_available >= 756 (3년): use full mean, data_sufficient = True
   elif days_available >= 60 (3개월): use full mean, data_sufficient = False
   else: skip (PER 산출 X, NaN row)
4) DB row 에 lookback_days, data_sufficient 저장
```

기존 10개 ETF 영향 X (모두 5년 이상 데이터).

---

## 5. Endpoint 응답

`/api/sector-cycle/valuation` 응답의 각 sector 항목에 신규 필드 2개 추가:
```json
{
  "ticker": "401170",
  "sector_name": "K-방산",
  "per_diff_pct": -12.3,
  "lookback_days": 252,
  "data_sufficient": false
}
```

DB row pass-through 패턴이라 router 코드 수정 거의 없음.

---

## 6. Frontend 표시

### 6.1 sector-val 탭

- 정렬 정책: `data_sufficient=true` 18개 → 평균 대비 % 정렬. *극값 상위 3 + 하위 3* (현 로직 유지).
- 데이터 부족 그룹: `data_sufficient=false` 항목들 → 메인 표 하단에 별도 sub-section, "상장 N년" 회색 라벨.

### 6.2 sector-mom 탭

- 1주/1개월 수익률 — 상장 30일 이상이면 산출 가능. 신규 8 ETF 모두 30일 초과.
- 데이터 결손 시 "-" 표시. 별도 라벨 X (모멘텀 산출 자체는 단기라 거의 모든 ETF 정상).

### 6.3 CSS

`static/css/main.css` 신규 룰:
- `.sector-val-row.insufficient` — opacity 0.7
- `.sector-val-row .data-warn` — `font-size: 10px; color: var(--sub2)` 회색 라벨

---

## 7. 영향 받는 파일

**Backend (Python):**
- `collector/sector_etf_kr.py` — SECTOR_ETF_KR dict 확장 + listed_date
- `processor/sector_valuation_kr_backfill.py` — lookback_days/data_sufficient 산출 추가
- `database/repositories.py` — sector_valuation_kr fetch 시 신규 컬럼 포함 (자동)
- `api/routers/sector_cycle.py` — `/valuation` endpoint 응답 pass-through (수정 거의 없음)

**DB migration:**
- Supabase SQL editor — `ALTER TABLE sector_valuation_kr ADD COLUMN lookback_days INT, ADD COLUMN data_sufficient BOOLEAN`

**Frontend:**
- `static/js/home.js` 또는 `sector.js` — sector-val 렌더에 data_sufficient 분기 추가
- `static/css/main.css` — 회색 라벨 룰 추가
- `templates/stocks.html` — 캐시 버스트

**Backfill / 운영:**
- `scripts/backfill_kr_sector_valuation.py` — 신규 8 ticker 1회 백필 실행
- `scheduler/job_kr.py` — 자동 iterate 이라 수정 0

---

## 8. 테스트 & 검증

1. 신규 8 ticker pykrx OHLCV 응답 — 최근 30일 데이터 fetch 검증. 실패 시 ticker 교체.
2. 신규 8 ticker pykrx PER 데이터 — `get_etf_fundamental` 또는 호환 함수 응답. 미지원 시 fallback 또는 *PER 산출 X 라벨*.
3. data_sufficient flag 정확성 — 401170/466920/445290 → false. 117700/244620/228810/098560/305720 → true.
4. Backfill 실행 — DB sector_valuation_kr row 18개 (기존 10 + 신규 8) 확인.
5. Frontend 시각 — sector-val/sector-mom 탭 신규 8개 노출 + 데이터 부족 라벨 정상.
6. 회귀 — 기존 10개 PER 값 변경 X.

---

## 9. Edge cases / fallback

- **pykrx 미지원 ETF**: K-로봇액티브(445290) 같은 active fund 는 PER 산출 불가 가능. → DB row 에 `per: null, data_sufficient: false` + frontend "데이터 미제공" 라벨.
- **상장 < 60일**: 산출 자체 skip. row 자체 적재 X.
- **us_proxy 매핑 오차**: 조선해운 → SEA 등 일부 부정확. 영향 작음 (LLM hint 용도).
- **DB migration 실패**: 신규 컬럼 추가 안 되면 endpoint 응답에 두 필드 누락 → frontend `data.lookback_days === undefined` 면 라벨 미표시 (degrade 가능).

---

## 10. 제한 / 추후 작업

- 거시경제 HMM 사이클 학습에 신규 섹터 *미편입* — 향후 데이터 3~5년 축적 후 재학습 시 편입.
- 미국 SPDR 미매핑 (XLI/XLU 등) 보강은 별도 작업.
- 신규 ETF *시가총액 작은* 경우 거래량 부족으로 PER 데이터 노이즈 가능 — 모니터링 후 제외/교체 결정.

---

## 11. 최종 산출물

- DB: `sector_valuation_kr` 테이블 18 row + 신규 2 컬럼
- Backend dict: 18개 항목
- Endpoint 응답: 신규 2 필드
- Frontend: 18개 노출 + 3개 항목 "데이터 부족" 라벨
- 캐시 버스트: main.js / main.css 한 차례
