# Update Log

---

## 2026-04-09 12:21 (UTC) — 30일 예측 버튼 로딩 무한루프 수정

### 문제
- 30일 예측 버튼 클릭 시 로딩만 계속 되고 결과가 표시되지 않는 버그
- 원인: 백엔드에서 ML 모델 학습(30~60초 이상 소요)을 백그라운드로 실행하지만 즉시 에러를 반환하고, 프론트엔드는 3회 × 3초 = 최대 9초만 대기하여 시간 부족으로 실패

### 수정 내용

| 파일 | 변경 사항 |
|------|-----------|
| `api/routers/chart.py` | `get_prediction()` 엔드포인트에 DB 폴링 대기 로직 추가 (최대 120초, 3초 간격). 백그라운드 스레드 완료 감지 후 즉시 결과 반환 |
| `static/js/chart.js` | 프론트엔드 재시도 루프 제거 → AbortController 기반 150초 타임아웃으로 변경. 로딩 점 애니메이션 추가. 실패 시 에러 토스트 메시지 표시 (`_showPredictError()` 함수 추가) |
| `static/js/i18n.js` | `chart.predictError` 번역 키 추가 (한국어/영어). `chart.predictLoading` 텍스트에서 말줄임표 제거 (JS에서 동적 애니메이션 처리) |

### 변경된 코드 요약

**api/routers/chart.py (line 182~223)**
- 기존: `result is None` → 백그라운드 스레드 시작 → 즉시 에러 반환
- 변경: `result is None` → 백그라운드 스레드 시작 → DB 폴링으로 최대 120초 대기 → 결과 반환 또는 타임아웃 에러

**static/js/chart.js (line 826~907)**
- 기존: 3회 재시도 루프 (9초 대기)
- 변경: 단일 fetch + 150초 타임아웃 + 로딩 애니메이션 + 에러 토스트

**static/js/i18n.js (line 181~182, 586~587)**
- 추가: `chart.predictError` (한국어: '예측 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.')
- 추가: `chart.predictError` (영어: 'Failed to load prediction. Please try again later.')
