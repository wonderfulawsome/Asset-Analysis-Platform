# KR 섹터 ETF 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한국 시장 특유 8개 섹터 ETF 추가 (총 10 → 18개) — 섹터 밸류에이션·섹터 모멘텀 탭에서 노출.

**Architecture:** `SECTOR_ETF_KR` dict 확장 → 모든 backfill·fetch·endpoint 가 자동 iterate. 데이터 부족(상장 < 3년) ETF 는 backend 기존 `hist_n` 필드 활용해 frontend 가 "데이터 부족" 라벨 부착. DB schema 변경 불필요.

**Tech Stack:** Python (pykrx + FDR 폴백, supabase-py) / Vanilla JS / CSS

**Spec:** `docs/superpowers/specs/2026-05-14-kr-sectors-design.md`

**Spec 대비 단순화:**
- DB 컬럼 (`lookback_days`/`data_sufficient`) 추가 *생략* — 기존 `hist_n` 필드 충분.
- 임계: `hist_n >= 36` (3년 월별) → data sufficient. frontend 분기.

---

## File Structure

| 파일 | 변경 유형 | 책임 |
|------|----------|------|
| `collector/sector_etf_kr.py` | Modify | `SECTOR_ETF_KR` dict 에 신규 8 항목 + 기존 10개 모두에 `listed_date` 필드 추가 |
| `scripts/check_kr_new_tickers.py` | Create | pykrx OHLCV/PER 응답 검증 일회용 스크립트 |
| `scripts/backfill_kr_sector_valuation.py` | Reuse | 신규 8 ticker 백필 실행 (수정 0 — dict iterate) |
| `static/js/home.js` | Modify | `loadSectorValuation` 의 valuations 렌더 — `hist_n < 36` 분기로 "데이터 부족" 라벨 부착 |
| `static/css/main.css` | Modify | `.sv-name.insufficient` opacity + `.sv-data-warn` 회색 라벨 |
| `templates/stocks.html` | Modify | `main.js?v=...` `main.css?v=...` 캐시 버스트 bump |

`processor/sector_valuation_kr_backfill.py` 와 `scheduler/job_kr.py` 는 dict iterate 패턴이라 코드 수정 0 (자동 신규 ticker 처리).

---

### Task 1: 신규 8 ticker 사전 검증 스크립트 작성

**Files:**
- Create: `scripts/check_kr_new_tickers.py`

목적: pykrx 가 신규 8 ticker 의 OHLCV 와 PER 응답하는지 사전 확인. 응답 실패 시 ticker 교체 또는 fallback 분류.

- [ ] **Step 1: 스크립트 파일 생성**

```python
"""KR 신규 섹터 ETF 사전 검증 — pykrx OHLCV + PER 응답 확인.

실행: python scripts/check_kr_new_tickers.py
"""
from __future__ import annotations

import datetime as _dt

NEW_TICKERS = {
    '401170': 'K-방산',
    '305720': '2차전지산업',
    '466920': '조선해운',
    '244620': '바이오',
    '228810': '미디어컨텐츠',
    '117700': '건설',
    '098560': '통신서비스',
    '445290': 'K-로봇액티브',
}


def _check_ohlcv(ticker: str) -> tuple[bool, str]:
    try:
        from pykrx import stock
        end = _dt.date.today().strftime('%Y%m%d')
        start = (_dt.date.today() - _dt.timedelta(days=30)).strftime('%Y%m%d')
        df = stock.get_etf_ohlcv_by_date(start, end, ticker)
        if df is None or df.empty:
            return False, 'empty result'
        return True, f'{len(df)} rows, latest close={df["종가"].iloc[-1]}'
    except Exception as e:
        return False, f'error: {e}'


def _check_per(ticker: str) -> tuple[bool, str]:
    try:
        from pykrx import stock
        today = _dt.date.today().strftime('%Y%m%d')
        df = stock.get_etf_portfolio_deposit_file(today, ticker)
        if df is None or df.empty:
            return False, 'empty portfolio'
        return True, f'{len(df)} holdings'
    except Exception as e:
        return False, f'error: {e}'


def main():
    print(f"{'Ticker':<8} {'Name':<12} {'OHLCV':<8} {'OHLCV detail':<35} {'Portfolio':<10} {'Portfolio detail'}")
    print('-' * 110)
    for ticker, name in NEW_TICKERS.items():
        ok_o, det_o = _check_ohlcv(ticker)
        ok_p, det_p = _check_per(ticker)
        print(f"{ticker:<8} {name:<12} {'OK' if ok_o else 'FAIL':<8} {det_o[:33]:<35} {'OK' if ok_p else 'FAIL':<10} {det_p[:50]}")


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 스크립트 실행 + 결과 확인**

Run: `python scripts/check_kr_new_tickers.py`
Expected: 각 ticker 별 OHLCV / Portfolio 응답 확인. 모두 OK 면 진행. FAIL 인 ticker 가 있으면 spec 의 ticker 교체 또는 fallback (PER 산출 X) 분류.

- [ ] **Step 3: 커밋**

```bash
git add scripts/check_kr_new_tickers.py
git commit -m "scripts: KR 신규 섹터 ETF 사전 검증 스크립트"
```

---

### Task 2: `SECTOR_ETF_KR` dict 확장 + listed_date 필드

**Files:**
- Modify: `collector/sector_etf_kr.py:18-29`

기존 10개에 `listed_date` 필드 추가 + 신규 8개 항목 (Task 1 결과로 검증된 ticker 만).

- [ ] **Step 1: dict 업데이트**

`collector/sector_etf_kr.py` 의 `SECTOR_ETF_KR` 전체 교체:

```python
SECTOR_ETF_KR = {
    # ── 기존 10개 (listed_date 추가) ──
    '139260': {'kr_name': 'IT',          'en_name': 'Technology',     'us_proxy': 'XLK',  'listed_date': '2008-04-30'},
    '091160': {'kr_name': '반도체',       'en_name': 'Semiconductor',  'us_proxy': 'SOXX', 'listed_date': '2006-06-27'},
    '300610': {'kr_name': '게임산업',     'en_name': 'Software/Game',  'us_proxy': 'IGV',  'listed_date': '2018-07-24'},
    '091170': {'kr_name': '은행',        'en_name': 'Financials',     'us_proxy': 'XLF',  'listed_date': '2006-06-27'},
    '139250': {'kr_name': '에너지화학',    'en_name': 'Energy/Chemical','us_proxy': 'XLE',  'listed_date': '2011-04-06'},
    '266420': {'kr_name': '헬스케어',     'en_name': 'Healthcare',     'us_proxy': 'XLV',  'listed_date': '2016-09-23'},
    '091180': {'kr_name': '자동차',       'en_name': 'Auto',           'us_proxy': 'XLY',  'listed_date': '2006-06-27'},
    '117680': {'kr_name': '철강',        'en_name': 'Steel/Materials','us_proxy': 'XLB',  'listed_date': '2009-10-30'},
    '341850': {'kr_name': '리츠',        'en_name': 'REIT',           'us_proxy': 'XLRE', 'listed_date': '2019-07-19'},
    '227560': {'kr_name': '필수소비재',    'en_name': 'Staples',        'us_proxy': 'XLP',  'listed_date': '2015-08-17'},
    # ── 신규 8개 (한국 특유 섹터, 2026-05-14 추가) ──
    '401170': {'kr_name': 'K-방산',       'en_name': 'Defense',        'us_proxy': 'ITA',  'listed_date': '2024-04-30'},
    '305720': {'kr_name': '2차전지산업',   'en_name': 'Battery',        'us_proxy': 'LIT',  'listed_date': '2018-09-12'},
    '466920': {'kr_name': '조선해운',     'en_name': 'Shipbuilding',   'us_proxy': 'SEA',  'listed_date': '2023-09-15'},
    '244620': {'kr_name': '바이오',       'en_name': 'Biotech',        'us_proxy': 'XBI',  'listed_date': '2016-05-13'},
    '228810': {'kr_name': '미디어컨텐츠',  'en_name': 'Media/Content',  'us_proxy': 'XLC',  'listed_date': '2015-10-07'},
    '117700': {'kr_name': '건설',        'en_name': 'Construction',   'us_proxy': 'ITB',  'listed_date': '2009-10-30'},
    '098560': {'kr_name': '통신서비스',   'en_name': 'Telecom',        'us_proxy': 'XLC',  'listed_date': '2008-12-12'},
    '445290': {'kr_name': 'K-로봇액티브', 'en_name': 'Robotics',       'us_proxy': 'BOTZ', 'listed_date': '2023-03-21'},
}
```

기존 10개 항목 keys 와 values 그대로 + `listed_date` 만 추가. 신규 8개 항목 추가.

- [ ] **Step 2: import 영향 확인**

Run: `python -c "from collector.sector_etf_kr import SECTOR_ETF_KR; print(len(SECTOR_ETF_KR), 'tickers'); print(list(SECTOR_ETF_KR.keys()))"`
Expected: `18 tickers` 출력 + 18개 ticker 목록.

- [ ] **Step 3: pykrx OHLCV 한 ticker 확인 (회귀 가드)**

Run: `python -c "from collector.sector_etf_kr import fetch_sector_etf_prices_kr; r = fetch_sector_etf_prices_kr(days=30); print(len(r), 'ticker OHLCV fetched'); print(list(r.keys()))"`
Expected: 18개 또는 일부 fetch 실패 — Task 1 검증 결과와 일치.

- [ ] **Step 4: 커밋**

```bash
git add collector/sector_etf_kr.py
git commit -m "feat(kr-sector): SECTOR_ETF_KR dict 8개 신규 + listed_date 필드"
```

---

### Task 3: 신규 8 ticker 백필 실행

**Files:**
- Reuse: `scripts/backfill_kr_sector_valuation.py` (또는 `processor/sector_valuation_kr_backfill.py` 직접 실행)

`SECTOR_ETF_KR` dict iterate 패턴이라 코드 수정 0. 단순 실행 + DB row 검증.

- [ ] **Step 1: 백필 실행**

Run: `python -m processor.sector_valuation_kr_backfill`
Expected: stdout 에 `[KR-backfill] 총 N 행 upsert 완료 (18 ETF × ~60개월)` 또는 fetch 실패 ticker 별 skip 메시지.

- [ ] **Step 2: DB row 카운트 검증**

Run:
```bash
python -c "
from database.repositories import fetch_sector_valuation_history
rows = fetch_sector_valuation_history(region='kr', days=60)
tickers = set(r['ticker'] for r in rows)
print(f'{len(tickers)} unique tickers, total {len(rows)} rows')
print(sorted(tickers))
"
```
Expected: 18 또는 13~18 (일부 fetch 실패 가능). 신규 8개 중 몇 개 들어왔는지 확인.

- [ ] **Step 3: 커밋 (DB upsert 만, 코드 변경 없음)**

스크립트 실행 결과만 정리 (커밋 X — DB row 가 origin of truth).

---

### Task 4: frontend `loadSectorValuation` — 데이터 부족 분기 추가

**Files:**
- Modify: `static/js/home.js:193-258`

KR 분기 (`isKr === true`) 의 `rowsHtml` 빌더에 `hist_n < 36` 일 때 row 옆에 "데이터 부족 (N개월)" 라벨 부착.

- [ ] **Step 1: rowsHtml 빌더 수정 (KR 분기 line 235~241)**

기존:
```javascript
rowsHtml = data.valuations.map(v => {
  const fgCol = colorByZ(v.per_z);
  return `
    <div class="sv-name">${krSector(v.ticker, v.sector_name)} <span style="color:#9ca3af;font-size:10px;">${v.ticker}</span></div>
    <div class="sv-cell" style="text-align:right;color:#9ca3af;">${fmtPer(v.per_mean)}</div>
    <div class="sv-cell" style="background:${fgCol};">${fmtPer(v.per)}</div>`;
}).join('');
```

신규:
```javascript
rowsHtml = data.valuations.map(v => {
  const fgCol = colorByZ(v.per_z);
  const histN = v.hist_n ?? 0;
  const insufficient = histN < 36;  // 3년 월별 = 36 표본 기준
  const warn = insufficient
    ? `<span class="sv-data-warn">데이터 부족 (${histN}개월)</span>`
    : '';
  const nameClass = insufficient ? 'sv-name insufficient' : 'sv-name';
  return `
    <div class="${nameClass}">${krSector(v.ticker, v.sector_name)} <span style="color:#9ca3af;font-size:10px;">${v.ticker}</span>${warn}</div>
    <div class="sv-cell" style="text-align:right;color:#9ca3af;">${fmtPer(v.per_mean)}</div>
    <div class="sv-cell" style="background:${fgCol};">${fmtPer(v.per)}</div>`;
}).join('');
```

US 분기는 그대로 (사용자 요청 범위 X).

- [ ] **Step 2: 변경 위치 lint/syntax 확인**

Run: `node -c static/js/home.js`
Expected: no errors.

- [ ] **Step 3: 커밋**

```bash
git add static/js/home.js
git commit -m "feat(sector-val): KR 데이터 부족 ETF 에 hist_n<36 라벨"
```

---

### Task 5: CSS — `.sv-name.insufficient` + `.sv-data-warn` 룰 추가

**Files:**
- Modify: `static/css/main.css`

기존 `.sv-name` 룰 근처에 추가.

- [ ] **Step 1: 룰 위치 grep**

Run: `grep -n "\.sv-name\|\.sv-cell\|\.sv-h" static/css/main.css | head -10`
Expected: 기존 룰 위치 파악.

- [ ] **Step 2: 신규 룰 append (파일 끝 또는 sv- 룰 그룹 끝)**

`static/css/main.css` 에 추가:
```css
/* ── sector-valuation 데이터 부족 ETF 라벨 ── */
.sv-name.insufficient {
  opacity: 0.7;                                    /* 회색 톤 */
}
.sv-data-warn {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(156, 163, 175, 0.15);
  color: #9ca3af;
  font-size: 9.5px;
  font-weight: 500;
  vertical-align: middle;
}
```

- [ ] **Step 3: 커밋**

```bash
git add static/css/main.css
git commit -m "style(sector-val): 데이터 부족 ETF 라벨 룰 추가"
```

---

### Task 6: 캐시 버스트

**Files:**
- Modify: `templates/stocks.html` (main.js + main.css `?v=` bump)

- [ ] **Step 1: 현재 버전 확인**

Run: `grep -n "main\.js?v=\|main\.css?v=" templates/stocks.html`
Expected: 두 줄 출력 (현재 v=??).

- [ ] **Step 2: 버전 +1 bump**

각 `?v=N` 의 N 을 1 증가. 예: `main.js?v=158` → `?v=159`, `main.css?v=138` → `?v=139`.

- [ ] **Step 3: 커밋**

```bash
git add templates/stocks.html
git commit -m "chore(cache): main.js/main.css 캐시 버스트 — KR 섹터 확장"
```

---

### Task 7: 통합 검증 (endpoint + frontend)

**Files:**
- 없음 (검증만)

- [ ] **Step 1: 로컬 서버 재시작**

Run: `python -m uvicorn api.app:app --port 8001 --loop asyncio`
Expected: `Application startup complete.`

- [ ] **Step 2: endpoint 응답 확인**

Run:
```bash
curl -s "http://localhost:8001/api/sector-cycle/valuation?region=kr" -o out_kr.json
PYTHONIOENCODING=utf-8 python -c "
import json, sys
sys.stdout.reconfigure(encoding='utf-8')
d=json.load(open('out_kr.json',encoding='utf-8'))
print(f'valuations: {len(d.get(\"valuations\",[]))} entries')
for v in d.get('valuations',[]):
    print(f'  {v[\"ticker\"]} {v[\"sector_name\"]:<15} per={v.get(\"per\")} hist_n={v.get(\"hist_n\")}')
"
rm out_kr.json
```
Expected: valuations 18개 또는 13~18개 (백필 결과 의존). 신규 8개 ticker 중 ETF 별 hist_n 출력.

- [ ] **Step 3: 브라우저에서 시각 확인**

`http://localhost:8001` → KR 모드 → 섹터 밸류에이션 탭
Expected: 신규 8개 표시 + 상장 < 3년 ETF (401170, 466920, 445290) 옆에 "데이터 부족 (N개월)" 회색 라벨.

- [ ] **Step 4: 회귀 — 기존 10개 PER 값 변경 X**

이전 백필 row 와 신규 백필 row 의 동일 (date, ticker) 조합에서 per 값 동일성 확인. Random 1~2 ticker 만 spot check.

Run:
```bash
PYTHONIOENCODING=utf-8 python -c "
from database.repositories import fetch_sector_valuation_history
rows = fetch_sector_valuation_history(region='kr', days=60)
sample = [r for r in rows if r['ticker'] == '139260'][:5]
for r in sample:
    print(r['date'], r['ticker'], r['per'])
"
```
Expected: IT(139260) 최근 5개월 PER 값 출력. 옛 값과 비교 (수동).

---

### Task 8: 사용자 시각 검증 + 커밋·푸시

**Files:**
- 없음 (사용자 승인 후 git push)

- [ ] **Step 1: 사용자에게 시각 검증 요청**

화면 캡쳐 또는 응답 sample 사용자에게 보여주기. 신규 8 섹터 노출 + 라벨 정상 확인 요청.

- [ ] **Step 2: 사용자 승인 후 push**

```bash
git push
```
Expected: Railway 자동 배포 1~2분 후 dinsightlab.com 에서 적용.

---

## Self-Review Checklist

**Spec coverage:**
- ✓ SECTOR_ETF_KR dict 확장 → Task 2
- ✓ listed_date 필드 → Task 2
- ✓ 백필 → Task 3
- ✓ 데이터 부족 라벨 → Task 4
- ✓ CSS → Task 5
- ✓ 캐시 버스트 → Task 6
- ✓ 검증 → Task 7

**Spec 대비 단순화:**
- DB 컬럼 (`lookback_days`/`data_sufficient`) 추가 *생략* — 기존 `hist_n` 활용. spec 수정 필요? 또는 plan 내 결정 명시로 충분 (현재 plan 상단 명시함).
- endpoint 응답 신규 필드 추가 *생략* — `hist_n` 이미 응답 포함.

**Placeholder scan:**
- TBD/TODO 없음 ✓
- 모든 step 에 실행 가능한 명령/코드 포함 ✓

**Type consistency:**
- `hist_n` 필드명 통일 ✓
- `insufficient` 임계 = 36 (월) 일관 ✓

**Risk:**
- pykrx 가 신규 ETF 일부 미지원 가능 (특히 active fund 445290). Task 1 사전 검증으로 조기 발견.
- 백필 시간 = ETF 18개 × pykrx fetch ≈ 1~3분 (네트워크 의존).

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-14-kr-sectors-expansion.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - 각 task 별로 fresh subagent 가 구현, task 사이 리뷰, 빠른 iteration.

**2. Inline Execution** - 이 세션에서 executing-plans skill 으로 일괄 실행, checkpoint 마다 리뷰.

**Which approach?**
