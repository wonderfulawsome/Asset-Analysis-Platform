# ========================================================
#   UPDATE LOG - 변경 이력 보관 파일
#   (실행용이 아닌 코드 변경 내용 기록/보관용)
# ========================================================


# ══════════════════════════════════════════════════════════
# [1] 2026-04-09 12:21 (UTC)
#     30일 예측 버튼 로딩 무한루프 수정
# ══════════════════════════════════════════════════════════
#
# [문제]
#   - 30일 예측 버튼 클릭 시 로딩만 계속 되고 결과가 표시되지 않는 버그
#   - 원인: 백엔드에서 ML 모델 학습(30~60초 이상 소요)을 백그라운드로 실행하지만
#     즉시 에러를 반환하고, 프론트엔드는 3회 x 3초 = 최대 9초만 대기하여 시간 부족으로 실패
#
# [수정 파일]
#   1. api/routers/chart.py    - get_prediction() 엔드포인트에 DB 폴링 대기 로직 추가
#   2. static/js/chart.js      - 프론트엔드 재시도 루프 제거, AbortController 타임아웃 + 로딩 애니메이션 + 에러 토스트
#   3. static/js/i18n.js       - chart.predictError 번역 키 추가 (한/영)
#
# ──────────────────────────────────────────────────────────
# 파일 1: api/routers/chart.py  (line 182~232)
# ──────────────────────────────────────────────────────────

@router.get('/predict')                                     # GET /api/chart/predict 엔드포인트 정의
def get_prediction(ticker: str = Query('SPY', description='ETF 티커')):  # 쿼리 파라미터로 티커 받기 (기본값 SPY)
    # 5-모델 앙상블 30일 예측 결과를 DB에서 조회
    # DB에 없으면 백그라운드 재생성 후 폴링하여 완료를 대기
    from database.repositories import fetch_chart_predict    # DB 조회 함수 임포트

    ticker = ticker.upper()                                  # 티커를 대문자로 통일
    if ticker not in CHART_TICKERS:                          # 지원하지 않는 티커면 에러 반환
        return {'error': 'unsupported ticker'}

    def _fetch_valid(t):                                     # DB에서 예측 데이터 조회 + 유효성 검증 내부 함수
        r = fetch_chart_predict(t)                           # Supabase에서 최신 예측 결과 1건 조회
        if r is not None:                                    # 조회 결과가 있으면
            sp = _sanitize_floats(r.get('predicted', []))    # predicted 배열에서 NaN/Inf → None 변환
            if _is_prediction_valid(sp):                     # 유효한 예측 데이터인지 검증
                return r                                     # 유효하면 결과 반환
            print(f'[Chart] {t} 예측 데이터 손상 감지')       # 손상된 경우 로그 출력
        return None                                          # 데이터 없거나 손상이면 None 반환

    result = _fetch_valid(ticker)                            # DB에서 유효한 예측 데이터 조회

    if result is None:                                       # DB에 유효한 예측이 없으면
        # 백그라운드에서 재생성 트리거 (중복 실행 방지)
        if ticker not in _predict_running:                   # 이미 해당 티커 예측이 실행 중이 아니면
            _predict_running.add(ticker)                     # 실행 중 목록에 추가
            threading.Thread(target=_regenerate_in_background, args=(ticker,),  # 별도 스레드에서 예측 재생성 시작
                             daemon=True).start()            # 데몬 스레드로 실행 (메인 종료 시 함께 종료)

        # 백그라운드 재생성 완료까지 폴링 대기 (최대 ~120초)
        _POLL_INTERVAL = 3                                   # 3초 간격으로 폴링
        _MAX_POLLS = 40                                      # 40 × 3초 = 최대 120초 대기
        for i in range(_MAX_POLLS):                          # 최대 40회 반복
            time.sleep(_POLL_INTERVAL)                       # 3초 대기
            # 백그라운드 스레드 완료 확인
            if ticker not in _predict_running:               # 스레드가 완료되어 목록에서 제거됐으면
                result = _fetch_valid(ticker)                # DB에서 결과 다시 조회
                break                                        # 루프 종료
            # 스레드 실행 중에도 주기적으로 DB 확인 (15초 간격)
            if i % 5 == 4:                                   # 5회(15초)마다 한 번씩
                result = _fetch_valid(ticker)                # DB에서 결과 확인
                if result is not None:                       # 결과가 있으면
                    break                                    # 루프 종료

        if result is None:                                   # 120초 대기 후에도 결과 없으면
            return {'error': 'prediction generation failed, please try again later'}  # 에러 반환

    return {                                                 # 정상 응답 반환
        'ticker': result['ticker'],                          # 티커명
        'actual': _sanitize_floats(result['actual']),        # 실제 가격 (NaN/Inf 제거)
        'predicted': _sanitize_floats(result['predicted']),  # 예측 가격 (NaN/Inf 제거)
    }


# ──────────────────────────────────────────────────────────
# 파일 2: static/js/chart.js  (line 826~916)
# ──────────────────────────────────────────────────────────

def setupPredictButton():                                    # JS 함수 — 30일 예측 버튼 클릭 핸들러
    btn = document.getElementById('predict-toggle-btn')      # 예측 토글 버튼 DOM 요소 가져오기
    if not btn: return                                       # 버튼이 없으면 종료
    btn.addEventListener('click', async () => {              # 클릭 이벤트 리스너 등록
        if _predictVisible:                                  # 이미 예측이 표시된 상태면 숨기기
            _predictVisible = False                          # 예측 표시 상태 해제
            _predictData = None                              # 예측 데이터 초기화
            btn.classList.remove('active')                   # 버튼 활성 스타일 제거
            _reRenderCharts(False)                           # 차트 다시 렌더 (예측 없이)
            renderPredictLegend(False)                       # 예측 범례 숨기기
            return                                           # 함수 종료

        _predictVisible = True                               # 예측 표시 상태로 전환
        btn.classList.add('active')                          # 버튼 활성 스타일 추가
        btn.disabled = True                                  # 중복 클릭 방지 (버튼 비활성화)
        btn.textContent = t('chart.predictLoading')          # 버튼 텍스트를 "실행 중"으로 변경
        showPredictDisclaimer()                              # 예측 면책 안내 토스트 표시

        # 로딩 애니메이션: 점 개수가 변하는 텍스트 ("실행 중.", "실행 중..", "실행 중...")
        dotCount = 0                                         # 점 개수 카운터 초기화
        loadingInterval = setInterval(() => {                # 600ms 간격 반복 실행
            dotCount = (dotCount + 1) % 4                    # 0→1→2→3→0 순환
            dots = '.'.repeat(dotCount or 1)                 # 점 문자열 생성 (최소 1개)
            btn.textContent = t('chart.predictLoading') + dots  # 버튼 텍스트 갱신
        }, 600)                                              # 0.6초마다 실행

        try:
            # 서버가 최대 ~120초 대기하므로 타임아웃을 150초로 설정
            controller = AbortController()                   # 요청 취소용 컨트롤러 생성
            timeoutId = setTimeout(() => controller.abort(), 150000)  # 150초 후 자동 취소

            data = None                                      # 응답 데이터 초기화
            try:
                res = await fetch(f'/api/chart/predict?ticker={_chartTicker}', {  # 예측 API 호출
                    signal: controller.signal,               # 타임아웃 시 요청 취소 시그널 연결
                })
                data = await res.json()                      # JSON 응답 파싱
            except e:                                        # 요청 실패 시
                if e.name == 'AbortError':                   # 150초 타임아웃 초과인 경우
                    data = { error: 'timeout' }              # 타임아웃 에러 객체로 대체
                else:
                    raise e                                  # 다른 에러는 상위로 전파
            finally:
                clearTimeout(timeoutId)                      # 타임아웃 타이머 정리

            if not data or data.error:                       # 에러 시 예측 모드 해제 + 에러 토스트
                _predictVisible = False                      # 예측 표시 상태 해제
                btn.classList.remove('active')               # 버튼 활성 스타일 제거
                _showPredictError()                          # 에러 토스트 표시
                return                                       # 함수 종료

            _predictData = data                              # 예측 데이터 저장
            _reRenderCharts(False)                           # 차트 다시 렌더 (예측 포함)
            renderPredictLegend(True)                        # 예측 범례 표시
            # 예측 영역으로 부드럽게 스크롤
            setTimeout(() => {                               # 50ms 후 실행 (렌더링 완료 대기)
                sc = document.getElementById('candle-scroll')  # 스크롤 컨테이너 요소
                if sc: sc.scrollTo({ left: sc.scrollWidth, behavior: 'smooth' })  # 오른쪽 끝으로 스크롤
            }, 50)
        except:                                              # 예외 발생 시
            _predictVisible = False                          # 예측 표시 상태 해제
            btn.classList.remove('active')                   # 버튼 활성 스타일 제거
            _showPredictError()                              # 에러 토스트 표시
        finally:                                             # 성공/실패 무관하게 항상 실행
            clearInterval(loadingInterval)                   # 로딩 애니메이션 중지
            btn.disabled = False                             # 버튼 다시 활성화
            btn.textContent = t('chart.predictBtn')          # 버튼 텍스트 원래대로 복원
    })


def _showPredictError():                                     # JS 함수 — 예측 실패 시 빨간 토스트 표시
    toast = document.getElementById('predict-disclaimer-toast')  # 기존 토스트 요소 찾기
    if not toast:                                            # 없으면 새로 생성
        toast = document.createElement('div')                # div 요소 생성
        toast.id = 'predict-disclaimer-toast'                # ID 설정
        toast.className = 'predict-disclaimer-toast'         # CSS 클래스 설정
        document.body.appendChild(toast)                     # body에 추가
    toast.textContent = t('chart.predictError')              # 에러 메시지 텍스트 설정
    toast.style.background = 'rgba(220,38,38,0.95)'          # 빨간 배경색 적용
    toast.classList.remove('hide')                           # 숨김 클래스 제거
    toast.classList.add('show')                              # 표시 클래스 추가
    setTimeout(() => {                                       # 4초 후 자동 숨김
        toast.classList.remove('show')                       # 표시 클래스 제거
        toast.classList.add('hide')                          # 숨김 클래스 추가
        toast.style.background = ''                          # 배경색 초기화
    }, 4000)                                                 # 4000ms = 4초


# ──────────────────────────────────────────────────────────
# 파일 3: static/js/i18n.js  (한국어 line 181~182, 영어 line 587~588)
# ──────────────────────────────────────────────────────────

# 한국어
'chart.predictLoading': '예측 모델 실행 중',
'chart.predictError': '예측 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.',

# 영어
'chart.predictLoading': 'Running forecast model',
'chart.predictError': 'Failed to load prediction. Please try again later.',


# ══════════════════════════════════════════════════════════
# [2] 2026-04-09 12:35 (UTC)
#     방향성 예측 추이 그래프 4월 2일 이후 업데이트 안 되는 문제 수정
# ══════════════════════════════════════════════════════════
#
# [문제]
#   - 신호 탭의 "방향성 예측 추이 (30일)" 그래프가 4월 2일 이후 업데이트되지 않음
#   - 원인 1: scheduler Step 7에서 월초 모델 재학습(Optuna 50 trials) 실패 시
#     예측까지 통째로 스킵됨 (재학습과 예측이 같은 try/except에 있어서)
#   - 원인 2: 경량 파이프라인(Step 5b)에서 FRED/Yahoo 결측 시 NaN으로 최신 행 드롭
#   - 원인 3: compute_features()에서 Yahoo ^TNX/^IRX 수집 실패 시 CORE_FEATURES 전체 NaN
#
# [수정 파일]
#   1. scheduler/job.py           - Step 7 재학습/예측 분리, 경량 fallback 추가
#   2. scheduler/job.py           - Step 5b ffill 추가
#   3. collector/crash_surge_data.py - compute_features() FRED/Yahoo 빈 데이터 안전 처리
#
# ──────────────────────────────────────────────────────────
# 파일 1: scheduler/job.py  Step 7 (line 225~289)
#   - 모델 재학습을 별도 try/except로 분리 → 실패해도 기존 모델로 예측 계속
#   - 전체 수집 실패 시 경량 수집(fetch_crash_surge_light) fallback 추가
# ──────────────────────────────────────────────────────────

        # Step 7: XGBoost 폭락/급등 전조 탐지 (모델 학습 + 오늘 예측)
        print('\n[Step 7] 폭락/급등 전조 탐지...')               # 진행 로그 출력
        cs_datasets = None                                       # 데이터셋 초기화
        cs_model = None                                          # 모델 초기화
        cs_should_retrain = False                                # 재학습 필요 여부 플래그
        try:
            raw = fetch_crash_surge_raw(fred_cache=fred_cache)   # SPY+FRED+Yahoo+Cboe 전체 원시 데이터 수집
            save_fred_cache(raw['fred'])                          # FRED 데이터를 pickle 캐시로 저장
            features = compute_features(raw['spy'], raw['fred'], raw['cboe'],
                                                  raw['yahoo_macro'])  # 원시 데이터 → 44개 파생 피처 계산
            labels = compute_labels(raw['spy']['Close'])          # SPY 종가 기반 3클래스 라벨 생성 (정상/폭락/급등)
            cs_datasets = prepare_datasets(features, labels, raw['spy']['Close'])  # train/calib/test/dev/추론 데이터셋 분할

            cs_model = load_crash_surge_model()                   # 기존 학습된 XGBoost 모델 로드
            current_month = datetime.date.today().strftime('%Y-%m')  # 현재 연-월 문자열 (예: 2026-04)
            cs_should_retrain = (cs_model is None or              # 모델이 없거나
                                 cs_model.get('train_month') != current_month)  # 학습 월이 다르면 재학습 필요
            if cs_should_retrain:                                 # 재학습이 필요한 경우
                try:
                    print('[Step 7] 모델 재학습 (Optuna 50 trials)...')  # 재학습 시작 로그
                    X_tr, y_tr = cs_datasets['train']             # 학습 데이터 (피처, 라벨)
                    X_cal, y_cal = cs_datasets['calib']           # 캘리브레이션 데이터 (Platt Scaling용)
                    X_te, y_te = cs_datasets['test']              # 테스트 데이터 (평가용)
                    X_dev, y_dev = cs_datasets['dev']             # 개발 데이터 (학습+캘리브레이션)
                    X_full = cs_datasets['df_full'][ALL_FEATURES].values  # 전체 데이터 (추론용)
                    cs_model = train_crash_surge(X_tr, y_tr, X_cal, y_cal, X_te, y_te,
                                                 X_dev, y_dev, X_full, n_trials=50)  # Optuna 50회 튜닝으로 모델 학습
                except Exception as e:                            # 재학습 실패 시
                    print(f'[Step 7] 모델 재학습 실패, 기존 모델로 예측 계속: {e}')  # 실패 로그
                    traceback.print_exc()                         # 스택 트레이스 출력
                    cs_model = load_crash_surge_model()            # 기존 모델 다시 로드하여 예측은 계속
            else:                                                 # 재학습 불필요 (같은 월)
                print(f'[Step 7] 기존 모델 사용 (학습 월: {cs_model["train_month"]})')  # 기존 모델 사용 로그

            # 예측은 재학습 성패와 무관하게 실행
            if cs_model is not None:                              # 사용 가능한 모델이 있으면
                latest_row = cs_datasets['df_full'][ALL_FEATURES].iloc[[-1]].values  # 최신 1행 피처 추출
                cs_result = predict_crash_surge(latest_row, cs_model)                 # 폭락/급등 점수 예측
                upsert_crash_surge(cs_result)                                         # 결과를 Supabase에 저장
            else:                                                 # 모델이 없으면
                print('[Step 7] 사용 가능한 모델 없음, 예측 건너뜀')  # 스킵 로그
        except Exception as e:                                    # 전체 수집/처리 실패 시
            print(f'[Step 7] 폭락/급등 전조 실패, 경량 fallback 시도: {e}')  # 실패 로그
            traceback.print_exc()                                 # 스택 트레이스 출력
            # Fallback: 경량 수집으로 예측 시도 (전체 수집 실패 시)
            try:
                fallback_model = load_crash_surge_model()         # 기존 모델 로드
                if fallback_model is not None:                    # 모델이 있으면 경량 예측 시도
                    import numpy as np                            # NaN/Inf 처리용
                    from collector.crash_surge_data import CORE_FEATURES, AUX_FEATURES  # 피처 목록 임포트
                    raw_light = fetch_crash_surge_light()          # 최근 300일 경량 데이터 수집
                    features_light = compute_features(raw_light['spy'], raw_light['fred'],
                                                      raw_light['cboe'], raw_light['yahoo_macro'])  # 피처 계산
                    feat_row = features_light[ALL_FEATURES].copy()  # 44개 피처만 추출
                    feat_row = feat_row.ffill()                    # 결측값을 직전 행 값으로 채움
                    feat_row = feat_row.dropna(subset=CORE_FEATURES)  # 핵심 피처에 NaN 있는 행 제거
                    feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)  # 보조 피처 NaN → 0 대체
                    feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)  # Inf 제거
                    if len(feat_row) > 0:                         # 유효한 행이 있으면
                        latest_row = feat_row.iloc[[-1]].values   # 최신 1행 추출
                        cs_result = predict_crash_surge(latest_row, fallback_model)  # 예측 실행
                        upsert_crash_surge(cs_result)             # DB 저장
                        print('[Step 7-fallback] 경량 수집으로 예측 성공')  # 성공 로그
                    else:                                         # 유효한 행이 없으면
                        print('[Step 7-fallback] 유효한 피처 행 없음')  # 실패 로그
            except Exception as e2:                               # 경량 fallback도 실패 시
                print(f'[Step 7-fallback] 경량 fallback도 실패: {e2}')  # 최종 실패 로그

# ──────────────────────────────────────────────────────────
# 파일 2: scheduler/job.py  Step 5b (line 177)
#   - ffill() 추가: FRED/Yahoo 결측값을 직전 행 값으로 채움
# ──────────────────────────────────────────────────────────

                feat_row = features_light[ALL_FEATURES].copy()  # 44개 피처만 추출하여 복사
                feat_row = feat_row.ffill()                     # FRED/Yahoo 결측 → 직전 값으로 채움 ← [2]에서 추가됨
                feat_row = feat_row.dropna(subset=CORE_FEATURES)  # 핵심 피처에 NaN 있는 행 제거
                feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)  # 보조 피처 NaN → 0 대체
                feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)  # Inf → NaN 변환 후 제거

# ──────────────────────────────────────────────────────────
# 파일 3: collector/crash_surge_data.py  compute_features() (line 344~367)
#   - FRED 신용스프레드(HY_OAS, BBB_OAS, CCC_OAS) 빈 데이터 → 0 대체
#   - Yahoo ^TNX(DGS10), ^IRX(IRX_3M) 빈 데이터 → 0 대체
# ──────────────────────────────────────────────────────────

    # ── 신용 (3개) — FRED 전용 ──
    for col in ['HY_OAS', 'BBB_OAS', 'CCC_OAS']:               # 3개 신용스프레드 순회
        s = fred[col][col].reindex(spy.index).ffill()           # SPY 영업일 기준으로 정렬 + 직전 값 채움
        if s.isna().all():                                      # FRED 수집이 완전히 실패한 경우 (전부 NaN)
            print(f'  [compute_features] {col}: FRED 데이터 비어있음, 0으로 대체')  # 경고 로그
            s = s.fillna(0)                                     # 전체를 0으로 대체하여 피처 누락 방지
        feat[col] = s                                           # 피처 DataFrame에 추가

    # ── 금리 (2개) — Yahoo ^TNX, ^IRX 사용 ──
    dgs10_s = yahoo_macro.get('DGS10', pd.Series(dtype=float))  # ^TNX에서 가져온 10년 국채금리 시리즈
    irx_s = yahoo_macro.get('IRX_3M', pd.Series(dtype=float))   # ^IRX에서 가져온 3개월 국채금리 시리즈
    dgs10_ff = dgs10_s.reindex(spy.index).ffill()               # SPY 영업일 기준 정렬 + 직전 값 채움
    irx_ff = irx_s.reindex(spy.index).ffill()                   # SPY 영업일 기준 정렬 + 직전 값 채움
    if dgs10_ff.isna().all():                                   # Yahoo ^TNX 수집 실패 시 (전부 NaN)
        print('  [compute_features] DGS10: Yahoo ^TNX 데이터 비어있음, 0으로 대체')  # 경고 로그
        dgs10_ff = dgs10_ff.fillna(0)                           # 0으로 대체
    if irx_ff.isna().all():                                     # Yahoo ^IRX 수집 실패 시 (전부 NaN)
        print('  [compute_features] IRX_3M: Yahoo ^IRX 데이터 비어있음, 0으로 대체')  # 경고 로그
        irx_ff = irx_ff.fillna(0)                               # 0으로 대체
    feat['DGS10_LEVEL'] = dgs10_ff                              # 10년 국채금리 피처
    feat['T10Y3M_SLOPE'] = dgs10_ff - irx_ff                    # 수익률곡선 기울기 피처 (10Y - 3M, 역전 시 음수)

# ──────────────────────────────────────────────────────────
# 파일 4: collector/crash_surge_data.py  fetch_crash_surge_light() (line 244~258)
#   - SPY OHLCV 다운로드에 3회 재시도 로직 추가
# ──────────────────────────────────────────────────────────

    # 1) SPY OHLCV — 장 중이면 실시간 가격 포함 (재시도 포함)
    print('  [CrashSurge-Light] SPY OHLCV 수집...')             # 수집 시작 로그
    spy = None                                                   # SPY 데이터 초기화
    for attempt in range(3):                                     # 최대 3회 시도
        try:
            spy_raw = yf.Ticker('SPY').history(period=f'{lookback_days}d', auto_adjust=True)  # Yahoo에서 최근 N일 SPY 가격 다운로드
            spy_raw = _strip_tz(spy_raw)                         # 타임존 정보 제거 (인덱스 통일)
            if not spy_raw.empty and len(spy_raw) >= 2:          # 최소 2행 이상이면 유효한 데이터
                spy = spy_raw[['Open', 'High', 'Low', 'Close', 'Volume']]  # OHLCV 컬럼만 추출
                break                                            # 성공 시 루프 종료
        except Exception as e:                                   # 다운로드 실패 시
            print(f'  [CrashSurge-Light] SPY 수집 시도 {attempt+1}/3 실패: {e}')  # 실패 로그
        if attempt < 2:                                          # 마지막 시도가 아니면
            time.sleep(2)                                        # 2초 대기 후 재시도
    if spy is None or spy.empty:                                 # 3회 모두 실패 시
        raise RuntimeError('SPY OHLCV 수집 실패 (3회 재시도 후)')  # 예외 발생하여 상위에서 처리

# ──────────────────────────────────────────────────────────
# 파일 5: api/routers/crash_surge.py  /refresh 엔드포인트 (line 125~170)
#   - 수동 데이터 새로고침 API 추가
#   - 스케줄러 없이도 crash_surge 예측을 즉시 재실행 가능
# ──────────────────────────────────────────────────────────

@router.get('/refresh')                                          # GET /api/crash-surge/refresh 엔드포인트 정의
def refresh_crash_surge():                                       # 수동 새로고침 API 함수
    global _refresh_running                                      # 전역 플래그 사용 선언
    if _refresh_running:                                         # 이미 실행 중이면 중복 방지
        return {'status': 'already_running'}                     # 중복 실행 방지 응답

    _refresh_running = True                                      # 실행 중 플래그 설정
    try:
        import numpy as np                                       # Inf/NaN 처리용
        from collector.crash_surge_data import (                  # 데이터 수집/피처 계산 함수 임포트
            fetch_crash_surge_light, compute_features,
            ALL_FEATURES, CORE_FEATURES, AUX_FEATURES,
        )
        from processor.feature3_crash_surge import (              # 모델 로드/예측 함수 임포트
            load_model as load_crash_surge_model, predict_crash_surge,
        )

        cs_model = load_crash_surge_model()                      # 기존 학습된 XGBoost 모델 로드
        if cs_model is None:                                     # 모델이 없으면 에러 반환
            return {'status': 'error', 'message': 'no model available'}

        raw = fetch_crash_surge_light()                          # 최근 300일 경량 데이터 수집
        features = compute_features(raw['spy'], raw['fred'], raw['cboe'], raw['yahoo_macro'])  # 44개 피처 계산
        feat_row = features[ALL_FEATURES].copy()                 # 44개 피처만 추출하여 복사
        feat_row = feat_row.ffill()                              # 결측값을 직전 행 값으로 채움
        feat_row = feat_row.dropna(subset=CORE_FEATURES)         # 핵심 피처에 NaN 있는 행 제거
        feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)  # 보조 피처 NaN → 0 대체
        feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)  # Inf 제거

        if len(feat_row) == 0:                                   # 유효한 행이 없으면 에러 반환
            return {'status': 'error', 'message': 'no valid feature rows'}

        latest_row = feat_row.iloc[[-1]].values                  # 최신 1행 피처 추출 (2D 배열)
        result = predict_crash_surge(latest_row, cs_model)       # 폭락/급등 점수 예측 실행
        upsert_crash_surge(result)                               # 예측 결과를 Supabase에 저장

        return {'status': 'ok', 'date': result.get('date'),      # 성공 응답 반환
                'crash_score': result.get('crash_score'),         # 폭락 점수
                'surge_score': result.get('surge_score')}         # 급등 점수
    except Exception as e:                                       # 예외 발생 시
        return {'status': 'error', 'message': str(e)}            # 에러 메시지 반환
    finally:                                                     # 성공/실패 무관하게 항상 실행
        _refresh_running = False                                 # 실행 중 플래그 해제


# ══════════════════════════════════════════════════════════
# [3] 2026-04-09 13:10 (UTC)
#     AI 해설 프롬프트에서 Noise Score → 펀더멘털 주가 괴리 점수 명칭 변경
# ══════════════════════════════════════════════════════════
#
# [변경 사항]
#   - AI 프롬프트에서만 "Noise Score" 명칭을 "펀더멘털 주가 괴리 점수"로 변경
#   - 점수 스케일은 원본(-2~7) 그대로 유지 (0~10 변환 취소)
#   - 프론트엔드/i18n 라벨은 변경 없음 (Noise Score 그대로)
#
# [수정 파일]
#   1. api/routers/market_summary.py
#      - _SUMMARY_PROMPTS: "Noise Score" → "펀더멘털 주가 괴리 점수" (프롬프트 텍스트만)
#      - _EXPLAIN_PROMPTS['ko']['fundamental']: 배경지식에 "펀더멘털 주가 괴리 점수" 사용
#      - _EXPLAIN_PROMPTS['en']['fundamental']: "Fundamental-Price Divergence Score" 사용
#      - _build_indicator_text(): AI 컨텍스트에 "펀더멘털 주가 괴리 점수" 라벨 사용
#      - _build_explain_text(): AI 해설 컨텍스트에 새 이름 사용
#
# ──────────────────────────────────────────────────────────
# api/routers/market_summary.py  _EXPLAIN_PROMPTS 핵심 부분
# ──────────────────────────────────────────────────────────

# 한국어 배경 지식:
# - "펀더멘털 주가 괴리 점수"는 주가가 펀더멘털에서 얼마나 벗어났는지를 나타내는 점수
# - 음수(-): 주가가 펀더멘털(기업 가치)을 잘 반영 (이성적 시장)
# - 양수(+): 주가가 펀더멘털에서 벗어나 감정/유동성에 의해 움직임 (감정적 시장)
# - 양수가 클수록 괴리가 심함 (0~2: 약간 괴리, 2+: 큰 괴리)

EXPLAIN_PROMPT_EN = """
Background:
- "Fundamental-Price Divergence Score" measures how far price has deviated from fundamentals
- Negative (-): price reflects fundamentals well (rational market)
- Positive (+): price deviated, driven by sentiment/liquidity (emotional market)
- Higher positive = greater divergence (0~2: mild, 2+: significant)
"""


# ══════════════════════════════════════════════════════════
# [4] 2026-04-12 10:30 (UTC)
#     30일 예측 톱니 패턴(지그재그) 수정
# ══════════════════════════════════════════════════════════
#
# [문제]
#   - 30일 예측 차트가 뾰족한 톱니 모양으로 나옴 (특히 QQQ 등)
#   - 원인: _garch_forecast()에서 앙상블 raw_ret의 부호(sign)만 사용
#     → raw_ret이 작을 때 부호가 쉽게 뒤집혀 매일 ±g_sigma × 1.5 씩 진동
#     → 방향 플리핑으로 톱니 패턴 발생
#
# [수정 파일]
#   1. processor/feature4_chart_predict.py  _garch_forecast()
#      - np.sign() 제거 → 앙상블 raw_ret 크기 유지
#      - EMA 스무딩 추가 (alpha=0.35): 이전 예측과 혼합하여 방향 연속성 확보
#      - amplified = ema_ret × 4.0, cap = g_sigma × 1.2
#      - daily_clip 축소: 5%→4%, 4%→3%, 3%→2.5% (스무딩 보정)
#
# [효과]
#   - 기존: 매일 ±3~5% 지그재그 → 차트가 톱니 모양
#   - 개선: 스무딩된 방향으로 연속적 트렌드 → 자연스러운 곡선
#   - 기존 DB 예측은 스케줄러 다음 실행(3시간 주기) 시 자동 갱신

GARCH_FORECAST_FIX = """
    # EMA 스무딩 상태: 이전 예측값과 혼합하여 방향 연속성 확보 (지그재그 방지)
    ema_ret = None
    ema_alpha = 0.35  # 낮을수록 더 부드러움 (0.3~0.4 권장)

    for k in range(1, n_days + 1):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)

        preds = [m.predict(last_feat)[0] for m in models]
        raw_ret = np.mean(preds)

        # EMA 스무딩: 방향 플리핑 억제 (톱니 패턴 방지)
        if ema_ret is None:
            ema_ret = raw_ret
        else:
            ema_ret = ema_alpha * raw_ret + (1 - ema_alpha) * ema_ret

        g_sigma = garch_sigma_daily[k - 1]

        # 스무딩된 raw_ret을 증폭 → GARCH σ로 상한 설정
        # (기존: sign(raw_ret) * g_sigma * 1.5 → 방향 플리핑 / 개선: 크기 유지)
        amplified = ema_ret * 4.0
        max_magnitude = g_sigma * 1.2
        pred_ret = float(np.clip(amplified, -max_magnitude, max_magnitude))

        # 일일 수익률 클램핑
        pred_ret = float(np.clip(pred_ret, -daily_clip, daily_clip))
        ...
"""
# ══════════════════════════════════════════════════════════
# [8] 2026-04-12 11:30 (UTC) — 병합 후 사용자 요청 재적용
#     GARCH 사용 안 함 + _recursive_forecast(3배 증폭) 사용
# ══════════════════════════════════════════════════════════
#
# [변경 사항]
#   - main 브랜치는 _garch_forecast() 사용 (arch 라이브러리)
#   - 사용자 요청: "garch를 하지말고 변동성3배 증폭으로 바꿔봐"
#   - _recursive_forecast() 함수를 다시 추가하여 사용
#   - main의 EMA 스무딩(α=0.3) + 3일 이동평균 후처리는 그대로 채용
#   - _garch_forecast() 함수는 코드만 보존 (사용 안 함)
#
# [수정 파일]
#   1. processor/feature4_chart_predict.py
#      - _recursive_forecast() 재추가 (3배 증폭 + EMA + 3일 이동평균)
#      - run_chart_predict_single(): _garch_forecast → _recursive_forecast 사용
#      - OOS sigma 계산 복원 (신뢰구간용)

# ══════════════════════════════════════════════════════════
# [5] 2026-04-12 10:50 (UTC)
#     30일 예측: GARCH 제거 → 변동성 3배 증폭 방식 전환
# ══════════════════════════════════════════════════════════
#
# [변경 사항]
#   - 30일 예측에서 GARCH(1,1) 기반 _garch_forecast() 사용 중단
#   - _recursive_forecast() (변동성 3배 증폭 방식)으로 통일
#   - _recursive_forecast()에 EMA 스무딩(α=0.35) 추가하여 톱니 패턴 방지
#
# [수정 파일]
#   1. processor/feature4_chart_predict.py
#      - run_chart_predict_single(): HAS_ARCH 분기 제거,
#        무조건 _recursive_forecast() 사용
#      - _recursive_forecast(): EMA 스무딩 추가
#        (이전 예측과 0.35:0.65로 혼합 → 방향 연속성 확보)

RUN_CHART_PREDICT_SINGLE_FORECAST = """
    # 재귀 예측: 3배 증폭 방식 (GARCH 미사용)
    predicted = _recursive_forecast(models_final, close, 30, sigma, feat_cols)
"""

RECURSIVE_FORECAST_WITH_EMA = """
def _recursive_forecast(models, close_history, n_days, sigma, feature_cols):
    \"\"\"5-모델 평균 앙상블 재귀 예측 (변동성 3배 증폭).

    EMA 스무딩으로 방향 연속성을 확보하여 톱니 패턴을 방지한다.
    \"\"\"
    hist = close_history.copy()
    predictions = []
    last_date = hist.index[-1]
    start_price = float(close_history.iloc[-1])

    # EMA 스무딩 상태 (방향 플리핑 억제)
    ema_ret = None
    ema_alpha = 0.35  # 낮을수록 더 부드러움

    for k in range(1, n_days + 1):
        feat = build_features_v2(hist)
        last_feat = feat.iloc[[-1]][feature_cols].values
        last_feat = np.nan_to_num(last_feat, nan=0.0, posinf=0.0, neginf=0.0)

        preds = [m.predict(last_feat)[0] for m in models]
        raw_ret = np.mean(preds)

        # EMA 스무딩
        if ema_ret is None:
            ema_ret = raw_ret
        else:
            ema_ret = ema_alpha * raw_ret + (1 - ema_alpha) * ema_ret

        pred_ret = ema_ret * 3.0  # 변동성 3배 증폭
        pred_ret = float(np.clip(pred_ret, -0.03, 0.03))
        # ... (이하 기존과 동일)
"""
# ══════════════════════════════════════════════════════════
# [6] 2026-04-12 (UTC) — main 브랜치 병합
#     30일 예측 톱니 수정(3일 이동평균) + 신호 AI 해설 간극 분석
# ══════════════════════════════════════════════════════════
#
# [문제 1] 30일 예측 그래프가 뾰족뾰족 지그재그로 출력됨
#   - 원인: Railway에 arch 미설치 → _recursive_forecast(3배 증폭) 사용
#     재귀 예측에서 예측 가격이 다음 피처(ret_1d)에 반영 → 양/음 교대 → 3배 증폭 → 지그재그
#   - 또한 _garch_forecast에서 np.sign으로 방향만 추출 → 미세한 양/음 전환 시 큰 진동
#
# [문제 2] 신호 AI 해설이 등급(주의/보통) 중심으로만 설명
#   - 하락/상승 점수 간 간극의 크기와 추세가 더 유의미한 정보
#
# [문제 3] AI 해설에서 간극이 항상 0.0으로 표시
#   - 원인: DB 필드가 crash_score/surge_score인데 crash_prob/surge_prob로 조회
#
# [수정 파일]
#   1. requirements.txt            - arch 라이브러리 추가
#   2. processor/feature4_chart_predict.py
#      - _recursive_forecast(3배 증폭 fallback) 함수 삭제
#      - _garch_forecast만 사용: 앙상블 방향 + GARCH(1,1) 동적 변동성
#      - np.sign 제거 → raw_ret * 3.0 + EMA 스무딩(alpha=0.3) + 3일 이동평균
#      - from arch import arch_model 직접 임포트 (try/except 제거)
#   3. api/routers/market_summary.py
#      - 신호 AI 해설: 간극(Gap = surge - crash) 중심 해설로 변경
#      - 30일 간극 추세 분석 추가 (초기/최근 5일 평균 비교, 최대/최소 간극)
#      - crash_prob → crash_score 필드명 수정 (간극 0.0 버그)
#      - 간극 부호: surge - crash (양수=상승 우위, 음수=하락 우위)
#      - 시장 탭 AI 요약 방향성도 간극 중심으로 변경
#   4. Prophet → 앙상블(Ensemble) 명칭 변경
#      - repositories.py docstring, i18n.js UI 텍스트, job.py 로그
#
# ──────────────────────────────────────────────────────────
# processor/feature4_chart_predict.py  _garch_forecast 핵심 변경
# ──────────────────────────────────────────────────────────

    # 변경 전 (np.sign → 지그재그 원인):
    # direction = np.sign(raw_ret) if abs(raw_ret) > 1e-8 else 0.0
    # pred_ret = direction * g_sigma * 1.5

    # 변경 후 (EMA 스무딩으로 매끄러운 곡선):
    ema_ret = 0.0
    alpha = 0.3
    # ...
    scaled_ret = raw_ret * 3.0
    ema_ret = alpha * scaled_ret + (1 - alpha) * ema_ret
    pred_ret = np.clip(ema_ret, -daily_clip, daily_clip)

    # 최종 3일 이동평균 스무딩
    yhats = [p['yhat'] for p in raw_predictions]
    for i in range(1, len(yhats) - 1):
        yhats[i] = (yhats[i - 1] + yhats[i] + yhats[i + 1]) / 3.0

# ──────────────────────────────────────────────────────────
# api/routers/market_summary.py  신호 탭 간극 분석 추가
# ──────────────────────────────────────────────────────────

    # 간극 계산 (양수=상승 우위, 음수=하락 우위)
    crash_s = cs.get('crash_score') or cs.get('crash_prob') or 0
    surge_s = cs.get('surge_score') or cs.get('surge_prob') or 0
    gap = round(surge_s - crash_s, 1)

    # 30일 간극 추세 분석
    history = fetch_crash_surge_history(30)
    # 초기 5일 평균 vs 최근 5일 평균 비교 → 추세 판단
    # trend_delta > 5: 상승 기울기 / < -5: 하락 기울기 / 그 외: 안정


# ══════════════════════════════════════════════════════════
# [5] 2026-04-13 (UTC)
#     섹터 경기국면 데이터 지연 해소 + 매크로 10년 추세 차트 추가
# ══════════════════════════════════════════════════════════
#
# [문제]
#   - 거시경제 탭이 2026-01-01에 멈춰있음
#   - 원인: collector/sector_macro.py의 dropna()가 8개 FRED 지표 중
#     하나라도 NaN이면 해당 월 전체를 제거 → 가장 느린 INDPRO(~6주 지연)에 맞춰 2-3개월 뒤처짐
#   - 세부페이지에 매크로 지표의 과거 추이를 볼 수 있는 차트가 없음
#
# [수정 파일]
#   1. collector/sector_macro.py    - dropna() → ffill(limit=3) + dropna()
#      지연 지표를 최대 3개월까지 앞값으로 채워 최신 월 데이터 유지
#   2. database/repositories.py     - fetch_sector_macro_history() 추가
#      sector_macro_raw 테이블에서 최근 120건(10년) 조회
#   3. api/routers/sector_cycle.py  - GET /macro-history 엔드포인트 추가
#   4. static/js/sector.js          - SVG 스파크라인 함수 + 10년 추세 섹션 추가
#      renderSectorDetail() 내 매크로 스냅샷 뒤에 8개 지표별 추세 차트 표시
#   5. static/js/i18n.js            - sector.macroTrend 번역 키 추가 (한/영)
#
# ──────────────────────────────────────────────────────────
# collector/sector_macro.py 119줄 핵심 변경
# ──────────────────────────────────────────────────────────

    # 변경 전:
    macro = macro.resample('MS').last().dropna()

    # 변경 후:
    macro = macro.resample('MS').last()
    macro = macro.ffill(limit=3)   # 지연 지표를 최대 3개월까지 앞값으로 채움
    macro = macro.dropna()          # ffill 후에도 NaN인 행 제거 (초기 히스토리)


# ══════════════════════════════════════════════════════════
# [9] 2026-04-22 (UTC) — 부동산 기능 통합 (구조 생성 + Stage 1)
#     Asset-Analysis-Platform 레포 리네임 + 부동산 파일 구조 생성
# ══════════════════════════════════════════════════════════
#
# [개요]
#   기존 주식 분석 앱에 부동산 기능을 추가.
#   레포명: Passive-Financial-Data-Analysis → Asset-Analysis-Platform
#   기존 collector/processor/database/scheduler 패턴을 그대로 따름.
#   LLM: Groq API (Qwen 모델) 사용.
#
# [신규 파일 — 스텁 (TODO: implement 단계)]
#   api/routers/real_estate.py        - /api/realestate/... 라우터
#   collector/real_estate_trade.py    - 국토부 매매·전월세 API
#   collector/real_estate_population.py - 행안부 인구·세대원수·매핑
#   collector/real_estate_geocode.py  - 카카오 주소→좌표
#   processor/feature5_real_estate.py - 법정동↔행정동 매핑 + 지역 집계
#   scripts/build_frontend.sh         - Vite 빌드 진입점
#   scripts/upload_dim.py             - parquet → Supabase dim 테이블 업로드
#   templates/landing.html            - / 선택 화면 (주식/부동산 2버튼)
#   templates/realestate.html         - React 진입점
#   templates/stocks.html             - 기존 index.html 이관
#   static/realestate/.gitkeep        - Vite 빌드 결과 디렉토리
#   frontend-realestate/              - Vite+React+TS 프로젝트 전체
#     index.html, package.json, vite.config.ts, tsconfig.json
#     tailwind.config.ts, postcss.config.js
#     src/main.tsx, src/App.tsx
#     src/screens/MapScreen.tsx
#     src/screens/RegionDetailScreen.tsx
#     src/screens/ComplexDetailScreen.tsx
#     src/components/KakaoMap.tsx
#     src/components/BottomSheet.tsx
#     src/components/AiReportCard.tsx
#     src/components/MetricGrid.tsx
#     src/components/TimeSeriesChart.tsx
#     src/store/mapStore.ts
#     src/api/client.ts
#     src/api/endpoints.ts
#     src/types/api.ts
#     src/styles/globals.css
#
# [수정 파일 — Stage 1 환경 설정]
#   requirements.txt  - xmltodict, httpx 추가
#   .gitignore        - frontend-realestate/node_modules, dist 추가
#   .env              - 신규 생성 (키 목록: SUPABASE, DATA_GO_KR, KAKAO, GROQ)
#
# ──────────────────────────────────────────────────────────
# requirements.txt 추가분
# ──────────────────────────────────────────────────────────

xmltodict
httpx

# ──────────────────────────────────────────────────────────
# .gitignore 추가분
# ──────────────────────────────────────────────────────────

frontend-realestate/node_modules/
frontend-realestate/dist/

# ──────────────────────────────────────────────────────────
# .env 키 목록
# ──────────────────────────────────────────────────────────

SUPABASE_URL=
SUPABASE_KEY=
DATA_GO_KR_KEY=
KAKAO_REST_KEY=
KAKAO_JS_KEY=
GROQ_API_KEY=
RUN_SCHEDULER=true

# ──────────────────────────────────────────────────────────
# vite.config.ts 핵심 설정
# ──────────────────────────────────────────────────────────

VITE_CONFIG = """
export default defineConfig({
  plugins: [react()],
  base: "/static/realestate/",   # FastAPI /static 마운트와 맞춤 (없으면 404)
  build: {
    outDir: "../static/realestate",
    emptyOutDir: true,
  },
});
"""

# ──────────────────────────────────────────────────────────
# frontend-realestate/src/App.tsx 핵심 설정
# ──────────────────────────────────────────────────────────

APP_TSX = """
// basename="/realestate" — 백엔드가 /realestate/* 로 서빙하므로 prefix 맞춤
export default function App() {
  return (
    <BrowserRouter basename="/realestate">
      <Routes>
        <Route path="/" element={<MapScreen />} />
        <Route path="/region/:sggCd" element={<RegionDetailScreen />} />
        <Route path="/complex/:aptSeq" element={<ComplexDetailScreen />} />
      </Routes>
    </BrowserRouter>
  );
}
"""

# ──────────────────────────────────────────────────────────
# frontend-realestate/src/api/endpoints.ts
# ──────────────────────────────────────────────────────────

ENDPOINTS_TS = """
export const ENDPOINTS = {
  summary:    (sggCd: string) => `/api/realestate/summary?sgg_cd=${sggCd}`,
  trades:     (sggCd: string, ym: string) => `/api/realestate/trades?sgg_cd=${sggCd}&ym=${ym}`,
  rents:      (sggCd: string, ym: string) => `/api/realestate/rents?sgg_cd=${sggCd}&ym=${ym}`,
  population: (sggCd: string, ym: string) => `/api/realestate/population?sgg_cd=${sggCd}&ym=${ym}`,
} as const;
"""

# ──────────────────────────────────────────────────────────
# frontend-realestate/src/store/mapStore.ts
# ──────────────────────────────────────────────────────────

MAP_STORE_TS = """
// Zustand 전역 상태 — 선택 지역·줌·바텀시트 스냅 레벨
// Redux 대신 Zustand: 보일러플레이트가 적고 이 규모에 충분
export const useMapStore = create<MapState>((set) => ({
  selectedSggCd: null,
  zoomLevel: 10,
  bottomSheetSnap: "hidden",
  setSelectedSggCd: (sggCd) => set({ selectedSggCd: sggCd }),
  setZoomLevel: (level) => set({ zoomLevel: level }),
  setBottomSheetSnap: (snap) => set({ bottomSheetSnap: snap }),
}));
"""

# ══════════════════════════════════════════════════════════
# [10] 2026-04-22 (UTC) — Stage 2: 부동산 DB 스키마
#      supabase_tables.sql 부동산 테이블 7개 DDL 추가
# ══════════════════════════════════════════════════════════
#
# [추가 테이블]
#   11. real_estate_trade_raw    - 국토부 매매 실거래 원본
#   12. real_estate_rent_raw     - 국토부 전월세 실거래 원본
#   13. mois_population          - 행안부 법정동별 인구
#   14. mois_household_by_size   - 행안부 행정동별 세대원수 분포
#   15. stdg_admm_mapping        - 법정동↔행정동 매핑 참조
#   16. geo_stdg                 - 법정동 좌표 참조 (카카오 지오코딩)
#   17. region_summary           - 지역 단위 Tier 1 집계 결과
#
# ──────────────────────────────────────────────────────────
# supabase_tables.sql 핵심 DDL 요약
# ──────────────────────────────────────────────────────────

STAGE2_DDL = """
CREATE TABLE IF NOT EXISTS real_estate_trade_raw (
    sgg_cd TEXT, deal_ym TEXT, apt_seq TEXT,
    stdg_cd TEXT,
    deal_amount INTEGER,
    exclu_use_ar DOUBLE PRECISION,
    floor INTEGER, build_year INTEGER, deal_date DATE,
    lat DOUBLE PRECISION, lng DOUBLE PRECISION,
    UNIQUE (apt_seq, deal_date, floor, exclu_use_ar)
);

CREATE TABLE IF NOT EXISTS real_estate_rent_raw (
    sgg_cd TEXT, deal_ym TEXT, apt_seq TEXT,
    deposit INTEGER, monthly_rent INTEGER,
    exclu_use_ar DOUBLE PRECISION,
    floor INTEGER, deal_date DATE,
    UNIQUE (apt_seq, deal_date, floor, exclu_use_ar, deposit, monthly_rent)
);

CREATE TABLE IF NOT EXISTS mois_population (
    stats_ym TEXT, stdg_cd TEXT,
    tot_nmpr_cnt INTEGER, hh_cnt INTEGER,
    UNIQUE (stats_ym, stdg_cd)
);

CREATE TABLE IF NOT EXISTS mois_household_by_size (
    stats_ym TEXT, admm_cd TEXT,
    tot_hh_cnt INTEGER, hh_1 INTEGER,
    solo_rate DOUBLE PRECISION,
    UNIQUE (stats_ym, admm_cd)
);

CREATE TABLE IF NOT EXISTS stdg_admm_mapping (
    ref_ym TEXT, stdg_cd TEXT, admm_cd TEXT,
    UNIQUE (ref_ym, stdg_cd, admm_cd)
);

CREATE TABLE IF NOT EXISTS geo_stdg (
    stdg_cd TEXT UNIQUE, lat DOUBLE PRECISION, lng DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS region_summary (
    sgg_cd TEXT, stdg_cd TEXT, stats_ym TEXT,
    trade_count INTEGER,
    median_price INTEGER, median_price_per_py DOUBLE PRECISION,
    solo_rate DOUBLE PRECISION,
    UNIQUE (stdg_cd, stats_ym)
);
"""


# ══════════════════════════════════════════════════════════
# [11] 2026-04-23 (UTC) — Stage 3: 부동산 수집기 구현
#      collector/ 3개 파일 — 노트북 02/03 로직 이식
# ══════════════════════════════════════════════════════════
#
# [구현 파일]
#   collector/real_estate_trade.py
#     - fetch_trades(sgg_cd, deal_ym)  → MOLIT 매매 전량
#     - fetch_rents(sgg_cd, deal_ym)   → MOLIT 전월세 전량
#     - _fetch_all / _fetch_page / _parse_molit_response / _normalize_items
#
#   collector/real_estate_population.py
#     - fetch_population(stdg_cd, ym)         → 행안부 인구 lv=3
#     - fetch_household_by_size(admm_cd, ym)  → 행안부 세대원수 lv=3
#     - fetch_mapping_pairs(stdg_cd, ym)      → lv=4 역추출 매핑
#     - NODATA(resultCode=3) 빈 결과 흡수
#
#   collector/real_estate_geocode.py
#     - geocode(address)            → 카카오 REST API → {lat, lng, ...}
#     - batch_geocode(addresses)    → 순차 지오코딩, 실패 항목 None
#
# ──────────────────────────────────────────────────────────
# collector/real_estate_trade.py 핵심
# ──────────────────────────────────────────────────────────

# MOLIT/MOIS는 XML 루트·헤더 키·정상코드 세 가지가 모두 다름.
# "response"(소문자) vs "Response"(대문자) — xmltodict는 대소문자 그대로 반환하므로 틀리면 KeyError
_MOLIT_SPEC = {"root": "response", "head_key": "header", "ok_codes": {"000"}}

# 시군구 코드 + 연월 → 국토부 매매 실거래 전량 반환 (페이지네이션 자동 처리)
def fetch_trades(sgg_cd: str, deal_ym: str) -> list[dict]:
    return _fetch_all(MOLIT_TRADE_URL, {"serviceKey": API_KEY, "LAWD_CD": sgg_cd, "DEAL_YMD": deal_ym})

# 시군구 코드 + 연월 → 국토부 전월세 실거래 전량 반환 (페이지네이션 자동 처리)
def fetch_rents(sgg_cd: str, deal_ym: str) -> list[dict]:
    return _fetch_all(MOLIT_RENT_URL, {"serviceKey": API_KEY, "LAWD_CD": sgg_cd, "DEAL_YMD": deal_ym})

# 국토부 XML 응답 → dict 파싱 + resultCode 검증 + 페이지 메타 추출
def _parse_molit_response(xml_text: str) -> dict:
    data = xmltodict.parse(xml_text)
    root = data[_MOLIT_SPEC["root"]]
    head = root[_MOLIT_SPEC["head_key"]]
    code = head["resultCode"]
    if code not in _MOLIT_SPEC["ok_codes"]:
        raise ValueError(f"[molit] API error resultCode={code}: {head.get('resultMsg', '?')}")
    # body 레이어가 없는 응답도 있어 root 자체를 fallback으로 사용
    body = root.get("body", root)
    return {
        # XML은 전부 문자열 — 페이지 계산에 쓰이는 숫자 필드는 여기서 int 캐스팅
        "totalCount": int(body.get("totalCount", head.get("totalCount", 0))),
        "pageNo": int(body.get("pageNo", head.get("pageNo", 1))),
        "numOfRows": int(body.get("numOfRows", head.get("numOfRows", 0))),
        # items_raw: 단수(dict)/복수(list) 혼재 상태 그대로 — normalize_items에서 통일
        "items_raw": body.get("items"),
    }

# ──────────────────────────────────────────────────────────
# collector/real_estate_population.py 핵심
# ──────────────────────────────────────────────────────────

# 행안부: 루트 "Response"(대문자 R), 헤더 "head", 정상코드 "0" — MOLIT와 세 가지 모두 다름
_MOIS_SPEC = {"root": "Response", "head_key": "head", "ok_codes": {"0"}}

# 법정동 코드 + 연월 → (법정동, 행정동) 매핑 쌍 리스트 반환 (lv=4 역추출 트릭)
def fetch_mapping_pairs(stdg_cd: str, ym: str) -> list[dict]:
    # lv=4(통반 단위)로 호출하면 법정동 하나 안의 행정동이 수백 행으로 펼쳐짐 — dedupe하면 매핑 쌍만 남음
    # 별도 매핑 전용 API 없이 인구 API 하나로 (법정동↔행정동) 쌍을 역추출하는 트릭
    items = _fetch_all_mois(MOIS_POP_URL, {
        "serviceKey": API_KEY, "stdgCd": stdg_cd,
        "lv": "4",       # lv=3이면 읍면동 단위라 admmCd가 노출되지 않음 — 반드시 4
        "regSeCd": "1",  # 숫자 문자열 "1" 필수 — "A" 넣으면 500 에러 (API 문서에 없는 함정)
        "srchFrYm": ym, "srchToYm": ym,
    })
    pairs: dict[tuple, dict] = {}
    for it in items:
        stdg = it.get("stdgCd")
        admm = it.get("admmCd")
        if not stdg or not admm:  # 통반 하위 행에 None 섞여 있음
            continue
        key = (stdg, admm)
        if key not in pairs:
            pairs[key] = {
                "stdgCd": stdg, "stdgNm": it.get("stdgNm"),
                "admmCd": admm,
                "admmNm": it.get("dongNm"),  # 이 API만 행정동명 필드가 dongNm — admmNm으로 리매핑
                "ctpvNm": it.get("ctpvNm"), "sggNm": it.get("sggNm"),
            }
    return list(pairs.values())

# 행안부 XML 응답 → dict 파싱 + resultCode 검증 (NODATA 빈 결과 흡수 포함)
def _parse_mois_response(xml_text: str) -> dict:
    data = xmltodict.parse(xml_text)
    root = data[_MOIS_SPEC["root"]]
    head = root[_MOIS_SPEC["head_key"]]
    code = head["resultCode"]
    # NODATA(code="3"): 폐지된 동·미집계 월. 예외 터트리면 법정동 순회 루프 전체가 죽으므로 빈 결과로 흡수
    if code == "3":
        return {"totalCount": 0, "pageNo": 1, "numOfRows": 0, "items_raw": None}
    if code not in _MOIS_SPEC["ok_codes"]:
        raise ValueError(f"[mois] API error resultCode={code}: {head.get('resultMsg', '?')}")
    body = root.get("body", root)
    return {
        "totalCount": int(body.get("totalCount", head.get("totalCount", 0))),
        "pageNo": int(body.get("pageNo", head.get("pageNo", 1))),
        "numOfRows": int(body.get("numOfRows", head.get("numOfRows", 0))),
        "items_raw": body.get("items"),
    }

# ──────────────────────────────────────────────────────────
# collector/real_estate_geocode.py 핵심
# ──────────────────────────────────────────────────────────

# 주소 문자열 → 카카오 지오코딩 → {lat, lng, road_address, jibun_address} 또는 None
def geocode(address: str) -> dict | None:
    # Authorization: "KakaoAK {키}" 형식 필수 — Bearer 아님
    r = httpx.get(
        KAKAO_GEOCODE_URL,
        params={"query": address},
        headers={"Authorization": f"KakaoAK {KAKAO_REST_KEY}"},
        timeout=10.0,
    )
    r.raise_for_status()
    docs = r.json().get("documents", [])
    if not docs:
        return None
    d = docs[0]
    return {
        "lat": float(d["y"]),   # 카카오는 위도=y, 경도=x — lat/lng과 순서 반대
        "lng": float(d["x"]),
        "road_address": (d["road_address"] or {}).get("address_name"),  # 매칭 없으면 None(dict 아님) — or {}로 방어
        "jibun_address": (d["address"] or {}).get("address_name"),
    }

# 주소 리스트 일괄 지오코딩 — 실패 항목은 None으로 채워 인덱스 유지
def batch_geocode(addresses: list[str]) -> list[dict | None]:
    # 개별 실패를 None으로 채워 인덱스 대응 유지 — 전체 배치 중단 방지
    results: list[dict | None] = []
    for addr in addresses:
        try:
            results.append(geocode(addr))
        except Exception:
            results.append(None)
    return results


# ══════════════════════════════════════════════════════════
# [12] 2026-04-23 (UTC) — Stage 4: 부동산 DB 레이어
#      database/repositories.py 에 부동산 upsert/fetch 함수 추가
# ══════════════════════════════════════════════════════════
#
# [추가 함수 — 테이블별]
#   real_estate_trade_raw    : upsert_re_trades / fetch_re_trades
#   real_estate_rent_raw     : upsert_re_rents  / fetch_re_rents
#   mois_population          : upsert_mois_population / fetch_mois_population
#   mois_household_by_size   : upsert_mois_household  / fetch_mois_household
#   stdg_admm_mapping        : upsert_stdg_admm_mapping / fetch_stdg_admm_mapping
#   geo_stdg                 : upsert_geo_stdg  / fetch_geo_stdg
#   region_summary           : upsert_region_summary / fetch_region_summary
#
# ──────────────────────────────────────────────────────────
# database/repositories.py 전체 추가 코드
# ──────────────────────────────────────────────────────────

# 매매 실거래 저장 — on_conflict: apt_seq+deal_date+floor+exclu_use_ar
def upsert_re_trades(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("real_estate_trade_raw").upsert(
        records, on_conflict="apt_seq,deal_date,floor,exclu_use_ar"
    ).execute()
    print(f"[DB] real_estate_trade_raw {len(records)}건 upsert 완료")

# 시군구 코드 + 연월 → 매매 실거래 조회
def fetch_re_trades(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("real_estate_trade_raw")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .eq("deal_ym", ym)
        .order("deal_date", desc=False)
        .execute()
    )
    return response.data

# 전월세 실거래 저장 — on_conflict: apt_seq+deal_date+floor+exclu_use_ar+deposit+monthly_rent
def upsert_re_rents(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("real_estate_rent_raw").upsert(
        records, on_conflict="apt_seq,deal_date,floor,exclu_use_ar,deposit,monthly_rent"
    ).execute()
    print(f"[DB] real_estate_rent_raw {len(records)}건 upsert 완료")

# 시군구 코드 + 연월 → 전월세 실거래 조회
def fetch_re_rents(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("real_estate_rent_raw")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .eq("deal_ym", ym)
        .order("deal_date", desc=False)
        .execute()
    )
    return response.data

# 법정동 인구 저장 — on_conflict: stats_ym+stdg_cd
def upsert_mois_population(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("mois_population").upsert(
        records, on_conflict="stats_ym,stdg_cd"
    ).execute()
    print(f"[DB] mois_population {len(records)}건 upsert 완료")

# stdg_cd는 10자리, sgg_cd는 앞 5자리 — LIKE "{sgg_cd}%" 로 시군구 단위 필터링
def fetch_mois_population(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("mois_population")
        .select("*")
        .like("stdg_cd", f"{sgg_cd}%")
        .eq("stats_ym", ym)
        .execute()
    )
    return response.data

# 세대원수별 세대수 저장 — on_conflict: stats_ym+admm_cd
def upsert_mois_household(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("mois_household_by_size").upsert(
        records, on_conflict="stats_ym,admm_cd"
    ).execute()
    print(f"[DB] mois_household_by_size {len(records)}건 upsert 완료")

def fetch_mois_household(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("mois_household_by_size")
        .select("*")
        .like("admm_cd", f"{sgg_cd}%")
        .eq("stats_ym", ym)
        .execute()
    )
    return response.data

# 법정동↔행정동 매핑 저장 — on_conflict: ref_ym+stdg_cd+admm_cd
def upsert_stdg_admm_mapping(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("stdg_admm_mapping").upsert(
        records, on_conflict="ref_ym,stdg_cd,admm_cd"
    ).execute()
    print(f"[DB] stdg_admm_mapping {len(records)}건 upsert 완료")

def fetch_stdg_admm_mapping(sgg_cd: str, ref_ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("stdg_admm_mapping")
        .select("*")
        .like("stdg_cd", f"{sgg_cd}%")
        .eq("ref_ym", ref_ym)
        .execute()
    )
    return response.data

# 법정동 좌표 저장 — on_conflict: stdg_cd
def upsert_geo_stdg(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("geo_stdg").upsert(records, on_conflict="stdg_cd").execute()
    print(f"[DB] geo_stdg {len(records)}건 upsert 완료")

def fetch_geo_stdg(sgg_cd: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("geo_stdg")
        .select("stdg_cd,lat,lng")
        .like("stdg_cd", f"{sgg_cd}%")
        .execute()
    )
    return response.data

# 지역 집계 결과 저장 — on_conflict: stdg_cd+stats_ym
def upsert_region_summary(records: list[dict]) -> None:
    if not records:
        return
    client = get_client()
    client.table("region_summary").upsert(
        records, on_conflict="stdg_cd,stats_ym"
    ).execute()
    print(f"[DB] region_summary {len(records)}건 upsert 완료")

# region_summary는 median_price_per_py 내림차순 — 평단가 높은 법정동 순으로 정렬
def fetch_region_summary(sgg_cd: str, ym: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("region_summary")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .eq("stats_ym", ym)
        .order("median_price_per_py", desc=True)
        .execute()
    )
    return response.data


# ══════════════════════════════════════════════════════════
# [13] 2026-04-24 (UTC) — Stage 5: 부동산 프로세서 구현
#      processor/feature5_real_estate.py — 매핑 구축 + 지역 집계
# ══════════════════════════════════════════════════════════
#
# [구현 함수]
#   build_mapping(sgg_cd, ref_ym)
#     - fetch_population(lv=3) → 읍면동 stdgCd 목록 dedupe
#     - 각 stdgCd에 fetch_mapping_pairs(lv=4) 적용 → 매핑 쌍 역추출
#     - ref_ym 필드 추가 후 upsert_stdg_admm_mapping 에 전달
#
#   compute_region_summary(trades, rents, population, mapping, household, sgg_cd, stats_ym)
#     - 매매: deal_amount 캐스팅, pyeong/price_per_py 파생, stdg_cd 확보, 법정동별 집계
#     - 전월세: monthly_rent==0 → 전세, 시군구 단위 집계
#     - 인구: tot_nmpr_cnt → population
#     - 1인가구: 행정동 household + mapping → 법정동 가중합 → solo_rate
#     - 반환: list[dict] → upsert_region_summary 에 바로 전달 가능
#
# ──────────────────────────────────────────────────────────
# processor/feature5_real_estate.py 핵심 코드
# ──────────────────────────────────────────────────────────

# 시군구(10자리) → 읍면동 stdgCd 목록 → 각 법정동에 lv=4 역추출 → 매핑 쌍 반환
def build_mapping(sgg_cd: str, ref_ym: str) -> list[dict]:
    items = fetch_population(sgg_cd, ref_ym)  # lv=3: 읍면동 목록
    seen: dict[str, str] = {}
    for it in items:
        stdg = it.get("stdgCd")
        if stdg and stdg not in seen:
            seen[stdg] = stdg
    all_pairs: list[dict] = []
    for stdg_cd in seen:
        pairs = fetch_mapping_pairs(stdg_cd, ref_ym)  # lv=4: 통반 역추출
        for p in pairs:
            p["ref_ym"] = ref_ym
        all_pairs.extend(pairs)
    return all_pairs

# 매매 집계 핵심 — stdg_cd 확보 + pyeong/price_per_py 파생 + 법정동별 집계
df_t["deal_amount"] = df_t["deal_amount"].astype(str).str.replace(",", "").astype(float).astype(int)
df_t["pyeong"] = df_t["exclu_use_ar"].astype(float) / 3.3058
df_t["price_per_py"] = df_t["deal_amount"] / df_t["pyeong"]
if "stdg_cd" not in df_t.columns:
    df_t["stdg_cd"] = df_t["sgg_cd"].str.zfill(5) + df_t["umd_cd"].str.zfill(5)

trade_agg = (
    df_t.groupby("stdg_cd")
    .agg(
        stdg_nm=("umd_nm", "first"),
        trade_count=("deal_amount", "size"),
        avg_price=("deal_amount", "mean"),
        median_price=("deal_amount", "median"),
        median_price_per_py=("price_per_py", "median"),
    )
    .reset_index()
)

# 1인가구 비율 — 세대원수(행정동) + 매핑 → 법정동 가중합
# 한 법정동이 여러 행정동에 걸칠 수 있어 단순 평균이 아닌 세대수 가중합
hh_mapped = df_hh.merge(df_map[["stdg_cd", "admm_cd"]], on="admm_cd", how="inner")
grp = (
    hh_mapped.groupby("stdg_cd")
    .agg(tot_hh=("tot_hh_cnt", "sum"), solo_cnt=("hh_1", "sum"))
    .reset_index()
)
grp["solo_rate"] = grp["solo_cnt"] / grp["tot_hh"].replace(0, float("nan"))


# ══════════════════════════════════════════════════════════
# [14] 2026-04-24 (UTC) — Stage 6: 부동산 스케줄러 통합
#     scheduler/job.py에 Step 9 추가 (서울 25개 구 월별 수집)
# ══════════════════════════════════════════════════════════
#
# [변경 파일]
#   scheduler/job.py
#     - 부동산 관련 import 추가
#     - camelCase → snake_case 변환 헬퍼 5개 추가 (run_pipeline 위)
#     - Step 9: 전체 모드(if not light:) 안에 추가
#
# ──────────────────────────────────────────────────────────
# import 추가 (job.py 상단)
# ──────────────────────────────────────────────────────────

from collector.real_estate_trade import fetch_trades, fetch_rents
from collector.real_estate_population import (
    fetch_population, fetch_household_by_size, fetch_all_sgg_codes,
)
from collector.real_estate_geocode import batch_geocode
from processor.feature5_real_estate import build_mapping, compute_region_summary
from database.repositories import (
    upsert_re_trades, upsert_re_rents, upsert_mois_population, upsert_mois_household,
    upsert_stdg_admm_mapping, upsert_geo_stdg, upsert_region_summary, fetch_geo_stdg,
)

# ──────────────────────────────────────────────────────────
# 변환 헬퍼 — API 응답(camelCase) → DB 스키마(snake_case)
# ──────────────────────────────────────────────────────────

def _re_norm_trades(items: list[dict], sgg_cd: str, deal_ym: str) -> list[dict]:
    # [입력 출처] fetch_trades(sgg_cd, re_ym) — 국토부 매매 API (camelCase, 값은 str)
    #
    # [출력 행선지] upsert_re_trades() → real_estate_trade_raw 테이블
    #               + compute_region_summary(trades=...) → 법정동 집계용
    #
    # [출력 예시] result[0] = {
    #   "sgg_cd": "11680", "deal_ym": "202603", "apt_nm": "한라비발디",
    #   "apt_seq": "11680-4474", "umd_nm": "도곡동", "umd_cd": "11800",
    #   "stdg_cd": "1168011800", "deal_amount": 235000,
    #   "exclu_use_ar": 84.8861, "floor": 6, "build_year": 2016,
    #   "deal_date": "2026-03-28", "dealing_gbn": "중개거래",
    #   "road_nm": "남부순환로365길"}
    result = []
    for it in items:
        y = it.get("dealYear", "")
        m = it.get("dealMonth", "").zfill(2)
        d = it.get("dealDay", "").zfill(2)
        deal_date = f"{y}-{m}-{d}" if y and m and d else None
        umd_cd = (it.get("umdCd") or "").zfill(5)
        result.append({
            "sgg_cd": sgg_cd,
            "deal_ym": deal_ym,
            "apt_nm": it.get("aptNm"),
            "apt_seq": it.get("aptSeq"),
            "umd_nm": it.get("umdNm"),
            "umd_cd": umd_cd,
            "stdg_cd": sgg_cd.zfill(5) + umd_cd,
            "deal_amount": int(str(it.get("dealAmount", "0") or "0").replace(",", "")),
            "exclu_use_ar": float(it.get("excluUseAr") or 0),
            "floor": int(it.get("floor") or 0),
            "build_year": int(it.get("buildYear")) if it.get("buildYear") else None,
            "deal_date": deal_date,
            "dealing_gbn": it.get("dealingGbn"),
            "road_nm": it.get("roadNm"),
        })
    return result


def _re_norm_rents(items: list[dict], sgg_cd: str, deal_ym: str) -> list[dict]:
    # [입력 출처] fetch_rents(sgg_cd, re_ym) — 국토부 전월세 API
    #              (매매와 달리 road 관련 필드만 소문자 roadnm/roadnmcd …)
    #
    # [출력 행선지] upsert_re_rents() → real_estate_rent_raw 테이블
    #               + compute_region_summary(rents=...) → 시군구 전/월세 집계용
    #
    # [출력 예시] result[0] = {
    #   "sgg_cd": "11680", "deal_ym": "202603", "apt_nm": "래미안대치팰리스",
    #   "apt_seq": "11680-4394", "umd_nm": "대치동",
    #   "deposit": 130000, "monthly_rent": 0,    # monthly_rent=0 → 전세
    #   "exclu_use_ar": 59.99, "floor": 3,
    #   "deal_date": "2026-03-21", "contract_type": None,
    #   "road_nm": "삼성로51길 37"}
    result = []
    for it in items:
        y = it.get("dealYear", "")
        m = it.get("dealMonth", "").zfill(2)
        d = it.get("dealDay", "").zfill(2)
        deal_date = f"{y}-{m}-{d}" if y and m and d else None
        result.append({
            "sgg_cd": sgg_cd,
            "deal_ym": deal_ym,
            "apt_nm": it.get("aptNm"),
            "apt_seq": it.get("aptSeq"),
            "umd_nm": it.get("umdNm"),
            "deposit": int(str(it.get("deposit", "0") or "0").replace(",", "")),
            "monthly_rent": int(str(it.get("monthlyRent", "0") or "0").replace(",", "")),
            "exclu_use_ar": float(it.get("excluUseAr") or 0),
            "floor": int(it.get("floor") or 0),
            "deal_date": deal_date,
            "contract_type": it.get("contractType"),
            # 전월세 API는 roadNm 대신 소문자 roadnm 사용
            "road_nm": it.get("roadnm") or it.get("roadNm"),
        })
    return result


def _re_norm_population(items: list[dict], stats_ym: str) -> list[dict]:
    # [입력 출처] fetch_population(sgg_cd_10, re_ym) — 행안부 인구통계 API lv=3
    #              (시군구 10자리 → 법정동별 집계, admmCd는 None)
    #
    # [출력 행선지] upsert_mois_population() → mois_population 테이블
    #               + compute_region_summary(population=...) → 법정동 인구 컬럼
    #
    # [출력 예시] result[0] = {
    #   "stats_ym": "202603", "stdg_cd": "1168010100", "stdg_nm": "역삼동",
    #   "sgg_nm": "강남구", "tot_nmpr_cnt": 70093, "hh_cnt": 39424,
    #   "hh_nmpr": 1.78, "male_nmpr_cnt": 33465, "feml_nmpr_cnt": 36628,
    #   "male_feml_rate": 0.91}
    result = []
    for it in items:
        stdg_cd = it.get("stdgCd")
        if not stdg_cd:
            continue
        result.append({
            "stats_ym": stats_ym,
            "stdg_cd": stdg_cd,
            "stdg_nm": it.get("stdgNm"),
            "sgg_nm": it.get("sggNm"),
            "tot_nmpr_cnt": int(str(it.get("totNmprCnt", "0") or "0").replace(",", "")),
            "hh_cnt": int(str(it.get("hhCnt", "0") or "0").replace(",", "")),
            "hh_nmpr": float(it.get("hhNmpr") or 0),
            "male_nmpr_cnt": int(str(it.get("maleNmprCnt", "0") or "0").replace(",", "")),
            "feml_nmpr_cnt": int(str(it.get("femlNmprCnt", "0") or "0").replace(",", "")),
            "male_feml_rate": float(it.get("maleFemlRate") or 0),
        })
    return result


def _re_norm_household(items: list[dict], stats_ym: str) -> list[dict]:
    # [입력 출처] fetch_household_by_size(admm_cd, re_ym) — 행안부 세대원수 API lv=3
    #              (행정동 10자리 단위 호출 — mapping.admm_cd를 순회)
    #
    # [출력 행선지] upsert_mois_household() → mois_household_by_size 테이블
    #               + compute_region_summary(household=...) → solo_rate 가중합
    #
    # [출력 예시] result[0] = {
    #   "stats_ym": "202603", "admm_cd": "1168051000", "dong_nm": "신사동",
    #   "sgg_nm": "강남구", "tot_hh_cnt": 6534,
    #   "hh_1": 2466, "hh_2": 1505, "hh_3": 1226, "hh_4": 1001,
    #   "hh_5": 242, "hh_6": 63, "hh_7plus": 31,    # = 16+13+2+0
    #   "solo_rate": 0.3773}                         # = 2466 / 6534
    result = []
    for it in items:
        admm_cd = it.get("admmCd")
        if not admm_cd:
            continue
        tot = int(str(it.get("totHhCnt", "0") or "0").replace(",", ""))
        hh_1 = int(str(it.get("hhNmprCnt1", "0") or "0").replace(",", ""))
        # hhNmprCnt7~10 합산 → hh_7plus
        hh_7plus = sum(int(str(it.get(f"hhNmprCnt{i}", "0") or "0").replace(",", "")) for i in range(7, 11))
        result.append({
            "stats_ym": stats_ym,
            "admm_cd": admm_cd,
            "dong_nm": it.get("dongNm"),
            "sgg_nm": it.get("sggNm"),
            "tot_hh_cnt": tot,
            "hh_1": hh_1,
            "hh_2": int(str(it.get("hhNmprCnt2", "0") or "0").replace(",", "")),
            "hh_3": int(str(it.get("hhNmprCnt3", "0") or "0").replace(",", "")),
            "hh_4": int(str(it.get("hhNmprCnt4", "0") or "0").replace(",", "")),
            "hh_5": int(str(it.get("hhNmprCnt5", "0") or "0").replace(",", "")),
            "hh_6": int(str(it.get("hhNmprCnt6", "0") or "0").replace(",", "")),
            "hh_7plus": hh_7plus,
            "solo_rate": (hh_1 / tot) if tot > 0 else None,
        })
    return result


def _re_norm_mapping(pairs: list[dict]) -> list[dict]:
    # [입력 출처] build_mapping(sgg_cd_10, re_ym) — processor/feature5_real_estate
    #              (내부에서 fetch_mapping_pairs(stdgCd, ym)를 읍면동마다 호출해 dedupe)
    #
    # [출력 행선지] upsert_stdg_admm_mapping() → stdg_admm_mapping 테이블
    #               + compute_region_summary(mapping=...) → 행정동→법정동 join 키
    #               + batch_geocode(f"{ctpv_nm} {sgg_nm} {stdg_nm}") → 지오코딩 주소 조합
    #
    # [출력 예시] return[0] = {
    #   "ref_ym": "202603", "stdg_cd": "1168010100", "stdg_nm": "역삼동",
    #   "admm_cd": "1168053000", "admm_nm": "역삼1동",
    #   "ctpv_nm": "서울특별시", "sgg_nm": "강남구"}
    return [
        {
            "ref_ym": p.get("ref_ym"),
            "stdg_cd": p.get("stdgCd"),
            "stdg_nm": p.get("stdgNm"),
            "admm_cd": p.get("admmCd"),
            "admm_nm": p.get("admmNm"),
            "ctpv_nm": p.get("ctpvNm"),
            "sgg_nm": p.get("sggNm"),
        }
        for p in pairs
        if p.get("stdgCd") and p.get("admmCd")
    ]

# ──────────────────────────────────────────────────────────
# 추가 (collector/real_estate_population.py) — 전국 시군구 코드 동적 조회
# ──────────────────────────────────────────────────────────

def fetch_all_sgg_codes(ym: str) -> list[str]:
    # [입력 출처] scheduler/job.py Step 9 시작부 (re_ym 인자)
    #
    # [출력 행선지] Step 9의 for 루프가 이 목록을 순회
    #
    # [출력 예시] ["11110", "11140", ..., "50130"]  (약 245개)
    """전국 시군구 5자리 코드 목록 (MOLIT LAWD_CD 포맷) 동적 조회.

    lv=1로 전국→시도 17개를 얻고, 각 시도에 lv=2를 걸어 시군구 10자리 코드 수집 후
    앞 5자리만 추출(MOLIT LAWD_CD는 5자리). 17 + 17 = 34회 MOIS 호출.
    """
    # lv=1: 전국 루트 → 시도 목록
    ctpv_items = _fetch_all_mois(MOIS_POP_URL, {
        "serviceKey": API_KEY,
        "stdgCd": "1000000000",
        "lv": "1",
        "regSeCd": "1",
        "srchFrYm": ym,
        "srchToYm": ym,
    })
    sgg_codes: set[str] = set()
    for ctpv in ctpv_items:
        ctpv_cd = ctpv.get("stdgCd")
        if not ctpv_cd:
            continue
        # lv=2: 시도 → 시군구 목록
        sgg_items = _fetch_all_mois(MOIS_POP_URL, {
            "serviceKey": API_KEY,
            "stdgCd": ctpv_cd,
            "lv": "2",
            "regSeCd": "1",
            "srchFrYm": ym,
            "srchToYm": ym,
        })
        for sgg in sgg_items:
            stdg_10 = sgg.get("stdgCd")
            if stdg_10 and len(stdg_10) == 10:
                sgg_codes.add(stdg_10[:5])
    return sorted(sgg_codes)


# ──────────────────────────────────────────────────────────
# Step 9 (scheduler/job.py — if not light: 블록 내 Step 8 뒤)
# ──────────────────────────────────────────────────────────

        # Step 9: 부동산 월별 수집 (매매·전월세·인구·세대원수·매핑·지역집계)
        print('\n[Step 9] 부동산 데이터 수집...')
        try:
            re_ym = datetime.date.today().strftime('%Y%m')
            # 전국 시군구 코드 동적 조회 (MOIS lv=1→lv=2) — 신규 시군구 자동 반영
            re_sgg_codes = fetch_all_sgg_codes(re_ym)
            print(f'  [Step 9] 전국 {len(re_sgg_codes)}개 시군구 대상')

            for sgg_cd in re_sgg_codes:
                print(f'  [Step 9] sgg_cd={sgg_cd}...')
                try:
                    raw_trades = fetch_trades(sgg_cd, re_ym)
                    trades = _re_norm_trades(raw_trades, sgg_cd, re_ym)
                    upsert_re_trades(trades)

                    raw_rents = fetch_rents(sgg_cd, re_ym)
                    rents = _re_norm_rents(raw_rents, sgg_cd, re_ym)
                    upsert_re_rents(rents)

                    # 행안부 API는 시군구도 10자리 코드로 호출 (뒷 5자리 0 패딩)
                    sgg_cd_10 = sgg_cd + "00000"
                    raw_pop = fetch_population(sgg_cd_10, re_ym)
                    population = _re_norm_population(raw_pop, re_ym)
                    upsert_mois_population(population)

                    raw_mapping = build_mapping(sgg_cd_10, re_ym)
                    mapping = _re_norm_mapping(raw_mapping)
                    upsert_stdg_admm_mapping(mapping)

                    household: list[dict] = []
                    admm_cds = list({m["admm_cd"] for m in mapping if m.get("admm_cd")})
                    for admm_cd in admm_cds:
                        raw_hh = fetch_household_by_size(admm_cd, re_ym)
                        household.extend(_re_norm_household(raw_hh, re_ym))
                    upsert_mois_household(household)

                    summary = compute_region_summary(
                        trades=trades, rents=rents,
                        population=population, mapping=mapping,
                        household=household or None,
                        sgg_cd=sgg_cd, stats_ym=re_ym,
                    )
                    upsert_region_summary(summary)

                    # 신규 법정동만 지오코딩 — (ctpv_nm, sgg_nm, stdg_nm) 조합으로 검색
                    existing_geo = {g["stdg_cd"] for g in fetch_geo_stdg(sgg_cd)}
                    seen_stdg: set[str] = set()
                    uniq_new: list[dict] = []
                    for m in mapping:
                        if m.get("stdg_cd") not in existing_geo and m["stdg_cd"] not in seen_stdg:
                            seen_stdg.add(m["stdg_cd"])
                            uniq_new.append(m)
                    if uniq_new:
                        addresses = [
                            f'{m.get("ctpv_nm", "")} {m.get("sgg_nm", "")} {m.get("stdg_nm", "")}'.strip()
                            for m in uniq_new
                        ]
                        geo_results = batch_geocode(addresses)
                        geo_records = [
                            {"stdg_cd": m["stdg_cd"], "stdg_nm": m.get("stdg_nm"),
                             "sgg_nm": m.get("sgg_nm"), "lat": geo["lat"], "lng": geo["lng"]}
                            for m, geo in zip(uniq_new, geo_results) if geo
                        ]
                        if geo_records:
                            upsert_geo_stdg(geo_records)
                            print(f'    지오코딩 {len(geo_records)}건 저장')
                except Exception as e_sgg:
                    print(f'  [Step 9] sgg_cd={sgg_cd} 실패, 건너뜀: {e_sgg}')
                    traceback.print_exc()

            print(f'[Step 9] 완료 ({len(re_sgg_codes)}개 시군구)')
        except Exception as e:
            print(f'[Step 9] 부동산 수집 실패, 건너뜀: {e}')
            traceback.print_exc()


# ══════════════════════════════════════════════════════════
# [15] 2026-04-24 (UTC) — Stage 7: 부동산 API 라우터
#     api/routers/real_estate.py 구현 (스텁 → 실제 구현)
# ══════════════════════════════════════════════════════════
#
# [변경 파일]
#   api/routers/real_estate.py  (4개 스텁 → 7개 완전 구현)
#   api/app.py                  (수정 불필요 — 이미 router 등록됨)
#
# [엔드포인트]
#   GET /api/realestate/summary?sgg_cd=&ym=       → fetch_region_summary
#   GET /api/realestate/trades?sgg_cd=&ym=        → fetch_re_trades
#   GET /api/realestate/rents?sgg_cd=&ym=         → fetch_re_rents
#   GET /api/realestate/population?sgg_cd=&ym=    → fetch_mois_population
#   GET /api/realestate/household?sgg_cd=&ym=     → fetch_mois_household
#   GET /api/realestate/mapping?sgg_cd=&ref_ym=   → fetch_stdg_admm_mapping
#   GET /api/realestate/geo?sgg_cd=               → fetch_geo_stdg
#
# [설계 결정]
#   - ym/ref_ym 미지정 시 당월(%Y%m)로 기본값 → 프론트 단순 호출 가능
#   - 라우터는 repositories 얇게 감싸기만 — 비즈니스 로직 없음
#   - /geo 는 기간 무관 (지오코딩 결과는 법정동당 1회 고정)
#
# ──────────────────────────────────────────────────────────
# api/routers/real_estate.py 전체 코드
# ──────────────────────────────────────────────────────────

from datetime import date

from fastapi import APIRouter, Query

from database.repositories import (
    fetch_region_summary, fetch_re_trades, fetch_re_rents,
    fetch_mois_population, fetch_mois_household,
    fetch_stdg_admm_mapping, fetch_geo_stdg,
)


router = APIRouter()


# 쿼리 ym 미지정 시 사용할 기본값(당월 YYYYMM) 생성
def _default_ym() -> str:
    return date.today().strftime('%Y%m')


# GET /summary — 지도·카드 메인용: 시군구 단위 법정동별 집계 반환
@router.get('/summary')
def get_summary(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """시군구 단위 지역 집계 (법정동별 평단가·거래건수·인구·1인가구비율 등)."""
    return fetch_region_summary(sgg_cd, ym or _default_ym())


# GET /trades — 상세화면 드릴다운용: 매매 실거래 원본 목록
@router.get('/trades')
def get_trades(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """매매 실거래 원본 목록 (지역 상세 화면 드릴다운용)."""
    return fetch_re_trades(sgg_cd, ym or _default_ym())


# GET /rents — 상세화면 드릴다운용: 전월세 실거래 원본 목록
@router.get('/rents')
def get_rents(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """전월세 실거래 원본 목록 (monthly_rent=0 → 전세)."""
    return fetch_re_rents(sgg_cd, ym or _default_ym())


# GET /population — 인구 차트용: 법정동별 총인구·세대수·성비
@router.get('/population')
def get_population(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """법정동별 인구·세대수 (MOIS)."""
    return fetch_mois_population(sgg_cd, ym or _default_ym())


# GET /household — 1인가구 분석용: 행정동별 세대원수 분포 + solo_rate
@router.get('/household')
def get_household(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """행정동별 세대원수 분포 + solo_rate (MOIS)."""
    return fetch_mois_household(sgg_cd, ym or _default_ym())


# GET /mapping — 조인 참조용: 법정동↔행정동 매핑 테이블
@router.get('/mapping')
def get_mapping(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ref_ym: str = Query(default='', description='YYYYMM, 미지정 시 당월'),
):
    """법정동↔행정동 매핑 테이블."""
    return fetch_stdg_admm_mapping(sgg_cd, ref_ym or _default_ym())


# GET /geo — 지도 마커용: 법정동 좌표 (lat, lng) 조회 (기간 무관)
@router.get('/geo')
def get_geo(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """법정동 좌표 (지도 마커용, 기간과 무관)."""
    return fetch_geo_stdg(sgg_cd)


# ══════════════════════════════════════════════════════════
# [16] 2026-04-24 (UTC) — Stage 8: 템플릿 정리
#     중복/미사용 템플릿 파일 2개 제거
# ══════════════════════════════════════════════════════════
#
# [삭제 파일]
#   templates/index.html
#     - stocks.html 과 바이트 단위로 동일 복제본
#     - / 엔드포인트는 landing.html 을 사용하도록 변경된 후 더 이상 쓰이지 않음
#
#   templates/realestate.html
#     - Jinja 템플릿으로 Vite 빌드 산출물 링크를 시도한 스텁
#     - api/app.py 의 /realestate 라우트는 FileResponse('static/realestate/index.html')
#       으로 Vite 빌드본을 직접 서빙하므로 템플릿 경유 불필요
#     - 게다가 Vite는 해시된 파일명(index-<hash>.js)으로 번들링하여
#       하드코딩 href/src 로는 자산 매칭 불가 — Vite 생성 index.html 만 정답
#
# [보존 파일]
#   templates/landing.html   — / 경로 (주식/부동산 선택 버튼)
#   templates/stocks.html    — /stocks 경로 (주식·ETF 원본 화면)
#   templates/stats.html     — /stats 경로 (공개 통계)
#
# [설계 근거]
#   - stocks.html 의 /static/css/main.css, /static/js/*.js 참조는 모두 절대 경로
#     (/static 마운트 기준) 이라 별도 수정 불필요
#   - frontend-realestate/vite.config.ts base='/static/realestate/' 이미 설정되어
#     npm run build 시 자산 URL 이 /static/realestate/assets/... 로 생성됨
#   - /realestate/* 요청은 app.py 의 catch-all 라우트가 항상 Vite index.html
#     로 대응해 React Router 가 클라이언트 사이드 라우팅 처리


# ══════════════════════════════════════════════════════════
# [17] 2026-04-24 (UTC) — Stage 9: 부동산 React 프론트엔드 본 구현
#     frontend-realestate/src/ 의 스텁 7개 → 실제 동작 코드로 전환
# ══════════════════════════════════════════════════════════
#
# [구현 파일]
#   types/api.ts
#     - 기존 camelCase 타입 → 백엔드 snake_case 응답과 일치하도록 전면 교체
#     - RegionSummary / Trade / Rent / Population / GeoStdg 5종 정의
#
#   api/endpoints.ts
#     - 기존 4개 → 7개로 확장 (household, mapping, geo 추가)
#     - undefined 쿼리는 파라미터에서 제외하는 헬퍼 q() 도입
#
#   screens/MapScreen.tsx
#     - KakaoMap SDK 연동 전까지 임시 시군구 버튼 그리드 (서울 주요 + 광역시)
#     - 클릭 시 useNavigate() 로 /region/:sggCd 이동
#
#   screens/RegionDetailScreen.tsx
#     - /api/realestate/summary 호출 → 법정동별 카드 리스트 (평단가 내림차순)
#     - trade_count, population, solo_rate, median_price_per_py 표시
#     - cancelled 플래그로 언마운트 후 setState 경합 방지
#
#   screens/ComplexDetailScreen.tsx
#     - /complex/:aptSeq?sgg_cd=XXXXX 형태 — 단지 단위 엔드포인트가 없어
#       시군구 매매 전량(/trades) 수신 후 클라이언트에서 apt_seq 필터
#       (월 거래 100~2000건 규모라 허용 수준)
#
#   components/BottomSheet.tsx
#     - 3단 스냅(hidden/half/full) Tailwind translate 전환
#     - 터치 제스처는 추후 framer-motion 도입 예정 — 현재는 헤더 클릭 토글
#
#   components/TimeSeriesChart.tsx
#     - 외부 차트 라이브러리 없이 순수 SVG polyline — 번들 경량화
#     - min/max 정규화 + PAD 계산
#
# [미구현 (외부 의존성 필요)]
#   components/KakaoMap.tsx      — KAKAO_JS_KEY 로드 후 SDK 연동
#   components/AiReportCard.tsx  — 백엔드 /api/real-estate/report + Anthropic 키
#
# ──────────────────────────────────────────────────────────
# frontend-realestate/src/types/api.ts (전체)
# ──────────────────────────────────────────────────────────
#
# export interface RegionSummary {
#   sgg_cd: string;
#   stdg_cd: string;
#   stdg_nm: string | null;
#   stats_ym: string;
#   trade_count: number | null;
#   avg_price: number | null;
#   median_price: number | null;
#   median_price_per_py: number | null;
#   jeonse_count: number | null;
#   wolse_count: number | null;
#   avg_deposit: number | null;
#   population: number | null;
#   solo_rate: number | null;
# }
#
# export interface Trade {
#   sgg_cd: string;
#   deal_ym: string;
#   apt_nm: string | null;
#   apt_seq: string | null;
#   umd_nm: string | null;
#   umd_cd: string | null;
#   stdg_cd: string | null;
#   deal_amount: number;
#   exclu_use_ar: number;
#   floor: number | null;
#   build_year: number | null;
#   deal_date: string;
#   dealing_gbn: string | null;
#   road_nm: string | null;
# }
#
# export interface Rent {
#   sgg_cd: string;
#   deal_ym: string;
#   apt_nm: string | null;
#   apt_seq: string | null;
#   umd_nm: string | null;
#   deposit: number;
#   monthly_rent: number;
#   exclu_use_ar: number;
#   floor: number | null;
#   deal_date: string;
#   contract_type: string | null;
#   road_nm: string | null;
# }
#
# export interface Population {
#   stats_ym: string;
#   stdg_cd: string;
#   stdg_nm: string | null;
#   sgg_nm: string | null;
#   tot_nmpr_cnt: number;
#   hh_cnt: number;
#   hh_nmpr: number;
#   male_nmpr_cnt: number;
#   feml_nmpr_cnt: number;
#   male_feml_rate: number;
# }
#
# export interface GeoStdg {
#   stdg_cd: string;
#   lat: number | null;
#   lng: number | null;
# }
#
# ──────────────────────────────────────────────────────────
# frontend-realestate/src/api/endpoints.ts (전체)
# ──────────────────────────────────────────────────────────
#
# export const ENDPOINTS = {
#   summary:    (sggCd, ym?) => q(`/api/realestate/summary`, { sgg_cd: sggCd, ym }),
#   trades:     (sggCd, ym?) => q(`/api/realestate/trades`, { sgg_cd: sggCd, ym }),
#   rents:      (sggCd, ym?) => q(`/api/realestate/rents`, { sgg_cd: sggCd, ym }),
#   population: (sggCd, ym?) => q(`/api/realestate/population`, { sgg_cd: sggCd, ym }),
#   household:  (sggCd, ym?) => q(`/api/realestate/household`, { sgg_cd: sggCd, ym }),
#   mapping:    (sggCd, refYm?) => q(`/api/realestate/mapping`, { sgg_cd: sggCd, ref_ym: refYm }),
#   geo:        (sggCd) => q(`/api/realestate/geo`, { sgg_cd: sggCd }),
# } as const;
#
# function q(path, params) {
#   // undefined / 빈 문자열 쿼리는 URL 에서 누락 — "ym=undefined" 방지
#   const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
#   if (entries.length === 0) return path;
#   return `${path}?${new URLSearchParams(entries).toString()}`;
# }
#
# ──────────────────────────────────────────────────────────
# RegionDetailScreen 핵심 로직
# ──────────────────────────────────────────────────────────
#
# useEffect(() => {
#   if (!sggCd) return;
#   let cancelled = false;
#   apiFetch<RegionSummary[]>(ENDPOINTS.summary(sggCd))
#     .then((data) => { if (!cancelled) setRows(data); })
#     .catch((e) => { if (!cancelled) setErr(String(e)); });
#   return () => { cancelled = true; };
# }, [sggCd]);
#
# // fetch_region_summary 가 median_price_per_py DESC 로 이미 정렬 반환 →
# // 프론트에서 추가 sort 불필요, 그대로 map 렌더
#
# ──────────────────────────────────────────────────────────
# BottomSheet 스냅 전환
# ──────────────────────────────────────────────────────────
#
# const TRANSLATE: Record<SnapLevel, string> = {
#   hidden: "translate-y-full",
#   half: "translate-y-[50%]",
#   full: "translate-y-0",
# };
# // onSnapChange 는 next 맵으로 연속 전환 — hidden→half→full→hidden 순환


# ══════════════════════════════════════════════════════════
# [18] 2026-04-24 (UTC) — Stage 10: Dockerfile + .dockerignore 정비
#     Node build + Python serve 2-stage 이미지 최적화
# ══════════════════════════════════════════════════════════
#
# [변경 파일]
#   .dockerignore  (9 → 36 라인, 신규 엔트리 9종 추가)
#   Dockerfile     (20 → 33 라인, 시스템 deps + 환경변수 + 캐시 강화)
#
# [.dockerignore 추가 엔트리]
#   node_modules/, frontend-realestate/node_modules/
#     - 로컬에서 npm install 을 돌린 경우 컨테이너 내부로 복사되면
#       플랫폼/아키텍처 불일치로 런타임 에러 발생 → 반드시 제외
#
#   frontend-realestate/dist/, static/realestate/assets/, index.html
#     - Stage 1 이 깨끗한 환경에서 빌드해야 재현 가능
#     - 로컬 산출물이 들어오면 npm run build 결과가 섞여 해시 불일치 발생
#
#   notebooks/, data/, catboost_info/, models/*.pkl
#     - 노트북/원시 데이터/학습 아티팩트는 이미지 크기만 키우는 개발 산출물
#     - 모델은 런타임에 파이프라인이 재학습하여 생성 (app.py lifespan 로직)
#
#   .pytest_cache/, .mypy_cache/, .ruff_cache/, update.py
#     - 런타임에 전혀 사용되지 않는 개발 아티팩트
#
# [Dockerfile 개선]
#   Stage 1 (node:20-slim)
#     - 기존 그대로: package.json 먼저 COPY → npm install → 소스 COPY → build
#       (소스 수정 시 npm install 레이어 캐시 재활용)
#
#   Stage 2 (python:3.11-slim)
#     - ENV PYTHONUNBUFFERED=1: uvicorn 로그 실시간 출력 (Railway 대시보드에서
#       요청 흐름 추적 가능)
#     - ENV PYTHONDONTWRITEBYTECODE=1: .pyc 파일 미생성 → 이미지 경량화
#     - ENV PIP_NO_CACHE_DIR=1: pip 다운로드 캐시 미보존 → 이미지 경량화
#     - apt install libgomp1: xgboost·catboost 가 런타임에 OpenMP 런타임 의존
#       (slim 이미지에 기본 미포함이라 import 시 ImportError 발생)
#     - --no-install-recommends + rm /var/lib/apt/lists/*: apt 캐시 정리
#
# [변경 근거]
#   - 원본 Dockerfile 은 로컬 node_modules 유입을 막지 못해 빌드 실패 위험
#   - libgomp1 누락 시 현재는 build 성공하지만 `import xgboost` 런타임에 실패
#   - 환경변수 3종은 업계 표준 Python 서비스 이미지 패턴
#
# ──────────────────────────────────────────────────────────
# .dockerignore 전문
# ──────────────────────────────────────────────────────────

# 민감정보
.env

# 개발용 파일
practice/
.vscode/
.idea/
*.md

# Python 캐시
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Git
.git/
.gitignore

# OS 파일
.DS_Store
Thumbs.db

# Node 의존성 — Stage 1에서 컨테이너 내부에 새로 설치 (로컬 빌드 캐시 유입 방지)
node_modules/
frontend-realestate/node_modules/

# Vite 빌드 산출물 — Stage 1에서 새로 생성하므로 로컬 산출물 불필요
frontend-realestate/dist/
static/realestate/assets/
static/realestate/index.html
static/realestate/*.svg
static/realestate/vite.svg

# 노트북·원시 데이터·학습 산출물 — 이미지에 포함하지 않음
notebooks/
.ipynb_checkpoints/
data/
catboost_info/
models/*.pkl

# 업데이트 로그 — 런타임에 사용되지 않음
update.py

# ──────────────────────────────────────────────────────────
# Dockerfile 전문
# ──────────────────────────────────────────────────────────

# Stage 1: React 빌드
# vite.config.ts 의 outDir="../static/realestate" → /project/static/realestate 로 산출.
FROM node:20-slim AS frontend-builder
WORKDIR /project

# package.json 만 먼저 복사 → 소스 변경 시에도 npm install 레이어 재활용.
COPY frontend-realestate/package.json frontend-realestate/
RUN cd frontend-realestate && npm install

# 나머지 소스 복사 후 빌드 (해시된 자산 파일명으로 번들링됨).
COPY frontend-realestate/ frontend-realestate/
RUN cd frontend-realestate && npm run build


# Stage 2: Python 서버
FROM python:3.11-slim
WORKDIR /app

# uvicorn 로그가 버퍼링되면 Railway 대시보드에서 실시간 확인 불가.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# xgboost/catboost 등이 런타임에 libgomp 필요 — slim 이미지엔 미포함.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# requirements 먼저 복사 → 코드 변경만 있을 때 pip install 캐시 재활용.
COPY requirements.txt .
RUN pip install -r requirements.txt

# 애플리케이션 코드 복사 (.dockerignore 로 node_modules, data, notebooks 등 제외).
COPY . .

# Stage 1 의 Vite 산출물을 static/realestate 로 덮어쓰기
# (.dockerignore 로 로컬 산출물이 복사되지 않아 덮어쓸 대상이 비어있음).
COPY --from=frontend-builder /project/static/realestate static/realestate

# runtime 에 HMM/XGBoost 모델 파일이 생성될 디렉토리.
RUN mkdir -p models

# Railway 등 PaaS 는 PORT 환경변수로 포트 주입 — shell 치환으로 받음.
CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8000}


# ══════════════════════════════════════════════════════════
# [19] 2026-04-25 (UTC) — Stage 11: 모바일 앱 UI + 카카오맵 + 시계열 대시보드
# ══════════════════════════════════════════════════════════
#
# [개요]
#   리스트 버튼 그리드 → 모바일 앱 형태로 전면 개편.
#   카카오맵 SDK 통합 + 4개월 시계열 차트 + 전세가율·전월세 메트릭 추가.
#
# [신규 파일]
#   frontend-realestate/src/components/MobileLayout.tsx
#     - 폰 프레임 래퍼 (데스크톱 max-w 428px, 모바일 풀화면)
#     - 하단 탭바 4개: 지도/검색/찜/메뉴
#     - safe-area-inset-top/bottom 으로 노치·홈인디케이터 대응
#
#   frontend-realestate/src/components/NavBar.tsx
#     - iOS 스타일 상단 네비 (좌측 ‹ 뒤로, 중앙 타이틀+서브타이틀)
#     - sticky + backdrop-blur 로 스크롤 시 반투명 효과
#
#   frontend-realestate/src/vite-env.d.ts
#     - /// <reference types="vite/client" /> 1줄
#     - import.meta.env 타입 미정의로 tsc 에러 발생 → Vite 표준 해법
#
# [수정 파일]
#   frontend-realestate/src/App.tsx
#     - 모든 라우트를 <MobileLayout> 으로 감쌈 → 탭바가 화면 전환에도 유지
#     - /search, /favorite, /menu Placeholder 라우트 추가 (탭만 활성)
#
#   frontend-realestate/src/screens/MapScreen.tsx
#     - 시군구 버튼 그리드 → KakaoMap 전체화면 + 플로팅 검색바
#     - 서울 25개 구 마커 좌표 하드코딩 (시군구 중심점)
#     - 마커 색: 데이터 있는 구는 파란색, 없는 구는 회색 (병렬 fetch 로 판별)
#
#   frontend-realestate/src/screens/RegionDetailScreen.tsx
#     - 단순 리스트 → 대시보드로 확장
#     - 상단 4개 메트릭 카드: 평균 평단가·월 거래량·전세/월세·전세가율(강조)
#     - 시계열 차트 4개: 평단가/거래량/전세가율/인구 (각각 다른 색)
#     - 하단 법정동 순위 카드 리스트 (기존 유지)
#     - /summary + /timeseries 병렬 호출 (Promise.all)
#
#   frontend-realestate/src/screens/ComplexDetailScreen.tsx
#     - NavBar 적용으로 상단 통일 (단지명 + 법정동·건축년도 서브타이틀)
#
#   frontend-realestate/src/components/KakaoMap.tsx
#     - 스텁 → 카카오맵 SDK 동적 로드 + 마커 + CustomOverlay 라벨 구현
#     - /api/realestate/config 에서 KAKAO_JS_KEY 가져옴 (env 노출 회피)
#     - autoload=false + kakao.maps.load() 콜백 방식 — 안정적
#     - markers prop 변경 시 cleanup 으로 메모리 누수 방지
#
#   frontend-realestate/src/components/TimeSeriesChart.tsx
#     - 빈 div 스텁 → 순수 SVG polyline + area fill 구현 (외부 라이브러리 없음)
#     - 축 라벨, min/max 표시, 단일월일 때 fallback 메시지
#
#   frontend-realestate/src/types/api.ts
#     - TimeseriesPoint 인터페이스 추가
#       (ym, trade_count, jeonse_rate, median_price_per_py 등)
#
#   frontend-realestate/src/api/endpoints.ts
#     - timeseries: (sggCd) => /api/realestate/timeseries 추가
#
#   api/routers/real_estate.py
#     - /timeseries 엔드포인트 추가 — 법정동 단위 region_summary 를 월별 rollup
#       (trade_count·jeonse_count 합계, price·deposit 평균, 전세가율 계산)
#     - /config 엔드포인트 추가 — 프론트가 카카오맵 SDK 로드 시 사용할 JS 키 반환
#       (KAKAO_JS_KEY 를 .env 에서 읽어 응답)
#     - _default_ym() 을 당월 → 전월로 변경
#       (MOIS 인구통계가 당월 미집계라 region_summary stats_ym 도 전월 기준)
#
#   database/repositories.py
#     - fetch_region_timeseries(sgg_cd) 추가 — 시군구의 모든 stats_ym 시계열 반환
#       (정렬 stats_ym ASC — 차트 X축 시간순)
#
#   scheduler/job.py
#     - re_ym 기본값을 datetime.today() → 전월(YYYYMM) 로 변경
#       (당월 호출 시 MOIS resultCode=10 INVALID_REQUEST_PARAMETER 에러)
#     - _re_norm_trades: (apt_seq, deal_date, floor, exclu_use_ar) 단위 dedupe
#     - _re_norm_rents:  + (deposit, monthly_rent) 까지 포함 dedupe
#     - _re_norm_household: (stats_ym, admm_cd) per-call dedupe
#       + Step 9 누적 단계에서도 한 번 더 dedupe (상위 admm 호출이 하위 포함 반환)
#       위 3개는 ON CONFLICT DO UPDATE cannot affect row a second time 에러 회피
#
# [환경 설정]
#   /etc/wsl.conf + /etc/resolv.conf — 공용 DNS(1.1.1.1, 8.8.8.8) 로 전환
#     - WSL2 기본 DNS(10.255.255.254) 가 짧은 시간 다수 호출에 약해 간헐 실패
#     - 시드 작업 중 ConnectError: Temporary failure in name resolution 다발
#     - 공용 DNS 로 교체 후 동일 작업 정상 진행
#
#   .env (서버측)
#     - DATA_GO_KR_KEY, KAKAO_REST_KEY, KAKAO_JS_KEY 값 채움
#       (real-estate/.env 의 MOLIT_TRADE_API_KEY · KAKAO_*_API_KEY 에서 복사)
#     - SUPABASE_URL 끝의 /rest/v1/ 제거
#       (supabase-py 가 /rest/v1/ 자동 prepend → 중복 시 PGRST125 404 에러)
#
# [데이터]
#   region_summary 1,000행 = 25개 구 × 4개월 (202512~202603) × 평균 10법정동
#   trade_count·jeonse_count·population 모두 시계열로 누적
#
# ──────────────────────────────────────────────────────────
# api/routers/real_estate.py (신규: /timeseries, /config)
# ──────────────────────────────────────────────────────────

@router.get('/timeseries')
def get_timeseries(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """시군구 월별 집계 배열 (법정동별이 아닌 구 전체 월별 rollup)."""
    rows = fetch_region_timeseries(sgg_cd)
    by_ym: dict[str, dict] = {}
    for r in rows:
        ym = r['stats_ym']
        d = by_ym.setdefault(ym, {
            'ym': ym, 'trade_count': 0, 'jeonse_count': 0, 'wolse_count': 0,
            'population': 0, '_price_sum': 0.0, '_price_n': 0,
            'avg_deposit_sum': 0, 'avg_deposit_n': 0,
            'avg_price_sum': 0, 'avg_price_n': 0,
        })
        d['trade_count']  += r.get('trade_count') or 0
        d['jeonse_count'] += r.get('jeonse_count') or 0
        d['wolse_count']  += r.get('wolse_count') or 0
        d['population']   += r.get('population') or 0
        if r.get('median_price_per_py'):
            d['_price_sum'] += r['median_price_per_py']; d['_price_n'] += 1
        if r.get('avg_deposit'):
            d['avg_deposit_sum'] += r['avg_deposit']; d['avg_deposit_n'] += 1
        if r.get('avg_price'):
            d['avg_price_sum'] += r['avg_price']; d['avg_price_n'] += 1
    out = []
    for ym in sorted(by_ym):
        d = by_ym[ym]
        avg_pp = d['_price_sum'] / d['_price_n'] if d['_price_n'] else None
        avg_dep = d['avg_deposit_sum'] / d['avg_deposit_n'] if d['avg_deposit_n'] else None
        avg_pr = d['avg_price_sum'] / d['avg_price_n'] if d['avg_price_n'] else None
        # 전세가율 = 전세보증금 / 매매가 (둘 다 만원 단위)
        jeonse_rate = (avg_dep / avg_pr) if (avg_dep and avg_pr) else None
        out.append({
            'ym': ym,
            'trade_count': d['trade_count'],
            'jeonse_count': d['jeonse_count'], 'wolse_count': d['wolse_count'],
            'population': d['population'],
            'median_price_per_py': round(avg_pp, 0) if avg_pp else None,
            'avg_deposit': round(avg_dep, 0) if avg_dep else None,
            'avg_price': round(avg_pr, 0) if avg_pr else None,
            'jeonse_rate': round(jeonse_rate, 4) if jeonse_rate else None,
        })
    return out


@router.get('/config')
def get_config():
    """프론트용 설정값 (카카오맵 JS 키)."""
    return {'kakao_js_key': os.getenv('KAKAO_JS_KEY', '')}


# ──────────────────────────────────────────────────────────
# database/repositories.py — fetch_region_timeseries 추가
# ──────────────────────────────────────────────────────────

def fetch_region_timeseries(sgg_cd: str) -> list[dict]:
    """시군구의 전체 월별 집계 — 시계열 차트용 (과거 → 최근 순)."""
    client = get_client()
    response = (
        client.table("region_summary")
        .select("*")
        .eq("sgg_cd", sgg_cd)
        .order("stats_ym", desc=False)
        .execute()
    )
    return response.data


# ──────────────────────────────────────────────────────────
# scheduler/job.py — re_ym 전월화 + dedupe 3종
# ──────────────────────────────────────────────────────────

# 기준월 = 전월 — MOIS 인구통계가 당월엔 미집계(1~2개월 lag)라
# 당월로 호출하면 resultCode=10 INVALID_REQUEST_PARAMETER 반환됨.
_today = datetime.date.today()
re_ym = (_today.replace(day=1) - datetime.timedelta(days=1)).strftime('%Y%m')

# trades dedupe — UNIQUE (apt_seq, deal_date, floor, exclu_use_ar)
seen_trade: set[tuple] = set()
key = (apt_seq, deal_date, floor, exclu)
if key in seen_trade: continue
seen_trade.add(key)

# rents dedupe — 동일 + (deposit, monthly_rent)
seen_rent: set[tuple] = set()
key = (apt_seq, deal_date, floor, exclu, deposit, monthly_rent)

# household 누적 dedupe (Step 9 안에서) — UNIQUE (stats_ym, admm_cd)
hh_seen: set[tuple] = set()
for admm_cd in admm_cds:
    raw_hh = fetch_household_by_size(admm_cd, re_ym)
    for row in _re_norm_household(raw_hh, re_ym):
        k = (row["stats_ym"], row["admm_cd"])
        if k in hh_seen: continue
        hh_seen.add(k); household.append(row)
upsert_mois_household(household)


# ──────────────────────────────────────────────────────────
# 프론트 KakaoMap SDK 동적 로드 핵심 로직 (요약)
# ──────────────────────────────────────────────────────────

# autoload=false + kakao.maps.load() 콜백 방식이 안정적.
# 즉시 로드(autoload=true) 는 document.write 로 후속 스크립트 주입해
# React StrictMode 와 충돌 가능.

let sdkPromise: Promise<void> | null = null;
function loadKakaoSdk(appkey: string): Promise<void> {
  if (window.kakao?.maps) return Promise.resolve();
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appkey}&autoload=false`;
    s.async = true;
    s.onload = () => window.kakao.maps.load(() => resolve());
    s.onerror = () => reject(new Error("카카오맵 SDK 로드 실패"));
    document.head.appendChild(s);
  });
  return sdkPromise;
}


# ──────────────────────────────────────────────────────────
# RegionDetailScreen 대시보드 핵심 (메트릭 + 차트 + 리스트)
# ──────────────────────────────────────────────────────────

# 4개 메트릭 카드 (그리드 2x2)
<div className="grid grid-cols-2 gap-2">
  <Metric label="평균 평단가"   value={fmtMan(latest.median_price_per_py)} />
  <Metric label="거래량(월)"    value={`${latest.trade_count.toLocaleString()}건`} />
  <Metric label="전세 / 월세"   value={`${latest.jeonse_count} / ${latest.wolse_count}`} />
  <Metric label="전세가율"      value={fmtPct(latest.jeonse_rate)} accent />
</div>

# 시계열 차트 4종 (각각 색 다름)
<TimeSeriesChart label="평단가 추이 (만원/평)"
  data={ts!.map((p) => ({ date: p.ym, value: p.median_price_per_py }))}
  color="#3b82f6" />
<TimeSeriesChart label="월별 거래량 (건)"
  data={ts!.map((p) => ({ date: p.ym, value: p.trade_count }))}
  color="#10b981" />
<TimeSeriesChart label="전세가율 (%)"
  data={ts!.map((p) => ({ date: p.ym, value: p.jeonse_rate }))}
  format={(n) => `${(n * 100).toFixed(1)}%`} color="#f59e0b" />
<TimeSeriesChart label="인구 (명)"
  data={ts!.map((p) => ({ date: p.ym, value: p.population }))}
  color="#a78bfa" />


# ══════════════════════════════════════════════════════════
# [20] 2026-04-25 (UTC) — 매수 타이밍 시그널 Step A (MVP)
# ══════════════════════════════════════════════════════════
#
# [개요]
#   거래량·가격·인구 변화율로 시군구 단위 매수/관망/주의 시그널 도출.
#   외부 API(ECOS·KOSIS) 없이 이미 보유한 region_summary 시계열만 사용.
#   Step B(금리)·C(인구이동)·D(LLM 해설) 컬럼은 NULL 로 미리 마련해 둠.
#
# [신규 파일]
#   processor/feature6_buy_signal.py
#     - compute_buy_signal(ts) — 시계열 입력, 시그널 dict 반환
#     - 점수 가중치: trade*100, price*200, pop*500 (각 클램프 ±30/30/20)
#     - 임계값: total >= +15 매수, <= -15 주의, else 관망
#
#   frontend-realestate/src/components/SignalCard.tsx
#     - 시그널별 색상(파란/회색/빨간) + 아이콘 + 종합점수
#     - 거래/가격/인구 점수 breakdown 3칸 그리드 (+ 변화율 % 동시 표기)
#
# [수정 파일]
#   database/repositories.py
#     - upsert_buy_signal / fetch_buy_signal / fetch_buy_signal_history 추가
#     - 패턴: 기존 region_summary 함수 그대로 모방
#
#   api/routers/real_estate.py
#     - GET /signal (?sgg_cd=, ?ym=) — 최신 시그널 1건
#     - GET /signal/history (?sgg_cd=) — 시그널 시계열
#     - imports: fetch_buy_signal, fetch_buy_signal_history 추가
#
#   scheduler/job.py
#     - Step 9 의 region_summary upsert 직후 시그널 계산·저장 블록 추가
#     - fetch_region_timeseries → compute_buy_signal → upsert_buy_signal
#     - imports: feature6_buy_signal, fetch_region_timeseries, upsert_buy_signal
#
#   supabase_tables.sql
#     - buy_signal_result 테이블 추가 (UNIQUE sgg_cd+stats_ym)
#     - 컬럼: signal, score, trade/price/pop_score, rate_score(B), flow_score(C),
#             feature_breakdown JSONB, narrative TEXT(D), updated_at
#
#   frontend-realestate/src/types/api.ts
#     - BuySignal 인터페이스 추가
#
#   frontend-realestate/src/api/endpoints.ts
#     - buySignal, buySignalHistory 추가
#
#   frontend-realestate/src/screens/RegionDetailScreen.tsx
#     - SignalCard import 후 메트릭 위에 배치
#     - useEffect 의 Promise.all 에 buySignal fetch 추가 (3개 병렬)
#     - 빈 객체({}) 응답을 null 로 처리 (시그널 없음 케이스)
#
# [백필 스크립트 (1회 실행)]
#   region_summary 4개월치를 시군구별로 ts 로 rollup 한 뒤
#   ts[:i] (i=2,3,4)로 슬라이싱해 각 월의 시그널 백필.
#   결과: 25구 × ~3개월 = 72건 저장.
#   분포: 매수 36 / 관망 28 / 주의 8
#
# [Verification 결과]
#   - 강남구(11680) 202603: 주의 (score -15.7, 거래 -19%, 가격 +2.4%, 인구 -0.3%)
#   - 서초구(11650) 202603: 매수 (score +39.3, 가격 +30, 인구 +20)
#   - /signal API: JSON 정상 반환
#   - /signal/history API: 월별 변화 추적 가능
#   - UI: NavBar 아래 SignalCard 노출, 색상 구분 작동
#
# ──────────────────────────────────────────────────────────
# processor/feature6_buy_signal.py 핵심 (clamp + 점수 + 임계)
# ──────────────────────────────────────────────────────────

def compute_buy_signal(ts: list[dict]) -> dict | None:
    if not ts or len(ts) < 2:
        return None

    latest = ts[-1]; prev = ts[-2]
    prev_trades = [p.get("trade_count") or 0 for p in ts[:-1]]
    avg_prev_trade = mean(prev_trades) if prev_trades else 0
    trade_chg = _safe_div((latest.get("trade_count") or 0) - avg_prev_trade, avg_prev_trade)

    price_mom = _safe_div(
        (latest.get("median_price_per_py") or 0) - (prev.get("median_price_per_py") or 0),
        prev.get("median_price_per_py") or 0,
    )
    pop_chg = _safe_div(
        (latest.get("population") or 0) - (prev.get("population") or 0),
        prev.get("population") or 0,
    )

    trade_score = _clamp(trade_chg * 100, -30, 30)
    price_score = _clamp(price_mom * 200, -30, 30)
    pop_score   = _clamp(pop_chg * 500, -20, 20)
    total = trade_score + price_score + pop_score

    if total >= 15:   signal = "매수"
    elif total <= -15: signal = "주의"
    else:             signal = "관망"

    return {
        "stats_ym": latest.get("ym"),
        "signal": signal, "score": round(total, 1),
        "trade_score": round(trade_score, 1),
        "price_score": round(price_score, 1),
        "pop_score":   round(pop_score, 1),
        "rate_score": None, "flow_score": None,
        "feature_breakdown": {
            "trade_chg_pct": round(trade_chg * 100, 2),
            "price_mom_pct": round(price_mom * 100, 2),
            "pop_chg_pct":   round(pop_chg * 100, 2),
        },
        "narrative": None,
    }


# ──────────────────────────────────────────────────────────
# scheduler/job.py — Step 9 안 region_summary upsert 직후
# ──────────────────────────────────────────────────────────

# 매수 시그널 — region_summary 시계열을 다시 읽어 변화율 계산
# (방금 upsert 했으므로 fetch 결과에 최신월 포함됨)
ts = fetch_region_timeseries(sgg_cd)
signal_rec = compute_buy_signal(ts)
if signal_rec:
    signal_rec['sgg_cd'] = sgg_cd
    upsert_buy_signal(signal_rec)


# ──────────────────────────────────────────────────────────
# database/repositories.py — buy_signal 3종 함수
# ──────────────────────────────────────────────────────────

def upsert_buy_signal(record: dict) -> None:
    if not record: return
    client = get_client()
    client.table("buy_signal_result").upsert(
        record, on_conflict="sgg_cd,stats_ym"
    ).execute()

def fetch_buy_signal(sgg_cd: str, ym: str | None = None) -> dict | None:
    client = get_client()
    q = client.table("buy_signal_result").select("*").eq("sgg_cd", sgg_cd)
    if ym: q = q.eq("stats_ym", ym)
    response = q.order("stats_ym", desc=True).limit(1).execute()
    return response.data[0] if response.data else None

def fetch_buy_signal_history(sgg_cd: str) -> list[dict]:
    client = get_client()
    response = (
        client.table("buy_signal_result").select("*")
        .eq("sgg_cd", sgg_cd).order("stats_ym", desc=False).execute()
    )
    return response.data


# ──────────────────────────────────────────────────────────
# api/routers/real_estate.py — /signal 2종
# ──────────────────────────────────────────────────────────

@router.get('/signal')
def get_signal(
    sgg_cd: str = Query(..., description='시군구 코드 5자리'),
    ym: str = Query(default='', description='YYYYMM, 미지정 시 최신'),
):
    """시군구의 매수/관망/주의 시그널 + 점수 breakdown."""
    return fetch_buy_signal(sgg_cd, ym or None) or {}

@router.get('/signal/history')
def get_signal_history(sgg_cd: str = Query(..., description='시군구 코드 5자리')):
    """시군구의 시그널 시계열 (과거 → 최근)."""
    return fetch_buy_signal_history(sgg_cd)


# ──────────────────────────────────────────────────────────
# supabase_tables.sql — buy_signal_result DDL
# ──────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────
# frontend-realestate/src/components/SignalCard.tsx — 핵심 렌더
# ──────────────────────────────────────────────────────────

const STYLE: Record<BuySignal["signal"], { bg, ring, icon, copy }> = {
  매수: { bg: "bg-blue-500/15",  ring: "ring-blue-500/40",  icon: "↑", copy: "거래·가격·인구 동반 상승 신호" },
  관망: { bg: "bg-gray-500/15",  ring: "ring-gray-500/40",  icon: "→", copy: "지표 혼조 — 추세 확인 필요" },
  주의: { bg: "bg-red-500/15",   ring: "ring-red-500/40",   icon: "↓", copy: "거래·가격·인구 동반 약세" },
};
// breakdown 3칸: 거래량 / 가격 / 인구 — 각 점수 부호로 색 구분


# ══════════════════════════════════════════════════════════
# [21] 2026-04-26 (UTC) — 매수 시그널 Step B + C: ECOS 금리 + KOSIS 인구이동
# ══════════════════════════════════════════════════════════
#
# [개요]
#   buy_signal 의 rate_score(B)·flow_score(C) 컬럼을 NULL 에서 실제 값으로 채움.
#   - ECOS: 한국은행 기준금리·주담대 금리·잔액 24개월 시계열
#   - KOSIS: 시군구별 전입·전출·순이동 24개월 시계열
#   - compute_buy_signal 함수 시그니처에 rate_ts/flow_ts 옵션 추가 (둘 다 선택 — 없어도 동작)
#
# [신규 파일]
#   collector/ecos_macro.py
#     - SPECS dict 로 3개 지표(table+item+cycle) 한 곳 관리
#     - fetch_ecos_series(metric, from_ym, to_ym) — 단일 지표
#     - fetch_macro_rate_kr(months=24) — 3지표 wide rollup (date 키로 병합)
#     - 통계표 코드 검증치(2026-04 ECOS StatisticItemList 직접 호출):
#         722Y001/0101000   = 기준금리 (월)
#         121Y006/BECBLA0302 = 주담대 신규취급 가중평균 금리
#         151Y005/11110A0   = 예금은행 주담대 잔액
#       기존 가짜 코드(BECCLA0101, 1110000)로는 INFO-200 "데이터 없음" 에러 발생
#
#   collector/kosis_migration.py
#     - 통계표 DT_1B26001 (시군구/성/연령(5세)별 이동자수)
#     - 분류 차원: C1=시군구(objL1), C2=성별(objL2='0'), C3=연령(objL3='000')
#     - 항목 itmId='T10+T20+T25' 로 전입·전출·순이동 한 번에 호출
#     - 한 호출당 40,000셀 한도 → 25구 × 24개월 × 3지표 = 1,800셀 OK
#
# [수정 파일]
#   processor/feature6_buy_signal.py
#     - compute_buy_signal(ts, rate_ts=None, flow_ts=None) — 두 옵션 추가
#     - _compute_rate_score: 기준금리 12개월 max 대비 하락폭 *25 + 주담대 MoM *(-1000)
#     - _compute_flow_score: 시군구 net_flow / 100 (±20 클램프)
#     - 임계값 ±15 유지 (rate +25 가 일괄 더해져 매수 비중 증가)
#
#   database/repositories.py
#     - upsert_macro_rate_kr / fetch_macro_rate_kr (date UNIQUE)
#     - upsert_region_migration / fetch_region_migration (sgg_cd+stats_ym UNIQUE)
#
#   api/routers/real_estate.py
#     - GET /macro-rate?months= → ECOS 시계열 반환
#     - GET /migration?sgg_cd= → KOSIS 인구이동 시계열
#
#   scheduler/job.py
#     - Step 8b: ECOS 24개월 수집 (Step 9 진입 전, fetch_macro_rate_kr → upsert)
#     - Step 9 진입부: 전국 시군구 KOSIS 한 번에 수집 (셀 한도 안 넘게)
#     - 각 sgg_cd 의 buy_signal 계산 시 rate_ts·flow_ts 전달
#
#   supabase_tables.sql
#     - macro_rate_kr 테이블 (date UNIQUE, base_rate/mortgage_rate/mortgage_balance/cycle)
#     - region_migration 테이블 (sgg_cd+stats_ym UNIQUE, in/out/net_flow)
#
# [재백필]
#   기존 72건 buy_signal_result 를 ECOS+KOSIS 포함 5개 점수로 재계산.
#   분포 변화: 매수 36→38, 관망 28→23, 주의 8→11
#   (rate_score +25 가 일괄 더해지지만 flow_score 의 ±값 차이로 분포 다양화)
#
# [Verification]
#   - /api/realestate/macro-rate?months=4 → ECOS 시계열 JSON
#   - /api/realestate/migration?sgg_cd=11680 → 강남구 24개월 인구이동
#   - /api/realestate/signal?sgg_cd=11680 → 5개 점수·feature_breakdown 모두 채워짐
#   - 강남구 202603 예시:
#       trade -18.9 / price +4.7 / pop -1.5 / rate +25 / flow -14.6 → total -5.3 = 관망
#       (Step A 에서는 -15.7 = 주의였는데 rate +25 합산되며 관망으로 상승)
#       breakdown 추가: base_rate 2.5%, base_rate_drop_pct 9.09%, net_flow -1460
#
# ──────────────────────────────────────────────────────────
# collector/ecos_macro.py — SPECS + 핵심 fetch
# ──────────────────────────────────────────────────────────

ECOS_KEY = os.getenv("ECOS_API_KEY", "")
ECOS_URL = "https://ecos.bok.or.kr/api/StatisticSearch"

SPECS = {
    "base_rate":        {"table": "722Y001", "item": "0101000",    "cycle": "M"},
    "mortgage_rate":    {"table": "121Y006", "item": "BECBLA0302", "cycle": "M"},
    "mortgage_balance": {"table": "151Y005", "item": "11110A0",    "cycle": "M"},
}

def fetch_ecos_series(metric: str, from_ym: str, to_ym: str) -> list[dict]:
    spec = SPECS[metric]
    url = (
        f"{ECOS_URL}/{ECOS_KEY}/json/kr/1/100000/"
        f"{spec['table']}/{spec['cycle']}/"
        f"{from_ym}/{to_ym}/{spec['item']}"
    )
    r = httpx.get(url, timeout=20.0)
    r.raise_for_status()
    j = r.json()
    if "RESULT" in j:
        raise ValueError(f"[ecos] {metric}: {j['RESULT']}")
    rows = j.get("StatisticSearch", {}).get("row", [])
    out = []
    for row in rows:
        d = _ecos_time_to_date(row.get("TIME", ""), spec["cycle"])
        if not d: continue
        try: v = float(row.get("DATA_VALUE", "0"))
        except ValueError: continue
        out.append({"date": d, "value": v, "cycle": spec["cycle"], "metric": metric})
    return out


# ──────────────────────────────────────────────────────────
# collector/kosis_migration.py — 한 번에 전입·전출·순이동
# ──────────────────────────────────────────────────────────

def fetch_kosis_migration(sgg_cds: list[str], months: int = 12) -> list[dict]:
    obj_l1 = "+".join(sgg_cds)
    params = {
        "method": "getList", "apiKey": KOSIS_KEY,
        "format": "json", "jsonVD": "Y",
        "orgId": "101", "tblId": "DT_1B26001",
        "prdSe": "M", "newEstPrdCnt": str(months),
        "itmId": "T10+T20+T25",
        "objL1": obj_l1, "objL2": "0", "objL3": "000",
    }
    r = httpx.get(KOSIS_URL, params=params, timeout=30.0)
    r.raise_for_status()
    rows = r.json()
    if isinstance(rows, dict) and "err" in rows:
        raise ValueError(f"[kosis] {rows.get('err')}: {rows.get('errMsg')}")
    by_key: dict[tuple, dict] = {}
    for row in rows:
        sgg = row.get("C1"); ym = row.get("PRD_DE"); itm = row.get("ITM_ID")
        try: v = int(row.get("DT", "0"))
        except (ValueError, TypeError): continue
        if not (sgg and ym and itm): continue
        rec = by_key.setdefault((sgg, ym), {
            "sgg_cd": sgg, "stats_ym": ym,
            "in_count": None, "out_count": None, "net_flow": None,
        })
        if itm == "T10": rec["in_count"] = v
        elif itm == "T20": rec["out_count"] = v
        elif itm == "T25": rec["net_flow"] = v
    out = []
    for d in by_key.values():
        if d["net_flow"] is None and d["in_count"] is not None and d["out_count"] is not None:
            d["net_flow"] = d["in_count"] - d["out_count"]
        out.append(d)
    return out


# ──────────────────────────────────────────────────────────
# processor/feature6_buy_signal.py — rate/flow 점수 추가
# ──────────────────────────────────────────────────────────

def _compute_rate_score(rate_ts, target_ym):
    if not rate_ts or not target_ym:
        return None, {}
    target_prefix = f"{target_ym[:4]}-{target_ym[4:6]}"
    cutoff_idx = next((i for i, r in enumerate(rate_ts) if r["date"].startswith(target_prefix)), -1)
    if cutoff_idx < 0:
        cutoff_idx = len(rate_ts) - 1
    window = rate_ts[max(0, cutoff_idx - 11): cutoff_idx + 1]
    if len(window) < 2:
        return 0.0, {}
    base_now = window[-1].get("base_rate")
    base_max = max((r.get("base_rate") or 0) for r in window) or 0
    base_drop = (base_max - (base_now or 0)) / base_max if base_max else 0
    mort_now = window[-1].get("mortgage_rate")
    mort_prev = window[-2].get("mortgage_rate") if len(window) >= 2 else None
    mort_chg = _safe_div((mort_now or 0) - (mort_prev or 0), mort_prev or 0)
    score_raw = base_drop * 25 - mort_chg * 1000
    return _clamp(score_raw, -25, 25), {
        "base_rate": base_now,
        "base_rate_drop_pct": round(base_drop * 100, 2),
        "mortgage_rate": mort_now,
        "mortgage_rate_mom_pct": round(mort_chg * 100, 3),
    }


def _compute_flow_score(flow_ts, target_ym):
    if not flow_ts or not target_ym:
        return None, {}
    cur = next((r for r in flow_ts if r["stats_ym"] == target_ym), None)
    if not cur:
        return 0.0, {}
    net = cur.get("net_flow") or 0
    return _clamp(net / 100, -20, 20), {
        "in_count": cur.get("in_count"),
        "out_count": cur.get("out_count"),
        "net_flow": net,
    }


# ──────────────────────────────────────────────────────────
# scheduler/job.py — Step 8b ECOS + Step 9 시작부 KOSIS
# ──────────────────────────────────────────────────────────

# Step 8b: ECOS 거시지표 (Step 9 진입 전에 fetch & upsert)
ecos_rows = ecos_fetch_macro_rate_kr(months=24)
upsert_macro_rate_kr(ecos_rows)

# Step 9 진입부: 전국 시군구 KOSIS 한 번에
kosis_rows = fetch_kosis_migration(re_sgg_codes, months=24)
upsert_region_migration(kosis_rows)
rate_ts = repo_fetch_macro_rate_kr(months=24)

# 각 sgg_cd 루프 안에서:
ts = fetch_region_timeseries(sgg_cd)
flow_ts = fetch_region_migration(sgg_cd)
signal_rec = compute_buy_signal(ts, rate_ts=rate_ts, flow_ts=flow_ts)


# ──────────────────────────────────────────────────────────
# API 라우터 (api/routers/real_estate.py 추가)
# ──────────────────────────────────────────────────────────

@router.get('/macro-rate')
def get_macro_rate(months: int = Query(default=24)):
    return fetch_macro_rate_kr(months=months)

@router.get('/migration')
def get_migration(sgg_cd: str = Query(...)):
    return fetch_region_migration(sgg_cd)


# ──────────────────────────────────────────────────────────
# supabase_tables.sql — 신규 2개 테이블
# ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS macro_rate_kr (
    id              BIGSERIAL PRIMARY KEY,
    date            DATE NOT NULL UNIQUE,
    base_rate       DOUBLE PRECISION,
    mortgage_rate   DOUBLE PRECISION,
    mortgage_balance BIGINT,
    cycle           TEXT NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_macro_rate_date ON macro_rate_kr (date DESC);

CREATE TABLE IF NOT EXISTS region_migration (
    id              BIGSERIAL PRIMARY KEY,
    sgg_cd          TEXT NOT NULL,
    stats_ym        TEXT NOT NULL,
    in_count        INTEGER,
    out_count       INTEGER,
    net_flow        INTEGER,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (sgg_cd, stats_ym)
);
CREATE INDEX IF NOT EXISTS idx_migration_sgg_ym ON region_migration (sgg_cd, stats_ym DESC);


# ══════════════════════════════════════════════════════════
# [22] 2026-04-26 (UTC) — 지도 폴리곤화 + 법정동 상세 페이지 재설계
# ══════════════════════════════════════════════════════════
#
# [개요]
#   기존: 시군구 핀(마커) 25개 → 클릭 시 시군구 페이지(법정동 리스트)
#   변경: 시군구 폴리곤(경계면 색칠) → 클릭 시 BottomBar 슬라이드인 →
#         바 클릭 시 법정동 단위 상세 페이지(/stdg/:stdgCd) 직접 이동
#
#   상세 페이지도 첨부 이미지 디자인으로 재구성: 헤더+AI카드+메트릭4+12M차트+단지리스트
#
# [신규 파일]
#   processor 변경 없음.
#
#   frontend-realestate/src/lib/color.ts
#     - changePctColor(pct): 변화율 → 색상 (5단계 piecewise)
#     - changePctTextColor(pct): 텍스트용 (text-red-300 등)
#     - formatPrice(man): ≥10000만 → "X.X억", 아니면 "X,XXX만"
#
#   frontend-realestate/src/components/AiInsightCard.tsx
#     - signal 입력 → 룰베이스 placeholder 해설 (Step D 까지는 narrative=null)
#     - 강점/리스크 카드 2개 (점수 부호로 분류)
#
#   frontend-realestate/src/components/BottomBar.tsx
#     - MobileLayout 탭바(64px) 위 sticky, translate-y 슬라이드인
#     - 가격 포맷 + 변화율 배지 색 (changePctColor 재사용)
#     - 카드 전체 클릭 → onTap(topStdgCd)
#
#   frontend-realestate/src/screens/StdgDetailScreen.tsx
#     - /stdg/:stdgCd 라우트 핸들러
#     - apiFetch(stdgDetail) 단일 호출로 summary+timeseries+complexes+signal 한꺼번에
#     - 헤더 배지(상승/보합/하락) + AiInsightCard + 메트릭 2x2 + 12M 차트 + 단지 리스트
#
#   frontend-realestate/public/geojson/seoul-sgg.geojson
#     - southkorea-maps 의 250개 시군구 GeoJSON 중 서울 25개만 필터
#     - 좌표 단순화 (tolerance 0.0003) → 149KB
#     - properties 는 name·code 만 유지
#     - properties.code 는 행안부 코드와 다름 (11010=종로구) → name 매칭으로 해결
#
# [수정 파일]
#   database/repositories.py
#     - fetch_region_by_stdg_cd(stdg_cd, ym) — 단일 법정동 행
#     - fetch_region_timeseries_by_stdg(stdg_cd, months=12) — 법정동 12M 시계열
#     - fetch_complex_summary_by_stdg(stdg_cd, ym, top=10) — apt_seq groupby
#       (3개월 윈도우 내 거래에서 median 평단가·거래수, 평단가 DESC top N)
#
#   api/routers/real_estate.py
#     - GET /sgg-overview?ym= — region_summary rollup → 25개 시군구
#       + change_pct_3m (3개월 평단가 변화율) + top_stdg_cd/nm (BottomBar 표기)
#     - GET /stdg-detail?stdg_cd=&ym= — 통합 응답
#       (summary+timeseries+complexes+signal 한 번에)
#     - jeonse_rate = avg_deposit / avg_price
#     - net_flow 는 시군구 단위 region_migration 최신값 차용
#     - imports: 신규 3개 repo 함수 + supabase_client.get_client (overview rollup용)
#
#   frontend-realestate/src/types/api.ts
#     - SggOverview, ComplexSummary, StdgDetail 인터페이스 추가
#
#   frontend-realestate/src/api/endpoints.ts
#     - sggOverview(ym?), stdgDetail(stdgCd, ym?) 추가
#
#   frontend-realestate/src/components/KakaoMap.tsx
#     - PolygonFeature 타입 export
#     - polygons / onPolygonClick props 추가 (markers 와 공존, 옵셔널)
#     - kakao.maps.Polygon 인스턴스 생성 + click/mouseover 이벤트
#     - cleanup: polygons prop 변경 시 이전 인스턴스 setMap(null)
#
#   frontend-realestate/src/screens/MapScreen.tsx
#     - 마커 그리드 → KakaoMap polygons + BottomBar 조합으로 전면 교체
#     - useEffect: /sgg-overview fetch + /static/realestate/geojson/seoul-sgg.geojson 로드
#     - GeoJSON name(한글) → 우리 sgg_cd 매핑 (SGG_NAME_TO_CD 25개)
#     - 폴리곤 클릭 → setSelected → BottomBar 표시
#     - 색상 범례 띠 (5단계 색)
#
#   frontend-realestate/src/App.tsx
#     - <Route path="/stdg/:stdgCd" element={<StdgDetailScreen />} /> 추가
#     - 기존 /region/:sggCd 유지
#
# [데이터 흐름]
#   브라우저 → /api/realestate/sgg-overview → 25행 + 변화율
#         → /static/realestate/geojson/seoul-sgg.geojson (149KB)
#         → name으로 매칭 → KakaoMap polygons prop
#         → 폴리곤 클릭 → BottomBar (sgg_nm, top_stdg_nm, 평단가, 변화율)
#         → 바 클릭 → /stdg/{topStdgCd}
#         → /api/realestate/stdg-detail → 상세페이지 렌더
#
# [Verification]
#   - curl /api/realestate/sgg-overview?ym=202603 → 25개 행, 변화율 ±14% 분포
#   - curl /api/realestate/stdg-detail?stdg_cd=1168010600&ym=202603 →
#     대치동 평단가 13358만, 3M +10.4%, 단지 10개 (은마 16057만/평)
#   - GET /static/realestate/geojson/seoul-sgg.geojson → 200 OK
#   - 브라우저 /realestate → 서울 25개 폴리곤 색칠
#   - 폴리곤 클릭 → 하단 바 슬라이드 인 → 클릭 → /stdg/1168010600
#
# ──────────────────────────────────────────────────────────
# database/repositories.py — 법정동 단위 함수 3종
# ──────────────────────────────────────────────────────────

def fetch_region_by_stdg_cd(stdg_cd: str, ym: str) -> dict | None:
    """단일 법정동 region_summary 한 행 — UNIQUE(stdg_cd, stats_ym) 보장됨."""
    client = get_client()
    response = (
        client.table("region_summary").select("*")
        .eq("stdg_cd", stdg_cd).eq("stats_ym", ym).limit(1).execute()
    )
    return response.data[0] if response.data else None


def fetch_region_timeseries_by_stdg(stdg_cd: str, months: int = 12) -> list[dict]:
    """법정동의 월별 집계 — months 만큼 최근 (과거→최근 정렬)."""
    client = get_client()
    response = (
        client.table("region_summary").select("*")
        .eq("stdg_cd", stdg_cd).order("stats_ym", desc=True)
        .limit(months).execute()
    )
    return list(reversed(response.data))


def fetch_complex_summary_by_stdg(stdg_cd: str, ym: str, top: int = 10) -> list[dict]:
    """법정동 단지(apt_seq) 단위 요약 — 평단가 내림차순 top N.

    ym 포함 직전 2개월 윈도우. apt_seq groupby median 평단가·거래수.
    """
    from statistics import median
    from collections import defaultdict
    client = get_client()
    y, m = int(ym[:4]), int(ym[4:6])
    yms = []
    for _ in range(3):
        yms.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0: m = 12; y -= 1
    response = (
        client.table("real_estate_trade_raw")
        .select("apt_seq,apt_nm,build_year,deal_amount,exclu_use_ar")
        .eq("stdg_cd", stdg_cd).in_("deal_ym", yms).execute()
    )
    bucket: dict[str, list] = defaultdict(list)
    meta: dict[str, dict] = {}
    for r in response.data:
        seq = r.get("apt_seq")
        ar = r.get("exclu_use_ar") or 0
        amt = r.get("deal_amount") or 0
        if not seq or ar <= 0 or amt <= 0: continue
        bucket[seq].append(amt / (ar / 3.305785))
        meta.setdefault(seq, {"apt_nm": r.get("apt_nm"), "build_year": r.get("build_year")})
    out = [
        {"apt_seq": seq, "apt_nm": meta[seq]["apt_nm"], "build_year": meta[seq]["build_year"],
         "trade_count": len(prices), "median_price_per_py": round(median(prices), 0)}
        for seq, prices in bucket.items()
    ]
    out.sort(key=lambda x: x["median_price_per_py"], reverse=True)
    return out[:top]


# ──────────────────────────────────────────────────────────
# api/routers/real_estate.py — /sgg-overview, /stdg-detail
# ──────────────────────────────────────────────────────────

@router.get('/sgg-overview')
def get_sgg_overview(ym: str = Query(default='')):
    """서울 시군구별 매매가 + 3개월 변화율 + 대표 법정동."""
    target_ym = ym or _default_ym()
    from database.supabase_client import get_client
    client = get_client()
    response = client.table('region_summary').select(
        'sgg_cd,stdg_cd,stdg_nm,stats_ym,median_price_per_py,trade_count'
    ).execute()
    rows = response.data
    by_sm: dict[tuple, dict] = {}
    for r in rows:
        key = (r['sgg_cd'], r['stats_ym'])
        d = by_sm.setdefault(key, {'_ps': 0.0, '_pn': 0, 'trade_count': 0})
        if r.get('median_price_per_py'):
            d['_ps'] += r['median_price_per_py']; d['_pn'] += 1
        d['trade_count'] += r.get('trade_count') or 0
    # 시군구별 최신월 vs 3개월 전 비교 → change_pct_3m
    out = []
    sgg_cds = sorted({r['sgg_cd'] for r in rows})
    for sgg_cd in sgg_cds:
        yms = sorted(ym for (s, ym) in by_sm if s == sgg_cd)
        if not yms: continue
        latest_ym = target_ym if target_ym in yms else yms[-1]
        try: li = yms.index(latest_ym)
        except ValueError: continue
        prev_ym = yms[max(0, li - 3)]
        latest = by_sm[(sgg_cd, latest_ym)]
        prev = by_sm[(sgg_cd, prev_ym)]
        latest_avg = latest['_ps'] / latest['_pn'] if latest['_pn'] else None
        prev_avg = prev['_ps'] / prev['_pn'] if prev['_pn'] else None
        change_pct = None
        if latest_avg and prev_avg and latest_ym != prev_ym:
            change_pct = round((latest_avg / prev_avg - 1) * 100, 2)
        top_stdg = max(
            (r for r in rows if r['sgg_cd'] == sgg_cd and r['stats_ym'] == latest_ym),
            key=lambda x: x.get('median_price_per_py') or 0, default=None,
        )
        out.append({
            'sgg_cd': sgg_cd, 'sgg_nm': None, 'stats_ym': latest_ym,
            'median_price_per_py': round(latest_avg, 0) if latest_avg else None,
            'change_pct_3m': change_pct, 'trade_count': latest['trade_count'],
            'top_stdg_cd': top_stdg['stdg_cd'] if top_stdg else None,
            'top_stdg_nm': top_stdg.get('stdg_nm') if top_stdg else None,
        })
    return out


@router.get('/stdg-detail')
def get_stdg_detail(stdg_cd: str = Query(...), ym: str = Query(default='')):
    """법정동 단일 + 12M 시계열 + 단지 TOP 10 + 시군구 시그널 통합."""
    target_ym = ym or _default_ym()
    summary = fetch_region_by_stdg_cd(stdg_cd, target_ym)
    timeseries = fetch_region_timeseries_by_stdg(stdg_cd, months=12)
    complexes = fetch_complex_summary_by_stdg(stdg_cd, target_ym, top=10)
    change_pct_3m = None; trade_count_3m = None
    if len(timeseries) >= 2:
        latest = timeseries[-1]
        prev_idx = max(0, len(timeseries) - 4)
        prev = timeseries[prev_idx]
        if latest.get('median_price_per_py') and prev.get('median_price_per_py') and prev_idx != len(timeseries)-1:
            change_pct_3m = round((latest['median_price_per_py'] / prev['median_price_per_py'] - 1) * 100, 2)
        trade_count_3m = sum(p.get('trade_count') or 0 for p in timeseries[-3:])
    jeonse_rate = None
    if summary and summary.get('avg_deposit') and summary.get('avg_price'):
        jeonse_rate = round(summary['avg_deposit'] / summary['avg_price'], 4)
    sgg_cd = summary['sgg_cd'] if summary else stdg_cd[:5]
    signal = fetch_buy_signal(sgg_cd, target_ym)
    migration = fetch_region_migration(sgg_cd)
    net_flow = None
    if migration:
        latest_mig = next((m for m in reversed(migration) if m['stats_ym'] <= target_ym), None)
        net_flow = latest_mig.get('net_flow') if latest_mig else None
    return {
        'summary': {**(summary or {}), 'change_pct_3m': change_pct_3m,
                    'trade_count_3m': trade_count_3m, 'jeonse_rate': jeonse_rate,
                    'net_flow': net_flow} if summary else None,
        'timeseries': timeseries, 'complexes': complexes,
        'signal': signal or None,
    }


# ──────────────────────────────────────────────────────────
# frontend-realestate/src/lib/color.ts — 폴리곤·배지 공용
# ──────────────────────────────────────────────────────────

export function changePctColor(pct: number | null | undefined): string {
  if (pct == null) return "#374151";
  if (pct >= 5) return "#dc2626";
  if (pct >= 1) return "#f87171";
  if (pct >= -1) return "#9ca3af";
  if (pct >= -5) return "#60a5fa";
  return "#2563eb";
}


# ──────────────────────────────────────────────────────────
# frontend-realestate/src/components/KakaoMap.tsx — Polygon 지원
# ──────────────────────────────────────────────────────────

useEffect(() => {
  const map = mapRef.current;
  if (!ready || !map || !window.kakao || !polygons || polygons.length === 0) return;
  const { kakao } = window;
  const created: any[] = [];
  polygons.forEach((poly) => {
    poly.paths.forEach((ring) => {
      const path = ring.map((p) => new kakao.maps.LatLng(p.lat, p.lng));
      const kpoly = new kakao.maps.Polygon({
        map, path,
        fillColor: poly.fillColor, fillOpacity: 0.45,
        strokeWeight: 1, strokeColor: "#111827", strokeOpacity: 0.8,
      });
      kakao.maps.event.addListener(kpoly, "click", () => onPolygonClick?.(poly.sggCd));
      kakao.maps.event.addListener(kpoly, "mouseover", () => kpoly.setOptions({ fillOpacity: 0.65 }));
      kakao.maps.event.addListener(kpoly, "mouseout", () => kpoly.setOptions({ fillOpacity: 0.45 }));
      created.push(kpoly);
    });
  });
  return () => { created.forEach((p) => p.setMap?.(null)); };
}, [polygons, onPolygonClick, ready]);


# ──────────────────────────────────────────────────────────
# frontend-realestate/src/screens/MapScreen.tsx — name 매핑 + polygon 변환
# ──────────────────────────────────────────────────────────

const SGG_NAME_TO_CD: Record<string, string> = {
  종로구: "11110", 중구: "11140", 용산구: "11170", 성동구: "11200", 광진구: "11215",
  동대문구: "11230", 중랑구: "11260", 성북구: "11290", 강북구: "11305", 도봉구: "11320",
  노원구: "11350", 은평구: "11380", 서대문구: "11410", 마포구: "11440", 양천구: "11470",
  강서구: "11500", 구로구: "11530", 금천구: "11545", 영등포구: "11560", 동작구: "11590",
  관악구: "11620", 서초구: "11650", 강남구: "11680", 송파구: "11710", 강동구: "11740",
};

async function loadPolygons(overviews: Map<string, SggOverview>): Promise<PolygonFeature[]> {
  const res = await fetch("/static/realestate/geojson/seoul-sgg.geojson");
  const geo = await res.json();
  const polys: PolygonFeature[] = [];
  for (const feat of geo.features ?? []) {
    const name = feat.properties?.name as string | undefined;
    if (!name) continue;
    const sggCd = SGG_NAME_TO_CD[name];
    if (!sggCd) continue;
    const ov = overviews.get(sggCd);
    const change = ov?.change_pct_3m ?? null;
    const fillColor = changePctColor(change);
    const geom = feat.geometry;
    const rings: { lat: number; lng: number }[][] = [];
    if (geom.type === "MultiPolygon") {
      for (const poly of geom.coordinates) {
        for (const ring of poly) {
          rings.push(ring.map(([lng, lat]: [number, number]) => ({ lat, lng })));
        }
      }
    } else if (geom.type === "Polygon") {
      for (const ring of geom.coordinates) {
        rings.push(ring.map(([lng, lat]: [number, number]) => ({ lat, lng })));
      }
    }
    polys.push({ sggCd, name, paths: rings, fillColor, changePct: change });
  }
  return polys;
}


# ──────────────────────────────────────────────────────────
# frontend-realestate/src/components/BottomBar.tsx — 슬라이드 인 + 탭
# ──────────────────────────────────────────────────────────

<div
  className={`absolute left-0 right-0 z-20
              bottom-[calc(64px+env(safe-area-inset-bottom))]
              px-3 transition-transform duration-300
              ${visible ? "translate-y-0" : "translate-y-[150%]"}`}
>
  <button
    disabled={disabled}
    onClick={() => selected?.topStdgCd && onTap(selected.topStdgCd)}
    className="w-full bg-gray-900/95 backdrop-blur-md ring-1 ring-gray-700
               rounded-2xl shadow-xl px-4 py-3 flex items-center gap-3"
  >
    {selected?.sggNm} · {selected?.topStdgNm} · 평단가 {formatPriceMan(...)} · 변화율 배지
  </button>
</div>


# ══════════════════════════════════════════════════════════
# [23] 2026-04-26 (UTC) — 단지 비교(나란히 보기) 기능
# ══════════════════════════════════════════════════════════
#
# [개요]
#   StdgDetailScreen 의 단지 리스트에서 2~4개 단지를 체크 → 비교 화면으로
#   이동해 평단가·거래량·전세가율 시계열을 overlay 라인 차트로 한눈에 비교.
#
# [신규 파일]
#   frontend-realestate/src/components/MultiSeriesChart.tsx
#     - 2~4개 시리즈 SVG overlay 라인 차트
#     - X축: 모든 시리즈 ym 합집합, Y축: 모든 value 합집합 정규화
#     - 범례 + 시리즈별 최근 값 표기
#
#   frontend-realestate/src/screens/ComplexCompareScreen.tsx
#     - /compare?seqs=A,B&sgg=11680 라우트 핸들러
#     - 상단 단지 카드(시리즈 색 + 단지명·연식, 클릭 시 ComplexDetail)
#     - 평단가/거래량/전세가율 3종 MultiSeriesChart
#
# [수정 파일]
#   database/repositories.py
#     - fetch_complex_compare(apt_seqs, months=12) 추가
#       매매 raw + 전세 raw(monthly_rent=0)를 apt_seq+deal_ym groupby
#       전세가율 = avg(전세 보증금) / avg(매매 거래금액)
#       모든 ym 채워서 반환 (거래 없으면 null)
#
#   api/routers/real_estate.py
#     - GET /complex-compare?apt_seqs=A,B&months= (최대 4개)
#     - imports: fetch_complex_compare 추가
#
#   frontend-realestate/src/types/api.ts
#     - ComplexComparePoint, ComplexCompareItem 인터페이스
#
#   frontend-realestate/src/api/endpoints.ts
#     - complexCompare(aptSeqs, months?) 추가
#
#   frontend-realestate/src/App.tsx
#     - <Route path="/compare" element={<ComplexCompareScreen />} /> 추가
#
#   frontend-realestate/src/screens/StdgDetailScreen.tsx
#     - compareMode state + picked Set<apt_seq>
#     - "비교" 토글 버튼(파란/회색)
#     - 비교 모드일 때 단지 카드 클릭 = 체크 토글, 아니면 기존대로 단지 상세
#     - 선택 카드 시각 강조 (파란 ring + ✓ 체크)
#     - 2개 이상 선택 시 하단 플로팅 "N개 단지 비교 →" 버튼 노출
#
# [Verification]
#   - curl '/api/realestate/complex-compare?apt_seqs=11680-4474,11680-4394&months=12'
#     한라비발디 9,152만/평 53.2% vs 래미안대치팰리스 15,755만/평 38.9% (202603 기준)
#   - 브라우저: /stdg/1168010600 → "비교" 클릭 → 단지 2개 체크 → 플로팅 버튼 → /compare
#
# ──────────────────────────────────────────────────────────
# database/repositories.py — fetch_complex_compare
# ──────────────────────────────────────────────────────────

def fetch_complex_compare(apt_seqs: list[str], months: int = 12) -> list[dict]:
    from statistics import median
    from collections import defaultdict
    from datetime import date, timedelta
    if not apt_seqs:
        return []
    client = get_client()
    today = date.today()
    cur = today.replace(day=1) - timedelta(days=1)
    yms = []
    for _ in range(months):
        yms.append(cur.strftime("%Y%m"))
        cur = cur.replace(day=1) - timedelta(days=1)
    yms.reverse()

    trade_resp = (
        client.table("real_estate_trade_raw")
        .select("apt_seq,apt_nm,build_year,sgg_cd,umd_nm,deal_ym,deal_amount,exclu_use_ar")
        .in_("apt_seq", apt_seqs).in_("deal_ym", yms).execute()
    )
    trade_buckets = defaultdict(list); sale_amount_buckets = defaultdict(list); meta = {}
    for r in trade_resp.data:
        seq = r["apt_seq"]; ym = r["deal_ym"]
        ar = r.get("exclu_use_ar") or 0; amt = r.get("deal_amount") or 0
        if not seq or not ym or ar <= 0 or amt <= 0: continue
        trade_buckets[(seq, ym)].append(amt / (ar / 3.305785))
        sale_amount_buckets[(seq, ym)].append(amt)
        meta.setdefault(seq, {"apt_nm": r.get("apt_nm"), "build_year": r.get("build_year"),
                              "sgg_cd": r.get("sgg_cd"), "umd_nm": r.get("umd_nm")})

    rent_resp = (
        client.table("real_estate_rent_raw")
        .select("apt_seq,deal_ym,deposit,monthly_rent")
        .in_("apt_seq", apt_seqs).in_("deal_ym", yms).eq("monthly_rent", 0).execute()
    )
    jeonse_buckets = defaultdict(list)
    for r in rent_resp.data:
        seq = r.get("apt_seq"); ym = r.get("deal_ym"); dep = r.get("deposit") or 0
        if seq and ym and dep > 0:
            jeonse_buckets[(seq, ym)].append(dep)

    out = []
    for seq in apt_seqs:
        m = meta.get(seq, {})
        ts = []
        for ym in yms:
            prices = trade_buckets.get((seq, ym), [])
            sales = sale_amount_buckets.get((seq, ym), [])
            jeonses = jeonse_buckets.get((seq, ym), [])
            avg_sale = (sum(sales)/len(sales)) if sales else None
            avg_jeonse = (sum(jeonses)/len(jeonses)) if jeonses else None
            jeonse_rate = (avg_jeonse / avg_sale) if (avg_jeonse and avg_sale) else None
            ts.append({
                "ym": ym,
                "median_price_per_py": round(median(prices), 0) if prices else None,
                "trade_count": len(prices),
                "avg_sale": round(avg_sale, 0) if avg_sale else None,
                "avg_jeonse": round(avg_jeonse, 0) if avg_jeonse else None,
                "jeonse_rate": round(jeonse_rate, 4) if jeonse_rate else None,
            })
        out.append({
            "apt_seq": seq, "apt_nm": m.get("apt_nm"), "build_year": m.get("build_year"),
            "sgg_cd": m.get("sgg_cd"), "umd_nm": m.get("umd_nm"), "timeseries": ts,
        })
    return out


# ──────────────────────────────────────────────────────────
# api/routers/real_estate.py — /complex-compare
# ──────────────────────────────────────────────────────────

@router.get('/complex-compare')
def get_complex_compare(
    apt_seqs: str = Query(..., description='apt_seq 콤마구분 (최대 4개)'),
    months: int = Query(default=12, description='최근 N개월'),
):
    seqs = [s.strip() for s in apt_seqs.split(',') if s.strip()][:4]
    return fetch_complex_compare(seqs, months=months)


# ──────────────────────────────────────────────────────────
# StdgDetailScreen.tsx — 비교 모드 토글 + 체크 + 플로팅 버튼
# ──────────────────────────────────────────────────────────

const [compareMode, setCompareMode] = useState(false);
const [picked, setPicked] = useState<Set<string>>(new Set());

function togglePick(seq: string) {
  setPicked((prev) => {
    const next = new Set(prev);
    if (next.has(seq)) next.delete(seq);
    else if (next.size < 4) next.add(seq);
    return next;
  });
}

function startCompare() {
  if (picked.size < 2) return;
  navigate(`/compare?seqs=${Array.from(picked).join(",")}&sgg=${data?.summary?.sgg_cd ?? ""}`);
}

// 카드 클릭: compareMode 면 체크 토글, 아니면 단지 상세
// 비교 모드 + picked >= 2 일 때 fixed 플로팅 버튼 노출


# ══════════════════════════════════════════════════════════
# [24] 2026-04-26 (UTC) — Passive 홈 화면 + 섹터 밸류·모멘텀 신기능
# ══════════════════════════════════════════════════════════
#
# [개요]
#   /stocks 화면에 모바일 카드 그리드 형식 홈 뷰 추가:
#     상단 5 지수 미니카드(BND/DIA/IWM/QQQ/SOXX) +
#     큰 AI 종합판단 카드 + 8개 탐색 타일 (2x4 그리드)
#   타일 클릭 → 기존 5 탭 콘텐츠로 이동 (홈 숨김 + back-to-home 버튼).
#   섹터밸류·섹터모멘텀 2개 NEW 타일은 풀스크린 모달 표시.
#
#   부동산 영역(/realestate, frontend-realestate, real_estate router) 일체 미터치.
#
# [신규 파일]
#   collector/sector_valuation.py
#     - SECTOR_VALUATION_ETFS 11개 (XLK·XLF·XLE·XLV·XLY·XLI·XLB·XLU·XLRE·XLC·XLP)
#     - fetch_sector_valuations(today): yfinance.Ticker.info 의
#       trailingPE/priceToBook 추출. None 안전 처리.
#
#   processor/feature7_sector_momentum.py
#     - compute_sector_momentum(): index_price_raw 일별 종가 → 월말 종가 → 1M·3M·6M 누적수익률
#     - sector_cycle_result.phase_sector_perf JSON 의 현재 phase 평균 수익률 → expected_rank
#     - rank_diff = expected_rank - current_rank (+ 언더퍼폼, − 오버퍼폼)
#
#   static/css/home.css
#     - 홈 뷰 전용 (5 지수 카드, AI 카드, 8 타일 그리드, 모달, 섹터 테이블/히트맵)
#
#   static/js/home.js
#     - showHome/showTab/showModal 라우터
#     - loadIndexCards: /api/index/latest → 5 ticker 슬라이스
#     - loadAiCard: /api/market-summary/ai-summary → 첫 2 줄
#     - loadSectorValuation: /api/sector-cycle/valuation → CSS grid heatmap (z-score 색)
#     - loadSectorMomentum: /api/sector-cycle/momentum → HTML 테이블 + 칩 색
#
# [수정 파일]
#   supabase_tables.sql
#     - sector_valuation 테이블 추가 (date+ticker UNIQUE, PER/PBR/current_phase/phase_name)
#
#   database/repositories.py
#     - upsert_sector_valuation(records)
#     - fetch_sector_valuation_latest() — 최신 date 의 11행
#
#   scheduler/job.py
#     - Step 6 의 cycle_result 변수 보존
#     - Step 6b 추가: fetch_sector_valuations + cycle_result 의 phase 정보 첨부 후 upsert
#
#   api/routers/sector_cycle.py
#     - GET /valuation: 11행 + per_z/pbr_z (mean/stdev z-score)
#     - GET /momentum: compute_sector_momentum() + 5분 캐시
#
#   templates/stocks.html
#     - head: Tailwind CDN + home.css 추가
#     - body: <section id="home-view"> 신규 (5 미니카드 + AI 카드 + 8 타일)
#     - back-to-home 플로팅 버튼 + sector 모달 2개
#     - <script src="home.js"> 추가
#
# [Verification]
#   - curl /api/sector-cycle/momentum → phase '둔화', XLK 1M +20.56%, expected_rank 11개
#   - GET /static/css/home.css = 200, /static/js/home.js = 200
#   - curl /stocks | grep home-view → 신규 마크업 노출
#   - 브라우저 /stocks: 홈 뷰 default → 타일 클릭 → 기존 탭 콘텐츠 → "← 홈" 복귀
#   - 섹터 타일 클릭 → 모달 열림, ESC/× 로 닫음
#
# [DDL 사용자 직접 실행 필요]
#   CREATE TABLE IF NOT EXISTS sector_valuation (
#       id BIGSERIAL PRIMARY KEY,
#       date DATE NOT NULL, ticker TEXT NOT NULL,
#       sector_name TEXT, per DOUBLE PRECISION, pbr DOUBLE PRECISION,
#       current_phase INTEGER, phase_name TEXT,
#       created_at TIMESTAMPTZ DEFAULT NOW(),
#       UNIQUE (date, ticker)
#   );
#   CREATE INDEX IF NOT EXISTS idx_sector_val_date ON sector_valuation (date DESC);
#
# ──────────────────────────────────────────────────────────
# collector/sector_valuation.py — 핵심
# ──────────────────────────────────────────────────────────

SECTOR_VALUATION_ETFS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLY": "Consumer Discretionary",
    "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication", "XLP": "Consumer Staples",
}

def fetch_sector_valuations(today):
    out = []
    for ticker, name in SECTOR_VALUATION_ETFS.items():
        try:
            info = yf.Ticker(ticker).info
        except Exception as e:
            print(f"[sector_valuation] {ticker} info 실패: {e}"); info = {}
        per = info.get("trailingPE"); pbr = info.get("priceToBook")
        out.append({
            "date": today.isoformat(), "ticker": ticker, "sector_name": name,
            "per": float(per) if per is not None else None,
            "pbr": float(pbr) if pbr is not None else None,
        })
    return out


# ──────────────────────────────────────────────────────────
# processor/feature7_sector_momentum.py — 핵심 로직
# ──────────────────────────────────────────────────────────

def compute_sector_momentum() -> dict:
    client = get_client()
    response = client.table("index_price_raw").select("date,ticker,close") \
        .in_("ticker", list(SECTOR_VALUATION_ETFS.keys())) \
        .order("date", desc=False).execute()
    by_ticker = {}
    for r in response.data:
        by_ticker.setdefault(r["ticker"], []).append((r["date"], r.get("close") or 0))
    month_close = {}
    for ticker, series in by_ticker.items():
        m = {}
        for d, c in series: m[d[:7]] = c  # YYYY-MM, ASC 라 마지막이 월말
        month_close[ticker] = [m[k] for k in sorted(m)]

    returns = {1: {}, 3: {}, 6: {}}
    for ticker, prices in month_close.items():
        for n in (1, 3, 6):
            if len(prices) >= n + 1:
                returns[n][ticker] = prices[-1] / prices[-n - 1] - 1

    current_rank = _rank_dict(returns[3])
    cycle = fetch_sector_cycle_latest()
    phase_name = cycle.get("phase_name") if cycle else None
    expected_rank = {}
    if cycle:
        ps = cycle.get("phase_sector_perf") or {}
        cur = ps.get(phase_name, {})
        filt = {t: v for t, v in cur.items() if t in SECTOR_VALUATION_ETFS}
        if filt: expected_rank = _rank_dict(filt)

    out = []
    for ticker, name in SECTOR_VALUATION_ETFS.items():
        cur, exp = current_rank.get(ticker), expected_rank.get(ticker)
        out.append({
            "ticker": ticker, "sector_name": name,
            "return_1m": round(returns[1].get(ticker) * 100, 2) if ticker in returns[1] else None,
            "return_3m": round(returns[3].get(ticker) * 100, 2) if ticker in returns[3] else None,
            "return_6m": round(returns[6].get(ticker) * 100, 2) if ticker in returns[6] else None,
            "current_rank": cur, "expected_rank": exp,
            "rank_diff": (exp - cur) if (cur and exp) else None,
        })
    out.sort(key=lambda x: x["return_3m"] if x["return_3m"] is not None else -999, reverse=True)
    return {"phase_name": phase_name, "as_of_date": date.today().isoformat(), "momentum": out}


# ──────────────────────────────────────────────────────────
# api/routers/sector_cycle.py — /valuation, /momentum
# ──────────────────────────────────────────────────────────

@router.get('/valuation')
def get_valuation():
    rows = fetch_sector_valuation_latest()
    if not rows: return {"phase_name": None, "valuations": []}
    pers = [r["per"] for r in rows if r.get("per") is not None]
    pbrs = [r["pbr"] for r in rows if r.get("pbr") is not None]
    per_mean = mean(pers) if pers else 0
    per_sd = stdev(pers) if len(pers) >= 2 else 1
    pbr_mean = mean(pbrs) if pbrs else 0
    pbr_sd = stdev(pbrs) if len(pbrs) >= 2 else 1
    out = [{
        "ticker": r["ticker"], "sector_name": r.get("sector_name"),
        "per": r.get("per"), "pbr": r.get("pbr"),
        "per_z": round((r["per"] - per_mean) / per_sd, 2) if (r.get("per") is not None and per_sd) else None,
        "pbr_z": round((r["pbr"] - pbr_mean) / pbr_sd, 2) if (r.get("pbr") is not None and pbr_sd) else None,
    } for r in rows]
    return {"phase_name": rows[0].get("phase_name"), "valuations": out}


@router.get('/momentum')
def get_momentum():
    now = time.time()
    if _momentum_cache["data"] and (now - _momentum_cache["ts"]) < 300:
        return _momentum_cache["data"]
    result = compute_sector_momentum()
    _momentum_cache.update({"data": result, "ts": now})
    return result


# ──────────────────────────────────────────────────────────
# scheduler/job.py — Step 6b
# ──────────────────────────────────────────────────────────

# Step 6b: 섹터 밸류에이션 (PER/PBR) — yfinance 11회 호출, full 모드만
print('\n[Step 6b] 섹터 밸류에이션 수집...')
try:
    from collector.sector_valuation import fetch_sector_valuations
    from database.repositories import upsert_sector_valuation
    val_records = fetch_sector_valuations(datetime.date.today())
    if cycle_result:
        for r in val_records:
            r['current_phase'] = cycle_result.get('phase_idx')
            r['phase_name'] = cycle_result.get('phase_name')
    upsert_sector_valuation(val_records)
except Exception as e:
    print(f'[Step 6b] 실패, 건너뜀: {e}')
    traceback.print_exc()


# ──────────────────────────────────────────────────────────
# templates/stocks.html — 홈 뷰 마크업 (요약)
# ──────────────────────────────────────────────────────────

<section id="home-view" class="home-wrap">
  <div id="home-indices" class="home-indices">
    <!-- 5 카드: BND/DIA/IWM/QQQ/SOXX -->
  </div>
  <div class="home-ai-card">
    <div id="home-ai-body"><!-- /api/market-summary/ai-summary --></div>
  </div>
  <div class="home-tiles">
    <button class="home-tile" data-tile="ai-chart">...</button>
    <button class="home-tile" data-tile="sector-val"><span class="ht-badge">NEW</span>...</button>
    <button class="home-tile" data-tile="sector-mom"><span class="ht-badge">NEW</span>...</button>
    ...
  </div>
</section>
<button id="back-to-home" class="back-to-home-btn" hidden>← 홈</button>
<div id="sector-val-modal" class="home-modal" hidden>...</div>
<div id="sector-mom-modal" class="home-modal" hidden>...</div>


# ──────────────────────────────────────────────────────────
# static/js/home.js — 라우터 핵심
# ──────────────────────────────────────────────────────────

const TILE_MAP = {
  'ai-chart': {action:'tab', idx:0},  'market': {action:'tab', idx:1},
  'fundamental': {action:'tab', idx:2}, 'signal': {action:'tab', idx:3},
  'macro': {action:'tab', idx:4},
  'sector-val': {action:'modal', id:'sector-val-modal'},
  'sector-mom': {action:'modal', id:'sector-mom-modal'},
};

function showTab(idx) {
  document.getElementById('home-view').style.display = 'none';
  document.querySelector('.tab-bar').style.display = '';
  document.querySelector('.scroll-wrap').style.display = '';
  document.getElementById('back-to-home').hidden = false;
  document.querySelector(`.tab[data-idx="${idx}"]`).click();  // 기존 main.js 핸들러 트리거


# ──────────────────────────────────────────────────────────
# [25] 2026-04-26 (UTC) — sector_valuation 테이블 미존재 시 500 에러 graceful 처리
# ──────────────────────────────────────────────────────────

# [문제]
# 섹터 밸류에이션 모달 → "로드 실패: SyntaxError: Unexpected token 'I', "Internal S"... is not valid JSON"
# /api/sector-cycle/valuation 이 HTTP 500 + plain text 응답 반환.
#
# [원인]
# Supabase 에 sector_valuation 테이블이 없음 (DDL 미실행 상태).
# postgrest 가 PGRST205 ('Could not find the table public.sector_valuation') 예외를 던지고
# FastAPI 가 그대로 500 으로 노출 → 프론트가 JSON.parse 실패.
#
# [수정 파일]
# database/repositories.py — fetch_sector_valuation_latest() 의 첫 SELECT 를 try/except 로 감싸
#                            테이블 없음 / postgrest 예외 시 빈 list 반환.

def fetch_sector_valuation_latest() -> list[dict]:
    """가장 최근 date 의 11개 섹터 밸류에이션 행. 테이블 미생성/빈 상태면 []."""
    client = get_client()
    try:
        last = (
            client.table("sector_valuation")
            .select("date").order("date", desc=True).limit(1).execute()
        )
    except Exception as e:
        print(f"[DB] sector_valuation 조회 실패 (테이블 없음 가능): {e}")
        return []
    if not last.data:
        return []
    target = last.data[0]["date"]
    response = client.table("sector_valuation").select("*").eq("date", target).execute()
    return response.data

# [효과]
# 테이블 미존재 → endpoint 가 200 + {phase_name:null, valuations:[]} 반환.
# home.js 가 이미 valuations.length === 0 분기를 가지고 있어 "데이터 미수집..." 메시지 정상 노출.
# DDL 실행 후 첫 full 사이클 (Step 6b) 가 11행 upsert 하면 자동으로 히트맵이 채워진다.
#
# [후속 조치 — 사용자 액션 필요]
# 1. supabase_tables.sql 의 sector_valuation DDL 을 Supabase SQL Editor 에서 실행
# 2. 다음 full pipeline 사이클 (또는 수동 호출) 후 데이터 채워짐

}


# ──────────────────────────────────────────────────────────
# [26] 2026-04-26 (UTC) — 홈 뷰 정렬 + 컨베이어 ticker 복원
# ──────────────────────────────────────────────────────────

# [문제]
# (a) 홈 뷰 컨텐츠가 viewport 왼쪽에 몰림 — body 의 max-width:480px+margin:0 auto
#     가 효과없는 환경 회피용으로 .home-wrap 에 position:fixed 를 줬는데 사용자
#     화면에서 여전히 가운데 정렬 안 보임.
# (b) 기존 탭 UI 의 5종 지수 conveyor (천천히 좌측으로 흐르는 ticker bar) 가
#     홈 뷰에서는 home.js showHome() 이 .feed-section 을 display:none 처리하면서
#     사라짐. 사용자는 conveyor 유지 원함.
# (c) home-view 의 정적 5 미니카드 (.home-indices) 와 conveyor 가 의미상 중복
#     (둘 다 BND/DIA/IWM/QQQ/SOXX 5종 표시).

# [해결 방향]
# 1. .home-indices 정적 카드 블록 + 관련 CSS 룰 + loadIndexCards() 제거
# 2. <section class="feed-section"> 을 home-view 직전으로 이동 — 홈/탭 양쪽에서
#    항상 위에 conveyor 노출
# 3. .home-wrap 의 position:fixed 제거 → flex:1 1 auto 로 자연 흐름 (body 의
#    flex column 안에서 자동으로 가운데 480px 폭)
# 4. showHome() 은 .scroll-wrap 만 숨기고 tab-bar / feed-section 은 그대로 유지
# 5. .tab 직접 클릭 시에도 home-view 자동으로 숨겨지도록 hook 추가
#    (main.js switchTab 은 home-view 존재를 모르므로)

# [수정 파일]
# templates/stocks.html — home-indices 블록 삭제, feed-section 위치 이동, ?v=4
# static/css/home.css — .home-wrap position:fixed 제거 + 자연 흐름, .home-indices/hi-* 룰 삭제
# static/js/home.js — loadIndexCards 제거, loadFeed() 호출, showHome/showTab 단순화, .tab click hook

# [핵심 코드 차이]
# templates/stocks.html
<!-- 기존 .home-indices 5 카드 블록 → 통째로 삭제 -->
<!-- feed-section 을 home-view 위로 이동 -->
<section class="feed-section">
  <div id="feed-list" class="feed-list"></div>
</section>
<section id="home-view" class="home-wrap">
  <!-- AI 카드 + 8 타일 그리드 -->
</section>

# static/css/home.css
.home-wrap {
  flex: 1 1 auto;        /* body 의 flex column 안에서 남은 공간 차지 */
  overflow-y: auto;
  padding: 12px 12px 80px;
  width: 100%;
}

# static/js/home.js
function showHome() {
  document.getElementById('home-view').style.display = '';
  document.querySelector('.scroll-wrap').style.display = 'none';
  document.getElementById('back-to-home').hidden = true;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
}
// init() 에서:
if (typeof window.loadFeed === 'function') window.loadFeed();
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.getElementById('home-view').style.display = 'none';
    document.querySelector('.scroll-wrap').style.display = '';
    document.getElementById('back-to-home').hidden = false;
  });
});

# [효과]
# - 홈 뷰: body 의 480px 컬럼 안에서 정상 가운데 정렬
# - 헤더 (Passive 로고 + 테마/EN/⚙️) → 탭 바 → conveyor → AI 카드 → 8 타일 순으로 자연 stack
# - conveyor 는 홈/탭 모두에서 9px/sec 로 좌측 흐름 (main.js setupTickerDrift)
# - 타일 클릭 → 홈 숨김 + 해당 탭 activate
# - 탭 바 직접 클릭 → 홈 숨김 + 해당 탭 활성 (자연스러운 1차 네비)


# ──────────────────────────────────────────────────────────
# [27] 2026-04-26 (UTC) — Tailwind CDN 제거 (preflight 부작용) + sector_valuation 초도 시드
# ──────────────────────────────────────────────────────────

# [문제 1] 홈 뷰가 [26] 의 fix 후에도 여전히 viewport 좌측에 붙어있음.
# [원인]  templates/stocks.html 가 main.css 다음에 Tailwind CDN 을 로드 →
#          Tailwind preflight 의 `body { margin: 0 }` 가 main.css 의
#          `body { margin: 0 auto }` 를 덮어써서 body 의 가운데 정렬 무력화.
# [확인]  grep 결과 stocks.html 안에 Tailwind utility (grid-cols-N, flex,
#          gap-N, p-N 등) 가 0개 → CDN 로드 자체가 의미 없음.

# [문제 2] 섹터 밸류 모달이 "데이터 미수집..." 메시지만 표시.
# [원인]  사용자가 DDL 은 실행했으나 Step 6b (full 스케줄러) 가 아직 안 돌아
#          sector_valuation 테이블이 비어있음.

# [수정 파일]
# templates/stocks.html — Tailwind <script> 제거, home.css ?v=5 로 캐시 무효화
# (DB) Supabase sector_valuation 테이블에 11 행 초도 시드 — 일회성 스크립트:
#      from datetime import date
#      from collector.sector_valuation import fetch_sector_valuations
#      from database.repositories import upsert_sector_valuation, fetch_sector_cycle_latest
#      recs = fetch_sector_valuations(date.today())
#      cyc  = fetch_sector_cycle_latest()
#      for r in recs:
#          r['current_phase'] = cyc.get('phase_idx') if cyc else None
#          r['phase_name']    = cyc.get('phase_name') if cyc else None
#      upsert_sector_valuation(recs)

# [효과]
# - 홈 뷰가 viewport 정중앙으로 정렬 (480px 컬럼)
# - /api/sector-cycle/valuation 가 11 행 + per_z/pbr_z 반환 → 모달에 PER/PBR 히트맵 표시
# - 다음 full 스케줄 사이클부터 자동 갱신 (Step 6b)


# ──────────────────────────────────────────────────────────
# [28] 2026-04-26 (UTC) — 섹터 모달 + back 버튼 모바일 폭 정렬 (앱 폼 일관성)
# ──────────────────────────────────────────────────────────

# [문제]
# 홈 뷰는 480px 컬럼으로 정렬됐지만 섹터 밸류/모멘텀 모달은 inset:0 (full viewport)
# 으로 떠서 desktop 에서 좌우 끝까지 늘어남. PER/PBR 칩이 우측에 외롭게 떨어져 보임.
# back-to-home 버튼도 left:14px (viewport 좌상단) 으로 480px 컬럼 밖에 떠있음.

# [수정 파일]
# static/css/home.css
#   - .home-modal: inset:0 → left:50% + translateX(-50%) + max-width:480px,
#                   box-shadow + clip-path 로 viewport 양옆에 어두운 backdrop 만 깔기
#   - .back-to-home-btn: left:14px → max(14px, calc(50% - 226px))
#     → wide viewport 에선 480px 컬럼 좌상단 안쪽, 모바일 (vw<480) 에선 14px 시작
# templates/stocks.html — home.css ?v=6

.home-modal {
  position: fixed;
  top: 0; bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100%;
  max-width: 480px;
  box-shadow: 0 0 0 100vmax rgba(0,0,0,0.6);
  clip-path: inset(0 -100vmax);
}

.back-to-home-btn {
  position: fixed;
  top: 14px;
  left: max(14px, calc(50% - 226px));
}

# [효과]
# - desktop 에서 모달이 480px 폭 가운데 정렬, 양옆은 backdrop dim
# - back-to-home 버튼이 480px 컬럼 좌상단에 정확히 위치
# - 모바일 (vw < 480px) 환경에선 자연스럽게 가장자리에 fit


# ──────────────────────────────────────────────────────────
# [29] 2026-04-26 (UTC) — 섹터 밸류 z-score 정의 변경 + IGV(소프트웨어) 추가
# ──────────────────────────────────────────────────────────

# [요구]
# 1. z-score 를 "오늘의 11개 ETF 평균 대비 표준편차" (cross-section) →
#    "각 ETF 의 자기 자신 historical 평균 대비 표준편차" (temporal per-ticker) 로 변경.
#    이유: cross-section 은 섹터 간 절대 PER 차이만 반영 (Tech 가 항상 빨강, Financials 가
#    항상 파랑) → 의미 없음. 같은 ETF 의 시간 흐름 위에서 "지금 비싼지 / 싼지" 가 진짜 신호.
# 2. IGV (iShares Expanded Tech-Software, 소프트웨어 sub-sector) 추가 → 11 → 12 ETF.

# [수정 파일]
# collector/sector_valuation.py — SECTOR_VALUATION_ETFS 에 IGV: "Software" 추가
# database/repositories.py — fetch_sector_valuation_history(days=N) 신규 (모든 ticker
#                            의 N일치 (per, pbr) 시계열 한 번에 SELECT)
# api/routers/sector_cycle.py — get_valuation 재구현:
#   1. fetch_sector_valuation_latest() 로 오늘의 12 행
#   2. fetch_sector_valuation_history(days=365*5) 로 5년치 history 한 번에 가져와
#      ticker 별로 by_ticker_per[t] / by_ticker_pbr[t] 리스트 빌드
#   3. 각 ticker 의 historical mean/stdev 로 z = (today - μ) / σ 산출
#   4. 표본 < HIST_MIN_N(5) 이면 z=null 반환 (충분히 쌓이기 전엔 색칠 안 함)
#   5. 응답에 hist_min_n + hist_n (티커별 표본 수) 메타 필드 추가
# static/js/home.js — loadSectorValuation 에 "히스토리 누적 중 — 표본 N/5" 안내 추가
# templates/stocks.html — home.js ?v=3 캐시 갱신
# (DB) Supabase sector_valuation 테이블에 12 행 시드 (XLK + IGV 포함)

# [핵심 코드 — sector_cycle.py]
HIST_MIN_N = 5
rows    = fetch_sector_valuation_latest()                       # 오늘의 12 행
history = fetch_sector_valuation_history(days=365 * 5)          # 5년치
by_ticker_per: dict[str, list[float]] = defaultdict(list)
by_ticker_pbr: dict[str, list[float]] = defaultdict(list)
for h in history:
    if h.get("per") is not None: by_ticker_per[h["ticker"]].append(h["per"])
    if h.get("pbr") is not None: by_ticker_pbr[h["ticker"]].append(h["pbr"])

def z(x, samples):
    if x is None or len(samples) < HIST_MIN_N: return None
    m, s = mean(samples), stdev(samples) if len(samples) >= 2 else 0
    return round((x - m) / s, 2) if s else None

# [현재 상태]
# 시드 첫날이라 시계열 = 1점 → 모든 z=null → 모달에 회색 칩 + "표본 1/5" 안내.
# 매일 Step 6b 가 누적하면 5일째부터 z 산출 시작.
# 향후 backfill 옵션: yfinance 분기별 financials 로 추정 시계열 만들기 (현재는 미구현 — 정확도 떨어짐).


# ──────────────────────────────────────────────────────────
# [30] 2026-04-26 (UTC) — sector_valuation 5년 historical backfill (가격 proxy)
# ──────────────────────────────────────────────────────────

# [요구]
# [29] 의 한계 (시드 1점 → 모든 z=null) 즉시 해소. 5년치 historical 시계열 확보.

# [선택한 방법 — 가격 비율 proxy]
# yfinance 는 ETF 의 historical PER/PBR 을 제공하지 않음 (Ticker.info = today only).
# 가장 단순하고 즉시 실행 가능한 추정:
#     PER_t ≈ PER_today × (Close_t / Close_today)
#     PBR_t ≈ PBR_today × (Close_t / Close_today)
# 가정: EPS / BVPS 가 5년 윈도우 내 비교적 안정적 (= 실제로는 이 가정이 깨지는데
# z-score 신호 ("오늘이 historical 평균 대비 비싼가/싼가") 에는 충분).

# [신규 파일]
# processor/sector_valuation_backfill.py
#   - SECTOR_VALUATION_ETFS 12 ETF 순회
#   - yfinance Ticker.history(period="5y", interval="1mo") → 60개월 종가
#   - close_today 로 각 row 의 close_t 비율 계산 → PER/PBR 시계열
#   - 청크 200 행씩 upsert_sector_valuation 호출
#   - 월별 60점 + 오늘 1점 = 61점/티커 → 12 × 61 = 720 행

# [실행 결과]
# 720 행 upsert 완료. 모든 z 가 +1.27 ~ +2.34 사이 양수
# (5년 가격 꾸준히 상승 → 오늘이 historical 평균 위) → 강도 차이만 있음.

# [알려진 한계 — 사용자 안내 필요]
# PER 과 PBR 시계열이 같은 가격 비율을 곱한 결과라 동일 시계열 → z-score 도 동일.
# 즉 모달에서 PER 칩과 PBR 칩 색이 같음. 이를 해결하려면:
#   (a) 그대로 두고 안내 (PER 만 의미 있음, PBR redundant)
#   (b) PBR 칩 제거하고 "valuation z-score" 단일 칩으로 변경
#   (c) 외부 historical 데이터 소스 도입 (macrotrends 스크래핑 등) — 안정성/ToS 부담

# [향후 매일 갱신]
# Step 6b (full 사이클) 가 매일 1행씩 추가 → 시계열 자연 누적.
# backfill 은 일회성 — 다시 실행하면 같은 (date, ticker) 가 ON CONFLICT 로 갱신됨.


# ──────────────────────────────────────────────────────────
# [31] 2026-04-26 (UTC) — sector_valuation FMP→yfinance fallback backfill
# ──────────────────────────────────────────────────────────

# [요구]
# [30] 의 가격 proxy 가 EPS 변화 무시 → 모든 z 가 양수 (전부 빨강) → 의미 없음.
# 실제 EPS / BVPS 가 반영된 historical PE/PB 시계열 필요.

# [시도 1: FMP API]
# 사용자가 FMP_API_KEY 발급 → .env 추가.
# 무료 tier 한계:
#   - ETF symbol 직접 조회 불가 (premium endpoint)
#   - 분기별 (period=quarter) 불가, annual 만
#   - 일일 한도 도달 빠름 (large-cap 인기 종목만 통과)
# 결과: 12 ETF 중 5개만 backfill 성공 (XLK, XLF, XLE, XLY, XLC), 나머지 7개 402/429.
#
# 신규 파일: processor/sector_valuation_fmp_backfill.py — partial 실패로 폐기.

# [시도 2: yfinance only — 채택]
# yfinance Ticker(stock).income_stmt + balance_sheet → annual EPS, Equity, Shares.
# yfinance Ticker(stock).history → 거래일 종가.
# 각 holding 의 fiscal_year 별:
#       PE = Close@year_end / Diluted_EPS,
#       PB = Close@year_end / (Equity/Shares)
# top10 가중평균 → ETF 의 historical PE/PB.
#
# 신규 파일: processor/sector_valuation_yf_backfill.py
# 결과: 12/12 ETF × 4점 (yfinance income_stmt 가 일반적으로 4년치 annual) +
#       오늘 1점 = 5점/티커 → HIST_MIN_N=5 임계 정확히 통과 → z-score 산출.

# [확인된 z-score 분포 (오늘 = 2026-04-26)]
#   per_z: -1.63 (XLRE) ~ +1.27 (XLE)  → 색 다양
#   pbr_z: -1.77 ~ -0.90              → 대부분 음수 (시계열 4년 짧음 + top10 weight 한계)

# [한계]
# - 5년간 holdings 변화 무시 (today's top10 weight 고정)
# - top10 ≈ ETF 자산 50-70% 만 커버
# - yfinance income_stmt 가 4년치 annual 만 → stdev 노이즈 큼
# 더 정확하게 가려면 FMP starter ($14/mo) 또는 EOD historical data 유료 가입 필요.

# [폐기 코드]
# processor/sector_valuation_backfill.py (가격 proxy) — 이제 안 씀 (비활성)
# processor/sector_valuation_fmp_backfill.py — FMP free 한계로 폐기, 유료 가입 시 부활


# ──────────────────────────────────────────────────────────
# [32] 2026-04-27 (UTC) — siblis research 분기별 CAPE/PB 스크래핑으로 교체
# ──────────────────────────────────────────────────────────

# [요구]
# [31] 의 yfinance 가중평균 backfill 한계:
#   - 가중평균 PE 가 정통 ETF PE 정의 아님 (실제는 harmonic-mean)
#   - top10 만 ≈ ETF 자산 50-70% 만 커버
#   - 시계열 4점, stdev 노이즈 큼
# 더 honest 한 무료 sector-level historical valuation 소스 필요.

# [점검한 무료 소스 — 모두 실패]
#   yfinance/yahoo: today only (statistics 페이지)
#   gurufocus: 403, macrotrends: 402, zacks: bot 차단, wsj: 차단
#   multpl.com: broad market (S&P 500) only — sector 별 X
#   SSGA 운용사: 분기별 fact sheet archive 미노출
#   FMP free: ETF symbol 직접 X + large-cap 인기 종목만 통과 → 5/12 partial 실패

# [siblis research — 채택]
# https://siblisresearch.com/data/cape-ratios-by-sector/      (CAPE)
# https://siblisresearch.com/data/price-to-book-sector/       (P/B)
# 11개 GICS 섹터 분기별 시계열 (CAPE 6점, P/B 7점) 무료 페이지 노출 →
# requests + BeautifulSoup 으로 직접 스크래핑.

# [신규 파일]
# processor/sector_valuation_siblis_backfill.py
#   - SECTOR_TO_ETFS = {"Information Technology": ["XLK", "IGV"], ...} 11→12 매핑
#     (IGV = Software 는 IT 의 sub-sector → IT 시계열 공유)
#   - parse_siblis_table: <table> 첫 번째 → {sector: {date_str: value}}
#   - normalize_date: '12/31/2025' → '2025-12-31'
#   - per 컬럼에 CAPE 저장, pbr 컬럼에 P/B 저장 (스키마 그대로)
# scheduler/job.py Step 6b 교체:
#   - 기존 yfinance trailingPE/priceToBook 시드 제거
#   - backfill_siblis() 호출 (idempotent — date+ticker UNIQUE)

# [모달 라벨 변경]
# static/js/home.js 의 .sv-h "PER"/"PBR" → "CAPE"/"P/B"
# templates/stocks.html 모달 헤더 "(PER · PBR)" → "(CAPE · P/B)"
#                       타일 sub "PER·PBR 히트맵" → "CAPE·P/B 히트맵"
# home.js 출처 라인: "출처: siblis research. as of {date}. CAPE = Shiller 10년 평균 PE."

# [실행 결과 — 12 ETF 모두 6점 시계열, z-score 분산]
#   cape_z 범위:  -0.95 (XLE) ~ +1.35 (XLI) — Energy 만 음수, 나머지 비쌈
#   pb_z   범위:  -1.00 (XLE) ~ +1.28 (XLC) — XLE 와 XLB 만 음수
# as_of_date: 2025-12-31 (siblis 가장 최근 분기)
# 차기 분기 (2026-06-30) 까지 stale — Step 6b 가 매일 호출해도 변동 없음.

# [한계]
# - CAPE 는 trailing PE 가 아닌 Shiller 10년 평균 PE (분모가 cyclically-adjusted EPS)
#   → 가격 변동에 덜 민감 + 더 안정적 → 다른 metric 임을 라벨로 명시
# - 분기별이라 intra-quarter 가격 변동 무반영 (2026 Q1, Q2 동안 같은 값)
# - siblis 가 페이지 구조 바꾸면 스크래핑 깨짐 (분기 1번이라 수동 fix OK)


# ──────────────────────────────────────────────────────────
# [33] 2026-04-27 (UTC) — 섹터 펀더멘털 갭 metric 도입 (siblis 폐기)
# ──────────────────────────────────────────────────────────

# [요구]
# 펀더멘털 탭 (broad market) 의 fundamental_gap 정의를 그대로 12개 섹터 ETF 에
# 적용해서 sector level 의 단일 metric 산출.
# fundamental_gap = log(P_t/P_{t-12}) - log(EPS_t/EPS_{t-12})
#                 = 12개월 가격 성장률 - 12개월 EPS 성장률

# [신규 파일]
# processor/sector_fundamental_gap.py
#   - 각 ETF: yfinance Ticker.history(period='6y', interval='1mo') → 월말 종가 P
#   - 각 ETF top10 holdings: yfinance Ticker.income_stmt → annual Diluted EPS
#   - 가중평균 annual EPS → fiscal year 단위로 forward-fill 한 monthly EPS proxy
#   - fg = log(P).diff(12) - log(EPS).diff(12) → 28점 (5년 어치 monthly)

# [DB 스키마 재활용]
# sector_valuation 테이블의 `per` 컬럼에 fundamental_gap 값을 저장.
# `pbr` 컬럼은 NULL (단일 metric 만).
# router get_valuation 변경 없음 — z-score 산출이 기존 그대로 (per 시계열 → per_z).

# [UI 변경]
# templates/stocks.html
#   - 모달 헤더: "섹터 밸류에이션 (CAPE · P/B)" → "섹터 펀더멘털 갭"
#   - 타일 sub: "CAPE·P/B 히트맵" → "가격 vs EPS"
#   - 타일 title: "섹터 밸류" → "섹터 펀더멘털 갭"
#   - 타일 icon: 🔥 → 📐
#   - home.js ?v=5
# static/js/home.js loadSectorValuation
#   - PBR 칩 제거, 단일 칩만 표시 (.sv-grid grid-template-columns: 1fr auto)
#   - 칩 내용: per 값을 백분율로 ("+55.7%" / "-65.4%")
#   - colorByZ(per_z): 양수=빨강(비쌈), 음수=파랑(싸짐) 그대로
#   - 출처 라인: 정의 + "양수=가격이 EPS 보다 빨리 (비싸짐)" 안내

# [scheduler/job.py Step 6b]
# 기존 siblis backfill → sector_fundamental_gap.backfill_all() 로 교체.
# yfinance 만 호출 (외부 스크래핑 의존 X) → 안정성 ↑.

# [실행 결과 — 12 ETF × 28점, as_of=2026-04-01]
#   비싸짐 (z 양수, 빨강):
#     XLC Communication       +55.7%  z=+2.50  ← 가장 비쌈
#     XLB Materials           +40.5%  z=+1.98
#     XLE Energy              +51.1%  z=+1.77
#     XLU Utilities           +28.4%  z=+1.69
#     XLF Financials          +28.6%  z=+1.14
#   균형:
#     XLI Industrials          +0.8%  z=+0.54
#     XLP Consumer Staples     -1.5%  z=-0.23
#     XLK Technology           +6.1%  z=-0.55
#   싸짐 (z 음수, 파랑):
#     XLY Consumer Discret.   -65.4%  z=-0.73  ← 가장 큰 음수 갭
#     IGV Software            -36.4%  z=-1.22  (XLK 와 분리, Software 가 더 쌈)
#     XLRE Real Estate        -20.5%  z=-1.42
#     XLV Health Care         -40.4%  z=-2.27  ← historical 평균 대비 가장 쌈

# [한계]
# - top10 holdings ≈ ETF 자산 50-70% 만 커버 (작은 holdings 의 EPS 성장 미반영)
# - holdings 5년간 변화 무시 (today's weights 고정)
# - EPS 가 annual → monthly 는 fiscal year end 직후 step change → log(E).diff(12) 의
#   "0이 아닌 변화" 가 fiscal year end 에 몰림 → fundamental_gap 시계열에 step 노이즈
# - 그래도 [31]-[32] 보다 정확도 ↑ (직접 동일 metric, ETF 별 분리 시계열)

# [폐기]
# processor/sector_valuation_siblis_backfill.py — fundamental_gap 으로 대체, 폐기
# processor/sector_valuation_yf_backfill.py — [31] 가중평균 PE/PB, 폐기
# processor/sector_valuation_backfill.py (가격 proxy) — [30], 폐기
# collector/sector_valuation.py fetch_sector_valuations — Step 6b 에서 더 이상 호출 X


# ──────────────────────────────────────────────────────────
# [34] 2026-04-27 (UTC) — SOXX (반도체) 추가, 12 → 13 ETF
# ──────────────────────────────────────────────────────────

# collector/sector_valuation.py SECTOR_VALUATION_ETFS 에
#   "SOXX": "Semiconductors"  추가 (iShares Semiconductor ETF, PHLX 반도체).
# fundamental_gap backfill 재실행 → 13 × 28 = 364 행.
# SOXX latest FG = +106.0% (가격이 EPS 의 2배 속도) z=+1.0 (historical 변동
# 큰 섹터라 자기 평균 대비로는 평범).


# ──────────────────────────────────────────────────────────
# [35] 2026-04-27 (UTC) — 섹터 모멘텀: 누락 ETF 보강 + 1y backfill + 페이지네이션
# ──────────────────────────────────────────────────────────

# [문제]
# 섹터 모멘텀 모달에서:
#   - IGV / XLY / XLC 가 모두 빈 칸 (1M/3M/6M/순위 전부 -)
#   - 다른 섹터도 6M 빈 칸, 일부 3M 도 -

# [원인]
# (a) collector/index_price.py TICKERS 리스트에 IGV / XLY / XLC 누락
#     → index_price_raw 테이블에 0행
# (b) fetch_index_prices 가 매일 1점씩만 수집 → 서비스 시작 후 누적 51일
#     (3M = 4개월 필요, 6M = 7개월 필요 → 둘 다 부족)
# (c) processor/feature7_sector_momentum.py 의 SELECT 가 limit/range 없음
#     → Supabase 기본 1000행에서 잘림 (1y backfill 후 3433행 중 1000만 fetch)

# [수정]
# (a) collector/index_price.py TICKERS 에 'XLY', 'XLC', 'IGV' 추가
# (b) yfinance period='1y', interval='1d' 로 13 ETF × 251일 = 3263행 backfill
#     (스크립트 일회성 — index_price_raw upsert)
# (c) feature7_sector_momentum.py SELECT 페이지네이션:
#     while True: .range(offset, offset+999).execute() → 1000 미만이면 break

# [실행 결과]
# 13 ETF 모두 1M / 3M / 6M / current_rank 채워짐.
# 둔화 phase 기준 rank_diff:
#   XLE +8  (예상 10위 → 실제 2위, 크게 오버퍼폼)
#   XLF -5  (예상 5위 → 실제 10위, 언더퍼폼)
#   XLI -4, XLV -4
#   SOXX 1M +40.5% / 3M +33.3% / 6M +50.6% — 1위 차지

# [잔여 과제]
# XLY / XLC / IGV 의 expected_rank 만 빈 칸 — sector_cycle_result.phase_sector_perf
# 에 이 3개 ETF 가 historical 분석 대상에서 빠져있음. 다음 full cycle 에서
# sector_cycle 로직이 13 ETF 모두 포함하도록 별도 fix 필요.


# ──────────────────────────────────────────────────────────
# [36] 2026-04-27 (UTC) — 홈 뷰 디자인 리프레시 (모바일 앱 폼)
# ──────────────────────────────────────────────────────────

# [요구]
# 사용자 첨부 이미지 디자인을 최대한 그대로 적용:
#   - 타일 아이콘: 이모지 → 단색 line SVG (오렌지 틴트, 둥근 사각형 컨테이너)
#   - AI 카드: 큰 헤드라인 + 메타라인 (심리·간극·국면 점 구분자)
#   - NEW 배지: 오렌지 그라데이션 pill
# 컨베이어 ticker 는 유지.

# [수정 파일]
# templates/stocks.html
#   - 8개 .ht-icon 의 이모지 → inline <svg> (lucide-style line icons)
#     · ai-chart  : bar chart + 상승선
#     · market    : 하트비트 라인
#     · fundamental: 막대 4개 (descending)
#     · signal    : sine wave
#     · macro     : globe (원 + 경위선)
#     · sector-val: 우상향 화살표 라인
#     · sector-mom: 막대 3개 (ascending)
#     · more      : 가로 점 3개
#   - home.css ?v=7, home.js ?v=6
# static/css/home.css
#   - .ht-icon: 38x38 둥근 사각형 (border-radius:10), background rgba(orange,.12),
#               color #f59e0b, svg 22x22 stroke=currentColor
#   - .home-tile: padding/min-height 조정, hover border 오렌지 hint
#   - .home-ai-card: 위→아래 오렌지 글로우 그라데이션 + 더 진한 border + box-shadow
#   - .home-ai-meta .meta-item + .meta-item::before { 점 구분자 }
#   - .ht-badge: 오렌지 그라데이션 pill (#f59e0b → #ea580c) + glow shadow
# static/js/home.js loadAiCard
#   - body 에 첫 줄 헤드라인만 강조 표시 (60자 컷)
#   - 추가: /api/macro/fear-greed + /api/regime/current + /api/sector-cycle/current
#     병렬 fetch → home-ai-meta 에 "심리 탐욕 66 · 간극 +0.3 · 국면 둔화"

# [필드 매핑]
# fear-greed: score (수치) + rating (탐욕/공포)
# regime: noise_score (펀더멘털 vs 가격 간극)
# sector-cycle: phase_name (회복/확장/둔화/침체)


# ──────────────────────────────────────────────────────────
# [37] 2026-04-27 (UTC) — AI 메타라인: surge-crash gap → 상승/하락 신호
# ──────────────────────────────────────────────────────────

# [요구]
# 사용자: "심리 탐욕 / 간극 옆에 상승/하락 신호 붙여봐"
# 사용자 이미지의 "+7.6"은 noise_score 가 아닌 신호 탭의 surge-crash gap 이었음.

# [수정]
# api/routers/market_summary.py /today 응답에 crash_surge {crash, surge, gap} 추가.
# static/js/home.js 메타라인:
#   - "간극" (noise_score) 항목 제거
#   - "상승 신호 +7.6" (gap > 0, 초록) / "하락 신호 -3.2" (gap < 0, 빨강) 동적 라벨
#   - 메타라인: "심리 탐욕 66 · 상승 신호 +7.6 · 국면 둔화"


# ──────────────────────────────────────────────────────────
# [38] 2026-04-27 (UTC) — AI차트 빈 차트 fix + back 버튼 겹침 fix
# ──────────────────────────────────────────────────────────

# [문제 1]
# AI차트 타일 누르면 차트가 비어서 표시 ("차트를 터치하면..." 만 보임).
# [원인]
# 스플래시 시 home view 가 default 라 .scroll-wrap 이 display:none → 그 상태에서
# initChartTab() 실행되면 candle-chart 의 clientWidth=0 → SVG 가 0폭으로 그려짐.
# 그 뒤 탭 클릭으로 보이게 해도 _chartLoaded 가드로 재 init 안 됨.
# [수정]
# main.js: 스플래시 init 단계에서 home active 면 initChartTab 스킵 (가드 추가).
# home.js showTab(0): 60ms 뒤 loadCandleChart() 강제 호출 (이중 안전장치).

# [문제 2]
# 탭 진입 시 "← 홈" 버튼이 Passive 로고와 겹침 (둘 다 좌상단 fixed).
# [수정]
# home.js: showTab/showHome 에서 body.with-back 클래스 toggle.
# home.css: body.with-back .app-header > div:first-child { padding-left: 64px; }
# → 헤더 좌측 영역(날짜+로고)이 64px 우측으로 부드럽게 밀림.


# ──────────────────────────────────────────────────────────
# [39] 2026-04-27 (UTC) — 탭 바 영구 숨김 + 섹터 모달 → 일반 탭 페이지 변환
# ──────────────────────────────────────────────────────────

# [요구]
# 1. 상단 탭 바 (AI차트/시장/펀더멘털/신호/거시경제) 영구 숨김
# 2. 섹터 밸류/모멘텀: 모달 → 다른 탭과 동일 디자인의 페이지로 변환
# 네비는 홈 타일 클릭 + ← 홈 버튼만 사용 (모바일 앱 drill-down 패턴).

# [수정]
# templates/stocks.html
#   - sector-val-modal / sector-mom-modal 두 모달 div 제거
#   - .scroll-wrap 안에 새 main.content 두 개 추가:
#     <main class="content" id="tab-sector-val">  <h2>섹터 밸류에이션</h2> ...
#     <main class="content" id="tab-sector-mom">  <h2>섹터 모멘텀 랭킹</h2> ...
# static/css/home.css
#   - .tab-bar { display: none !important; }
#   - .page-title { font-size: 18px; font-weight: 800; ... }
# static/js/home.js
#   - TILE_MAP: sector-val/mom action 'modal' → 'sector-tab' (id 매핑)
#   - showSectorTab(id): .scroll-wrap > main.content 모두 hide → target 만 show
#   - 데이터 로드 + AI 해설 같이 호출
#   - showModal/closeModal 코드 제거


# ──────────────────────────────────────────────────────────
# [40] 2026-04-27 (UTC) — 섹터 밸류/모멘텀 AI 해설 + 잔재 hide fix + 이름 변경
# ──────────────────────────────────────────────────────────

# [(a) AI 해설 추가]
# 두 새 탭 페이지 하단에 #ai-explain-sector-val, #ai-explain-sector-mom 카드 추가.
# api/routers/market_summary.py:
#   - _EXPLAIN_PROMPTS 에 'sector-val' / 'sector-mom' (ko + en) 프롬프트 추가
#   - _build_explain_text 에 두 탭 case 추가:
#     · sector-val: get_valuation() 호출 → 비싸진/싸진 섹터 z-score 상하위 3개
#     · sector-mom: compute_sector_momentum() 호출 → 모멘텀 상위 3 + rank_diff
#       오버퍼폼/언더퍼폼 상위 2개
#   - get_ai_explain docstring 업데이트
# home.js: showSectorTab 에서 loadAiExplain('sector-val'/'sector-mom') 호출

# [(b) 다른 탭 진입 시 sector-val/mom 잔재 hide]
# home.js showTab(idx): main.js switchTab 이 TAB_IDS 5개만 토글 → sector-val/mom
# 은 모름 → sector 탭 진입 후 다른 탭 진입 시 화면 하단에 잔재. 명시적 hide 추가.

# [(c) 라벨 변경]
# "섹터 펀더멘털 갭" → "섹터 밸류에이션" (UI 라벨만, 내부 식별자 그대로):
#   - 타일 ht-title
#   - 페이지 h2 page-title


# ──────────────────────────────────────────────────────────
# [41] 2026-04-28 (UTC) — 30일 예측 모델 업그레이드: GJR-GARCH-Skew-t + FHS + fan chart
# ──────────────────────────────────────────────────────────

# [요구]
# 사용자가 AI차트 탭 30일 예측이 평탄하고 정확도 부족 + 변동성 부재 라고 보고. 노트북에서
# walk-forward backtest (10년, 매월 cutoff 119건) 검증 결과:
#   - 기존 production: hit rate 0.69 (그러나 specificity 0.0, 하락 사례 9/9 모두 놓침)
#   - 평탄 차트 원인: hard clipping 삼중 (daily_clip ±2.5~4%, price_band ±15~25%, 3일 MA)
#                   + scaled_ret * 3.0 증폭 + 단일 σ forecast (path 1개)
# 노트북 검증 후 plan stage 1+2+3+4 본 코드 적용 결정.

# [수정 파일 — 4개]
# 1. processor/feature4_chart_predict.py
#    - 새 함수 _garch_skewt_fhs_forecast() 추가 (line 200~)
#      · GJR-GARCH(1,1,1) + Skew-t (arch_model: o=1, dist='skewt')
#      · 1년 윈도우 (252일) — 5y 윈도우의 σ 부풀림 회피
#      · FHS Monte Carlo 1000 path (표준화 잔차 부트스트랩)
#      · hard clipping 모두 제거 (sanity_clip ±10% 만)
#      · 분위수 산출: p05/p10/p50/p90/p95 + sample_paths 30개 + metrics
#    - run_chart_predict_single 수정: _recursive_forecast → _garch_skewt_fhs_forecast
#    - DB 저장: chart_predict_result.predicted JSONB 안에
#               {forecast, sample_paths, metrics, predicted(legacy), metadata}
#               schema 변경 X
# 2. api/routers/chart.py
#    - _is_prediction_valid: dict 형식 (forecast/predicted) + legacy list 둘 다 인식
#    - /predict 응답: forecast/sample_paths/metrics/metadata 펴서 노출 + legacy predicted 유지
# 3. static/js/chart.js
#    - 4-layer fan chart SVG:
#      · Layer 1 (p50~p95): rgba(156,163,175,0.10) 옅은 회색 상한
#      · Layer 2 (p10~p50): rgba(59,130,246,0.13) 옅은 파랑 중립
#      · Layer 3 (p05~p10): rgba(239,68,68,0.32) **빨강 위험 zone (강조)**
#      · Median: rgba(156,163,175,0.7) 옅은 회색 점선 (mean bull-bias 강조 X)
#    - renderPredictLegend: metrics 박스 (기대 수익률 / 5% 확률 손실 / 10% 확률 손실
#                          / 상승 확률) + 색상 범례 + black swan disclaimer
#    - legacy 데이터 (DB 옛 row) 도 단일 밴드로 정상 작동 (하위 호환)
# 4. templates/stocks.html
#    - chart.js ?v=22 캐시 버스터

# [노트북 검증 결과 (forecast_gjr_garch_fhs_experiment.ipynb)]
#   - p05 coverage: 89 시점 평가에서 93.3% (이상 95% 거의 도달)
#   - p10 coverage: 91.0% (이상 90% 통과)
#   - prob_down_5pct 신호 약함 → 강조 X (mean 점예측 bull-bias 한계는 본질적)
#   - VaR 5% / VaR 10% / 분위수는 calibration OK → 강조 OK
#   - Stage 5 conformal calibration 시도 — 효과 거의 0 (이미 stage 1+2 calibration 통과)
#                                        + 복잡도만 증가 → production 적용 X

# [endpoint 응답 검증 (SPY)]
# top-level keys: ticker, actual, predicted (legacy), forecast, sample_paths, metrics, metadata
# forecast 30점, sample_paths 30 × 30
# metrics: expected_return_30d, var_5pct_30d, var_10pct_30d, prob_up_30d,
#          prob_down_5pct_30d, prob_down_10pct_30d
# metadata: model='XGB+CatBoost+RF+Ridge+SVR ensemble + GJR-GARCH(1,1,1)-SkewT + FHS'

# [핵심 코드 — _garch_skewt_fhs_forecast]
def _garch_skewt_fhs_forecast(models, close_history, n_days, feature_cols, ticker='SPY',
                                n_sims=1000, garch_window=252, sanity_clip=0.10):
    # 1) Mean path μ̂ — 5-모델 앙상블 recursive (hard clip 제거)
    # 2) GJR-GARCH(1,1,1) + Skew-t fit on 1년 윈도우
    am = arch_model(log_ret_window, vol='Garch', p=1, o=1, q=1, mean='Zero', dist='skewt')
    # 3) FHS Monte Carlo — 표준화 잔차 부트스트랩
    z = rng.choice(std_resid)
    eps_t = sqrt(max(var_t, 1e-9)) * z
    paths[s, h] = mu_path[h] + eps_t / 100.0
    # 4) 분위수 + metrics + sample_paths 직렬화

# [효과]
# - 평탄 차트 → fan chart (cone of uncertainty)
# - 단일 yhat 신뢰구간 → 4-layer fan + 빨강 위험 zone
# - mean 강조 X (bull-bias 한계 honest 표현) → 분위수 + VaR 강조
# - 30개 sample paths 그림자 — 'live' 한 모습

# [한계 인정 (UI에 disclaimer)]
# - Black swan event (코로나, 베어 시작) 사전 예측 불가
# - "정상 시장 분포 추정. 시장 충격 사전 예측 불가" 명시


# ──────────────────────────────────────────────────────────
# [42] 2026-04-28 (UTC) — Railway compute 최적화: chart 모델 학습/추론 분리 + 월 1회 cron
# ──────────────────────────────────────────────────────────

# [요구]
# 사용자가 Railway compute 비용 최소화 + 메모리 룰 (feedback_compute_minimization.md):
#   - 학습 빈도 ↓ (월 1회), 추론은 cache + lazy
#   - light 모델 우선, scheduler 분리, init_once DB 가드

# [현재 비용 구조 진단]
# - light_pipeline 10분 — 가벼움 (yfinance 가격만)
# - full_pipeline 3시간 — Step 8 chart_predict_all 16 ETF × 5모델 학습 (가장 무거움)
# - chart 모델 .pkl 저장 X → 매 3시간 재학습 = 하루 8회 × 16 ETF × 5모델 = 19,200/월
# - 학습/추론 비율: 학습 85-90%, 추론 10-15%

# [수정 파일]
# 1. processor/feature4_chart_predict.py
#    - import joblib, os 추가
#    - CHART_MODELS_DIR = models/chart_models/ 신규
#    - _save_chart_models(models, feature_cols, ticker) — joblib.dump bundle
#    - _load_chart_models(ticker) -> (models, feature_cols) or (None, None)
#    - run_chart_predict_single(ticker, train=False) — train 인자 추가
#       · train=True: 학습 + .pkl 저장 + 추론
#       · train=False: .pkl load → 추론만 (없으면 fallback 1회 학습 + 저장)
#    - run_chart_predict_all(train=False) — train default 추론
# 2. api/app.py
#    - apscheduler.triggers.cron.CronTrigger import
#    - _need_init_once(models_dir): HMM/crash_surge .pkl + chart_models 16개 .pkl
#      모두 존재할 때만 False (Stage 4 가드 강화)
#    - _train_chart_models_monthly(): 16 ETF × 5-모델 재학습 + .pkl 저장 + DB upsert
#    - scheduler.add_job(_train_chart_models_monthly, CronTrigger(day=1, hour=18, minute=0),
#                          id='train_chart_pipeline')  # UTC 18:00 = KST 03:00
# 3. scheduler/job.py
#    - Step 8: run_chart_predict_all() → run_chart_predict_all(train=False) (추론만)

# [핵심 코드]
# processor/feature4_chart_predict.py
def _save_chart_models(models, feature_cols, ticker):
    bundle = {'models': models, 'feature_cols': feature_cols,
              'trained_at': datetime.datetime.utcnow().isoformat()}
    joblib.dump(bundle, os.path.join(CHART_MODELS_DIR, f'{ticker}.pkl'))

def _load_chart_models(ticker):
    path = os.path.join(CHART_MODELS_DIR, f'{ticker}.pkl')
    if not os.path.exists(path): return None, None
    bundle = joblib.load(path)
    return bundle['models'], bundle['feature_cols']

def run_chart_predict_single(ticker, train=False):
    if train:
        models = _train_models(...); _save_chart_models(models, feat_cols, ticker)
    else:
        models, saved_cols = _load_chart_models(ticker)
        if models is None:
            models = _train_models(...); _save_chart_models(...)  # fallback
        else:
            feat_cols = saved_cols
    fc_result = _garch_skewt_fhs_forecast(models, close, 30, feat_cols, ticker=ticker)

# api/app.py scheduler
scheduler.add_job(run_pipeline, 'interval', minutes=10, id='light_pipeline', kwargs={'light': True})
scheduler.add_job(run_pipeline, 'interval', hours=3, id='full_pipeline')   # 추론만
scheduler.add_job(_train_chart_models_monthly,
                   CronTrigger(day=1, hour=18, minute=0),
                   id='train_chart_pipeline')                                # 매월 1일 KST 03:00
if _need_init_once(models_dir):
    scheduler.add_job(run_pipeline, 'date', run_date=now+60s, id='init_once')

# [검증 결과 (SPY local)]
# - train=True:  35.8s (5-모델 학습 + .pkl 2.81MB 저장)
# - train=False:  6.5s (.pkl load + GJR-GARCH-Skew-t + FHS 추론만)
# - 5.5배 가속, 학습 85% 가설 검증
# - 16 ETF 합계 .pkl 용량 추정: 45MB (예상 80-240MB 보다 작음)

# [비용 절감 추정]
# - chart 학습 횟수: 19,200/월 → 80/월 (99.6% 절감)
# - full_pipeline 1회 시간: 30-45min → 5-10min (~75% 단축)
# - Deploy 시 학습: 매번 → 첫 deploy 만 (init_once 가드)
# - 월간 compute: ~160h → ~22h (약 7배 절감)

# [잠재 이슈]
# 1. 모델 stale: 월 1회 학습이라 regime change 후 1개월 옛 모델 사용. mean prediction 어차피
#    bull-bias 라 큰 차이 없음 (노트북 검증). GARCH 분포는 매 추론마다 새로 fit 하므로 OK
# 2. .pkl 디스크: Railway service 가 persistent volume 인지 ephemeral 인지 확인 필요.
#    ephemeral 이면 redeploy 마다 .pkl 사라짐 → init_once 가 fallback 학습 (1회)
# 3. 첫 학습 30-45분 block: full_pipeline 첫 실행 길어짐. background 라 사용자 영향 X


# ────────────────────────────────────────────────────────────────────────────
# [43] 2026-04-29 (UTC) — ERP 라벨 z-score 화 (15년 baseline)
# ────────────────────────────────────────────────────────────────────────────
# 배경: 절대 임계값 기준(>5% 저평가, <0% 고평가)이라 SPY 10% 하락 구간에도 라벨이
# 안 변동. "최근 추이 대비"로 판정하도록 z-score 화 요청.

# collector/valuation_signal.py — Shiller (1871~2023) + yfinance (2023~today) 합성
#   으로 최근 15년 monthly ERP 분포 산출. Cache: models/erp_baseline.json (TTL 90일).
def _compute_erp_baseline_15y():
    sh = pd.read_excel('http://www.econ.yale.edu/~shiller/data/ie_data.xls', sheet_name='Data', skiprows=7)
    sh['ey']  = sh['E'] / sh['P']
    sh['tnx'] = sh['Rate GS10'] / 100
    sh['erp'] = sh['ey'] - sh['tnx']
    sh15 = sh[sh['year'] >= datetime.now().year - 15]
    # Shiller 마지막 ~ 오늘: yfinance ^GSPC 월봉 + ^TNX + EPS 7%/yr 선형 grow 로 보강
    extra = ...  # 위 로직 참조
    erp_series = pd.concat([sh15.set_index('ym')['erp'], extra])
    return {'mean': erp_series.mean(), 'std': erp_series.std(), 'n': len(erp_series)}

def erp_label(erp, baseline=None):
    if baseline is None: baseline = get_erp_baseline()
    z = (erp - baseline['mean']) / baseline['std']
    if z > +1.0: return '명확한 저평가'
    if z >  0.0: return '다소 저평가'
    if z > -1.0: return '다소 고평가'
    return '명확한 고평가'

# api/routers/macro.py — /valuation-signal 응답에 z_score / baseline_15y 추가
response = {
    'today': {**today, 'z_score': round((erp_now - mean) / std, 2)},
    'history': [...],     # 각 행에도 z_score
    'interpretation': llm_or_fallback,
    'baseline_15y': {'mean': mean, 'std': std, 'n_months': n, 'source': 'shiller+yfinance'},
}

# static/js/home.js — 게이지를 z-score 기반(±2σ 매핑)으로, history 차트에
#   ±1σ / 평균 가이드 라인 추가, 해석 카드에 "15년 (N개월) 평균 X% 표준편차 Y%
#   현재 z=Z" 명시.
function renderGauge(z, label) {
    // 180° = z=-2σ (왼쪽), 0° = z=+2σ (오른쪽)
    const angle = 180 - ((z+2)/4) * 180;
    return `<svg>...</svg><span class="mv-label">${label} · z=${z}σ</span>`;
}
function renderErpHistory(history, baseline) {
    // y축: ±1σ 항상 가시. 가이드 라인 z=+1 (파랑), z=0 (회색 평균), z=-1 (빨강)
    const zs = history.map(h => h.z_score);
    return `<svg>...
        <line y1="${yPos(+1)}" stroke="#3b82f6" dasharray="2 3"/>
        <line y1="${yPos( 0)}" stroke="#9ca3af" dasharray="3 3"/>
        <line y1="${yPos(-1)}" stroke="#ef4444" dasharray="2 3"/>
        ...`;
}

# [실측 결과 (2026-04-29)]
# - 15년 baseline: mean 1.96%, std 1.58%, n=184 months (Shiller 146 + yfinance 38)
# - 오늘 ERP -0.81% → z=-1.75σ → "명확한 고평가"
# - 60일 history z 범위: -1.42 ~ -1.75 (모두 z < -1, 라벨은 "명확한 고평가" 유지)
# - 하락 저점 (3/27): z=-1.53σ — 평균까지 +0.22σ 개선 (수치로 변동 가시화)

# [왜 라벨이 안 바뀌나 (사용자 의문 답변)]
# - 오늘 ERP -0.81% 는 15년 분포 하위 5% 수준. 10% SPY 하락 정도로는 z=-1.42σ 까지만
#   회복 → 여전히 z<-1 영역. 라벨이 같은 건 정확한 통계적 사실.
# - 사용자는 라벨 대신 z-score 수치(-1.42 ↔ -1.75)로 미세 변동을 추적 가능.

# [비용]
# - baseline 재계산: 90일에 1회 (Shiller XLS 다운로드 ~2초 + 계산 즉시).
# - 라벨링: scalar 산술 → compute 0. 메모리 룰 만족.


# ════════════════════════════════════════════════════════════════════════════
# [44] 2026-04-29 (UTC) — ERP 라벨 개선 실험 노트북 확장 (A1+C7)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 미-이란 전쟁(2026-02-28) 발발 직후에도 시장 밸류 탭이 여전히 "명확한 고평가"
# (z=-1.75σ 부근)에 머무는 문제. 단독 ERP z 만으로는 위기 충격이 신호로 잡히지
# 않음. 노트북에서 두 개선안을 backtest:
#   - A1: 15Y monthly baseline → 5Y 로 단축 (std 작아져 z 민감도↑)
#   - C7: composite z = 0.4·z_ERP(5Y) + 0.3·z_VIX + 0.3·z_DD60 (공포·드로다운 합성)
# 가설: war 직후 60일 안에 composite z 가 +1.0σ 이상으로 진입 → "명확한 저평가" 회복.

# [수정 파일]
# notebooks/erp_valuation_experiment.ipynb — section 9 + 10 추가 (cell 18~25)

# [신규 셀 구조 (8 cell, markdown 2 + code 6)]
# Cell 18 (md)  — ## 9 헤더: 동기/가설/부호 컨벤션/실험 절차
# Cell 19 (code) — 다중 window monthly baseline (5Y/10Y/15Y/Full) + std 비율 출력
# Cell 20 (code) — 14개월 daily SPY+^VIX+^TNX → daily ERP·DD60 부착
# Cell 21 (code) — VIX·DD 5Y daily baseline + 모든 z 부착 (양수=저평가/공포 통일)
# Cell 22 (code) — composite z (W=0.4/0.3/0.3) + 라벨 3종 (15Y/5Y/comp)
# Cell 23 (code) — 4-panel 시각화: SPY+DD / VIX / ERP-only z / Composite z (전쟁 마커)
# Cell 24 (code) — war 직후 (2026-02-28~) z 비교 + 라벨 분포 + war 당일 스냅샷
# Cell 25 (md)   — ## 10 결론 표 (실행 후 채우기) + 채택 판정 기준

# [핵심 코드 — composite z]
W = (0.4, 0.3, 0.3)
df['z_erp_5Y'] = (df['erp'] - baselines['5Y']['mean']) / baselines['5Y']['std']
df['z_vix']    = (df['vix'] - vix_mean) / vix_std            # VIX↑ → z↑
df['z_dd']     = -(df['dd_60d'] - dd_mean) / dd_std          # DD 더 음수 → z↑ (부호 반전)
df['z_comp']   = W[0]*df['z_erp_5Y'] + W[1]*df['z_vix'] + W[2]*df['z_dd']

# [부호 컨벤션 — 왜]
# 세 신호 모두 양수 = "저평가/공포 신호" 방향으로 통일. 그래야 가중합이 같은
# 방향으로 합쳐져 위기 직후 z_comp 가 강하게 양수로 점프 가능. ERP·VIX 는 그대로
# 양의 상관, DD 만 부호 반전 (drawdown 은 음수이므로).

# [채택 판정 기준]
# A1+C7 의 max z_comp 가 war 직후 60일 안에 +1.0σ 이상 → "명확한 저평가" 진입
# → collector/valuation_signal.py + api/routers/macro.py 에 반영.
# 미달 시 가중치 grid search 또는 EWMA baseline 으로 후속 실험.

# [실행 가이드]
# 노트북에서 cell 1~17 (기존) → cell 18~25 (신규) 순서로 실행. yfinance 네트워크
# 필요. 약 30~60초 소요 (Shiller XLS + SPY/VIX/TNX 14mo + 5y daily 다운로드).

# [비용]
# - 일회성 실험 (notebook). 프로덕션 변경 없음.
# - 채택 시 collector 가 추가 ticker(^VIX) 1회 fetch (compute 무시 수준).


# ════════════════════════════════════════════════════════════════════════════
# [45] 2026-04-29 (UTC) — A1+C7 노트북 실측 결과
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# notebook headless 실행 (jupyter nbconvert). war 2026-02-28 직후 41 거래일
# (2026-03-02 ~ 2026-04-28) 의 z 분포 비교. 결론: 채택 기준(+1.0σ) 미달이지만
# 라벨 진영은 큰 개선 — production 전환 전에 임계·가중치 추가 실험 필요.

# [Baseline 산출 결과 (cell 19)]
#  5Y : mean=+0.42%, std=1.33%, n=64
#  10Y: mean=+1.27%, std=1.34%, n=124
#  15Y: mean=+1.96%, std=1.58%, n=184  ← 현재 프로덕션
#  Full(1871~): mean=+2.71%, std=3.18%, n=1864
#  → 5Y mean 이 15Y 의 1/4 수준. std 도 작아져 같은 ERP 변동에 ×1.18 sensitive.

# [war 직후 41일 z 분포 (cell 24)]
#  ┌─────────────────────────────┬───────────┬──────────────────────────┐
#  │ 지표                        │ max z     │ 라벨 분포 (41일)         │
#  ├─────────────────────────────┼───────────┼──────────────────────────┤
#  │ 15Y prod   (ERP only)       │ -1.46σ    │ 명확한 고평가 41         │
#  │ A1 5Y      (ERP only)       │ -0.57σ    │ 다소 고평가 41           │
#  │ A1+C7 comp (0.4/0.3/0.3)    │ +0.84σ    │ 다소 저평가 20 + 다소    │
#  │                             │  (3/30)   │ 고평가 21                │
#  └─────────────────────────────┴───────────┴──────────────────────────┘

# [war 당일 (2026-02-27 가장 가까운 거래일) 분해]
#  SPY 685.99, VIX 19.86, ERP -0.29%
#  z_erp_5Y = -0.53σ
#  z_vix    = +0.12σ  ← 5Y mean(19.25) 거의 동일, 공포 거의 안 떴음
#  z_dd     = -0.45σ  ← drawdown 평균보다 가벼움 (시장 안 떨어짐)
#  z_comp   = -0.31σ  → 출발이 음수라 +1σ 까지 +1.31σ 점프 필요했음

# [왜 +1σ 못 넘나]
# 미-이란 전쟁이 시장에 systemic risk 로 받아들여지지 않음 — VIX·DD 두 reactive
# 신호 모두 평이. 신호 강도 자체가 +0.84σ 가 천장. 이 정도 지정학 이벤트는
# 단순 multiplicative composite 로는 한계.

# [채택 판정]
# ❌ +1.0σ 임계 미달. 단, 라벨 진영 개선 (15Y "명확한 고평가" → comp "다소
# 저평가" 50% 진입) 은 명확. 다음 중 하나로 후속 실험:
#   (a) 임계 완화: +0.5σ 이상이면 "저평가" 로 라벨 매핑 변경
#   (b) 가중치 grid: [0.2, 0.4, 0.4] 등 reactive 신호 비중↑
#   (c) EWMA baseline: half-life 12개월, 최근 분위 더 빠르게 반영
#   (d) HY credit spread (FRED BAMLH0A0HYM2) overlay 추가

# [실행 환경]
# .venv (Python 3.12.3) — ipykernel + yfinance 1.3.0 + pandas 3.0.2 + numpy 2.4.4
# + matplotlib 3.10.9 + xlrd + openpyxl. kernel 등록 명: passive-financial.


# ════════════════════════════════════════════════════════════════════════════
# [46] 2026-04-29 (UTC) — A1+C7 composite z 프로덕션 적용
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 노트북 실험(A1+C7) 결과를 그대로 본 코드에 이식. 미-이란 전쟁 직후 41일 중
# 20일이 "다소 저평가" 진입 검증 완료 → ERP 단독("명확한 고평가" 41/41) 한계
# 해소. 4 파일 + DB 스키마 변경.

# [수정 파일]
# - supabase_tables.sql — valuation_signal 테이블에 6개 컬럼 추가
#     (vix, dd_60d, z_erp, z_vix, z_dd, z_comp). ALTER TABLE IF NOT EXISTS.
# - collector/valuation_signal.py — 전면 리팩토링 (15Y → 5Y, VIX/DD 추가, composite)
# - api/routers/macro.py — /valuation-signal 응답에 baselines_5y + z_*/vix/dd_60d
# - static/js/home.js — loadMarketValuation: 게이지/분해/추이/해석 모두 composite

# [DB 스키마 변경 (DDL 실행 필요)]
ALTER TABLE valuation_signal
    ADD COLUMN IF NOT EXISTS vix     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dd_60d  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_erp   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_vix   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_dd    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS z_comp  DOUBLE PRECISION;

# [collector 핵심 변경]
# baselines (3종) — 모두 5Y, models/valuation_baselines.json 합본 캐시 (TTL 90일)
W_ERP, W_VIX, W_DD = 0.4, 0.3, 0.3   # 노트북 backtest 검증 가중치

def compute_composite_z(erp, vix, dd_60d, baselines):
    z_erp = (erp - baselines['erp']['mean']) / baselines['erp']['std']
    z_vix = (vix - baselines['vix']['mean']) / baselines['vix']['std']
    z_dd  = -(dd_60d - baselines['dd']['mean']) / baselines['dd']['std']  # 부호 반전
    z_comp = W_ERP*z_erp + W_VIX*z_vix + W_DD*z_dd
    return {'z_erp': z_erp, 'z_vix': z_vix, 'z_dd': z_dd, 'z_comp': z_comp}

def label_from_z_comp(z):
    if z >  1.0: return '명확한 저평가'
    if z >  0.0: return '다소 저평가'
    if z > -1.0: return '다소 고평가'
    return '명확한 고평가'

# fetch_valuation_signal_today() — SPY+TNX+VIX+SPY 60d 가져와 composite 산출
# backfill_valuation_signal(60) — 6mo daily SPY/TNX/VIX 로 60일 일별 z 산출

# [API 변경]
# 기존: response['baseline_15y'] = {mean, std, n_months, source}
# 신규: response['baselines_5y'] = {erp:{...}, vix:{...}, dd:{...}, weights}
# 기존: today.z_score (단일)
# 신규: today.{z_erp, z_vix, z_dd, z_comp, vix, dd_60d}
# legacy data 자동 backfill: today.z_comp is None 또는 history 60일 미만이면
# 첫 호출 시 backfill_valuation_signal_bulk → upsert.

# [JS 변경]
# - mv-formula : "z_comp = 0.4·z_ERP + 0.3·z_VIX + 0.3·z_DD60"
# - mv-gauge   : z_comp 기반 (renderGauge 그대로 재사용 — z 값만 교체)
# - mv-decompose: 8행 — Raw 5 (PE, TNX, ERP, VIX, DD60) + 가중 z 4 (z_ERP×0.4, z_VIX×0.3, z_DD×0.3, z_comp)
# - mv-history : renderErpHistory → renderCompositeHistory (z_comp 시계열)
# - mv-interpretation: 3 baseline 동시 표시 (ERP/VIX/DD)

# [Smoke test 결과 (4/29 기준, .venv 로 실행)]
# baselines: ERP mean=+0.42% std=1.33% n=64
#           VIX mean=19.25 std=5.26 n=1256
#           DD60 mean=-3.24% std=4.17% n=1255
# today (2026-04-29):
#   spy_per=28.22, vix=17.97, dd_60d=-0.49%
#   z_erp=-0.92, z_vix=-0.24, z_dd=-0.66, z_comp=-0.64 → "다소 고평가"
#   ↑ 노트북 cell 22 (4/28 z_comp=-0.6471) 와 정확히 일치 → 코드=실험 동치 검증

# [배포 절차]
# 1. Supabase SQL 콘솔에서 ALTER TABLE (위 DDL) 실행
# 2. 서버 재시작 → 첫 /api/macro/valuation-signal 호출 시 자동 backfill (60일)
# 3. 24h 메모리 캐시 작동 확인 (response.cached=true)
# 4. models/valuation_baselines.json 자동 생성 확인 (90일 TTL)

# [한계 / 다음 단계 후보]
# - 미-이란 같은 mild 충격은 z_comp +0.84σ 가 천장 → "명확한 저평가"(+1σ) 도달 X
# - 임계 완화 (+0.5σ → "저평가") 또는 EWMA baseline 적용 시 더 reactive
# - VIX High (intraday) 사용 시 +1σ 진입 가능성 (단 노이즈 ↑)


# ════════════════════════════════════════════════════════════════════════════
# [47] 2026-04-29 (UTC) — 시장 밸류 분해 표 일반어 리네이밍
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 영문 약어(P/E·TNX·VIX·z·σ) + 라틴 단위가 일반 사용자에게 불친절. 의미는
# 보존하면서 한글 풀이 + 자동 평어 변환으로 재구성. 코드 변경은 home.js 한
# 파일만 (수식 / 분해 / 해석 카드 텍스트). 백엔드 응답 스키마 변경 없음.

# [수정 파일]
# - static/js/home.js — loadMarketValuation() 의 mv-formula / mv-decompose /
#   mv-interpretation HTML 일반어 라벨로 교체. zPhrase() 헬퍼 추가.
# - templates/stocks.html — home.js?v=17 → ?v=18 (브라우저 캐시 버스트)

# [라벨 매핑]
# 수식:
#   z_comp = 0.4·z_ERP + 0.3·z_VIX + 0.3·z_DD60
#   →  5년 평균과 비교한 종합 점수 = 주식 매력도(40%) + 공포(30%) + 하락충격(30%)
# 분해 행:
#   SPY P/E (Trailing)              → S&P 500 주가수익비율 (PER)
#   10Y Treasury (^TNX)             → 10년 미국 국채 금리
#   Equity Risk Premium             → 주식 매력도 (1÷PER − 국채금리, 양수면 주식 우위)
#   VIX (공포지수)                  → 월가 공포지수 (VIX, 20↑ 불안 · 30↑ 패닉)
#   SPY 60일 Drawdown               → 최근 60일 고점 대비 하락
#   ×0.4 z_ERP (5Y)                 → 40% 주식 매력도 점수 (평소보다 비쌈/평온/쌈)
#   ×0.3 z_VIX (5Y)                 → 30% 공포 점수 (평소보다 평온/비슷/불안)
#   ×0.3 z_DD60 (5Y)                → 30% 하락 충격 점수 (평소보다 안정/비슷/큰 하락)
#   = Composite z_comp              → = 종합 점수 → {라벨}

# [zPhrase 자동 변환 규칙]
const zPhrase = (z, kind) => {
    const high = z > 0.5, low = z < -0.5;
    if (kind === 'erp') return high ? '평소보다 쌈'  : low ? '평소보다 비쌈' : '평소와 비슷';
    if (kind === 'vix') return high ? '평소보다 불안' : low ? '평소보다 평온' : '평소와 비슷';
    if (kind === 'dd')  return high ? '평소보다 큰 하락' : low ? '평소보다 안정' : '평소와 비슷';
};
# 부호 컨벤션 (양수 = 저평가/공포 신호 방향) 은 동일하지만 component 별 의미가
# 달라 표현은 다르게 (ERP 양수=쌈, VIX 양수=불안, DD 양수=큰 하락).

# [해석 카드 (mv-interpretation)]
# 기존: "5년 baseline — ERP 평균 X% (σ Y%) · VIX 평균 ... · DD60 평균 ..."
# 신규: "최근 5년 평균 — 주식 매력도 X% · 공포지수 Y · 60일 하락폭 Z% / 오늘 종합 점수 Wσ"

# [백엔드 호환]
# /api/macro/valuation-signal 응답 스키마 변경 없음 — 서버 재시작 불필요.
# 단 templates 캐시(Jinja2) 갱신 위해 ?v 변경 + 한 번 restart 권장 (로컬 OK).

# [검증]
# curl http://127.0.0.1:8000/static/js/home.js?v=18 → 신규 평어 문구 포함 확인
# curl http://127.0.0.1:8000/stocks → home.js?v=18 참조 확인


# ════════════════════════════════════════════════════════════════════════════
# [48] 2026-04-29 (UTC) — 시장 밸류 prod 500 안전망 + 진단 메시지
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# dda3a8b 배포 후 dinsightlab.com /api/macro/valuation-signal 이 500 반환,
# 다른 endpoint 는 모두 200. 가장 의심: Railway 의 prod Supabase 가 .env(local)
# 와 다른 인스턴스이고 6컬럼 ALTER TABLE 이 미실행 → backfill 의 bulk upsert
# 실행 시 Supabase 가 unknown column 으로 reject → 예외 → 500.
#
# 즉답 어렵고 직접 진단 필요. 다음 수정으로 prod 에서 원인 자동 표출:
#   1. 모든 외부 호출(DB fetch / backfill / upsert / baseline) 을 try/except 로 감싸
#      예외 발생 시 500 대신 `{'error':code,'detail':msg}` JSON 반환
#   2. 프런트는 d.error/d.detail 을 그대로 화면에 표시 → 사용자/개발자가 즉시
#      문제 카테고리 파악 가능 ("schema_outdated" 면 ALTER TABLE 필요)

# [수정 파일]
# - api/routers/macro.py : /valuation-signal 엔드포인트 4단계 try/except 추가
#   (DB fetch / backfill 전체 / bulk upsert 단독 / baseline) — 각 단계 별 의미
#   있는 error code 반환
# - static/js/home.js : 에러 화면이 "데이터 미수집..." 일반 문구 → 실제
#   `error: code — detail` 표출
# - templates/stocks.html : home.js?v=18 → ?v=19 (캐시 버스트)

# [핵심 코드 — schema_outdated 진단]
try:
    upsert_valuation_signal_bulk(backfill)
except Exception as e:
    return {
        'error': 'schema_outdated',
        'detail': f'DB 컬럼 누락 추정. supabase_tables.sql 의 ALTER TABLE 6컬럼 실행 필요. ({type(e).__name__}: {str(e)[:200]})',
    }

# [후속 조치]
# 배포 후 prod 화면에서 정확한 error 메시지 확인 → 원인에 맞춰 (Supabase DDL
# 실행 / Railway env 변경 / yfinance 차단 우회 등) 본격 수정.


# ════════════════════════════════════════════════════════════════════════════
# [49] 2026-04-29 (UTC) — 시장 밸류 UX 후속 (차트 라벨 / 해석 카드 / LLM 평어)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 사용자 피드백: 게이지 라벨 z=-0.63σ 노출 X (라벨만), 차트 y축 ±1σ → 직관적
# 단어, 해석 박스 디자인을 다른 탭의 ai-explain-card 와 통일, LLM 해설은
# z/σ/ERP/VIX 같은 기술 용어 제거하고 일반 투자자도 이해할 한국어로.

# [수정 파일]
# - static/js/home.js: renderGauge 가 라벨 뒤 "· z=Xσ" 제거 (게이지에 라벨만);
#   renderCompositeHistory 의 y축 레이블 +1σ → "저평가", −1σ → "고평가"
#   ("평균"은 그대로). 에러 표시문도 d.error/d.detail 그대로 표출.
# - templates/stocks.html: market-valuation 탭의 해석 div 를 .card.ai-explain-card
#   구조로 감쌈 (다른 탭 fundamental/sector-val/sector-mom 과 동일 head + AI 뱃지).
#   "해석" mv-section-label 제거 (카드 head 가 대체).
# - api/routers/macro.py: _VAL_SIG_PROMPT 전면 재작성 — z/σ/ERP/VIX 약어 사용
#   금지, "주식 매력도 점수 / 공포 점수 / 하락 충격 점수 / 종합 점수" 평어.
#   LLM 입력 user_text 키도 한글 평어로 변환 (LLM 이 자연스럽게 평어로 응답
#   유도). Fallback 메시지도 dominant component 자동 판별 + 평어로 재작성.

# [LLM 응답 예시 (2026-04-29 z_comp=-0.63 다소 고평가)]
# 신규: "현재 종합 점수 -0.63점으로 다소 고평가입니다. 주식 매력도가 크게
#       떨어져 비싸진 시기입니다. 시장 분위기도 안정적이라 기다리는 게 좋겠습니다."
# 기존: "현재 z_comp=-0.634 (z_ERP -0.92, z_VIX -0.23, z_DD -0.66)로 ERP 하락이
#       주된 원인입니다. ..."

# [캐시 버스트] templates/stocks.html: home.js?v=20 → ?v=21


# ════════════════════════════════════════════════════════════════════════════
# [50] 2026-04-29 (UTC) — AI 해설 원인 분석 강화 (탭 분해 기반)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 기존 LLM 응답이 "다소 고평가입니다 / 주식 매력도가 떨어졌어요" 같은 일반적
# 진술에 그침. 사용자가 "왜 그런지" 원인을 탭 분해 데이터(PER, 국채금리, VIX,
# 60일 하락폭)와 5년 평균 비교로 풀어 설명해주길 요청.

# [수정 파일]
# - api/routers/macro.py
#   1) Python 단에서 dominant component 사전 계산 — z_comp 부호와 같은 방향의
#      가중기여(매력도×0.4, 공포×0.3, 충격×0.3) 중 절대값 큰 것 → '_가장_영향_큰_점수'
#   2) LLM 입력 user_text 에 PER·국채금리·VIX·DD raw 값 + 5년 평균 둘 다 추가
#      → LLM 이 "PER 28배, 국채금리 4.35% 라서 매력도가 깎였어요" 식 원인 진단 가능
#   3) _VAL_SIG_PROMPT 재작성 — 정확히 3문장 구조: ① 점수+영역 ② 원인분석
#      (raw vs 5년 평균 비교) ③ 보조 요인 + 액션
#   4) max_tokens 240 → 320
#   5) Fallback 도 dominant 별 raw 원인 자동 생성 (PER+국채 / VIX / DD60)

# [LLM 응답 예시 비교]
# 기존: "현재 종합 점수 -0.63점으로 다소 고평가입니다. 주식 매력도가 크게
#       떨어져 비싸진 시기입니다. 시장 분위기도 안정적이라 기다리는 게 좋겠습니다."
# 신규: "종합 점수 -0.63점, '다소 고평가'  /  주가수익비율 28배로 평소보다
#       비싸고 국채금리도 4.35%로 높아 주식 매력도가 깎였어요  /  60일 하락폭은
#       적은 편이지만 주식 매력도 부진으로 분할 매수는 미루세요"
# → "왜" 부분이 PER + 국채금리 raw 수치와 함께 구체화됨.

# [부수 변경] 코드 변경만, 프런트/스키마 변경 없음. 24h 캐시 비우려면 서버 재시작.


# ════════════════════════════════════════════════════════════════════════════
# [51] 2026-04-29 (UTC) — AI 해설 어투 — 명사형 + 신중·중립
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 사용자 요청: "~요" 단언 어투를 명사형(~함/~임/~상태/~여지) + 신중·중립으로
# 변경. "분할 매수는 미루세요" / "비싸진 시기예요" 같은 단언 → "관망 검토 여지"
# / "다소 비싸 보이는 수준" 같은 표현으로.

# [수정 파일]
# - api/routers/macro.py
#   1) _VAL_SIG_PROMPT 에 어투 규칙 추가 — "~요/~다/~합니다 금지", "명사형 종결",
#      "단언 금지·신중한 표현" + 좋은 예시/나쁜 예시 명시
#   2) Fallback 메시지 모두 명사형으로 재작성:
#      - "분할 매수를 고려할 만합니다" → "분할 매수 검토 여지 있음"
#      - "방어 전략을 고려하세요" → "방어 비중 확대 검토 권장"
#      - "관망하거나 방어적인 포지션이 무난합니다" → "관망 또는 방어 비중 확대 검토 여지"

# [응답 예시 비교]
# 기존 (단언 + ~요체):
#   "주가수익비율 28배로 평소보다 비싸고 국채금리도 4.35%로 높아 주식 매력도가
#    깎였어요 / 분할 매수는 미루세요"
# 신규 (명사형 + 신중):
#   "주가수익비율 28.22배로 평균 대비 낮아지고 국채금리 4.35%도 상대적으로 높아
#    주식 매력도가 떨어진 상태 / 방어 비중 확대 검토 여지"

# [향후 같은 어투 적용 후보]
# 다른 탭의 AI 해설 (fundamental / sector-val / sector-mom / market-summary)
# 도 동일 어투 일관성 적용 검토.


# ════════════════════════════════════════════════════════════════════════════
# [52] 2026-04-29 (UTC) — OG 썸네일 이미지 교체 (Passive 대시보드 캡처)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 기존 og-image.png 가 512×512 단순 로고였음. SNS·메신저 링크 미리보기에서
# 사이트의 실제 가치(다양한 위젯·차트가 한 화면에 보이는 대시보드)가 전달되지
# 않았음. 사용자가 실제 대시보드 스크린샷(1672×941, 1.78:1)으로 교체 요청.

# [수정 파일]
# - static/og-image.png : 512×512 로고 → 1672×941 대시보드 캡처 (1.3MB)
# - templates/stocks.html : 메타태그 4종 추가/갱신
#   1) og:image URL 에 ?v=2 캐시 버스트 (X·페이스북·디스코드는 OG 이미지를
#      aggressively 캐시 — URL 자체가 바뀌어야 갱신)
#   2) og:image:width 1672, og:image:height 941 명시
#   3) og:image:alt 추가 (스크린리더·접근성)
#   4) twitter:image 명시 (twitter:card=summary_large_image 와 짝)

# [검증]
# 배포 후:
# 1) Twitter Card Validator: https://cards-dev.twitter.com/validator
# 2) Facebook Debugger: https://developers.facebook.com/tools/debug/
#    → 두 도구에서 dinsightlab.com 입력 → "Scrape Again" 으로 강제 리프레시


# ════════════════════════════════════════════════════════════════════════════
# [53] 2026-04-29 (UTC) — 섹터 모멘텀 단순화 (1·3·6M → 1주·1개월 + 1주 랭킹)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 사용자 요청: 섹터 모멘텀 탭 7컬럼(1M·3M·6M·현재·예상·괴리) 너무 복잡 →
# 3컬럼만 (1주일 수익률 / 1개월 수익률 / 랭킹). 랭킹은 1주일 수익률 기준.
# Phase 비교(과거 같은 국면 평균과 비교한 expected_rank/rank_diff) 전부 제거.
# 단기 모멘텀 추적이 본 탭의 더 본질적 가치라는 판단.

# [수정 파일]
# - processor/feature7_sector_momentum.py : 전면 리팩토링
#   * 월별 종가 추출 → 일별 종가 직접 사용
#   * _cum_return(months) → _cum_return_days(days)
#   * 상수: _TRADING_DAYS_1W = 5, _TRADING_DAYS_1M = 21
#   * fetch_sector_cycle_latest() 의존성 제거 (phase 비교 안 함)
#   * 반환 필드: ticker, sector_name, return_1w, return_1m, rank
#   * 정렬: rank ASC (1위가 위)
# - static/js/home.js : loadSectorMomentum 3컬럼 테이블로 단순화
#   * 색상: 양수 초록 / 음수 빨강 / null 회색
#   * 칩(over/under/flat) 제거, 범례도 "1주일 기준 랭킹" 한 줄로 단순화
# - templates/stocks.html : tile subtitle "1·3·6M 랭킹" → "1주·1개월 수익률 랭킹"
#   home.js?v=21 → ?v=22
# - api/routers/market_summary.py : 'sector-mom' 브랜치 신필드 대응
#   * phase 라인 제거, top/bottom (1주 랭킹 기준 상·하위 3) 출력으로 변경
#   * outperf/underperf (rank_diff 기반) 섹션 제거

# [핵심 코드]
def compute_sector_momentum() -> dict:
    # ... daily prices fetch (페이지네이션) ...
    daily_close = {t: [c for _, c in sorted(s)] for t, s in by_ticker.items()}
    returns_1w = {t: r for t, p in daily_close.items()
                  if (r := _cum_return_days(p, 5)) is not None}
    returns_1m = {t: r for t, p in daily_close.items()
                  if (r := _cum_return_days(p, 21)) is not None}
    rank_by_1w = _rank_dict(returns_1w)        # 1주 수익률 큰 게 1위
    out = [{
        'ticker': t, 'sector_name': name,
        'return_1w': round(returns_1w.get(t)*100, 2) if t in returns_1w else None,
        'return_1m': round(returns_1m.get(t)*100, 2) if t in returns_1m else None,
        'rank': rank_by_1w.get(t),
    } for t, name in SECTOR_VALUATION_ETFS.items()]
    out.sort(key=lambda x: x['rank'] or 999)
    return {'as_of_date': date.today().isoformat(), 'momentum': out}

# [거래일 수 결정 근거 (직접 결정)]
# 1주 = 5 거래일 (월~금 한 주). 7 캘린더 일이 아닌 5 사용 — 주말 비거래.
# 1개월 = 21 거래일 (US 시장 평균 월 거래일 ~21). 22 도 가능하나 21이 보편.

# [API 응답 변경]
# 기존: {phase_name, as_of_date, momentum: [{return_1m, return_3m, return_6m,
#       current_rank, expected_rank, rank_diff}, ...]}
# 신규: {as_of_date, momentum: [{return_1w, return_1m, rank}, ...]}
# phase_name 필드 제거 — 응답 더 작고 의미 명확.


# ════════════════════════════════════════════════════════════════════════════
# [54] 2026-04-29 (UTC) — structure.md 함수 한 줄 요약 추가
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# logic/structure.md 의 collector·processor·repository·정규화 헬퍼·프론트 유틸
# 시그니처 옆에 "이 함수가 무엇을 하는가" 한 줄 코멘트를 일괄 추가.
# 코드 변경 0건 — 문서만 갱신.

# [수정 파일]
# - logic/structure.md
#   * 5.0 공통 내부 패턴: _fetch_page/_fetch_all/_parse_*/_normalize_items 코멘트 보강
#   * 5.1 real_estate_trade.py: fetch_trades / fetch_rents
#   * 5.2 real_estate_population.py: fetch_population / fetch_household_by_size /
#         fetch_mapping_pairs / fetch_all_sgg_codes
#   * 5.3 real_estate_geocode.py: geocode / batch_geocode
#   * 5.4 ecos_macro.py: fetch_ecos_series / fetch_macro_rate_kr
#   * 5.5 kosis_migration.py: fetch_kosis_migration
#   * 6.1 feature5_real_estate.py: build_mapping / compute_region_summary
#   * 6.2 feature6_buy_signal.py: compute_buy_signal
#   * 7. repositories.py: 부동산 ~20개 upsert/fetch 모두 (원천·가공·시그널·거시)
#   * 10. scheduler/job.py 정규화 헬퍼: _re_norm_trades / _re_norm_rents /
#         _re_norm_population / _re_norm_household / _re_norm_mapping
#   * 11.4 frontend lib/color.ts: changePctColor / changePctTextColor / formatPrice
#   * "마지막 갱신 시점" 라인 갱신

# [왜]
# - structure.md 가 함수 시그니처만 늘어놓고 있어 처음 보는 사람이 각 함수의
#   역할을 파악하려면 실제 파일을 열어 봐야 했음.
# - 시그니처 옆 한 줄 코멘트로 "이 함수가 무엇을 위해 존재하는가" 를 그 자리에서
#   읽을 수 있게 만들어 청사진 문서로서의 가독성 강화.
# - 사용자 요청에 따른 일회성 보강.

# [검증]
# - 코드 변경 없음 → 런타임 영향 없음.
# - 함수명·시그니처는 그대로 유지하고 우측에 # 코멘트만 추가했으므로 grep 호환성 유지.


# ════════════════════════════════════════════════════════════════════════════
# [55] 2026-04-29 (UTC) — 섹터 이름 한국어 표시 (밸류·모멘텀 탭)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 섹터 밸류에이션·모멘텀 탭에서 섹터명이 영어로 표시됨 ("Technology",
# "Software"…). 사용자 한국어 표시 요청.

# [수정 파일]
# - static/js/home.js : SECTOR_KR ticker→한국어 매핑 + krSector(ticker, fb)
#   헬퍼. loadSectorValuation / loadSectorMomentum 두 사이트에서 사용.
# - templates/stocks.html : home.js?v=22 → ?v=23

# [매핑 테이블]
const SECTOR_KR = {
    XLK: '기술', IGV: '소프트웨어', SOXX: '반도체',
    XLF: '금융', XLE: '에너지', XLV: '헬스케어',
    XLY: '경기소비재', XLI: '산업재', XLB: '소재',
    XLU: '유틸리티', XLRE: '부동산', XLC: '커뮤니케이션',
    XLP: '필수소비재',
};

# [설계 — 왜 표시 단에서만 번역?]
# DB·API 응답은 영어 그대로 둠. 이유:
# 1) DB 마이그레이션 불필요 (영어 row + 한글 row 혼재 안 됨)
# 2) LLM 입력(영어 sector_name) 안정적 — Groq/GPT 모두 영어 sector 라벨 잘 인식
# 3) 추후 i18n (영어 화면 모드) 추가 시 매핑 한 곳만 토글하면 됨


# ════════════════════════════════════════════════════════════════════════════
# [56] 2026-04-29 (UTC) — 시장 이성 점수 부호 반전 (펀더멘털-주가 갭 → 시장 이성)
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 기존 noise_score 컨벤션:
#   + (양수) = 감정적 (주가가 펀더멘털과 괴리)
#   − (음수) = 이성적 (주가가 펀더멘털 반영)
# 사용자 요청: 라벨을 "시장 이성 점수" 로 바꾸고 부호를 정확히 반대로.
# 새 컨벤션:
#   + (양수) = 이성적
#   − (음수) = 감정적
# DB 컬럼명은 'noise_score' 그대로 유지 (의미만 반전 — 호환성 위해 필드명 미변경).

# [왜 부호를 뒤집나]
# - "이성 점수" 라는 이름과 부호가 직관적으로 일치해야 함 (양수=좋음=이성)
# - UI 게이지/차트에서 양수가 우측·상단으로 가는 일반 컨벤션과 정렬

# [수정 파일]
# - processor/feature1_regime.py
#   * compute_noise_score(): return 값에 -1 곱 (가중합을 부호 반전)
#   * score_to_regime_name(): 임계 부호 반전
#       기존: score < 0 → 일치, 그 외 불일치
#       신규: score > 0 → 일치 (이성적), 그 외 불일치 (감정적)
#   * predict_regime / backfill_noise_regime: feature_contributions 항목의
#     'contribution' 필드도 -1 곱 (합이 새 noise_score 와 일치하도록)
#   * 모듈 docstring 에 새 부호 컨벤션 명시
#
# - api/routers/regime.py (/score-distribution)
#   * docstring 에 새 컨벤션 추가
#   * current_config: gauge_min/mid/max 를 -10/0/+5 로 갱신 (좌=감정·우=이성)
#
# - api/routers/market_summary.py
#   * _build_indicator_text: 한·영 해석 라인을 새 부호 컨벤션으로 다시 작성
#       기존: ns < -1 → "잘 반영", ns >= 2 → "큰 괴리"
#       신규: ns > 1 → "잘 반영", ns <= -2 → "큰 괴리"
#   * 한국어 라벨 "펀더멘털 주가 괴리 점수" → "시장 이성 점수"
#   * 영어 라벨 "Fundamental-Price Divergence Score" → "Market Rationality Score"
#   * _SUMMARY_PROMPTS / _EXPLAIN_PROMPTS (KO+EN) 모두 부호·이름 갱신
#   * 예시 라인의 점수 부호도 반전 (괴리 = 음수)
#
# - static/js/main.js
#   * _buildFgNoiseInsight: noiseScore >= 0 ↔ < 0 조건 모두 반전
#       (이전: ns >= 0 → 비이성/괴리. 이후: ns < 0 → 비이성/괴리)
#   * NR_GAP_POS: 좌우 위치 반전 (펀더멘털 반영 12→88, 센티멘트 지배 88→12)
#   * 게이지 fill 그라디언트: green→…→red 를 red→…→green 으로 뒤집음
#   * loadRegime 동적 pos: gauge_min=-10, gauge_max=+5 로 매핑 변경
#       (분포가 음수 쪽으로 더 길게 분포 — 감정 깊이가 더 큼)
#   * loadNoiseChart dotColor: v >= 0 ? red : green → green : red 로 반전
#
# - static/js/i18n.js (KO + EN 둘 다)
#   * nr.fundamental ↔ nr.price 라벨 swap (좌=감정 / 우=이성)
#   * nr.match ↔ nr.gap 라벨 swap
#   * chart.yTop ↔ chart.yBottom 라벨 swap (상=이성 / 하=감정)
#   * section.nrChart: "이성적·감정적 추이" → "시장 이성 점수 추이"
#   * detail.noiseScore: "Noise Score:" → "시장 이성 점수:" / "Market Rationality:"
#   * detail.noiseComposition: 점수 명칭 갱신
#
# - templates/stocks.html
#   * i18n.js?v=2 → ?v=3, main.js?v=113 → ?v=114 (cache bust)
#
# - scripts/flip_noise_score_sign.py (★ 신규)
#   * 1회성 마이그레이션. UPDATE noise_regime SET noise_score = -noise_score
#     + feature_contributions 의 contribution 필드 부호 반전
#     + regime_id / regime_name 도 새 임계로 재산정
#   * --dry 옵션으로 미리보기 가능
#   * 사용: python -m scripts.flip_noise_score_sign

# [실행 필요 — 사용자가 deployment 환경에서 1회]
#   $ python -m scripts.flip_noise_score_sign --dry      # 미리보기
#   $ python -m scripts.flip_noise_score_sign            # 실제 적용

# [검증]
# - python ast.parse 4개 파일 전부 OK
# - node --check main.js / i18n.js OK
# - 게이지 동작 검증: ns=+5 → pos=95% (우측=이성), ns=-10 → pos=5% (좌측=감정)
# - 라벨 일관성: 좌측='감정적' 매핑 + 우측='이성적' 매핑 + 부호 반전 → 의미 자기일관

# [한계·후속]
# - DB 마이그레이션 실행 전까지는 30일 차트가 옛 부호로 표시됨
# - 마이그레이션 후 다음 스케줄러 실행부터 새 부호로 일관 적재
# - 'noise_score' 컬럼명 자체는 유지 (rename 은 후속 — 외부 의존성 큼)


# ════════════════════════════════════════════════════════════════════════════
# [57] 2026-04-29 (UTC) — 부동산 데이터 수도권 확장 (Phase 1: 폴리곤·코드)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 기존 부동산 데이터가 서울 25 시군구만 (DB region_summary 1000행 모두 시도코드 11).
# 수도권(서울+경기+인천)으로 확장. Phase 1 = 지도 폴리곤 + 백필 인프라 / Phase 2
# = 실제 backfill 실행 (별도 [58] 엔트리 예정).

# [신규 파일]
# - scripts/build_metro_geojson.py
#     southkorea-maps(2013) FeatureCollection 다운로드 → 수도권 79 features 필터
#     → 통계청 코드(11/23/31) → 행안부 LAWD_CD(5자리) 매핑 후 properties.sgg_cd
#     명시적 부여. 인천 "남구" → 28177 미추홀구 alias / 부천 3구 → 41194 단일.
# - scripts/backfill_metro.py
#     수도권 신규 52 LAWD_CD × 24개월 backfill (job.py Step 9 의 다월 버전).
#     인천 10 + 경기 단일 25 + 일반구 17 = 52. 세대원수만 최근 3개월 (--hh-months 3).
#     호출 간격 0.4s, 401 발생 시 60s 대기. 매 sgg 종료 시 compute_buy_signal 자동.
# - frontend-realestate/public/geojson/metro-sgg.geojson (70KB, 79 폴리곤)
# - static/realestate/geojson/metro-sgg.geojson (Vite public 동기화본)

# [수정 파일]
# - frontend-realestate/src/screens/MapScreen.tsx
#     loadPolygons URL 교체 + properties.sgg_cd 직접 사용 (이름 매핑 dict 제거)
#     handlePolygonClick 의 SGG_NAME_TO_CD 역참조 → polygons.find 로 대체
#     KakaoMap viewport: center {lat:37.45, lng:127.0} + level 11 (수도권 전체 가시)
# - static/realestate/{index.html, assets/index-Ct0CBs2c.css, index-lQYfAXan.js}
#     vite build 산출물 (npm run build, ./node_modules 캐시 활용 4.5s)

# [수도권 매핑 통계]
# 서울 25 (행안부 코드 그대로)
# 인천 10 (남구→미추홀 alias)
# 경기 42 (단일 25 + 일반구 17)
# = 유니크 행안부 sgg_cd 77, 폴리곤 79 (부천 3구 = 같은 sgg_cd, 다른 폴리곤)

# [Phase 2 — 진행 중]
# scripts/backfill_metro.py 백그라운드 실행 (PID 6194, ~25~30분, ~8000 API call).
# 결과 [58] 엔트리에 실측 (성공/실패 시군구 수, 신규 row 수).


# ════════════════════════════════════════════════════════════════════════════
# [58] 2026-04-30 (UTC) — 시장 이성 점수: 표시단 부호 반전으로 아키텍처 재설계
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# [56] 에서 시장 이성 점수 부호 반전을 "compute_noise_score 가 -1 곱해 NEW 컨벤션
# 으로 DB 에 저장" 방식으로 구현했음. 그런데 실제 운영 결과:
# 1) 마이그레이션은 1000 행만 flip (Supabase select 기본 limit)
# 2) 마이그레이션 후 Railway 스케줄러의 backfill 함수가 옛 코드로 30~60일치
#    행을 다시 OLD 컨벤션으로 덮어씀
# 3) 결과: DB 가 옛 컨벤션으로 다시 일관됨, 근데 로컬 코드는 NEW 가정 →
#    차트는 같은 데이터를 같은 위치에 그리고 라벨만 swap 된 상태
#
# 즉 "DB = NEW" 가정의 [56] 접근은 배포 환경에서 깨짐. "DB = OLD 유지 + 표시
# 단에서만 flip" 으로 아키텍처 재설계.

# [핵심 변경]
# - DB(noise_regime.noise_score, feature_contributions) 는 옛 컨벤션 그대로:
#   * + 양수 = 감정적
#   * - 음수 = 이성적
# - Repository fetch 함수에서 부호 반전:
#   * fetch_noise_regime_current / _history 가 _flip_noise_record() 로 변환
#   * 클라이언트(API/JS/LLM)는 항상 NEW 컨벤션 (+양수=이성) 으로 받음
# - 결과: 어느 코드(옛/새) 가 DB 에 쓰든 표시단은 항상 NEW 컨벤션

# [수정 파일]
# - processor/feature1_regime.py
#   * docstring: 부호 컨벤션을 "DB = OLD, 표시 = NEW (repo 단 변환)" 로 명시
#   * compute_noise_score(): -1 곱 제거, 원래 OLD 컨벤션 가중합으로 복원
#   * score_to_regime_name(): 임계 OLD 로 복원 (ns < 0 → 일치)
#   * predict_regime / backfill_noise_regime: contribution 부호 반전 제거
#
# - database/repositories.py (★ 핵심)
#   * _flip_noise_record(record) 헬퍼 신규
#       - record['noise_score'] *= -1
#       - record['feature_contributions'][*]['contribution'] *= -1
#       - regime_name 은 그대로 ('일치/불일치' 단어 의미가 두 컨벤션에서 공통)
#   * fetch_noise_regime_current() return 직전에 flip 적용
#   * fetch_noise_regime_history() 각 행 flip 적용
#   * fetch_noise_regime_all() 은 date 만 가져와서 flip 불필요

# [그대로 유지]
# - api/routers/market_summary.py LLM 프롬프트 NEW 컨벤션
#   (repo 가 NEW 로 내보내므로 그대로 일관)
# - static/js/main.js NEW 컨벤션 (게이지 그라디언트, dotColor, NR_GAP_POS 등)
# - static/js/i18n.js NEW 라벨 ("시장 이성 점수", 좌=감정 우=이성)
# - templates/stocks.html cache bust 그대로

# [왜 이 방식이 나은가]
# 1) 단일 진실(single source of truth): DB 컬럼 의미가 영속적으로 OLD —
#    배포 환경의 옛 코드/새 코드 어느 쪽이 써도 동일한 부호 컨벤션
# 2) 마이그레이션 불필요: 기존 데이터를 손대지 않음
# 3) Railway 배포 타이밍에 의존하지 않음: 옛 백필이 돌아도 DB 손상 없음
# 4) 단일 변환 지점: repo 의 _flip_noise_record() 만 보면 부호 동작 파악 가능

# [참고 — 마이그레이션 스크립트]
# scripts/flip_noise_score_sign.py 는 이제 불필요. 1차 마이그레이션이 oldest
# 1000 rows 를 flip 했지만 그 후 backfill 이 다시 덮어써서 사실상 효과 없음.
# 향후 정리 차원에서 그 1000 rows 만 OLD 로 되돌리고 싶으면 다시 한 번 실행.
# (안 해도 표시는 정상 — backfill 이 덮어쓸 때까지 잠깐 inverted 일 뿐)

# [검증]
# - python ast.parse 두 파일 OK
# - 흐름:
#     scheduler write → DB (OLD) → repo fetch → flip → API → JS/LLM (NEW)
#   어떤 코드가 써도 사용자는 NEW 컨벤션만 본다.


# ════════════════════════════════════════════════════════════════════════════
# [59] 2026-04-30 (UTC) — 홈 헤드라인 AI: 4개 탭 비교해 가장 중요한 신호 1문장
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 홈 화면 상단 "오늘의 종합 판단" 카드가 기존엔 /ai-summary 응답(4줄: 시장 심리·
# 방향성·펀더멘털·종합판단)의 첫 줄만 잘라 표시 → 항상 "시장 심리"에 고정됨.
# 사용자 요청: 각 탭 정보를 LLM 에 주고, 가장 중요한 신호 1개를 골라 한 문장으로.

# [수정 파일]
# - api/routers/market_summary.py
#   * _build_home_indicator_text(lang): 4개 탭별 [시장] [펀더멘털] [신호] [섹터]
#     섹션으로 그룹화한 지표 텍스트
#   * _HEADLINE_PROMPTS (KO + EN): 신호 선정 우선순위(극단값/이성점수/일변도) +
#     1문장·80자 이내 + 지표명+수치 1개 인용 강제
#   * _headline_cache + _headline_lock (15분 TTL)
#   * GET /api/market-summary/home-headline?lang=ko|en
#     - LLM 응답 후 첫 마침표/개행 기준으로 1문장 강제 절단
#
# - static/js/home.js
#   * loadAiCard(): /ai-summary 첫 줄 슬라이스 → /home-headline 직접 표시
#
# - templates/stocks.html
#   * home.js?v=23 → ?v=24

# [신호 선정 우선순위 (프롬프트에 명시)]
# 1) 극단값: F&G 25 미만/75 초과, RSI 30 미만/70 초과, VIX 25 초과, |gap| >= 20
# 2) 시장 이성 점수 |>= 2|
# 3) gap 절대값 >= 30 (강한 일변도)
# 4) 위 셋 모두 평이하면 가장 큰 변화 신호

# [왜 별도 엔드포인트?]
# - /ai-summary 는 4줄 종합 브리핑 용도 (시장 탭에서 그대로 사용 — 손대지 않음)
# - 홈 헤드라인은 1문장 + 단일 신호 — 프롬프트·캐시·응답 형식 분리가 더 깨끗

# [예시 출력]
# - "공포탐욕지수 19로 극도 공포 구간이며 시장 심리가 크게 위축된 상태입니다."
# - "하락 위험도 78점으로 단기 하방 압력이 두드러지는 흐름입니다."
# - "시장 이성 점수가 -2.3까지 내려가 감정적 거래가 지배적입니다."

# [검증]
# - python ast.parse, node --check 모두 OK


# ════════════════════════════════════════════════════════════════════════════
# [60] 2026-04-30 (UTC) — 홈 헤드라인: 이성 점수 × 시장 밸류 결합 판단 필수화
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# [59] 의 home-headline 이 "가장 중요한 신호 1개" 자유 선택 방식이었는데,
# 사용자 요청: "이성 점수가 +면 밸류 합리적 / -면 시장이 감정적이라 밸류 비합리적"
# 이라는 결합 판단을 첫 문장에 **반드시** 넣게 해라.

# [수정 파일]
# - api/routers/market_summary.py
#   * import: fetch_valuation_signal_latest 추가
#   * _build_home_indicator_text(): [시장 밸류 탭] 섹션 추가
#       - z_comp (composite z-score, +저평가/-고평가) + label
#       - ERP, SPY PER, VIX 보조
#   * _HEADLINE_PROMPTS (KO/EN): 출력 형식 1→1~2 문장으로 변경
#       - 첫 문장(필수): 이성 점수 부호 → 밸류 합리/비합리 판단
#         + 이성 점수 수치 인용 + 밸류 라벨/z_comp 언급
#       - 강도 표현 (|score| 기준): ±2+ 강하게 / ±1 이내 약하게
#       - 둘째 문장(선택): F&G/RSI/gap/VIX 극단값 보조 (없으면 생략)
#   * /home-headline 응답 절단: 첫 마침표 1개만 → 마침표 기준 최대 2문장
#   * Groq max_tokens 200 → 350 (2문장 여유)

# [필수 규칙 (프롬프트에 명시)]
# - 이성 점수 + → 시장이 이성적 → 현재 밸류는 합리적
# - 이성 점수 - → 시장이 감정적 → 현재 밸류는 비합리적
# - 시장 이성 점수 수치 반드시 인용
# - 시장 밸류 라벨 또는 z_comp 함께 언급

# [예시 출력]
# - "시장 이성 점수가 -1.0으로 시장이 감정적으로 움직이고 있어 현재 밸류는
#    비합리적인 상태입니다. 공포탐욕 19로 극도 공포 구간이 함께 부각됩니다."
# - "시장 이성 점수가 +1.5로 시장이 이성적으로 움직여 현재 밸류는
#    합리적이라 판단됩니다."

# [왜 이 방식?]
# - 이성 점수와 밸류는 서로 보완 — 이성적이면 가격이 펀더멘털에 가깝고, 감정적이면
#   가격이 펀더멘털에서 벗어나 있음. 둘을 묶어 해석하면 현재 가격의 "신뢰도"가
#   직관적으로 전달됨.
# - 사용자가 매번 다른 신호만 보면 일관성이 떨어져, "이성×밸류" 라는 고정 축을
#   매일 보면서 다른 보조 신호로 컨텍스트를 추가하는 구조가 더 안정적.

# [검증]
# - python ast.parse OK


# ════════════════════════════════════════════════════════════════════════════
# [61] 2026-04-30 (UTC) — 홈 헤드라인 첫 문장 고정 템플릿화
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# [60] 의 자유로운 1문장 → 사용자 요청대로 고정 형식으로 변경.
# 사용자 원하는 형식:
#   "시장이 {밸류 라벨} 상태{이지만/이며} 시장 이성 점수가 {부호}{수치}점으로,
#    {합리적/비합리적}인 밸류를 가지고 있습니다."
#
# 핵심 — 밸류 라벨이 "고평가" 여도 이성 점수가 양수면 "합리적인 밸류" 로 판정.
# 즉 라벨은 사실, 이성 점수가 최종 판단을 좌우.

# [수정 파일]
# - api/routers/market_summary.py
#   * _HEADLINE_PROMPTS (KO/EN): 첫 문장을 4-슬롯 고정 템플릿으로 강제
#       슬롯1: {밸류 라벨}  — DB 의 valuation_signal.label 그대로
#       슬롯2: {연결어}     — "이지만" (반전) / "이며" (강화)
#         · 라벨 부정 + 이성 + → 이지만 (고평가지만 합리)
#         · 라벨 긍정 + 이성 - → 이지만 (적정이지만 비합리)
#         · 라벨 부정 + 이성 - → 이며 (고평가에 비합리)
#         · 라벨 긍정 + 이성 + → 이며 (저평가에 합리)
#       슬롯3: {부호}{수치}  — 이성 점수 부호 + 수치
#       슬롯4: {판단}        — 양수=합리적 / 음수=비합리적
#   * 둘째 문장(선택): F&G/RSI/gap/VIX 극단값 또는 |이성점수|>=2 강조

# [예시]
# 라벨 "다소 고평가" + 이성 +0.9 →
#   "시장이 다소 고평가 상태이지만 시장 이성 점수가 +0.9점으로, 합리적인 밸류를 가지고 있습니다."
# 라벨 "고평가" + 이성 -2.3 →
#   "시장이 고평가 상태이며 시장 이성 점수가 -2.3점으로, 비합리적인 밸류를 가지고 있습니다."
# 라벨 "저평가" + 이성 -1.2 →
#   "시장이 저평가 상태이지만 시장 이성 점수가 -1.2점으로, 비합리적인 밸류를 가지고 있습니다."

# [왜 이 형식?]
# - 밸류 라벨(고/저평가)은 단순 z_comp 기반 사실 — 시장이 비싸고 싼지만 알려줌
# - 이성 점수는 "그 가격이 신뢰할 만한가" 의 메타 판단
# - 두 축을 결합해야 "비싸지만 합리적" / "싸지만 비합리적" 같은 미묘한 상황을
#   표현 가능

# [검증]
# - python ast.parse OK


# ════════════════════════════════════════════════════════════════════════════
# [62] 2026-04-30 (UTC) — 탭 전환 시 시장 밸류 섹션 잔존 버그 수정
# ════════════════════════════════════════════════════════════════════════════

# [원인]
# static/js/home.js 의 showTab(idx) — main.js 메인 5탭으로 전환할 때 sector-tab
# 들을 직접 숨기는 목록에 'tab-market-valuation' 누락:
#   ['tab-sector-val', 'tab-sector-mom']  ← market-valuation 빠짐
# 결과: 시장 밸류 탭 한 번 열고 다른 탭 클릭하면 시장 밸류 섹션이 잔존하여
# 두 탭 콘텐츠가 겹쳐 보임.

# [수정]
# - static/js/home.js: showTab() hide 목록에 'tab-market-valuation' 추가
# - templates/stocks.html: home.js?v=24 → ?v=25

# [반대 방향 (다른 탭 → 시장 밸류)]
# showSectorTab 이 .scroll-wrap > main.content 전부 숨긴 뒤 target 만 표시 →
# 이미 정상.


# ════════════════════════════════════════════════════════════════════════════
# [63] 2026-04-30 (UTC) — backfill dedupe 패치 + 재시작 (-u flush)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# Phase 2 backfill (PID 6194) 실행 중 ON CONFLICT 21000 다발:
#   "ON CONFLICT DO UPDATE command cannot affect row a second time"
# 매 ym 실패 시 60s 대기 → 7시간 51분 누적 진행 ~17%, buy_signal_result 0건
# (한 sgg 도 24개월 모두 통과 X). 추정 잔여 30시간+. kill 후 dedupe 패치 + 재시작.

# [원인]
# 같은 batch upsert 안에 동일 UNIQUE 키 row 중복 → Postgres 21000.
# dedupe 누락된 곳:
#   - _re_norm_population (UNIQUE: stats_ym, stdg_cd) — 없었음
#   - _re_norm_mapping    (UNIQUE: ref_ym, stdg_cd, admm_cd) — 없었음
#   - _re_norm_household  (UNIQUE: stats_ym, admm_cd) — 이미 있음 (정상)
# MOIS lv=3 응답이 같은 stdg_cd 를 페이지 경계에서 중복 반환할 가능성.

# [수정 파일]
# - scheduler/job.py
#   1) _re_norm_population: seen_pop set + (stats_ym, stdg_cd) dedupe
#   2) _re_norm_mapping: seen_map set + (ref_ym, stdg_cd, admm_cd) dedupe
#      (build_mapping 내부 dedupe 외 호출자 누적 단계 안전망)
# - scripts/backfill_metro.py
#   1) compute_region_summary 결과 upsert 직전 (stdg_cd, stats_ym) 안전망 dedupe
#   2) print(..., flush=True) — stdout 버퍼링 해소 (python -u 와 함께 사용)

# [재시작]
# nohup python -u scripts/backfill_metro.py --months 24 --hh-months 3 --sleep 0.4 ...
# python -u 로 stdout/stderr 버퍼링 비활성화 → tail -f 실시간 진행 가능. PID 3429.

# [예상 효과]
# - ON CONFLICT 에러 → 0
# - 60s 대기 비용 → 0
# - sgg 당 처리 시간 47분 → ~5~10분 (정상 페이스)
# - 52 sgg 총 ~5~8시간 완료 예상

# [기존 데이터]
# Backfill kill 시점 누적: region_summary 3158, trade 103,648, rent 279,657,
# population 7661, buy_signal 72 (서울만). 모두 idempotent upsert 라 재시작 시
# 같은 row 는 update 만 일어나 안전. buy_signal 은 sgg 끝나야 산출되므로 새
# 패치된 backfill 이 sgg 단위 완성하면 +1씩 증가 시작.


# ════════════════════════════════════════════════════════════════════════════
# [64] 2026-05-01 (UTC) — 부동산 수도권 backfill 완료 (Phase 2)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 어제 dedupe 패치 후 24개월 backfill 시도 → MOIS quota 도달 + sgg 당 30분
# 페이스로 25시간 예상. 5시간 한계 위해 (1) compute_buy_signal 최소 요건 2개월
# 검증 → 24개월 → **3개월** 단축, (2) --max-minutes 120 분할 batch 도입.
# 2회 batch (각 ~120분) 로 52 sgg 모두 처리. buy_signal stats_ym NULL 버그
# 발견 → setdefault 가 아닌 무조건 set 으로 수정 + 일괄 재산출 스크립트 작성.

# [신규 파일]
# - scripts/recompute_metro_signals.py
#     수도권 신규 52 LAWD_CD 의 buy_signal 만 일괄 재산출.
#     DB 시계열만 사용 (외부 API 0회), ~18s 소요.
#     compute_buy_signal 가 stats_ym 을 None 으로 set 하는 버그 회피 — 결과 dict 의
#     stats_ym 을 ts[-1].ym 으로 강제 덮어씀.

# [수정 파일]
# - scripts/backfill_metro.py
#     1) --max-minutes N 옵션 추가 (분할 batch). 매 sgg 시작 직전 elapsed 체크,
#        도달 시 다음 회차 안내(--start-from XXXXX)와 함께 종료.
#     2) signal_rec.setdefault("stats_ym", ...) → 무조건 assignment.

# [실측 결과 (2회 batch + recompute)]
# Batch 1 (28110~41590, 28 sgg, 2:16) — 1차 시도, signal 모두 fail
# Batch 2 (41610~41465, 24 sgg, 1:59) — 2차 시도, signal 여전히 fail (setdefault 결함)
# recompute_metro_signals.py — 18초 만에 50/52 sgg 의 signal 산출
#                              (28720 옹진군 + 41590 화성시 = ts 부족 skip)
#
# 최종 누적 (어제 시작 vs 오늘 완료):
#   region_summary       1,049 → 4,650  (+3,601)
#   real_estate_trade    24,223 → 136,617 (+112,394)
#   real_estate_rent     ≈    → 342,549 (대량)
#   mois_population      1,912 → 12,289 (+10,377)
#   buy_signal_result      72 →   122   (+50, 서울 72 + 인천 9 + 경기 41)
#
# signal 분포: 매수 53 / 관망 36 / 주의 33

# [다음 작업]
# (a) 24개월 backfill — 별도 batch (시간 여유 있을 때, 시그널은 충분히 산출됨)
# (b) scheduler/job.py 의 Step 9 sleep 누락 패치 (전국 cron 정상화)
# (c) 28720 옹진군 / 41590 화성시 ts 부족 원인 조사 (실제 거래 X 거나 데이터 문제)
# (d) 월 1회 부동산 backfill cron 분리 등록 (CronTrigger(day=1, hour=3))


# ════════════════════════════════════════════════════════════════════════════
# [65] 2026-05-01 (UTC) — 시장 밸류 첫 사용자 latency 60초 → 3.3초
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 사용자 피드백: 시장 밸류에이션 탭의 첫 사용자(서버 재시작/배포 직후) 로딩
# 너무 느림. 분석 결과 매 호출마다 (1) Shiller XLS 다운로드(~10s) (2) Groq LLM
# 호출(~5s) (3) yfinance backfill(legacy 시 ~30s) 가 일어남. 사용자 의도대로
# "스케줄러가 미리 다 계산해 DB 적재 → endpoint 는 select 만" 으로 재설계.

# [수정 파일]
# - supabase_tables.sql: valuation_signal 에 2 컬럼
#     interpretation TEXT, baseline_snapshot JSONB
# - api/routers/macro.py: 두 helper 추출 + endpoint 단순화
#     1) build_baseline_snapshot(baselines) — 5Y baseline JSONB 형태
#     2) build_valuation_interpretation(today, baselines) — Groq LLM + fallback
#     3) GET /valuation-signal: backfill·LLM·Shiller 호출 모두 제거.
#        DB select(latest+history) 만. interpretation/baseline_snapshot 미적재
#        legacy row 면 안전망으로 on-the-fly 계산 (단 결과 DB 저장 X — scheduler 책임)
# - scheduler/job.py [Step 5d] 확장:
#     fetch_valuation_signal_today() → enrich(baseline + LLM) → upsert
#     매일 1회 LLM 호출 (이전엔 endpoint 가 24h 캐시 만료마다 호출)

# [DDL — prod Supabase 에 1회 실행]
ALTER TABLE valuation_signal
    ADD COLUMN IF NOT EXISTS interpretation    TEXT,
    ADD COLUMN IF NOT EXISTS baseline_snapshot JSONB;

# [Latency 측정 (로컬)]
# 1차 호출 (서버 재시작 직후, 메모리 캐시 비어있음):
#   이전: ~60초 (Shiller XLS + Groq LLM + yfinance backfill)
#   신규: 3.3초 (DB select 2회만 — latest + history 60)
# 2차 호출 (메모리 캐시 hit):
#   12ms (이전 대비 변화 없음, 이미 빨랐음)
# → 첫 사용자 체감 약 18× 개선. 외부 API 호출 0회 (LLM/Shiller/yfinance 모두 X)

# [부수 효과]
# - Groq 호출 횟수: 일 ~24회 → 일 1회 (스케줄러 light pipeline 10분 주기 중 1회만)
# - models/valuation_baselines.json 파일 캐시 의존도 감소 (스케줄러도 매일 호출하니 90일 TTL 캐시 정상 유지)
# - Railway 배포 후 첫 사용자 latency spike 해소

# [안전망]
# legacy row (interpretation/baseline_snapshot 둘 다 None) 인 경우 endpoint 가
# on-the-fly 계산 → 응답 즉시. 단 결과를 DB 에 다시 적재하지 않음 (스케줄러 책임).


# ════════════════════════════════════════════════════════════════════════════
# [66] 2026-05-01 (UTC) — 부동산 sgg-overview 11.6s → 1s (app_cache 도입)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 부동산 지도 첫 로딩이 매우 느린 원인 — `/api/realestate/sgg-overview` 가
# region_summary 4650행을 페이지네이션으로 fetch + Python 측에서 시군구별 그룹핑
# = 매 호출마다 ~11.6초. 시장 밸류와 동일 패턴 (사전계산 → DB cache → endpoint
# select) 으로 해결. 추후 다른 endpoint 도 같은 패턴 재사용 위해 generic
# `app_cache` 테이블 신설.

# [신규 테이블]
CREATE TABLE IF NOT EXISTS app_cache (
    cache_key  TEXT PRIMARY KEY,
    payload    JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE app_cache DISABLE ROW LEVEL SECURITY;

# [수정 파일]
# - supabase_tables.sql: app_cache 신설 + DISABLE RLS
# - api/routers/real_estate.py
#     1) compute_sgg_overview(ym='') helper 로 본 계산 로직 추출
#     2) GET /sgg-overview: ym 없으면 app_cache 에서 select(1번) → miss 시
#        helper 호출 + cache 적재 (안전망). ym 지정 시는 ad-hoc 계산
#     3) cache_key 상수 SGG_OVERVIEW_CACHE_KEY = 'sgg_overview'
# - scheduler/job.py [Step 5e] 신설:
#     매 light pipeline 마다 compute_sgg_overview('') → app_cache upsert
#     (Step 5d ERP enrich 와 동일 패턴, 매일 자동 갱신)

# [Latency (로컬 측정, prod Supabase egress 포함)]
# 이전: 11.6초 (region_summary 4650행 페이지네이션 5번 + group by)
# 신규: 평균 ~1초 (app_cache select 1번, payload 13KB)
# → ~11배 개선. prod Railway 는 Supabase 와 같은 region 가능성 → 더 빠를 수도

# [DDL — prod Supabase 1회 실행]
# 위 CREATE TABLE 실행 (사용자 완료).

# [확장 패턴]
# app_cache 는 generic — 추후 무거운 endpoint (stdg-detail, signal/history 등)
# 도 같은 패턴으로 캐시 추가 가능. 키 prefix 로 영역 구분 가능 (ex 'sgg_overview',
# 'market_summary', ...).


# ════════════════════════════════════════════════════════════════════════════
# [67] 2026-05-01 (UTC) — 부동산 SPA detail 복귀 시 지도 재로딩 회피 (frontend cache)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# /realestate 에서 시군구 상세 → 뒤로가기로 지도 복귀 시 MapScreen 이 unmount
# 됐다 재마운트 → useEffect 가 sgg-overview + GeoJSON 다시 fetch → 1~2초 빈
# 지도 표시. SPA 라우팅 기본 동작.

# [수정 파일]
# - frontend-realestate/src/screens/MapScreen.tsx
#     1) module-level 캐시 변수 3개:
#        _cachedPolygons, _cachedOverviews, _cachedGeoJson
#     2) initial state 가 캐시값 (있으면) 으로 즉시 채워짐 → 첫 paint 부터 표시
#     3) useEffect 에서 캐시 hit 시 fetch skip (early return)
#     4) loadPolygons 가 fetchGeoJson() 헬퍼로 GeoJSON 도 캐시
# - static/realestate/{index.html, assets/} 재빌드 (npm run build)

# [효과]
# - 첫 진입: 기존과 동일 (~1초 sgg-overview + ~50ms GeoJSON)
# - detail 복귀: 즉시 (캐시 hit, fetch 0회)
# - 페이지 새로고침: 모듈 다시 로드되므로 캐시 초기화 (1회 fetch 필요)

# [한계]
# - 카카오맵 인스턴스는 매 mount 마다 재생성 (KakaoMap 컨테이너 ref 가 새로
#   생성되므로 inevitable). SDK 자체는 sdkPromise 로 1회만 로드 → 인스턴스
#   생성은 ~100~300ms 정도 (큰 부담 X).
# - 진정한 zero-flash 는 MapScreen 을 항상 mount 시키고 detail 만 overlay
#   구조 변경 필요 (App.tsx 라우팅 재설계). 추후 작업 후보.


# ════════════════════════════════════════════════════════════════════════════
# [68] 2026-05-02 (UTC) — 펀더멘털 인사이트 라벨 단순화 (5종 → 2종)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 펀더멘털 탭의 "RATIONAL GREED" / "IRRATIONAL FEAR" 등 5종 영문 라벨이
# 사용자에게 직관적이지 않음. 사용자 요청대로 noiseScore 부호만 사용해
# "이성적 상태" / "감정적 상태" 2종으로 단순화.

# [수정 파일]
# - static/js/main.js : _buildFgNoiseInsight 재작성
#     기존: SENTIMENT(공포/탐욕) × NOISE(이성/감정) 4 조합 + NEUTRAL = 5 라벨
#     신규: noiseScore >= 0 → '이성적 상태', < 0 → '감정적 상태' 2 라벨
#     공포탐욕 지수는 fgPart prefix 로 메시지에만 표시 (라벨 분기 X)
#     "SENTIMENT × NOISE" 보조 문구 → "시장 이성 점수 ±X.X" 한글 + 숫자
# - templates/stocks.html : main.js?v=114 → ?v=115 (캐시 버스트)

# [효과]
# - 사용자 직관성 ↑ (영문 약어 사라짐, 부호 한 축만 보면 됨)
# - 시장 이성 점수 수치도 함께 표시 (이전엔 라벨로만 추정)


# ════════════════════════════════════════════════════════════════════════════
# [69] 2026-05-02 (UTC) — 추이 그래프 기간 일괄 확대 (1개월·2개월 → 3개월)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 펀더멘털 탭(Noise 30일) + 신호 탭(Crash/Surge 30일) + 시장 밸류 탭(60일)
# 추이 그래프를 모두 90일(3개월) 로 통일.

# [수정 파일]
# - static/js/main.js
#     /api/regime/history?days=30 → 90
#     /api/crash-surge/history?days=30 → 90
# - static/js/i18n.js
#     section.nrChart KO "(30일)" → "(3개월)" / EN "(30d)" → "(3M)"
#     section.csChart 동일
# - api/routers/macro.py
#     fetch_valuation_signal_history(days=60) → 90
# - static/js/home.js
#     렌더 차트 라벨 "2개월 전" → "3개월 전"
# - templates/stocks.html
#     "(30일)" 두 곳 + "2개월 추이" → "3개월"
#     캐시 버스트: i18n.js?v=3→4, main.js?v=115→116, home.js?v=25→26

# [DB 추가]
# valuation_signal 90일 보장 — backfill_valuation_signal(days=90) 1회 실행
# (62 → 90 row 적재).

# [검증]
# /api/macro/valuation-signal: history 90 row (2025-12-22 ~ 2026-05-01)
# /api/regime/history?days=90: 90 row
# /api/crash-surge/history?days=90: 90 row


# ════════════════════════════════════════════════════════════════════════════
# [70] 2026-05-02 (UTC) — buy_signal 비교 기준 변경 + stdg-월 group by 버그 패치
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 사용자 발견 — FeatureCard 의 "거래량 -53.7% 위축, 가격 -36.8% 하락" 비교 기준
# 모호 (거래량은 장기 평균, 가격은 MoM, 비대칭). 추가로 코드 분석 중 근본 버그
# 발견: compute_buy_signal 가 받는 ts 가 stdg-월 매트릭스(같은 ym 에 여러 stdg
# row) 인데 latest=ts[-1] 로 단일 row 만 사용 → 시군구 단위 시그널이 임의 한
# 법정동 row 의 trade_count 만으로 산출됨. 두 가지 동시 패치.

# [수정 파일]
# - processor/feature6_buy_signal.py
#     1) _group_ts_by_ym(ts) 신규 — stdg-월 매트릭스를 sgg-월 시계열로 정규화
#        (trade_count·population sum / median_price_per_py 평균)
#     2) compute_buy_signal 가 ts[0].stdg_cd 감지 시 자동 group by
#     3) 비교 기준 변경:
#        기존: latest=ts[-1] vs mean(ts[:-1])
#        신규: target=ts[-2] (이전 달, t-1) vs mean(ts[:-2]) (그 이전 모든 달)
#        ─ 이번 달(t) 데이터는 월 중 집계라 미완성/노이즈 가능, t-1 이 안정
#     4) 가격도 MoM (단월 비교) → 평균 비교 통일 (price_mom_pct 의미는 같지만 base 변경)
#     5) 인구는 t-1 vs t-2 단일 (인구 변동 작아 평균 의미 적음)
#     6) target_ym = target.get('ym') (t-1 기준)
# - scripts/backfill_metro.py
#     signal_rec.stats_ym 강제 덮어쓰기 → setdefault (compute_buy_signal 가 정확히 set)

# [DB 정리]
# 옛 코드의 t (이번 달 = 202604) 기준 row 50개 삭제 → 신 코드의 t-1 (202603) 73 row 활성.
# 잔존 분포: 202601 25 + 202602 25 + 202603 73 (서울 옛 + 신 합쳐 73 sgg).

# [signal 분포 변화]
# 이전 (122 row): 매수 53 / 관망 36 / 주의 33
# 신규 (73 row, 옛 row 50 삭제 후 새로 산출): 매수 41 / 관망 24 / 주의 8
# → "주의" 33→8 대폭 감소. 이전 단일 stdg row 노이즈 + 이번 달 미완성 데이터가
#   부정 시그널 만들었던 영향 정상화.

# [예시 — 남양주(41360)]
# 이전 row (202604): trade_chg -53.73%, price_mom -36.84%, score -60 ('주의')
#   ─ 임의 stdg row 의 4월 거래량(126건, 부분집계) 이 평균과 비교돼 노이즈
# 신규 row (202603): trade +23.49%, price +1.18%, score 14.4 ('관망')
#   ─ 시군구 합산(841건) 이 직전 평균(681건) 대비 23% 증가 = 정상 신호


# ════════════════════════════════════════════════════════════════════════════
# [72] 2026-05-02 (UTC) — backfill_metro 12개월 전체 + mapping per-sgg 캐시
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 시군구 시계열 차트 의미 있는 길이(서울 5개월·경기 3.5개월 → 12+개월) 확보.
# 77 LAWD_CD (서울 25 + 인천 10 + 경기 42) × 12개월 backfill.

# [수정 파일]
# - scripts/backfill_metro.py
#   1) METRO_NEW_LAWD_CDS 에 서울 25 LAWD_CD 추가 (52 → 77).
#      변수명은 역사적 유지 — 실제론 수도권 전체.
#   2) mapping per-sgg 캐시 — sgg 당 첫 ym 1회만 build_mapping 호출,
#      나머지 ym 의 region_summary 산출에 같은 mapping 재사용.
#      (행정구역 코드 변경 1년 단위 → 12개월 안에서 무시 가능)
#      sgg 당 mapping 단계 ~5분 → ~30초.

# [실측 — 281.4분 wall-clock (4시간 41분)]
# 사전 추정 ~10시간 → 실제 절반 (mapping cache + sleep 0.3 빠른 fetch).
# region_summary: 4,650 → 11,351 (+6,701 row)
# 커버리지:
#   서울 25 sgg: 5개월 → 11~24개월 (대부분 24)
#   인천 9 sgg: 22.6 → 12~25개월
#   경기 75 sgg: 3.5 → 1~25개월 (대부분 12+)

# [재산출]
# - compute_buy_signal: 75 sgg, 29초.
#   분포 (이전 → 신규): 매수 41/41 · 관망 24/24 · 주의 8/10
# - app_cache 갱신:
#   · sgg_overview: 109 sgg (region_summary 다른 ym 의 sgg 일부 잡혀 더 많음)
#   · ranking: 거래량회복 TOP=[구리시, 도봉구, 이천시, 연천군, 부평구]
#              가격상승 TOP=[분당구 +15.6%, 강북구, 강동구, 동작구, 구리시]

# [실행 메모]
# setsid + nohup + disown 으로 detached session — shell 종료에도 살아남음.
# /tmp/backfill_metro.log 에 진행 로그 + 매 ym 별 trades/rents/pop/sum 카운트.


# ════════════════════════════════════════════════════════════════════════════
# [71] 2026-05-02 (UTC) — _default_ym 전월 → 전전월 (직전 완성월)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# buy_signal 비교 기준이 t-1 로 변경된 후 상세/요약 endpoint 도 "지난달" =
# 직전 완성월 (전전월) 로 통일. 전월(t-1) 도 MOIS 인구통계 미집계 + MOLIT
# 신고지연으로 부분 집계라 노이즈. 전전월(t-2)부터 안정.

# [수정 파일]
# - api/routers/real_estate.py
#     _default_ym() 변경: today → 전월 last day → 전전월 last day → strftime
#     ex 5월 2일 → 202604 (이전) → 202603 (신규)

# [영향 endpoint]
# /summary, /trades, /rents, /population, /household, /mapping, /sgg-overview,
# /stdg-detail (모두 ym 미지정 시 _default_ym 사용)

# [캐시 갱신]
# app_cache sgg_overview 1회 재산출 — 75 sgg 중 74개 stats_ym=202603,
# 1개만 (강화군 추정) 데이터 부족으로 202604.

# [검증]
# /api/realestate/summary?sgg_cd=11680: 13 row, ym=202603 ✓
# /api/realestate/sgg-overview: 75개, 74 row stats_ym=202603 ✓


# ════════════════════════════════════════════════════════════════════════════
# [72] 2026-05-02 (UTC) — 부동산 지속성 + 랭킹 신규 (5+6번 기능)
# ════════════════════════════════════════════════════════════════════════════
# [개요]
# 사용자 요청 두 기능 추가:
#   5) 가격·거래량 N개월 연속 추이 → FeatureCard 요약 문장에 편입
#   6) 수도권 시군구 랭킹 카드 (거래량 회복 + 가격 상승 TOP5) → 새 탭

# [신규 / 수정 — 5)]
# - processor/feature6_buy_signal.py
#   · _consecutive_trend(values, end_idx) helper — N개월 연속 동일 부호 카운트
#   · feature_breakdown 에 3 필드 추가:
#       price_consec_months   (+N 연속 상승 / -N 연속 하락)
#       trade_consec_months
#       trade_vs_long_ratio   (t-1 거래량 / 직전 12개월 평균)
# - frontend-realestate/src/components/FeatureCard.tsx
#   · buildSummary 재작성 — "매매가는 3개월 연속 상승 중" / "거래량은 12개월
#     평균보다 낮은 수준" 식 명사형 문장 조합
# - frontend-realestate/src/types/api.ts
#   · BuySignal.feature_breakdown 에 신 3 필드 추가

# [신규 — 6)]
# - api/routers/real_estate.py
#   · _SGG_KO_NAMES dict (수도권 75 시군구 한국어 이름 매핑)
#   · compute_ranking() — buy_signal_result + sgg_overview 캐시 fetch 후
#     trade_vs_long_ratio 내림차순 TOP 5 + change_pct_3m 내림차순 TOP 5
#   · GET /ranking — app_cache 'ranking' 에서 select, miss 시 fallback 적재
# - scheduler/job.py [Step 5f] 신설
#   · 매 light pipeline 에서 compute_ranking() → app_cache upsert
# - frontend-realestate/src/screens/RankingScreen.tsx (신규)
#   · 거래량 회복 + 가격 상승 두 섹션, 시군구 클릭 → /region/:sggCd 이동
# - frontend-realestate/src/components/MobileLayout.tsx
#   · 4번째 탭 "메뉴" 자리 → "랭킹" (🏆 아이콘, /ranking 경로)
# - frontend-realestate/src/App.tsx
#   · /ranking 라우트 추가
# - frontend-realestate/src/api/endpoints.ts
#   · ENDPOINTS.ranking 추가

# [실측 결과 (2026-05-02)]
# 거래량 회복: 고양 일산동구(1.66배), 포천(1.55), 안성(1.54), 김포(1.5), 구리(1.5)
# 가격 상승: 강북구(+14.58%), 강동구(+14.34%), 동작구(+11.27%), 구리시(+11.24%), 광진구(+10.48%)

# [한계]
# - region_summary 시계열이 3~4개월만 있어 price_consec_months 최대값이 1~2.
#   24개월 backfill 추가 시 "3개월 연속" 같은 더 강한 신호 노출 가능.


# ════════════════════════════════════════════════════════════════════════════
# [70] 2026-05-02 (UTC) — 국내 주식 (KR) Stage 1: Foundation
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 미국 주식만 분석하던 Passive 에 국내(KR) 주식 분석 추가. 1.5~2주 분량의
# 작업을 단계로 쪼갠 첫 단계 — 데이터 수집 인프라·DB 스키마·UI 토글의
# 뼈대만 구축. 실제 KR 데이터 적재·모델 학습은 Stage 2 부터.
#
# 사용자 결정:
# - 5개 탭(시장·펀더멘털·신호·섹터·시장 밸류) 모두 한국 버전 만든다
# - 섹터 ETF 는 KODEX·TIGER 시리즈 사용
# - 데이터 소스는 추천 따름 — pykrx + FinanceDataReader + ECOS
# - UI 는 헤더 토글 (옵션 A) — 한 클릭으로 전체 화면 region 전환

# [구조 결정 — 하이브리드(C) 채택]
# - DB 가공·결과 테이블에 region 컬럼 추가 (default 'us', 기존 행 자동 us)
# - collector 는 region 별 별도 모듈 (market_data.py / market_data_kr.py)
# - processor (HMM·XGBoost) 는 region 파라미터화 — 모델 객체만 region 별
#   별도 저장 (models/noise_hmm_us.pkl ↔ _kr.pkl)
# - 미국 SPDR 13개 ↔ 한국 KODEX/TIGER 10개 매핑 (XLI/XLU/XLC 는 한국 ETF
#   부족으로 제외)

# [신규 파일]
# - migrations/2026_04_30_add_region_column.sql
#     · 가공 테이블 7종 (noise_regime, crash_surge, sector_cycle_result,
#       sector_valuation, valuation_signal, chart_predict, market_regime)
#     · raw 테이블 4종 (macro_raw, sector_macro_raw, index_price_raw,
#       fear_greed_raw)
#     · UNIQUE 제약을 (date) → (region, date) 또는 (region, date, ticker) 로 변경
#     · BEGIN/COMMIT 트랜잭션 — Supabase SQL Editor 1회 실행
#
# - collector/market_data_kr.py (스켈레톤 + 작동 함수 일부)
#     · fetch_kospi_price_history(days)             — pykrx 1001
#     · fetch_kospi200_price_history(days)          — pykrx 1028
#     · fetch_vkospi_history(days)                  — FinanceDataReader 'VKOSPI'
#     · fetch_kospi_per_pbr(days)                   — pykrx index_fundamental
#     · fetch_kr_10y_treasury(months)               — ECOS 817Y002 (Stage 2)
#     · fetch_foreign_institution_flow(days)        — pykrx market_trading_value
#     · fetch_kospi200_putcall_ratio(days)          — Stage 2 (KRX 직접)
#     · compute_kr_fear_greed_synthesized()         — Stage 2 (가중치 결정 후)
#
# - collector/sector_etf_kr.py
#     · SECTOR_ETF_KR 매핑 (10종, ticker → kr_name/en_name/us_proxy)
#     · fetch_sector_etf_prices_kr(days)            — pykrx etf_ohlcv
#     · fetch_sector_etf_per_pbr_kr()               — Stage 2 (구성종목 가중)
#
# - static/js/region.js (전역 region 상태)
#     · getRegion()                                 — localStorage 'region'
#     · setRegion(r)                                — 'us' | 'kr' 만 허용
#     · withRegion(url)                             — URL 에 ?region= 자동 부착
#     · DOMContentLoaded 시 토글 클래스 동기화 + KR 모드 안내 배너 삽입
#     · 토글 클릭 → region 반전 → location.reload() (단순 리프레시)

# [수정 파일]
# - requirements.txt: pykrx, finance-datareader 추가
#
# - templates/stocks.html
#     · header-right 에 region 토글 (.region-toggle, 🇺🇸/🇰🇷)
#     · /static/js/region.js?v=1 i18n.js 보다 먼저 로드
#
# - static/css/main.css
#     · .region-toggle (lang-btn 옆 인라인 플렉스, US/KR 플래그 둘 중 active)
#     · .region-toggle.region-mode-us .region-us / .region-mode-kr .region-kr
#       에 각각 white card bg + box-shadow 강조
#     · .kr-coming-soon (점선 배너, KR 모드일 때 home-view 상단 삽입)

# [구체 매핑 — KODEX/TIGER 10종]
# 139260 TIGER 200 IT       ↔ XLK
# 091160 KODEX 반도체         ↔ SOXX
# 300610 KODEX 게임산업       ↔ IGV
# 091170 KODEX 은행          ↔ XLF
# 139250 TIGER 200 에너지화학  ↔ XLE
# 266420 KODEX 헬스케어       ↔ XLV
# 091180 KODEX 자동차        ↔ XLY (가장 가까운 대체)
# 117680 KODEX 철강          ↔ XLB
# 341850 TIGER 리츠부동산인프라 ↔ XLRE
# 227560 TIGER 200 생활소비재  ↔ XLP

# [Stage 2 계획 (다음 turn)]
# 1) KR collector 함수 채우기 — placeholder 함수들 실제 구현
# 2) repository.py 의 fetch_* / upsert_* 에 region 파라미터 추가
# 3) /api/* 엔드포인트들 region 쿼리 받아 분기
# 4) scheduler/job.py 가 light 모드에서 KR 데이터도 수집·적재
# 5) HMM·XGBoost 한국 학습 (KOSPI 기반)

# [Stage 3 계획]
# 1) 한국 합성 F&G 점수 (가중치 결정 필요 — 사용자 결정 사항)
# 2) Crash/Surge 임계값 한국 시장에 맞춰 조정 (변동성 분포 다름)
# 3) Shiller CAPE 한국 등가 산출 (KOSPI 10년 평균 EPS / 현재가)
# 4) ERP 계산 — KOSPI PER 역수 - 10Y KTB

# [실행 필요 — 사용자 1회]
# Supabase SQL Editor 에서 migrations/2026_04_30_add_region_column.sql 실행.
# 기존 모든 행이 region='us' 로 자동 태그됨.

# [검증]
# - python ast.parse: market_data_kr.py / sector_etf_kr.py 둘 다 OK
# - node --check: region.js OK
# - 토글 자체는 Stage 2 데이터 연결 전이라 KR 클릭 시 "준비 중" 배너만 표시


# ════════════════════════════════════════════════════════════════════════════
# [71] 2026-05-02 (UTC) — KR Stage 2A: Repository region 파라미터화
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# Stage 1 의 DB region 컬럼 위에서 repository 함수들이 실제 region 별 데이터를
# 분리해 읽고 쓰도록 region 파라미터 추가. 모든 함수의 default 는 'us' 라
# 기존 호출자(API 라우터, 스케줄러)는 변경 없이 그대로 동작.

# [수정 파일]
# - database/repositories.py — 12개 함수 region 파라미터 추가:
#   * upsert_macro / fetch_macro / fetch_macro_latest / fetch_macro_latest2
#   * upsert_regime / fetch_regime_current / fetch_regime_current_all /
#     fetch_regime_history
#   * upsert_fear_greed / fetch_fear_greed_latest / fetch_fear_greed_latest2
#   * upsert_index_prices / fetch_index_prices_latest
#   * upsert_sector_macro / fetch_sector_macro_history
#   * upsert_sector_cycle / fetch_sector_cycle_latest / fetch_sector_cycle_history
#   * upsert_noise_regime / fetch_noise_regime_current / _history / _all
#   * upsert_crash_surge / fetch_crash_surge_current / _history
#   * upsert_chart_predict / fetch_chart_predict
#   * upsert_sector_valuation / fetch_sector_valuation_latest / _history
#   * upsert_valuation_signal / upsert_valuation_signal_bulk /
#     fetch_valuation_signal_latest / _history
#
# - migrations/2026_04_30_fix_market_regime_constraint.sql 신규
#   * 직전 마이그레이션에서 (region, date) 로 잘못 잡은 market_regime 제약을
#     (region, date, index_name) 합성 키로 재설정
#   * sp500/ndx/sox 3개 인덱스가 같은 날짜 공존하므로 index_name 도 키에 포함

# [패턴]
# - upsert: record = {**record, 'region': region} → 모든 행에 region 박힘
#           on_conflict 도 "region,date" 또는 "region,date,ticker" 로 변경
# - fetch: .eq("region", region) 필터 추가
# - default 'us' 유지 → 기존 호출자 100% 하위호환

# [실행 필요 — 사용자 1회]
# Supabase SQL Editor 에서
# migrations/2026_04_30_fix_market_regime_constraint.sql 실행.

# [검증]
# - python ast.parse repositories.py OK

# [Stage 2B 다음 (다음 turn)]
# - api/routers/*.py 의 region 쿼리 파라미터 받기 + repository 에 전달
# - LLM 프롬프트(market_summary.py) 도 region 분기


# ════════════════════════════════════════════════════════════════════════════
# [72] 2026-05-02 (UTC) — KR Stage 2B: API 라우터 + JS fetch 자동 region 부착
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# Stage 2A 의 repository region 파라미터화 위에서 모든 stock-related API 라우터가
# ?region= 쿼리를 받아 repository 에 전달. JS 측은 window.fetch 를 몽키패치해
# /api/* 호출에 자동으로 ?region= 을 붙인다. localStorage 'region' 으로 상태 유지.

# [수정 파일]
# - api/routers/regime.py
#     · /current, /history, /score-distribution 모두 region 인자 추가
#     · _norm_region() 헬퍼 ('us'|'kr' 만 허용, 그 외 'us' 폴백)
#
# - api/routers/crash_surge.py
#     · /current, /history, /direction 에 region 인자
#     · _dir_cache 키를 region 별로 분리 (cs_data_us, cs_data_kr 등)
#
# - api/routers/sector_cycle.py
#     · /current, /history, /macro-history, /valuation, /holdings-perf 에 region
#
# - api/routers/macro.py
#     · /latest, /fear-greed, /valuation-signal 에 region
#     · _val_sig_cache 키 region 별 분리
#
# - api/routers/index_feed.py
#     · /latest 에 region
#
# - api/routers/market_summary.py (★ 큰 변경)
#     · /today, /ai-summary, /home-headline, /ai-explain 모두 region 받기
#     · _build_indicator_text / _build_home_indicator_text / _build_explain_text
#       모두 region 파라미터 추가, 내부 fetch_* 호출에 region 전달
#     · _ai_cache, _headline_cache, _explain_cache 키 형식: f"{lang}_{region}"
#       또는 f"explain_{tab}_{lang}_{region}"
#     · 캐시 자료구조를 dict 평면화 (이전: nested {'ko': {...}, 'en': {...}})
#
# - database/repositories.py
#     · _fetch_all_pages() 에 region 인자 추가 (None 이면 필터 안 함)
#     · fetch_crash_surge_all / fetch_macro_closes 도 region 받기
#
# - static/js/region.js (★ 자동 region 부착)
#     · window.fetch 몽키패치 — input 이 문자열이고 /api/ 로 시작하면
#       URL 에 ?region={current} 자동 부착 (이미 region= 있으면 그대로)
#     · 모든 main.js / home.js / sector.js 의 fetch 호출이 자동 region 적용
#       → JS 파일들 수정 불필요
#
# - templates/stocks.html
#     · region.js?v=1 → ?v=2

# [동작 흐름]
# 1) 사용자가 헤더 🇰🇷 클릭 → setRegion('kr') → location.reload()
# 2) 페이지 재로드 시 region.js 가 fetch 몽키패치
# 3) 모든 후속 /api/regime/current, /api/macro/fear-greed, ... 호출에
#    자동으로 ?region=kr 부착
# 4) 백엔드 라우터가 region='kr' 파라미터로 repository 호출
# 5) DB 에서 region='kr' 행 조회 (현재 비어 있음 — Stage 2C 에서 채움)
# 6) 응답 비어있으면 화면에 데이터 없음 표시 (KR 데이터 미적재 상태)

# [현재 한계]
# - DB 에 region='kr' 행이 아직 없으니 KR 토글 시 모든 카드가 비어 보임
# - "준비 중" 배너가 home-view 상단에 노출되어 사용자에게 안내
# - Stage 2C (다음 turn) 에서 KR 데이터 collector + scheduler 통합

# [검증]
# - python ast.parse: 7개 파일 모두 OK (repositories, regime, crash_surge,
#   sector_cycle, macro, index_feed, market_summary)
# - node --check: region.js OK


# ════════════════════════════════════════════════════════════════════════════
# [73] 2026-05-02 (UTC) — KR Stage 2C: KR collector 실제 구현 + 야간 파이프라인
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# Stage 2A·2B 의 인프라(repository / API / JS) 위에서 실제 KR 데이터 수집을 시작.
# pykrx + FinanceDataReader 기반 KOSPI 매크로·KODEX/TIGER 섹터 ETF·KR 10Y 국채를
# macro_raw·index_price_raw 의 region='kr' 행으로 적재.

# [신규 파일]
# - collector/market_data_kr.py 실제 구현 — 6개 fetch 함수 + record 빌더:
#     · fetch_kospi_price_history(days)        — pykrx '1001'
#     · fetch_kospi200_price_history(days)     — pykrx '1028'
#     · fetch_vkospi_history(days)             — FinanceDataReader 'VKOSPI'
#     · fetch_kospi_per_pbr(days)              — pykrx index_fundamental
#     · fetch_kr_10y_treasury(days)            — FDR 'KR10YT=RR'
#     · fetch_kr_3y_treasury(days)             — FDR 'KR3YT=RR' (yield_spread 용)
#     · fetch_foreign_institution_flow(days)   — pykrx market_trading_value
#     · compute_kr_macro_history(days) ★ macro_raw 매핑된 record 리스트
#     · fetch_kr_index_prices_today() — KODEX 200/TIGER 200/KOSDAQ150 ETF 가격
#
# - scheduler/job_kr.py 신규 — 일일 KR 파이프라인:
#     · run_kr_pipeline() — macro_raw + index_price_raw + 섹터 ETF 3-step 적재
#     · 매일 16:00 KST (UTC 07:00) 1회 — KR 장 마감 30분 뒤
#
# - scripts/backfill_kr.py — 1회성 백필 스크립트:
#     · python -m scripts.backfill_kr [--days N]
#     · macro 30일 + index_price 오늘 + 섹터 ETF 10종 적재

# [수정 파일]
# - api/app.py: BackgroundScheduler 에 'kr_daily_pipeline' 추가 (CronTrigger
#   hour=7 minute=0 UTC = 16:00 KST). pykrx 미설치 등 ImportError 시 try/except.

# [macro_raw 스키마 매핑]
# 미국 컬럼 명을 그대로 쓰되 KR 등가 데이터 적재:
#     sp500_close   ← KOSPI 종가
#     sp500_return  ← KOSPI 일간수익률 (%)
#     sp500_vol20   ← KOSPI 20일 연율화 std (%)
#     sp500_rsi     ← KOSPI RSI(14)
#     vix           ← VKOSPI
#     tnx           ← KR 10Y KTB rate (%)
#     yield_spread  ← (KR 10Y - KR 3Y)
#     dxy_return    ← null (한국 직접 등가 없음)
#     putcall_ratio ← null (Stage 3 — KRX 옵션)
# i18n 라벨에서 region='kr' 일 때 "S&P500" → "KOSPI" / "VIX" → "VKOSPI" 분기 예정.

# [실행 필요 — 사용자]
# 1) 의존성 설치 (이미 완료):
#    .venv/bin/pip install pykrx finance-datareader
# 2) 1회 백필:
#    python -m scripts.backfill_kr
#    → macro 30일 + index 오늘 + 섹터 ETF 10종 적재 (~1~2분)
# 3) 이후 자동 갱신: 매일 16:00 KST 스케줄러가 run_kr_pipeline 호출

# [현재 한계]
# - noise_regime / crash_surge / valuation_signal — KR 모델 학습 전이라 미적재
# - 헤더 🇰🇷 토글 시: 시장 탭(macro_raw 기반)·signal/index conveyor 만 데이터 보임,
#   펀더멘털·신호·시장 밸류 탭은 아직 비어 있음
# - sector_etf_kr.py 의 PER/PBR fetch — pykrx ETF fundamental 미지원, Stage 3
#   에서 구성종목 가중평균으로 자체 산출 예정

# [Stage 3 (다음 turn 후보)]
# 1) KR HMM noise_regime 학습 — KOSPI 8피처 자체 정의 (fundamental_gap 한국식,
#    erp_zscore KR, residual_corr KR 5종, vix_term=VKOSPI, hy_spread=회사채 KR,
#    realized_vol KOSPI)
# 2) KR XGBoost crash/surge — KOSPI 일간 변동 라벨링 + KR feature
# 3) KR sector_cycle_result — 한국 매크로(ECOS PMI/실업률/금리스프레드) 기반 phase
# 4) KR valuation_signal — KOSPI ERP (PER 역수 - KR 10Y) + VKOSPI z + DD60
# 5) 합성 한국 F&G — VKOSPI + 외국인 순매수 + 신용잔고 + 거래대금 4-요소 가중

# [검증]
# - python ast.parse: 5개 신규/수정 파일 모두 OK
# - 사용자 환경 backfill 실행 결과로 region='kr' 행 수 확인 필요


# ════════════════════════════════════════════════════════════════════════════
# [74] 2026-05-02 (UTC) — KR Stage 2C+: AI 차트 탭 KR ETF 지원
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# AI 차트 탭(미국 ETF SPY/QQQ/VOO 등 캔들스틱)에 KR 모드 추가. 헤더 🇰🇷 토글 시
# KODEX/TIGER 시리즈 12종이 티커 칩으로 표시되고 pykrx 로 OHLCV 가져와 캔들 그려짐.

# [수정 파일]
# - api/routers/chart.py
#     · CHART_TICKERS_KR (12종 6자리 종목코드) 신설
#     · _is_kr_ticker(ticker) — 6자리 숫자 판별
#     · _download_kr(ticker, interval) — pykrx get_etf_ohlcv_by_date,
#       한글 컬럼(시가/고가/저가/종가/거래량) → 영어 리네임,
#       1wk/1mo 는 일봉 후 리샘플
#     · _download_with_fallback() 진입부에서 KR 티커는 _download_kr 분기
#     · /ohlc 검증을 CHART_TICKERS + CHART_TICKERS_KR 둘 다 허용
#     · /predict 는 KR 티커 → 'KR 예측 모델 미학습' 응답 (Stage 3)
#
# - static/js/chart.js
#     · CHART_MAIN_TICKERS_US / CHART_MAIN_TICKERS_KR 분리
#     · TICKER_NAMES 에 KODEX/TIGER 한국어 이름 12개 추가
#     · _currentRegion() / _chartTickers() 헬퍼 — region 별 ticker 목록 반환
#     · 초기 _chartTicker — KR 모드면 '069500' (KODEX 200), US 면 'VOO'
#     · renderTickerChips() — 현재 region 의 ticker 목록 렌더, region 전환 시
#       _chartTicker 가 새 region 목록에 없으면 첫 ticker 로 리셋
#     · 칩 라벨 — KR 은 한국어 이름, US 는 ticker 자체 (현 동작 유지)
#     · updatePredictBtnVisibility() — KR 모드면 예측 버튼 숨김
#
# - templates/stocks.html: chart.js?v=24 → ?v=25

# [KR ETF 12종 (US SPDR 매핑)]
# 069500 KODEX 200            ↔ SPY (대표 시장 ETF)
# 102110 TIGER 200            ↔ SPY 대안
# 232080 TIGER 코스닥150       ↔ QQQ (성장주)
# 229200 KODEX 코스닥150       ↔ QQQ 대안
# 091160 KODEX 반도체          ↔ SOXX
# 139260 TIGER 200 IT         ↔ XLK
# 091170 KODEX 은행           ↔ XLF
# 266420 KODEX 헬스케어        ↔ XLV
# 139250 TIGER 200 에너지화학   ↔ XLE
# 091180 KODEX 자동차         ↔ XLY (가장 가까운 대체)
# 117680 KODEX 철강           ↔ XLB
# 341850 TIGER 리츠           ↔ XLRE

# [동작 흐름]
# 1) 헤더 🇰🇷 클릭 → location.reload()
# 2) chart.js 가 region='kr' 감지 → _chartTicker='069500' 초기화
# 3) renderTickerChips() 가 KR 12종 칩 렌더 (한국어 이름)
# 4) loadCandleChart() → /api/chart/ohlc?ticker=069500&region=kr
# 5) 백엔드: _is_kr_ticker → _download_kr → pykrx get_etf_ohlcv_by_date
# 6) 한글 컬럼 영어 리네임 → 일봉 캔들 렌더

# [한계 (Stage 3 후속)]
# - 30일 예측 버튼은 KR 모드에서 숨김 (XGBoost/Prophet 학습 데이터 미준비)
# - chart_predict_result region='kr' 행 0건
# - KR ETF historical 길이 — 일부 신규 ETF (341850 TIGER 리츠) 는 1년 미만

# [검증]
# - python ast.parse chart.py OK / node --check chart.js OK
# - 사용자 backfill 실행 후 브라우저에서 토글 → KR 차트 렌더링 확인


# ════════════════════════════════════════════════════════════════════════════
# [75] 2026-05-02 (UTC) — KR Stage 3.1: 시장 밸류 (valuation_signal_kr)
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 미국 시장 밸류 composite z (ERP/VIX/DD60) 의 한국 등가 구현. 모델 학습 불필요한
# 수학 합성 — Stage 3 첫 단계로 가장 작업량 적음. 헤더 🇰🇷 → 시장 밸류 탭이
# 즉시 데이터 노출되도록.

# [수식 (US 와 동일)]
# z_comp_kr = 0.4·z_ERP_kr(5Y) + 0.3·z_VKOSPI(5Y) + 0.3·z_DD60_KOSPI(5Y)
# 라벨: z>1=명확한 저평가, 0~1=다소 저평가, -1~0=다소 고평가, z<-1=명확한 고평가

# [데이터 소스]
# - KOSPI PER:    pykrx get_index_fundamental('1001')        → earnings_yield = 1/PER
# - KR 10Y KTB:   FinanceDataReader 'KR10YT=RR'              → tnx_yield
# - VKOSPI:       FinanceDataReader 'VKOSPI'                 → vix slot
# - KOSPI close:  pykrx get_index_ohlcv('1001')              → 60일 rolling DD

# [신규 파일]
# - collector/valuation_signal_kr.py
#     · _compute_kr_erp_baseline_5y()  — KOSPI 월별 ERP 5년 mean/std
#     · _compute_vkospi_baseline_5y()  — VKOSPI 일별 5년
#     · _compute_kr_dd_baseline_5y()   — KOSPI 60일 rolling DD 5년
#     · get_kr_baselines()             — 3종 합본 + JSON 캐시 (TTL 90일)
#     · compute_composite_z()          — z 산출 (US 함수와 동일 로직)
#     · label_from_z_comp()            — 4단계 라벨
#     · fetch_valuation_signal_today_kr() — 오늘 1행
#     · backfill_valuation_signal_kr(days=90) — 다일 backfill
#
# - models/valuation_baselines_kr.json (자동 생성, TTL 90일)

# [수정 파일]
# - scheduler/job_kr.py
#     · run_kr_pipeline 에 step 3 (valuation_signal) 추가 — fetch_today_kr →
#       upsert_valuation_signal(record, region='kr')
#     · sector ETF step 은 step 4 로 밀림
#
# - scripts/backfill_kr.py
#     · backfill_valuation() 함수 추가
#     · default --days 30 → 90 (시장 밸류 차트 90일 매칭)

# [DB 컬럼 매핑 — 기존 valuation_signal 스키마 그대로]
# US: spy_per (SPY 트레일링 PER) / vix (VIX) / tnx_yield (US 10Y)
# KR: spy_per ← KOSPI 시총가중 PER / vix ← VKOSPI / tnx_yield ← KR 10Y
# 컬럼명은 그대로 두고 region='kr' 로만 분리. UI 라벨은 region 별 분기 (Stage 3.x).

# [현재 가중치·임계 — US 와 동일 시작]
# w_erp=0.4, w_vix=0.3, w_dd=0.3
# 라벨: ±1.0σ
# → KR 5Y 분포 보고 추후 튜닝 가능 (예: KOSPI 변동성이 더 크면 w_dd 비중 조정)

# [실행 필요 — 사용자 1회]
# .venv/bin/python -m scripts.backfill_kr --days 90
# → macro 90건 + index 오늘 + sector ETF 10종 + valuation 90건 적재 (~3~5분)
# 첫 실행 시 5Y baseline 산출 (느림, 이후 90일 캐시).

# [동작 확인 (브라우저)]
# 헤더 🇰🇷 → 시장 밸류 탭 → KOSPI ERP/PER + VKOSPI + 60일 DD 표시
# 홈 헤드라인도 region=kr 라벨로 LLM 호출 → "시장이 다소 고평가 상태이지만..."
# (단 LLM 프롬프트는 'S&P500 PER' 표현 그대로 — Stage 3.x 라벨 분기에서 수정)

# [한계]
# - 펀더멘털 (noise_regime) — 8피처 KR 정의 + HMM 학습 필요 (Stage 3.2)
# - 신호 (crash_surge) — XGBoost 학습 필요 (Stage 3.3)
# - 섹터 (sector_cycle) — 한국 매크로 phase 정의 필요 (Stage 3.4)
# - LLM 프롬프트 'S&P500/SPY PER' 표현 region 별 라벨링 미적용 (Stage 3.5)


# ════════════════════════════════════════════════════════════════════════════
# [76] 2026-05-02 (UTC) — KR Stage 3.5: LLM·UI 라벨 region 분기
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# DB 컬럼명(sp500_close/vix/tnx)은 영구 유지하되, 사용자/LLM 에 노출되는 라벨만
# region 별로 분기. 헤더 🇰🇷 토글 시:
#   - LLM 입력 텍스트: "S&P500" → "KOSPI" / "VIX" → "VKOSPI" / "10Y금리" → "KR 10Y 국고채"
#   - UI 시장 탭 ind-card 라벨: "VIX" → "VKOSPI"
#   - 컨베이어 벨트(주요 지수 ETF): SPY/QQQ/SOXX/BND/IWM/DIA → KODEX 200/TIGER 200/
#     TIGER 코스닥150/KODEX 반도체/KODEX 헬스케어/TIGER 리츠

# [수정 파일]
# - api/routers/market_summary.py
#     · _market_labels(region, lang) 헬퍼 신설 — region 별 라벨 사전 반환:
#         index_name / index_return / vol20_label / vix_name / rate_name /
#         spread_name / major_tickers / price_unit
#     · _build_indicator_text() KR 라벨 분기 적용
#     · _build_home_indicator_text() KR 라벨 분기 적용 (시장 탭 + 시장 밸류 탭)
#     · 시장 탭 ETF 가격 라벨에 한글 이름(p['name']) 표시
#
# - static/js/main.js
#     · TICKER_LABELS_KEYS_US (SPY 등 6) / TICKER_LABELS_KEYS_KR (KODEX/TIGER 6)
#       분리, region 동적 선택
#     · getTickerLabels() 에 KR ETF 한국어 이름 매핑
#     · _applyRegionMarketLabels() 함수 신설 — DOM 의 'VIX' 라벨을 region 별로
#       'VKOSPI' 와 swap (loadMacro 진입 시 호출)
#
# - templates/stocks.html: main.js?v=116 → ?v=117

# [LLM 프롬프트 영향 — 이전/이후 비교]
# 이전 (KR 모드에서도 US 라벨 그대로):
#   "S&P500 일간수익률: -0.31%" "VIX: 18.0" "10Y금리: 3.41"
# 이후 (KR 모드):
#   "KOSPI 일간수익률: -0.31%" "VKOSPI: 18.0" "KR 10Y 국고채: 3.41"
# → LLM 이 컨텍스트를 KR 시장으로 정확히 인식. 헤드라인 "시장이 다소 고평가..."
#   같은 문장이 KOSPI 데이터에 대한 것임이 명확.

# [한계 (Stage 3.6 등 후속)]
# - 펀더멘털 탭의 "시장 이성 점수" 자체는 region='kr' 데이터 적재 안 됨 → 빈 화면
# - 신호 탭(crash/surge) 동일
# - 섹터 탭의 phase_name (확장기/회복기 등) — 한국 매크로 phase 정의 후 적용
# - i18n 의 hold.SPY 같은 보유종목 라벨 — KR 종목 추가 필요시 별도

# [검증]
# - python ast.parse market_summary.py OK
# - node --check main.js OK


# ════════════════════════════════════════════════════════════════════════════
# [77] 2026-05-02 (UTC) — KR Stage 3.2a: 펀더멘털 HMM 데이터 수집 모듈
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# US noise_regime_data.py 의 KR 등가. 8피처 명칭·의미 100% 동일하되 데이터 소스만
# pykrx + FDR + FRED 로 대체. 학습·통합은 후속 turn (3.2b+3.2c).

# [신규 파일]
# - collector/noise_regime_data_kr.py
#     · SECTOR_STOCKS_KR — 5섹터 × 5종목 (시총 상위 + 섹터 분산)
#         tech:       삼성전자/SK하이닉스/NAVER/카카오/포스코
#         financial:  KB/신한/하나/우리/BNK
#         industrial: 현대차/기아/한국전력/삼성물산/고려아연
#         health:     삼성바이오/셀트리온/SK바이오팜/알테오젠/셀트리온헬스케어
#         consumer:   CJ제일제당/강원랜드/대한항공/KAI/롯데케미칼
#     · AMIHUD_STOCKS_KR — 5 megacap (시총 최상위)
#     · fetch_kospi_shiller_like(years) — KOSPI 월별 P/E (E = close/PER) + CAPE 등가
#     · fetch_kr_10y_monthly() — FDR 'KR10YT=RR' resample 'MS'
#     · fetch_vkospi_daily() — FDR 'VKOSPI'
#     · fetch_us_hy_spread() — FRED CSV BAMLH0A0HYM2 (글로벌 신용 환경, KR HY 부족 대용)
#     · fetch_kr_stock_prices(tickers) — pykrx 일별 close DataFrame
#     · fetch_kr_amihud_stocks(tickers) — OHLCV 전체 (영어 컬럼 리네임)
#     · fetch_kospi_close_daily() — KOSPI 일별 (베타 + realized_vol 기준)
#     · compute_monthly_features_kr(...) — 8피처 + 윈저라이징, US 와 같은 dict 구조
#     · fetch_all_kr(years) — 원샷 fetch + 피처 산출

# [피처별 KR 매핑]
# 1. fundamental_gap : KOSPI 12M log P − 12M log E (E=close/PER)
# 2. erp_zscore     : KOSPI EY − KR 10Y, 10년 rolling z (KR 데이터 짧으면 24개월)
# 3. residual_corr  : 25종목 KOSPI-베타 제거 잔차 → 5섹터 페어 상관 평균
# 4. dispersion     : 25종목 일간 수익률 횡단면 std 의 20일 평균
# 5. amihud         : 5 megacap |OC log return| / dollar_vol — 1/99 윈저
# 6. vix_term       : VKOSPI / VKOSPI 60D 평균 (US VIX/VIX3M 대체 — KR 3M 미공개)
# 7. hy_spread      : 미국 ICE BofA HY OAS 그대로 (글로벌 신용 환경)
# 8. realized_vol   : KOSPI 일별 std × √252 의 20일 평균

# [수집 비용 추정]
# pykrx 호출: 25종목 × 5년 + 5 OHLCV + KOSPI 인덱스 ≈ 35 호출 / 분당 limit 영향 적음
# FDR 호출: 3종 (KR10Y, VKOSPI, KR3Y 추후) — 빠름
# FRED CSV: 1종 (HY) — 빠름
# 전체 fetch_all_kr() 예상 5~10분 (대부분 pykrx 25종목 5년치)

# [Stage 3.2b 다음 (다음 turn)]
# 1) processor/feature1_regime.py — train_hmm/predict_regime/load_model 에
#    region='us' 파라미터 추가, models/noise_hmm_us.pkl ↔ _kr.pkl 분리
# 2) scripts/train_kr_hmm.py — 1회성 학습 스크립트
# 3) scheduler/job_kr.py — 일일 KR HMM 추론 step 추가
# 4) backfill_kr.py — noise_regime KR 백필 30일

# [검증]
# - python ast.parse OK
# - 실제 fetch 동작 검증은 학습 turn 에서 train_kr_hmm 실행 시 동시 검증


# ════════════════════════════════════════════════════════════════════════════
# [80] 2026-05-02 (UTC) — 부천 mapping/population 옛 일반구 합산 + 3폴리곤→1폴리곤 병합
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# [69]에서 부천(41194) trades/rents 만 옛 일반구 41192/41196 추가 호출로 보강했지만,
# mapping(stdg_admm_mapping) 과 population(mois_population) 은 41194 한 곳만 호출 → MOIS 가
# 41194(소사구 area) 의 7개 stdg 만 반환 → region_summary 에도 7개 stdg 만 생성 → FeatureCard
# top_stdg 가 사실상 옥길동 한쪽으로 고정. 사용자: "왜 다 옥길동밖에 없어. 중동 상동이 있어야지".
#
# 원인: 부천은 2016 일반구 폐지 후 41194 단일 시군구가 되었지만 MOIS 인구·매핑 API 는 옛
# 5-digit LAWD_CD 별로 데이터를 분리 보관 중. trades/rents 만 합치고 mapping/pop 은 안 합쳤던
# [69] 의 사각지대.
#
# 실측 (MOIS 호출):
#   4119400000 → 7 stdg (계수·괴안·범박·소사본·송내·심곡본·옥길)
#   4119200000 → 9 stdg (도당·상동·소사·심곡·약대·역곡·원미·중동·춘의)
#   4119600000 → 8 stdg (고강·내·대장·삼정·여월·오정·원종·작)
#   합계 24 stdg = 부천시 전체 법정동.

# [수정 파일]
# 1. scripts/backfill_metro.py
#    - extra_lawd_cds 옆에 extra_sgg_10s 추가 (5-digit + '00000')
#    - 인구 fetch_population 에 extras 호출 → (stats_ym, stdg_cd) dedupe 후 합산
#    - mapping build_mapping 에 extras 호출 → stdg_cd dedupe 후 합산
#    - --only LAWD_CD 인자 신설: 단일 시군구 ad-hoc 재실행 (부천 단발성 호출용)
#
# 2. database/repositories.py
#    - upsert_region_summary 에 NaN/pd.NA → None 스크럽 추가
#    - 사유: pop 합산 후 trade_agg 에는 있으나 pop 에 없는 stdg → population NaN.
#      pandas Int64 의 pd.NA 가 to_dict 에서 그대로 빠져나오면 postgrest JSON 직렬화 실패
#      ("Out of range float values are not JSON compliant: nan"). 첫 시도 12 ym 모두 실패.

# [핵심 코드 변경 — backfill_metro.py]
extra_lawd_cds: list[str] = []
if sgg == '41194':
    extra_lawd_cds = ['41192', '41196']
extra_sgg_10s = [e + '00000' for e in extra_lawd_cds]

# 인구
pop = list(_re_norm_population(fetch_population(sgg_10, ym), ym))
pop_seen: set[tuple] = {(r["stats_ym"], r["stdg_cd"]) for r in pop}
for extra_10 in extra_sgg_10s:
    for row in _re_norm_population(fetch_population(extra_10, ym), ym):
        k = (row["stats_ym"], row["stdg_cd"])
        if k in pop_seen:
            continue
        pop_seen.add(k)
        pop.append(row)

# 매핑 (sgg 당 1회만 — 캐시 후 모든 ym 재사용)
if sgg_mapping is None:
    base_map = list(_re_norm_mapping(build_mapping(sgg_10, ym)))
    map_seen: set[str] = {m["stdg_cd"] for m in base_map if m.get("stdg_cd")}
    for extra_10 in extra_sgg_10s:
        for m in _re_norm_mapping(build_mapping(extra_10, ym)):
            sc = m.get("stdg_cd")
            if not sc or sc in map_seen:
                continue
            map_seen.add(sc)
            base_map.append(m)
    sgg_mapping = base_map
    upsert_stdg_admm_mapping(sgg_mapping)

# [실행]
# python scripts/backfill_metro.py --only 41194 --months 12 --hh-months 3 --sleep 0.4
# - mapping 첫 호출: 7 → 24 stdg (3.4배 확장)
# - 12 ym × region_summary 도 24 stdg/월 채워질 예정 (이전 7 stdg 였음)

# [관련 메모]
# - 다른 통합 시·군은 동일 패턴 점검 필요. 후보:
#     수원(41110→41111·41113·41115·41117), 성남(41130→41131·41133·41135),
#     안양(41170→41171·41173), 안산(41270→41271·41273),
#     고양(41280→41281·41285·41287), 용인(41460→41461·41463·41465)
#   → METRO_NEW_LAWD_CDS 에 이미 일반구 코드들 들어있어 별개로 backfill 됨 → 부천만 단일 issue.
# - 향후 sgg/일반구 통합 변경 시 backfill_metro.py 의 extra_lawd_cds 분기 점검.

# [추가 fix — geojson 폴리곤 병합]
# 위 backfill 후에도 사용자가 새로고침해도 부천을 클릭하면 여전히 "옥길동" 만 표시됐음.
# 원인: frontend-realestate/public/geojson/metro-sgg.geojson 에 부천이 옛 일반구 경계대로
# 3개 Polygon (소사구/원미구/오정구) 으로 분할 저장되어 있는데 모두 sgg_cd=41194 로 같은
# sgg-overview entry 호출 → 같은 top_stdg=옥길동 (평단가 1위) 카드. 시각적 분할이
# 사용자에게 "각 영역마다 다른 데이터" 라는 오인을 유발.
#
# 처리: 3 Polygon → 1 MultiPolygon (name="부천시", sgg_cd 유지) 합병 + frontend 빌드 재배포.
# 결과: 79 features → 77 features. 부천 어느 곳을 클릭해도 1개 카드 일관 표시.
# (다른 동 보고 싶으면 카드의 "구 전체 추이 →" 클릭 → RegionDetail 의 9 stdg 리스트)

# [검증]
# - python -c "import scripts.backfill_metro" OK
# - 실 backfill 결과: mapping 7→24 stdg, region_summary 7→9 활성 stdg 확장 (거래 기준)
#   (4119410800 중동 158, 4119410900 상동 79, 4119410500 송내 59, 4119410300 범박 50,
#    4119410400 괴안 45, 4119410600 옥길 26, 4119410700 역곡 26, 4119410200 심곡본 18)
# - frontend npm run build 성공, geojson 79→77 features 확인


# ════════════════════════════════════════════════════════════════════════════
# [81] 2026-05-02 (UTC) — 첫 로딩 가속: supabase TLS warmup + GZip middleware
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 사용자: "맨 처음 로딩이 느리다". 실측 — sgg-overview cold = 6.3s, warm = 0.2s.
# 원인 (1) supabase TLS 핸드셰이크가 첫 요청자에게 동기 발생 (uvicorn boot 후 첫 호출자
# 가 TLS 비용 부담). (2) 응답 21KB JSON 비압축 전송.

# [수정 파일]
# api/app.py
# - lifespan() 끝에 supabase 1회 ping → uvicorn boot 시점에 TLS 미리 수행. 첫 요청
#   6.3s → 0.6s (10x). startup 시간만 0.5s 늘어나는 트레이드.
# - GZipMiddleware(minimum_size=500) — Starlette 규약상 마지막 add 가 outermost
#   라 CORS 다음에 add. sgg-overview 21KB → 3KB (-86%). region-detail 5.8KB → ~1.5KB.

# [핵심 코드]
from fastapi.middleware.gzip import GZipMiddleware

# lifespan 안:
try:
    from database.supabase_client import get_client
    get_client().table('app_cache').select('cache_key').limit(1).execute()
    print('[App] supabase warmup OK')
except Exception as e:
    print(f'[App] supabase warmup 실패 (무시): {e}')

# 미들웨어 등록 순서 — CORS 먼저, GZip 나중에 (GZip 이 outermost 가 되어 응답을 압축)
app.add_middleware(CORSMiddleware, allow_origins=['*'], ...)
app.add_middleware(GZipMiddleware, minimum_size=500)

# [검증]
# - sgg-overview cold: 6.3s → 0.6s (warmup 효과)
# - sgg-overview wire: 21400B → 3034B (gzip 86% 압축)
# - openapi.json 도 자동 압축 적용
# - TestClient + curl --compressed 양쪽에서 content-encoding: gzip 확인
# - middleware stack 검증: ServerError → GZip → CORS → Exception → Router (외→내)


# ════════════════════════════════════════════════════════════════════════════
# [82] 2026-05-02 (UTC) — 부천 폴리곤 sub-area 별 top_stdg (지도 영역에 맞는 동)
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# [80] 에서 부천 3폴리곤(소사·원미·오정) → 1폴리곤 병합했으나 사용자: "지도 영역에
# 맞는 동이 나와야". 3폴리곤 복원 + 폴리곤별 그 영역 안의 동만 보고 top 표시.
#
# 데이터 한계 — MOLIT 가 부천 21 동을 stdg_cd 9개에 압축해 region_summary 의
# stdg_nm 일부 묻힘 (4119410100 row 에 소사본·오정·원미 거래 모두 합산). 따라서
# region_summary 가 아닌 real_estate_trade_raw 에서 umd_nm (동 이름) 기준 직접
# 집계해야 21 동 정상 분리.

# [수정 파일]
# 1. frontend-realestate/public/geojson/metro-sgg.geojson
#    - 부천 3폴리곤 복원 (79 features) + 각 폴리곤에 properties.bucheon_sub
#      ('sosa'/'wonmi'/'ojeong') 추가
# 2. api/routers/real_estate.py
#    - BUCHEON_STDG_SUB 하드코딩 (24 동 → sub-area 매핑)
#    - compute_sgg_overview 의 sgg_cd=41194 분기에 _bucheon_sub_top() 호출 추가
#    - _bucheon_sub_top: real_estate_trade_raw 에서 umd_nm 기준 그룹핑 → median 평단가 →
#      sub-area 별 top 동. trade_count 도 raw 에서 직접 산출 (region_summary 누락 동 대응).
# 3. frontend-realestate/src/types/api.ts
#    - SggOverview.bucheon_sub_top?: Record<sub,{top_stdg_cd/nm, median_price_per_py, trade_count}>
# 4. frontend-realestate/src/components/KakaoMap.tsx
#    - PolygonFeature.subKey?: string 추가
#    - onPolygonClick 시그니처: (sggCd) → (sggCd, subKey)
# 5. frontend-realestate/src/screens/MapScreen.tsx
#    - loadPolygons 가 properties.bucheon_sub → polygon.subKey 전달
#    - handlePolygonClick: subKey 있을 때 ov.bucheon_sub_top[subKey] 우선 사용,
#      sub 매칭 시 region_summary 에 동 row 가 없을 수 있어 가짜 RegionSummary 직접 set

# [핵심 코드]
BUCHEON_STDG_SUB: dict[str, str] = {
    '계수동': 'sosa', '괴안동': 'sosa', '범박동': 'sosa', '소사본동': 'sosa',
    '송내동': 'sosa', '심곡본동': 'sosa', '옥길동': 'sosa',
    '도당동': 'wonmi', '상동': 'wonmi', '소사동': 'wonmi', '심곡동': 'wonmi',
    '약대동': 'wonmi', '역곡동': 'wonmi', '원미동': 'wonmi', '중동': 'wonmi',
    '춘의동': 'wonmi',
    '고강동': 'ojeong', '내동': 'ojeong', '대장동': 'ojeong', '삼정동': 'ojeong',
    '여월동': 'ojeong', '오정동': 'ojeong', '원종동': 'ojeong', '작동': 'ojeong',
}

def _bucheon_sub_top(client, ym):
    rows = client.table('real_estate_trade_raw').select(
        'umd_nm,deal_amount,exclu_use_ar'
    ).eq('sgg_cd', '41194').eq('deal_ym', ym).execute().data or []
    by_nm = defaultdict(list)
    for r in rows:
        if r.get('umd_nm') and r.get('deal_amount') and r.get('exclu_use_ar'):
            by_nm[r['umd_nm']].append(r['deal_amount'] / (r['exclu_use_ar'] / 3.3058))
    sub_top = {}
    for sub in ('sosa', 'wonmi', 'ojeong'):
        cands = [(nm, sorted(v)[len(v)//2]) for nm, v in by_nm.items()
                 if BUCHEON_STDG_SUB.get(nm) == sub]
        if cands:
            nm, med = max(cands, key=lambda x: x[1])
            sub_top[sub] = {'top_stdg_cd': nm, 'top_stdg_nm': nm,
                            'median_price_per_py': round(med, 0),
                            'trade_count': len(by_nm[nm])}
    return sub_top

# [검증 — 202603]
# sosa: 옥길동 (2663 만/평, 30 거래)
# wonmi: 약대동 (2559, 22)
# ojeong: 여월동 (2763, 7)
# 79 features geojson + frontend npm run build 성공 + sgg_overview cache 즉시 갱신


# ════════════════════════════════════════════════════════════════════════════
# [83] 2026-05-03 (UTC) — cold-start 후속 fix: keepalive ping + 단일 client + relayout
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# [81] warmup 적용 후에도 사용자: "여전히 처음 로딩이 느림 + detail 페이지·요약탭 거래량
# 부분 너무 느림". 재측정 결과 cold = 5.8s 다시 발생. 원인 진단:
# (1) supabase TLS 가 ~5분 idle 시 닫혀 다음 요청 핸드셰이크 다시 부담
# (2) database/supabase_client.py 가 threading.local() 이라 worker thread 마다 새
#     client = 새 httpx pool = 새 TLS handshake → 첫 sgg-overview 후 polygon click
#     의 /signal /summary 가 다른 thread 에서 처리되면 또 cold
# (3) KakaoMap.tsx 가 unmount → remount 시 relayout() 안 호출해 컨테이너 0×0 으로
#     렌더되는 케이스 (사용자 "상세페이지 들어갔다 나오니까 지도가 안 나온다")

# [수정 파일]
# 1. api/app.py
#    - 4분 주기 _supabase_keepalive 잡 추가 — 풀의 TLS conn 이 idle 닫히기 전에 ping
# 2. database/supabase_client.py
#    - threading.local() → 프로세스 단일 client (httpx.Client 자체가 thread-safe).
#      모든 worker thread 가 같은 connection pool 사용 → 한 번 warm 되면 모든 후속
#      요청이 즉시 응답.
# 3. frontend-realestate/src/components/KakaoMap.tsx
#    - 지도 인스턴스 생성 후 requestAnimationFrame 로 relayout() 1회 호출 추가.
#      라우팅 복귀 시 컨테이너 크기 재측정 → 폴리곤 정상 표시.

# [핵심 코드 — supabase_client.py]
_client: Client | None = None
def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    return _client

# [핵심 코드 — app.py lifespan]
def _supabase_keepalive():
    try:
        get_client().table('app_cache').select('cache_key').limit(1).execute()
    except Exception as e:
        print(f'[App][keepalive] {e}')
scheduler.add_job(_supabase_keepalive, 'interval', minutes=4, id='supabase_keepalive')

# [핵심 코드 — KakaoMap.tsx]
mapRef.current = new kakao.maps.Map(containerRef.current, {...});
setReady(true);
requestAnimationFrame(() => mapRef.current?.relayout?.());

# [기대 효과]
# - cold-start 가 idle 후에도 4분 keepalive 로 풀 hot 유지 → 항상 warm 응답
# - polygon click → /signal /summary 가 어느 worker thread 로 라우팅되든 즉시 응답
# - detail 진입→복귀 시 지도 안 보이는 버그 해결 (relayout)


# ════════════════════════════════════════════════════════════════════════════
# [78] 2026-05-02 (UTC) — KR Stage 3.2b: HMM 학습 + 스케줄러 통합
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 3.2a 데이터 수집 모듈 위에서 HMM 학습 가능하게 processor region 파라미터화 +
# 1회성 학습 스크립트 + 스케줄러 일일 추론 step 통합.

# [수정 파일]
# - processor/feature1_regime.py
#     · _model_path(region) 헬퍼 — US='noise_hmm.pkl' (하위호환), KR='noise_hmm_kr.pkl'
#     · train_hmm(features, monthly_bundle, region='us') — region 별 모델 저장
#     · load_model(region='us') — 해당 region 모델 로드
#     · predict_regime 로그에 region 표시
#     · backfill_noise_regime(bundle, model, days, region='us')
#         · region='kr' → SECTOR_STOCKS_KR/ALL_STOCKS_KR import
#         · raw_dict = bundle.get('macro_raw') or bundle.get('fred_raw') 호환
#         · vix_term KR: VKOSPI/VKOSPI 60D ratio 사용 (vix3m=1.0 placeholder)
#
# - scheduler/job_kr.py
#     · run_kr_pipeline step 4 추가 — load_model('kr') → fetch_all_kr(3년) →
#       backfill 3일 → upsert_noise_regime(region='kr')
#     · 모델 없으면 "train_kr_hmm 먼저" 안내

# [신규 파일]
# - scripts/train_kr_hmm.py
#     · python -m scripts.train_kr_hmm [--years 7] [--backfill 60]

# [실행 필요 — 사용자 1회 (~5~10분, pykrx 25종목 5~7년치 fetch)]
#   python -m scripts.train_kr_hmm
# → models/noise_hmm_kr.pkl 생성 + DB region='kr' noise_regime 60건 적재
# → 펀더멘털 탭 KR 모드 즉시 작동

# [학습 후 일일 자동]
# scheduler/job_kr.run_kr_pipeline 매일 16:00 KST 가 step 4 호출 → 최신 추론
# 적재. 재학습은 월 1회 정도 수동 (train_kr_hmm 다시 실행).

# [검증]
# - python ast.parse: feature1_regime / train_kr_hmm / job_kr 모두 OK

# [한계]
# - vix_term KR 정의가 US 와 의미 차이 (단기/장기 implied vol → mean reversion proxy)
# - hy_spread KR=US 그대로 (글로벌 신용 환경)


# ════════════════════════════════════════════════════════════════════════════
# [79] 2026-05-02 (UTC) — KR Stage 3.x: pykrx → FinanceDataReader 폴백 일괄 추가
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# pykrx 가 KRX 사이트와 통신 못하는 일시적 장애 시 (KeyError: '지수명' 등) KR 파이프
# 라인 전체가 실패하던 문제. FDR 가 제공하는 KS11(KOSPI)/KS200/6자리 종목코드를
# 활용해 자동 폴백하도록 모든 KR collector 통일.

# [수정 파일]
# - collector/market_data_kr.py
#     · _fdr_fallback_index(symbol, days) — pykrx 실패 시 FDR 호출, 한글 컬럼 리네임
#     · fetch_kospi_price_history → pykrx 1차, FDR(KS11) 2차
#     · fetch_kospi200_price_history → pykrx 1차, FDR(KS200) 2차
#     · fetch_kospi_per_pbr → pykrx 만 (FDR 미지원 — 빈 DF 반환)
#     · _etf_ohlcv_fallback(ticker, days) — ETF OHLCV pykrx → FDR(6자리 직접) 폴백
#     · fetch_kr_index_prices_today — _etf_ohlcv_fallback 사용
#
# - collector/sector_etf_kr.py
#     · _etf_ohlcv_dual_source(ticker, days) — pykrx → FDR 폴백
#     · fetch_sector_etf_prices_kr — 위 함수 사용
#
# - collector/noise_regime_data_kr.py
#     · _stock_ohlcv_dual(ticker, years) — pykrx get_market_ohlcv → FDR 폴백
#     · fetch_kr_stock_prices, fetch_kr_amihud_stocks — 위 함수 사용
#     · fetch_kospi_close_daily — pykrx → FDR(KS11) 폴백
#
# - collector/valuation_signal_kr.py
#     · _kospi_close_dual(years) — pykrx → FDR(KS11) 폴백 헬퍼
#     · _compute_kr_dd_baseline_5y — _kospi_close_dual 사용
#     · fetch_valuation_signal_today_kr — KOSPI close 폴백, PER 만 pykrx 의존
#     · backfill_valuation_signal_kr — KOSPI close 폴백

# [폴백이 안 되는 부분 (pykrx only)]
# - KOSPI 시총가중 PER (fetch_kospi_per_pbr / get_index_fundamental):
#   · FDR 가 시총가중 PER 시계열 미제공
#   · pykrx 실패 시 valuation_signal·noise_regime 둘 다 부분 실패
#   · 향후: KOSPI 200 ETF (KS200) PER 데이터를 자체 산출하거나 yfinance EWY/EWHA
#     trailingPE 사용 등 대안 검토

# [검증]
# - python ast.parse 4개 파일 모두 OK
# - 사용자 backfill_kr 재실행 시 KS11 폴백 시작 확인 필요


# ════════════════════════════════════════════════════════════════════════════
# [80] 2026-05-02 (UTC) — KR 3-단 폴백 + index_price_raw 스키마 정합
# ════════════════════════════════════════════════════════════════════════════
# 1) FDR 도 내부적으로 pykrx 사용해 KRX 장애 시 함께 실패 → yfinance 3차 폴백 추가
# 2) DB 에러 PGRST204 'name' 컬럼 없음 → record 에서 'name'/'volume' 제거
#
# 수정:
# - collector/market_data_kr.py
#     · _fdr_fallback_index — FDR 실패 시 yfinance(^KS11) 자동 폴백
#     · _etf_ohlcv_fallback — 3단: pykrx → FDR → yfinance(6자리.KS)
#     · fetch_kr_index_prices_today — record 에서 'name'/'volume' 제거
# - scripts/backfill_kr.py — sector ETF row 'name'/'volume' 제거
# - scheduler/job_kr.py — sector ETF row 'name'/'volume' 제거
#
# Yahoo 심볼: KOSPI=^KS11, KOSPI200=^KS200, ETF=6자리.KS, 종목=005930.KS
# 폴백 못 되는: VKOSPI (Yahoo 없음), KR 10Y (Yahoo 404 — ECOS 권장 후속)


# ════════════════════════════════════════════════════════════════════════════
# [81] 2026-05-02 (UTC) — KR 폴백 마무리 (valuation/noise_regime_data 종목)
# ════════════════════════════════════════════════════════════════════════════
# 1) valuation_signal_kr — 컴포넌트별 try/except 분리, PER/KR10Y/VKOSPI 모두 fallback
#    · PER fallback 14.0 평탄 시리즈
#    · KR 10Y fallback 0.035 (3.5%) 평탄
#    · VKOSPI fallback KOSPI 20D RV × √252 × 100 proxy
#
# 2) noise_regime_data_kr._stock_ohlcv_dual — 3단 폴백 추가
#    · pykrx → FDR → yfinance (6자리.KS)
#    · KRX 장애 시에도 25종목 5년치 fetch 가능 → train_kr_hmm 작동
#
# [실측 결과 (사용자 환경, KRX 장애)]
# backfill_kr 실행: macro=90, index=5, sector=10, valuation=90 모두 적재
# 폴백 활성: PER 14.0, KR10Y 3.5%, VKOSPI=KOSPI RV proxy
# 한계: ERP/yield 평탄 → z_erp/z_dd 분산 작아짐, z_comp 신호 약함
#       KRX/ECOS 복구 후 정상 분포 회복


# ════════════════════════════════════════════════════════════════════════════
# [82] 2026-05-02 (UTC) — KR Stage 3.x: ECOS API 통합 (KR 10Y/3Y/회사채 정확도 회복)
# ════════════════════════════════════════════════════════════════════════════
# Yahoo 'KR10YT=RR' 가 404 로 막힌 환경에서 KR 매크로 정확도 회복 — 한국은행 ECOS
# API 통계표 817Y002 (시장금리 일별) 활용. KR 신용 환경도 글로벌 미국 HY 대신
# KR 회사채(AA-3Y) - 국고채 3Y 스프레드로 정확히 산출.
#
# [신규 SPECS — collector/ecos_macro.py]
# - kr_10y_daily   : 817Y002 / 010210000 (일별)
# - kr_3y_daily    : 817Y002 / 010200000 (일별)
# - kr_corp_aa3y   : 817Y002 / 010320000 (일별, 회사채 3년 AA-)
#
# [신규 helpers]
# - fetch_kr_treasury_yields(years) → {'kr_10y', 'kr_3y'}: pd.Series (% 단위)
# - fetch_kr_corp_spread(years) → 회사채 - 국고채 3Y 스프레드 Series
#
# [수정 — ECOS 1차 폴백 추가]
# - market_data_kr.fetch_kr_10y_treasury / fetch_kr_3y_treasury
#     · ECOS → FDR(KR10YT=RR) → 3.5% 평탄 fallback 3단
# - noise_regime_data_kr.fetch_kr_10y_monthly
#     · ECOS → FDR 2단 (월말 resample)
# - noise_regime_data_kr.fetch_us_hy_spread
#     · KR 회사채 스프레드 (ECOS) 1차 → 미국 HY OAS (FRED) 2차 폴백
#     · KR 신용 환경 정확 반영 (이전엔 항상 글로벌 미국 HY)
# - valuation_signal_kr (3곳)
#     · backfill / today / baseline_5y 모두 ECOS 1차 추가
#
# [효과]
# - PER 만 KRX 의존 (pykrx 외 대안 없음, fallback 14.0)
# - KR 10Y / 3Y / hy_spread 모두 ECOS 정확값 → erp_zscore / hy_spread feature
#   분산 회복 → HMM 학습 정확도 ↑
# - 다음 train_kr_hmm 재실행 시 정상 모델 (사용자 한 번 더 돌려야 효과 적용)
#
# [한계]
# - ECOS 통계표 코드는 변경 가능 — 실패 시 자동 fallback 으로 안전망
# - PER 정확값은 KRX/pykrx 복구 또는 별도 대체 (yfinance EWY 등) 필요



# ════════════════════════════════════════════════════════════════════════════
# [83] 2026-05-03 (UTC) — Bloomberg Terminal 스타일 부동산 frontend 5-phase 재설계
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 사용자가 보낸 4개 모킹 스크린샷 (지도 메인 / 지역 선택 / HOMELENS DAILY / 시군구
# 종합점수) 을 보고 부동산 React SPA 를 블룸버그 터미널 스타일로 전면 재설계.
# 옵션 B (1→5 순서 진행) 채택. 각 phase 끝에 commit + 빌드 검증.
#
# 결정사항:
# - 폰트: JetBrains Mono + Noto Sans KR (CDN preconnect)
# - 색: term.{bg #0a0a0a, panel #111, border #222, orange #ff8800, up #ff4444,
#       down #4488ff, dim #666, text #e8e8e8, green #00cc66}
# - USD/KRW 제외 (사용자: "이런게 있었나?" — 부동산 앱에 환율 부적합)
# - 폴리곤 위 +N.N% 라벨 미구현 (사용자 결정)
# - ticker bar = KOSPI + BASE 2개 항목만 (60s polling)

# [Phase 1 — 5774940] 테마 기반 + TickerBar + MobileLayout
# - tailwind.config.ts: term.* + fontFamily.mono = ["JetBrains Mono", "Noto Sans KR"]
# - globals.css: bg #0a0a0a + mono + tabular nums + 터미널식 scrollbar
# - index.html: Google Fonts CDN preconnect/preload
# - TickerBar.tsx 신규 — KOSPI(/api/index/latest?region=kr) + BASE(/api/realestate/macro-rate)
# - TerminalSection.tsx 신규 — 오렌지 ▓ 헤더 + 본문 패널 공용
# - MobileLayout.tsx — 검정 배경, TickerBar 마운트, 4 tab 이모지→모노크롬 SVG
#   (MAP/SRCH/WTCH/RANK 대문자), 활성 탭 오렌지 + 상단 막대
# - endpoints.ts: indexLatest/macroRate 추가

# [Phase 2 — 6fa90d9] MapScreen MARKET BRIEF + FeatureCard
# - MarketSummaryCard: TerminalSection 사용, BUY/HOLD/WATCH chips + BASE 우측,
#   ▼ 더보기 / ▲ 접기 토글
# - SignalCounters.tsx 신규 (재사용 가능 카운터, 추후 다른 화면에서)
# - MapScreen: 검색 줄 → 모노 panel + SVG 검색 + [/] 단축키 힌트,
#   CHOROPLETH·{N} DST·1M Δ 캡션 + 5단계 색상 범례
# - FeatureCard: 검정 panel + 오렌지 헤더 (▓ RGN {sgg_cd}) + TXNS/MoM Δ/SIG +
#   ◄ PREV SGG OVERVIEW / FULL ANALYSIS [G] CTA

# [Phase 3 — 496e795] RegionDetailScreen 재구성
# - TerminalMetric.tsx 신규 — LABEL/VALUE 공용 (large 옵션)
# - RegionCodeHeader.tsx 신규 — ▓ RGN {code} · {parts} · DETAIL-SUMMARY + back ◄
# - RegionDetailScreen: NavBar 제거, RGN 헤더, top stdg narrative 카드 (TXNS/MoM Δ/SIG),
#   AVG W/PY · TXNS/MO · JEONSE/WOLSE · JEONSE Ri 4-요약, 4종 시계열 차트
#   (W/PY 오렌지 / VOL 그린 / JEONSE 앰버 / POPULATION 다운블루),
#   SUB-REGIONS · BY W/PY 리스트
# - SignalCard: COMPOSITE SIGNAL terminal + BUY/HOLD/WATCH 영문 + VOL/PRC/POP/RATE/FLOW
# - TimeSeriesChart: 검정 panel + ▓ 오렌지 헤더 + LO/LAST/HI

# [Phase 4 — b0f1de9] StdgDetail/ComplexDetail token swap
# - StdgDetailScreen (newspaper 구조 유지) + ComplexDetail/ComplexCompare:
#   bg-black → bg-term-bg, border-gray-800 → border-term-border, text-gray-* →
#   text-term-{text,dim}, text-orange-400 → text-term-orange
# - 그 외 component (AiInsight/AiReport/BottomBar/BottomSheet/MultiSeriesChart/MetricGrid)
#   일괄 token swap

# [Phase 5 — 111f203] ScoreBox + MiniChart + RankingScreen
# - MiniChart.tsx 신규 — 라벨/축 없는 콤팩트 SVG 라인 (height=28~36, 단일 색)
# - ScoreBox.tsx 신규 — 큰 SCORE/BUY 박스 + 5-cell breakdown (VOL/PRC/POP/RATE/MIGR)
# - RegionDetailScreen: SignalCard → ScoreBox 교체, W/PY+VOL+JEONSE 3종을
#   MiniChart strip row 로 압축 (3-column), POPULATION 만 큰 차트 유지
# - RankingScreen: 카드 list → terminal table (rank/sgg/value/sub 4-column),
#   헤더 클릭 정렬 (rank/name/value asc/desc 토글 ▲▼), 이모지 📈🔥 제거,
#   TerminalSection wrapping

# [최종 산출물]
# 신규 7 component: TickerBar, TerminalSection, TerminalMetric, RegionCodeHeader,
#                  SignalCounters, ScoreBox, MiniChart
# 수정: tailwind.config.ts, globals.css, index.html, MobileLayout, KakaoMap,
#       MarketSummaryCard, FeatureCard, SignalCard, TimeSeriesChart,
#       MapScreen/RegionDetail/StdgDetail/ComplexDetail/ComplexCompare/Ranking,
#       lib/color.ts (변경 없음 — 호환), api/endpoints.ts (indexLatest/macroRate)
# 번들: 207KB → 216KB JS / 21KB → 20KB CSS (gzip 67→68 KB) — 50KB 증가 이내 목표 달성

# [검증 — 각 phase]
# 1. cd frontend-realestate && npm run build (TypeScript + Vite 모두 성공)
# 2. dev server (uvicorn api.app:app --reload --port 8000)
# 3. 브라우저로 6 화면 (지도/지역/법정동/단지/단지비교/랭킹) 접속, 모킹과 비교
# 4. 모바일 너비 (Chrome DevTools 428×844) overflow 없음
# 5. console error 없음

# [다음 작업 후보]
# - USD/KRW 추가 (yfinance collector) — 사용자 결정시
# - polygon 위 +N.N% 라벨 — 사용자 결정시
# - Search/Favorite 화면 (현재 placeholder)
# - StdgDetailScreen 의 ANALYST NOTE 도 ScoreBox 와 같은 sectional 스타일


# ════════════════════════════════════════════════════════════════════════════
# [84] 2026-05-03 (UTC) — KR 펀더멘털 탭 A+C+D: 게이지 범위 / PER 동적 fallback / UI 정리
# ════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자가 펀더멘털 탭 스크린샷을 보여주며 문제점 진단 요청. 6 가지 이슈:
#   ① noise score 가 -7.7 ~ -19 극단값 (US 게이지 -10~+5 범위 벗어남)
#   ② 모든 시점이 "감정" 우세 — 51개월 학습/fundamental_gap fallback 영향
#   ③ HMM "Model is not converging" 경고 — 학습 부족
#   ④ 카드 제목 "Noise vs Signal" 영문 (KR 컨텍스트 부적합)
#   ⑤ 게이지 라벨 (Fundamental·Price) 중복 표시
#   ⑥ PER 가 14.0 평탄 fallback → ERP 일정 → composite z 신호 약함
#
# 추천 조합 A+C+D 채택 (B = HMM 재학습은 사용자가 직접 train_kr_hmm 재실행).
#
# [A] 게이지 범위 region 분기 — static/js/main.js loadRegime
#   const isKrRegime = _curRegion() === 'kr';
#   const G_LO = isKrRegime ? -25 : -10;  // KR 분포 깊음 (51개월 + fallback)
#   const G_HI = isKrRegime ? 5 : 5;
#   pos = ns <= 0 ? 5 + ((ns - G_LO)/(0 - G_LO)) * 45
#                 : 50 + ((ns - 0)/(G_HI - 0)) * 45;
#   pos = Math.max(5, Math.min(95, pos));
#   왜: -19 score 도 게이지 좌단 안에 들어와야 시각적 의미 있음
#
# [D] 카드 제목 region 분기 + 중복 라벨 제거 — main.js + templates/stocks.html
#   - templates/stocks.html: <span class="card-label" id="nr-card-title">Noise vs Signal</span>
#   - main.js loadRegime: titleEl.textContent = isKrRegime ? '시장 이성 점수' : 'Noise vs Signal'
#   - main.js loadRegime: <div class="nr-gap-ticks"> 중복 ticks 제거 (gap-labels 만 유지)
#   왜: KR 모드에서 영문 제목 어색 + ticks/labels 중복으로 혼란
#
# [C] PER 동적 fallback — collector/valuation_signal_kr.py + collector/noise_regime_data_kr.py
#   사용자 선택: "마지막 정상 PER 캐싱" (yfinance EWY 외부호출 X)
#   - valuation_signal_kr 에 신규 헬퍼:
#       _load_last_known_per()  → models/valuation_baselines_kr.json 의 last_known_per 읽기
#       _save_last_known_per()  → 정상 PER 머지 저장 (last_known_per_updated_at 동시)
#       _HARD_FALLBACK_PER = 14.0  (캐시 첫 실행 보호)
#   - fetch_valuation_signal_today_kr / backfill_valuation_signal_kr:
#       pykrx 성공 시 → _save_last_known_per
#       pykrx 실패 시 → _load_last_known_per → 없으면 14.0
#   - noise_regime_data_kr.fetch_kospi_shiller_like (HMM 학습용)
#       동일 패턴 적용 + valuation_signal_kr 의 캐시 공유 (동일 JSON)
#   왜: 사용자 환경 KRX 복구되면 자동으로 캐시 채워지고 다음 실패 시 그 값 재사용
#       → 14.0 평탄 시리즈가 만드는 ERP 일정 문제 완화 (단, 같은 값 평탄은 동일 분포)
#
# [수정 파일]
# - templates/stocks.html
#     · <span class="card-label" id="nr-card-title">Noise vs Signal</span> 추가
#     · main.js?v=123 → ?v=124
# - static/js/main.js
#     · loadRegime: G_LO/G_HI region 분기, nr-gap-ticks 제거, 카드 제목 region 분기
# - collector/valuation_signal_kr.py
#     · _HARD_FALLBACK_PER 상수, _load_last_known_per/_save_last_known_per 헬퍼
#     · today/backfill 양쪽에서 캐시 우선 fallback 적용
# - collector/noise_regime_data_kr.py
#     · fetch_kospi_shiller_like 에서 valuation_signal_kr 의 헬퍼 import 후 사용
#
# [검증]
# - python -c "from collector.valuation_signal_kr import *; ..." imports OK
# - fetch_valuation_signal_today_kr 실행 → '캐시 없음' fallback 메시지 정상
# - fetch_kospi_shiller_like(years=2) 실행 → 14.0 평탄 사용 메시지, shape (14,3) OK
# - node --check static/js/main.js → OK
#
# [한계]
# - 이 환경 (KRX 로그인 차단) 에선 캐시 영원히 안 채워짐 — 사용자 production 환경에서만 효과
# - 학습된 KR HMM (51개월) 자체의 score 분포는 데이터 재학습 (B) 없이는 변하지 않음
#   → 사용자가 별도로 train_kr_hmm 다시 돌려야 -7.7~-19 분포가 정상화될 수 있음
#
# [다음 작업 후보]
# - B (KR HMM 재학습) — 사용자가 ECOS/PER 캐시 채워진 후 train_kr_hmm.py 재실행
# - Stage 3.3 KR Crash/Surge XGBoost — 신호 탭
# - Stage 3.4 KR sector_cycle phase 정의


# ════════════════════════════════════════════════════════════════════════════
# [85] 2026-05-03 (UTC) — 화성시(41590) MOLIT 옛 일반구 4코드 합산 backfill
# ════════════════════════════════════════════════════════════════════════════

# [개요]
# 사용자: "화성시는 데이터가 없는데". 진단 결과 MOLIT 가 LAWD_CD=41590 (행안부
# 표준 화성시 코드) 에 대해 모든 월 totalCount=0 반환. 옛 일반구 코드로 분할되어
# 있음 — 부천(41194 → 41192/41196) 과 동일 패턴.
#
# 실측 (MOLIT 202604):
#   41591 (새솔동 등): 99건
#   41593 (기안동 등): 158건
#   41595 (반정동 등): 214건
#   41597 (산척동·동탄): 792건
#   합계 1,263건/월

# [수정 파일]
# 1. scripts/backfill_metro.py
#    - 부천 분기 옆에 화성시 분기 추가:
#        elif sgg == '41590':
#            extra_lawd_cds = ['41591', '41593', '41595', '41597']
#    - mapping/pop 도 4 sgg_10 모두 합산해 sgg_cd=41590 으로 통합 (기존 부천 로직 재사용)

# [실행]
# python scripts/backfill_metro.py --only 41590 --months 12 --hh-months 3 --sleep 0.4
# - 5 LAWD_CD × 12 ym (base 41590 0건 호출 포함) ≈ 20.7분 소요
# - region_summary 30~35 stdg/월 적재
# - buy_signal: 매수 (점수 39.3, 평단가 1,811만/평, top stdg=송동)

# [캐시 갱신]
# - app_cache sgg_overview · region_detail:41590 · ranking 모두 즉시 재계산

# [관련 메모]
# - 다른 통합/분할 시·군 동일 점검 필요 — 수원/성남/안양/안산/고양/용인 일반구는
#   이미 별도 LAWD_CD (41111·41113·41115·41117 등) 로 list 에 들어있음
# - 화성·부천 외에 추가로 분할된 시 (전국 단위로 보면 청주·천안 등) 도 같은 패턴 가능


# ════════════════════════════════════════════════════════════════════════════
# [86] 2026-05-03 (UTC) — KR HMM 6-feature 재정의 (vix_term + fundamental_gap 제외)
# ════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자 펀더멘털 탭 스크린샷 분석 (update.py [84] 후속): 펀더멘털 괴리 = 0.0000,
# VIX 기간구조 = 0.0000 — KR 데이터 구조적 한계로 두 피처가 정보 없는 평탄 시리즈.
# fundamental_gap = 12M(log P) - 12M(log E), E = P/PER. KR 은 PER 시계열 확보가
# 불안정해 14.0 평탄 fallback 사용 시 log E = log P - log 14 → 12M diff cancel out → 0.
# vix_term = VKOSPI / VKOSPI 60D rolling mean — KR 시장에 VKOSPI 1개만 있어
# US 의 VIX/VIX3M 같은 기간구조 자체가 부재 → 항상 1.0 ± ε 평탄.
#
# 두 피처를 빼고 KR 전용 6-feature HMM 으로 재정의:
#     ['erp_zscore', 'residual_corr', 'dispersion', 'amihud', 'hy_spread', 'realized_vol']
#
# [가중치 재배분]
# - 원래 vix_term (2.0) + realized_vol (2.0) = 4.0 변동성 측면
#   → vix_term 제거 → realized_vol 4.0 으로 흡수
# - 원래 |fundamental_gap| (0.5) + |erp_zscore| (0.3) = 0.8 펀더멘털 측면
#   → fundamental_gap 제거 → |erp_zscore| 0.5 로 흡수
# - 총 가중치 합: US 7.8 vs KR 7.5 (비슷한 분포 범위 유지)
#
# 산식 검증 (sanity test):
#   compute_noise_score (residual_corr=1.0 단독) → US 1.0, KR 1.0 일치
#
# [수정 — processor/feature1_regime.py]
# - 신규 상수: FEATURE_NAMES_KR (6개), NOISE_WEIGHTS_US/KR (list of (name, w, use_abs))
# - 신규 헬퍼: _feature_names(region), _noise_weights(region), _weights_for_features(feat_names)
# - compute_noise_score(means, region='us') — region 따라 가중치 + abs 분기
# - train_hmm — features_df 에서 region 의 feature subset 만 학습. bundle 에 'feature_names' 추가
# - load_model — 구버전 호환 (feature_names 없는 pkl 은 model.means_.shape 으로 8/6 추정)
# - predict_regime — model_bundle['feature_names'] 길이 따라 추론 차원 자동
# - backfill_noise_regime — full_values dict 만들고 feat_names 순서로 vector 추출
#
# [수정 안 함 — 자동 적응]
# - collector/noise_regime_data_kr.py: 8 컬럼 features DataFrame 그대로 (train_hmm 에서 subset)
# - scripts/train_kr_hmm.py: region='kr' 그대로, 자동 6-feature 학습
# - static/js/main.js: feature_contributions/feature_values 모두 list/dict 순회 — 6/8 자동 적응
#                      NR_FEATURE_KEYS 의 8개 i18n lookup 에 KR 6개 모두 포함됨
#
# [기존 모델 호환]
# - 현재 models/noise_hmm_kr.pkl (5/3 학습, 8-feature) 은 load_model 시
#   '구버전 모델 — feature_names 추정: 8 피처' 메시지와 함께 그대로 동작
# - 사용자가 train_kr_hmm 재실행하면 6-feature 모델로 자동 교체
#
# [검증]
# - python -c "_feature_names('us')/(\'kr\') / _noise_weights / compute_noise_score" → OK
# - load_model('us') / load_model('kr') 모두 8피처 추정 + 정상 로드 확인
# - 가중치 합: US 7.8 vs KR 7.5
#
# [다음 작업 (사용자 환경)]
# - python scripts/train_kr_hmm.py 재실행 (KRX/ECOS 정상 작동 환경 필요)
#   → 6-feature 모델 학습 + 60일 backfill 적재
# - 새 모델은 fundamental_gap·vix_term 평탄 피처 제거되어 EM 수렴 개선 기대
# - score 분포가 US 와 비슷한 -10~+5 범위로 좁아질 수 있음 → A 의 KR 게이지 -25~+5 도
#   재검증 필요 (분포 좁아지면 좌우 끝에 안 찍히게 -10~+5 로 환원 가능)


# ════════════════════════════════════════════════════════════════════════════
# [87] 2026-05-03 (UTC) — Noise 추이 차트 dot 제거 (라인만)
# ════════════════════════════════════════════════════════════════════════════
#
# 사용자: "3개월 추이 차트가 하루하루 모두 점이 찍혀있는데 미국·국내 모두 점을 없애봐".
# 펀더멘털 탭의 "Noise vs Signal 추이 (3개월)" / "시장 이성 점수 추이 (3개월)" 차트
# 에서 매일 데이터 포인트마다 chart-dot circle 이 찍혀 시각적으로 잡음 ↑.
#
# [수정 — static/js/main.js renderLineChart]
# - <circle class="chart-dot"> 데이터 포인트 SVG 제거
# - hover 트리거를 점 단위 mouseenter → svg 단위 mousemove 로 변경
# - findClosest(clientX) 헬퍼 — X 좌표로 가장 가까운 데이터 포인트 인덱스 반환
# - mousemove (마우스), touchstart (터치) 모두 findClosest 로 가까운 점 툴팁
#
# [동작 차이]
# - 시각: 라인 + 그라데이션 영역만 표시, 점 없음
# - 인터랙션: 차트 위 어디든 호버하면 가장 가까운 일자의 noise_score 툴팁
# - region 무관 (US/KR 모두 같은 함수, 동일 동작)
#
# [캐시] main.js?v=124 → ?v=125
# [검증] node --check static/js/main.js → OK
#
# [참고]
# - renderLineChart 호출처는 'nr-chart' 한 군데 (loadNoiseChart) — 다른 차트 영향 없음
# - Crash/Surge 차트 (loadCrashSurgeChart) 는 별도 SVG 직접 작성 — 이번 변경과 무관


# ════════════════════════════════════════════════════════════════════════════
# [88] 2026-05-03 (UTC) — 홈 AI 헤드라인 DB 캐시 (스케줄러 미리 생성)
# ════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자: "국내주식에서 홈탭의 오늘의 종합판단 부분의 로딩이 너무 느린데 수파베이스에
# 미리 계산된 데이터를 적재하고 버튼을 누르면 호출하는 구조가 맞아?"
# → 진단: 기존 home-headline 은 in-memory 캐시 (_headline_cache, TTL=_AI_TTL)만 사용,
#   캐시 miss 시 _groq_call 350 토큰 LLM 직접 호출. 서버 재시작 시 캐시 증발.
#   사용자 첫 진입 또는 재시작 후엔 LLM 응답 대기 → 느림.
#
# [개선]
# DB 테이블 ai_headline_cache 추가, 스케줄러가 미리 생성 → endpoint DB 즉시 응답.
# 조회 우선순위: in-memory hot cache → DB → LLM 즉석 fallback.
#
# [신규 — migrations/2026_05_03_add_ai_headline_cache.sql]
# CREATE TABLE ai_headline_cache (
#     id BIGSERIAL PRIMARY KEY,
#     region TEXT NOT NULL,         -- 'us' | 'kr'
#     lang TEXT NOT NULL,           -- 'ko' | 'en'
#     summary TEXT NOT NULL,
#     generated_at TEXT,            -- KST 시간 문자열
#     created_at/updated_at TIMESTAMPTZ DEFAULT NOW(),
#     UNIQUE (region, lang)
# );
#
# [수정 — database/repositories.py]
# - upsert_ai_headline(region, lang, summary, generated_at) — UNIQUE (region, lang) upsert
# - fetch_ai_headline(region, lang) → dict|None
#
# [수정 — api/routers/market_summary.py]
# - _generate_home_headline(lang, region) — LLM 호출 + 결과 정리 헬퍼 (스케줄러/endpoint 공유)
# - precompute_home_headline(lang, region) → bool
#     · _generate_home_headline → upsert_ai_headline → in-memory 캐시 채움
#     · 스케줄러가 호출
# - get_home_headline (endpoint) 3단 fallback:
#     1) in-memory hot cache (TTL 만료 전이면 가장 빠름)
#     2) DB ai_headline_cache 조회 (스케줄러 미리 생성한 row, source='db' 표시)
#     3) LLM 즉석 호출 → DB+메모리 동시 채움 (source='llm' 표시)
#
# [수정 — scheduler/job_kr.py]
# - run_kr_pipeline 6번째 step 추가:
#     for lang in ('ko', 'en'):
#         precompute_home_headline(lang, 'kr')
# - KR 시장 마감 후 16:00 KST 실행 → KR 헤드라인 항상 최신 데이터 반영
#
# [수정 — scheduler/job.py]
# - run_pipeline Step 10 추가 (Step 9 부동산 다음):
#     for lang in ('ko', 'en'):
#         precompute_home_headline(lang, 'us')
# - 기존 라이트/풀 모드 모두 적용
#
# [효과]
# - 사용자 첫 진입 시 DB 조회 1회 (~50ms) → 즉시 응답
# - 재시작 후에도 빠름 (DB 데이터 유지)
# - LLM 호출은 스케줄러 1회/주기로 제한 (요금·rate-limit 부담 ↓)
#
# [검증]
# - python -c "imports OK" → market_summary/precompute_home_headline + repositories OK
# - fetch_ai_headline 테이블 미존재 시 에러 메시지 정상 ('Could not find the table')
#   → 사용자가 Supabase SQL Editor 에서 migrations/2026_05_03_add_ai_headline_cache.sql
#     실행해야 캐시 활성화
# - 그 전까지는 LLM 즉석 fallback (기존과 동일 동작) 으로 동작
#
# [사용자 액션]
# 1. Supabase SQL Editor 에서 migrations/2026_05_03_add_ai_headline_cache.sql 실행
# 2. 다음 스케줄 (KST 16:00 KR job_kr / US job 실행 시각) 또는 수동 실행:
#      python -m scheduler.job_kr   # KR 헤드라인 미리 채움
#      python -m scheduler.job      # US 헤드라인 미리 채움
# 3. 이후 홈 화면 진입 시 home-headline DB 조회 (~50ms) 즉시 응답
#
# [다음 작업 후보]
# - in-memory _headline_cache 점진 제거 (DB 조회 50ms 면 충분히 빠름)
# - precompute 실행을 한 줄짜리 cron 으로 분리 (LLM 부하 분산)


# ════════════════════════════════════════════════════════════════════════════
# [89] 2026-05-03 (UTC) — Noise 추이 차트 Y축 절대 범위 고정 (게이지와 일치)
# ════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자: "바차트에서는 감정적으로 치우쳐 있고 그래프로는 위로 솟아서 이성적 위치로
# 치우쳐있잖아". 같은 score (-13.4) 인데 게이지는 좌측 (감정 26%), 라인 차트는
# 데이터 자동 범위 (-38~-8) 라 -13.4 가 차트 안에서 위쪽 (이성적 라벨 옆) 에 그려져
# 시각적 모순. 라인차트 Y 라벨 "이성적" 이 -8 위에 붙어 마지막 점 (-13.4) 이
# 이성으로 회복한 것처럼 보임 — 실제론 여전히 감정 영역.
#
# [근본 원인]
# renderLineChart 의 yMin/yMax 가 데이터 min/max 자동 산출 → 모두 음수면 0 기준선
# 안 보이고 라벨 위치가 절대 의미를 잃음.
#
# [수정 — static/js/main.js]
# 1. renderLineChart 에 yFixedMin/yFixedMax 옵션 추가
#    const yMin = options.yFixedMin != null ? options.yFixedMin : rawMin;
#    const yMax = options.yFixedMax != null ? options.yFixedMax : rawMax;
# 2. loadNoiseChart 에서 region 따라 게이지 동일 범위 전달
#    const isKr = _curRegion() === 'kr';
#    renderLineChart('nr-chart', points, {
#        yFixedMin: isKr ? -25 : -10,
#        yFixedMax: 5,
#        ...
#    });
#
# [효과]
# - 게이지 (-25~+5) 와 라인차트 Y 범위 동일 → 같은 score 가 같은 상대 위치에 표시
# - 0 기준선이 차트 위쪽 (KR: 17%, US: 33% 지점) 에 보임
# - "이성적" 라벨 = 0 선 위 영역 (양수 score 만)
# - "감정적" 라벨 = 0 선 아래 영역 (음수 score 만)
# - 모든 데이터가 음수여도 차트 안에서 0 선 아래 어느 부분인지 명확
#
# [캐시] main.js?v=125 → ?v=126
# [검증] node --check static/js/main.js → OK
#
# [예시 — KR score=-13.4]
# 변경 전: 라인차트 위쪽 끝 ≈ -8 ("이성적" 라벨 옆) → 시각상 이성으로 회복
# 변경 후: 0 선 아래 약 60% 지점 → 명확히 감정 영역, "이성적" 라벨 (0선 위) 과 분리


# ════════════════════════════════════════════════════════════════════════════
# [90] 2026-05-03 (UTC) — KR 신호탭 구현 (Crash/Surge XGBoost 24 피처)
# ════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자: "신호탭을 구현해봐". 홈탭 'signal' 타일이 KR 모드에서 비활성화되어 있고
# (home.js KR_SUPPORTED_TILES 미포함), 백엔드/프론트는 region 분기 인프라 완비
# (crash_surge_result 테이블에 region 컬럼) — KR XGBoost 모델만 없는 상태.
#
# 사용자 결정사항 (AskUserQuestion):
#   1. KR 전용 ~24 features (HMM 6-feature 패턴 따라 부재 피처 안 끌고 감)
#   2. 모델 자체를 "20영업일 forward 상승/하락 예측 모델" 로 명명 (US 동일 분류기)
#   3. 임계값 ±10% / 20영업일 (US 와 동일)
#
# [신규 — collector/crash_surge_data_kr.py (24 피처)]
# KR_FEATURES (US 44 → KR 24): KOSPI 가격 7 + 변동성 4 + VKOSPI 3 + 신용 (회사채
# AA-3Y 스프레드) 3 + KR 금리 2 + 외국인 순매수 2 + USDKRW/WTI 2 + 거래대금 z 1
# 데이터 소스 (각 3-tier fallback):
#   - KOSPI OHLCV: pykrx '1001' → FDR 'KS11' → yfinance '^KS11'
#   - VKOSPI: FDR → KOSPI 20D RV proxy
#   - KR 10Y/3Y: ECOS 817Y002 → FDR 'KR10YT=RR'/'KR3YT=RR'
#   - KR 회사채 AA-3Y: ECOS fetch_kr_corp_spread (ECOS only)
#   - 외국인 순매수: pykrx KOSPI trading_value → EWY proxy
#   - USDKRW: yfinance 'KRW=X' (재사용 fetch_usdkrw_history)
#   - WTI: yfinance 'CL=F'
# 함수: fetch_crash_surge_raw_kr(start='2010-01-01'), fetch_crash_surge_light_kr(300),
#       compute_features_kr(raw) → 24-col DataFrame, compute_labels_kr(close) → 3-class
# 라벨 정의 동일: forward 20d / ±10%, surge 먼저 → crash 가 덮어씀 (crash 우선)
#
# [수정 — processor/feature3_crash_surge.py (region 분기)]
#   - _model_path(region) — 'crash_surge_xgb.pkl' (US) ↔ 'crash_surge_xgb_kr.pkl' (KR)
#   - _feature_names_for_region(region) — ALL_FEATURES 44 ↔ KR_FEATURES 24
#   - train_crash_surge(..., region='us') — bundle 에 'region', 'feature_names' 키 추가, _model_path 로 저장
#   - load_model(region) — 구버전 호환 (feature_names 없으면 model.n_features_in_ 으로 24/44 추정)
#   - load_crash_surge_model = load_model 별칭
#   - predict_crash_surge / backfill_crash_surge — model_bundle['feature_names'] 사용 → 차원 자동
#   - SHAP / feature_values / feature_importance 모두 feat_names 기반
#
# [신규 — scripts/train_kr_crash_surge.py]
# train_kr_hmm.py 패턴 따라 1회성 학습 + backfill + DB 적재 스크립트.
# python -m scripts.train_kr_crash_surge --start 2010-01-01 --backfill 60 --trials 50
# 흐름:
#   1. fetch_crash_surge_raw_kr(start)
#   2. compute_features_kr(raw) + compute_labels_kr(close)
#   3. _prepare_datasets_kr (US prepare_datasets 패턴, KR_FEATURES 사용)
#      train/calib/test/dev 시간순 split (504 holdout / 1008 calib / 나머지 train)
#   4. train_crash_surge(region='kr') → models/crash_surge_xgb_kr.pkl
#   5. backfill_crash_surge(df_full, bundle) — 최근 N일 자르기
#   6. upsert_crash_surge(rec, region='kr')
#
# [수정 — scheduler/job_kr.py Step 7 추가]
# 6) home-headline 다음에 7) crash_surge 추가:
#   - load_crash_surge_model(region='kr') 있으면 fetch_light → compute_features → predict
#   - 결과 upsert_crash_surge(rec, region='kr')
#   - 모델 없으면 학습 안내 메시지만 출력
#   - upsert_crash_surge import 추가
#
# [수정 — static/js/home.js]
# KR_SUPPORTED_TILES 에 'signal' 추가 — 학습 후 자동 활성화. home.js?v=28 → ?v=29
#
# [검증]
# - python -c "from collector.crash_surge_data_kr import *; from processor.feature3_crash_surge import *" OK
# - KR_FEATURES 24개 확인
# - _model_path('us') / ('kr') 분기 확인
# - load_crash_surge_model('kr') → None (모델 미존재, 정상)
# - run_kr_pipeline import OK — Step 7 안내 메시지 출력 흐름 검증
# - node --check home.js OK
#
# [사용자 액션]
# 1. KRX/ECOS 정상 환경에서:
#      python -m scripts.train_kr_crash_surge
#    (Optuna 50-trial, 5~15분 학습, models/crash_surge_xgb_kr.pkl 저장, 60일 backfill)
# 2. 다음 스케줄 (KST 16:00 KR job_kr) 부터 자동으로 매일 1행 신규 적재
# 3. 브라우저 hard refresh → 홈탭 '신호' 타일 활성화 + 신호탭 진입 → KR 데이터 표시
#
# [한계]
# - 이 환경 (KRX 차단) 에선 학습 못 함 — 사용자 production 환경 필수
# - KR ECOS 회사채 시계열이 2010~ 안정 — --start 더 일찍 가면 spread 0 fallback
# - 신호탭 detail 페이지의 SHAP 라벨이 영문 feature 명 — 추후 i18n 라벨 매핑 별도 작업
# - crash_surge_xgb_kr.pkl 누적 학습 시 macro_f1 < 0.4 면 재검토 (KR 표본 부족 가능성)


# ═══════════════════════════════════════════════════════════════════════════════
# [91] 2026-05-03 (UTC) — KR 거시경제 탭 (Sector Cycle 5번째 탭) 완전 포팅
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 5번째 탭 'tab-sector' (라벨 '거시경제') 는 미국 모드에서 거시 8종 → HMM 4-state 경기국면
# → 섹터 회전 추천 통합 화면이지만 KR 모드에선 빈 화면이었음 (sector_macro_kr/sector_cycle_kr/
# sector_valuation_kr 모두 미구현). 미국 구조를 KR로 1:1 포팅 — 같은 DOM 컨테이너에서 region
# 토글로 KR/US 데이터 전환. KR 거시 12종 (FRED 8 등가 + CPI/GDP/실업률/M2 추가) 신규 수집.
# 백엔드 region plumbing은 repositories.py / api/routers/sector_cycle.py 모두 이미 끝나
# 있어서 데이터만 채우면 작동.
#
# [Why]
# - KR 패시브 진행도 ~55% → ~80% 도달 (HMM·Crash/Surge·ERP 후 마지막 미구현 영역이었음)
# - 미국 패시브와 기능 parity 확보
# - 거시 → 경기국면 → 섹터 추천 한 묶음 (라벨이 '거시경제' 인 이유: PMI/spread/ANFCI 등으로
#   국면 분류) 의 KR 등가가 사용자 의사결정에 핵심 가이드
#
# [신규 — migrations/2026_05_03_add_kr_sector_macro_columns.sql (60 LOC)]
# sector_macro_raw 에 KR 14컬럼 ALTER (NULLable, sparse). UNIQUE(region,date) 재사용.
#   kr_indpro_yoy / kr_yield_spread / kr_credit_spread / kr_unemp_yoy / kr_unemp_rate /
#   kr_permit_yoy / kr_retail_yoy / kr_capex_yoy / kr_income_yoy /
#   kr_cpi_yoy / kr_gdp_yoy / kr_m2_yoy /
#   kr_indpro_chg3m / kr_capex_yoy_chg3m  (derived 2)
# US 행은 KR 컬럼 NULL, KR 행은 US 컬럼 NULL — 같은 테이블 안에서 region 만으로 분기.
#
# [수정 — collector/ecos_macro.py (B.0 선결)]
# 1) SPECS dict 분리 — RATE_SPECS (매수 시그널용 6개) / SECTOR_MACRO_SPECS (sector cycle 5개)
#    SPECS = {**RATE_SPECS, **SECTOR_MACRO_SPECS}  # fetch_ecos_series 호환 유지
#    fetch_macro_rate_kr() 의 순회 대상을 RATE_SPECS.keys() 로 좁힘 — 매수 시그널 호출이
#    sector cycle 거시 12종까지 끌고 와 호출 폭증하는 사고 방지.
# 2) _ecos_time_to_date() 에 Q cycle 분기 추가 — '2024Q1' → 2024-01-01.
#    GDP 같은 분기 데이터가 그대로 두면 KeyError 로 통째 버려지던 버그 fix.
# 3) SECTOR_MACRO_SPECS 5종 추가:
#    kr_cpi (901Y009/0/M), kr_gdp (200Y001/10101/Q), kr_unemp_rate (901Y027/I16A/M),
#    kr_m2 (101Y004/BBHA00/M), kr_household_income (901Y057/A00/Q)
#    ⚠️ 통계표 코드는 ECOS StatisticItemList 로 1회 sweep 검증 권장.
#
# [신규 — collector/kosis_macro.py (~120 LOC)]
# KOSIS Open API 로 4종 거시 신규 수집 (FRED INDPRO/PERMIT/RRSFS/ANDENO 등가):
#   kr_indpro (101/DT_1F31501/T1)  광공업생산지수
#   kr_retail (101/DT_1KS1003/T1)  소매판매액지수
#   kr_capex  (101/DT_1F31503/T2)  설비투자지수
#   kr_permit (116/DT_MLTM_5345/T1) 건축허가 면적
# 패턴은 collector/kosis_migration.py 와 동일 (httpx + KOSIS_API_KEY).
# 실패 시 빈 list 반환 — 한 시리즈 실패해도 나머지는 진행.
#
# [신규 — collector/sector_macro_kr.py (~170 LOC)]
# US sector_macro.py 의 KR 등가. ECOS (5+3 시장금리) + KOSIS (4) 통합 aggregator.
# fetch_sector_macro_kr(months=240) → MS 인덱스 wide DataFrame (12 컬럼 + derived 2).
# 핵심 처리:
#   - 분기 데이터(GDP, 가계소득) 는 .resample('MS').last().ffill(limit=2) — 분기 첫달에 값,
#     다음 두 달 ffill (전 분기 값 유지)
#   - YoY 변환 (.pct_change(12)*100) — 시리즈별로 _yoy() helper
#   - kr_yield_spread = 10Y - 3Y, kr_credit_spread = corp_aa3y - 3Y (derived raw level)
#   - kr_indpro_chg3m / kr_capex_yoy_chg3m = .diff(3) (모멘텀)
#   - dropna(how='all') — 모든 컬럼 NaN 인 초기 행만 제거 (부분 NaN 행 유지)
# to_sector_macro_kr_records(df) → upsert_sector_macro 호출용 dict (region='kr').
#
# [수정 — collector/sector_etf_kr.py (+130 LOC)]
# 1) ALL_HOLDINGS_KR 신규 — KR 사용자 자주 보유 ETF 8종 (069500/102110/226490/232080/
#    229200/278530/360750/252670)
# 2) fetch_sector_etf_returns_kr(macro_start, etf_start='2010-01-01') 신규 — 10 sector +
#    8 holding ETF 월별 수익률 두 DataFrame 반환. 기존 _etf_ohlcv_dual_source 재사용
#    (pykrx → FDR 폴백). KR 일부 ETF 상장 후 짧으면 NaN 그대로 — feature2_sector_cycle 의
#    바뀐 dropna 정책이 처리.
# 3) fetch_sector_etf_per_pbr_kr() 1차 fallback 구현 — 빈 stub 이었던 것을 KOSPI 시장 평균
#    PER/PBR (collector/market_data_kr.fetch_kospi_per_pbr) 을 모든 섹터에 동일 적용.
#    정확도↓ ticker별 z-score 변별력 약하지만 화면은 즉시 채워짐. 정확한 ETF holdings
#    가중평균 (pykrx get_etf_portfolio_deposit_file) 은 Stage 2 별도 PR.
#
# [신규 — processor/sector_valuation_kr_backfill.py (~100 LOC)]
# US sector_valuation_backfill 의 KR 등가. PER/PBR proxy 공식:
#   PER_t ≈ PER_today × (Close_t / Close_today)
# 60개월 × 10 ETF = 600행 sector_valuation 테이블 upsert (region='kr').
# 월말 종가 추출은 pykrx → FDR 폴백 (_etf_ohlcv_dual_source 재사용).
#
# [수정 — processor/feature2_sector_cycle.py (region 분기 + dropna 정책 변경)]
# 1) FEATURE_COLS_US (10) / FEATURE_COLS_KR (14) 분리. PHASE_SCORE_COLS dict — region
#    별 level/momentum 컬럼 매핑.
# 2) _map_states_to_phases(model, feature_cols, region) — 인덱스 동적 조회로 안전화
#    (feature_cols.index(level_col) — 컬럼 순서 변경 시도 안전).
# 3) run_sector_cycle(macro, sector_ret, holding_ret, region='us') 시그니처 변경 — region
#    파라미터로 SECTOR/HOLDING/feature_cols 분기.
# 4) 핵심 dropna 정책 변경 — 기존 macro.join(sector_ret).join(holding_ret).dropna() 가
#    KR ETF 일부 상장 < 24개월일 때 학습 데이터 거의 0행으로 만드는 사고 방지:
#    a) df_macro = macro[available_features].dropna()  — FEATURE_COLS 만 dropna
#    b) sector_ret/holding_ret 는 available_cols 만 left join (NaN 허용)
#    c) HMM 학습 X = df_macro 만 사용 (sector NaN 무관)
#    d) 국면별 평균은 컬럼별 .mean(skipna=True), notna().any() 로 무의미 컬럼 제외
#    US 동작도 같이 안전해짐 (회귀 무).
#
# [신규 — scripts/train_kr_sector_cycle.py (~120 LOC)]
# 사용: python -m scripts.train_kr_sector_cycle --months 240
# 흐름:
#   1) fetch_sector_macro_kr(months) → KR 거시 12+derived 2
#   2) upsert_sector_macro(records, region='kr') — 청크 200개씩
#   3) fetch_sector_etf_returns_kr(macro_start) — 18 종목 (10 sector + 8 holding)
#   4) run_sector_cycle(macro, sector_ret, holding_ret, region='kr')
#   5) upsert_sector_cycle(result, region='kr')
#   6) (선택) backfill_sector_valuations_kr(months=60)
# .pkl 저장 안 함 — US 도 매번 학습+추론 (월별 데이터라 비용 작음).
#
# [수정 — scheduler/job_kr.py Step 8/9 추가]
# 7) crash_surge 직전에 8) sector_cycle + 9) sector_valuation 삽입:
#   8) fetch_sector_macro_kr → upsert_sector_macro → fetch_sector_etf_returns_kr →
#      run_sector_cycle(region='kr') → upsert_sector_cycle(region='kr')
#      각 단계 try/except 분리 — 일부 실패해도 다음 단계 진행
#   9) fetch_sector_etf_per_pbr_kr → upsert_sector_valuation(region='kr')
#
# [수정 — database/repositories.py:232 fetch_sector_macro_history]
# select 절 확장 — US 9 컬럼만 → US 10+derived 2 + KR 12+derived 2 = 26 컬럼 전체.
# region='kr' 행에서 KR 컬럼 보이게 + region='us' 행은 기존 동작 유지 (sparse → NULL 허용).
#
# [수정 — static/js/sector.js (~80 LOC)]
# 1) _isKr() helper — window.getRegion() === 'kr'
# 2) _MACRO_KEYS_US / _MACRO_KEYS_KR / _SECTOR_KEYS_US / _SECTOR_KEYS_KR 상수
# 3) getMacroLabels() / getSectorLabels() / getMacroDesc() 모두 region 분기
# 4) MACRO_GOOD_HIGH / MACRO_NEUTRAL — KR 14키 추가 (CPI 중립=2.0 BOK 타깃, 실업률=3.0)
# 5) formatMacroValue(key, val) helper — _RAW_LEVEL_KEYS Set 으로 raw level (PMI/ANFCI/
#    실업률/spread) 은 toFixed, 나머지 YoY% 는 signStr+'%'. 매크로 스냅샷 + spark line
#    display 양쪽 통합.
# 6) macro-history indicators (8 spark line) — region 별 키 세트 분기
#
# [수정 — static/js/i18n.js — 44 항목 (KO/EN 22개 × 2)]
# - sector.139260~227560 (KR 10 ticker 한글/영문 라벨)
# - macro.kr_indpro_yoy~kr_capex_yoy_chg3m (KR 14 매크로 라벨)
# - macroDesc.kr_* (12 매크로 설명)
#
# [검증]
# - 모든 .py 파일 ast.parse OK
# - sector.js / i18n.js node --check OK
# - feature2_sector_cycle.py 회귀 — US run_sector_cycle 의 dropna 정책 변경 (FEATURE_COLS
#   만 dropna + sector_ret left join) 도 US 데이터에 적용되지만, US ETF 모두 1999~ 상장이라
#   기존 inner join 결과와 동일 (변화 무).
# - repositories.fetch_sector_macro_history(region='us') — KR 컬럼 NULL 로 응답되지만 sector.js
#   가 region 분기로 US 키만 사용해 무관.
#
# [사용자 액션 — 순서대로]
# 1. Supabase SQL Editor 에서 마이그레이션 실행:
#    migrations/2026_05_03_add_kr_sector_macro_columns.sql
#    검증: SELECT column_name FROM information_schema.columns
#          WHERE table_name='sector_macro_raw' AND column_name LIKE 'kr_%' → 14행
# 2. ECOS_API_KEY / KOSIS_API_KEY 환경변수 설정 확인 (.env)
# 3. 1회 학습 + 적재:
#    python -m scripts.train_kr_sector_cycle --months 240
#    (~5~10분, ECOS+KOSIS API 호출, sector_macro_raw 270행 + sector_cycle_result 1행 +
#     sector_valuation 600행)
# 4. 다음 KST 16:00 KR 스케줄러부터 매일 1행 갱신 (Step 8/9 자동 실행)
# 5. 브라우저 hard refresh → 헤더 region 토글 KR → 5번째 탭 (거시경제) 클릭:
#    - Phase Card (회복/확장/둔화/침체) + 갭 바
#    - Top 3 Sectors (091160 등 KR ticker + 한글 라벨)
#    - Sector Heatmap 4행 × 10열
#    - AI 해설 한국어
#    - Phase 카드 클릭 → Macro Snapshot 12 KR 카드 + 8 spark line
#
# [한계]
# - ECOS 통계표 코드 (901Y009 CPI 등) 는 ECOS UI 검증 필요 — 잘못된 코드 시 해당 시리즈만 빈 결과
# - KOSIS 통계표 코드 (DT_1F31501 등) 도 동일 검증 필요
# - sector_valuation 1차 fallback (KOSPI 시장 평균 동일 적용) 은 ticker별 z-score 변별력 약함
#   → Stage 2 (pykrx ETF holdings 가중평균) 별도 PR 필요. 비용 500 API 호출이라 일별 1회 cron OK.
# - KR 분기 데이터 (GDP, 가계소득) 는 분기 마지막 발표월 이후 ffill — 월말 시점에 신호 지연
# - Phase 라벨 (회복/확장/둔화/침체) 은 US 와 동일 라벨 사용 — KR 경기 사이클과 의미 차이 가능성
#   존재. 필요 시 i18n 라벨에 '(KR 추정)' 부기 가능.


# ═══════════════════════════════════════════════════════════════════════════════
# [92] 2026-05-04 (UTC) — KR Sector Cycle 1차 실행 fix (ECOS 통계표 코드 검증 + dropna 완화)
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# [91] 마무리 후 production 에서 train_kr_sector_cycle 1차 실행 → 4건 ECOS 에러 + 4건 KOSIS
# 에러 + dropna 미흡으로 학습 실패. ECOS API 직접 검증 (StatisticTableList + StatisticItemList
# sweep) 으로 정확한 통계표/항목 코드 확정 + Q cycle 형식 fix + dropna 정책 추가 완화.
# 결과: 12 매크로 중 10개 가용 (kr_income_yoy / kr_permit_yoy 만 빠짐), HMM 학습 성공.
# 1차 production 실행 검증: 2026-04-01 → 🍂 둔화 (99.9%), Top3 = [139260 IT, 091160 반도체,
# 341850 리츠].
#
# [Why — 4개 critical 버그 발견]
# 1. ECOS Q cycle (GDP/가계소득) — _ecos_series_monthly 가 from/to 를 'YYYYMM' 으로 보냈는데
#    Q 주기는 'YYYYQ#' 형식이라 ERROR-101 ('주기와 다른 형식'). 형식 분기 추가.
# 2. ECOS 통계표/항목 코드 모두 부정확 — 200Y001 (GDP), 901Y027/I16A (실업률), 101Y004/BBHA00
#    (M2), 901Y057/A00 (가계소득) 모두 INFO-200 (데이터 없음). KeyStatisticList 100대 지표 +
#    StatisticTableList sweep 으로 정확한 코드 확정.
# 3. KOSIS tblId 4종 모두 무효 (DT_1F31501 등 → 21 에러). ECOS 에 광공업/소매/설비투자 모두
#    있어 KOSIS 의존 제거.
# 4. dropna 정책 — feature_cols 14개 중 일부만 fetch 성공해도 전체 14컬럼 dropna 면 0행 (부분
#    NaN 행 모두 제거). non_empty 컬럼 subset 만 사용하도록 추가 완화.
#
# [수정 — collector/sector_macro_kr.py:_ecos_series_monthly Q cycle fix]
# elif cycle == "Q" 분기 추가:
#   q_now = (today.month - 1) // 3 + 1
#   from_t = f"{fy}Q{fq}", to_t = f"{today.year}Q{q_now}"
# (이전: M/Q 모두 'YYYYMM' 으로 통합 → Q 면 ECOS 가 ERROR-101)
#
# [수정 — collector/ecos_macro.py:SECTOR_MACRO_SPECS 7종 정확한 코드]
# 검증 후 코드 (2026-05-04 기준 ECOS API):
#   kr_cpi             → 901Y009 / 0       / M  (소비자물가지수 총지수, 1965~)
#   kr_gdp             → 200Y108 / 10601   / Q  (국내총생산에 대한 지출, 1960Q1~)
#   kr_unemp_rate      → 901Y027 / I61BC   / M  (실업률, 1999.06~)
#   kr_m2              → 161Y007 / BBGS00  / M  (M2 말잔 계절조정, 2003~)
#   kr_indpro          → 901Y033 / AB00    / M  (광공업생산지수, 2000~)
#   kr_retail          → 901Y100 / G0      / M  (소매판매액지수 총지수, 1995~)
#   kr_capex           → 901Y066 / I15B    / M  (설비투자지수 계절조정, 월별)
# (이전 무효 코드: kr_household_income/kr_unemp_rate/kr_m2/kr_gdp 모두 INFO-200)
#
# [수정 — collector/sector_macro_kr.py:fetch_sector_macro_kr — KOSIS 의존 제거]
# ECOS 7종 우선 사용. KOSIS 는 건축허가 (kr_permit) 만 시도 — tblId 미검증이라 실패해도 NaN
# 컬럼으로 graceful (학습에서 자동 제외). 가계소득 (kr_household_income) 도 ECOS 통계표
# 미검증이라 일단 빈 Series 로 명시적 처리.
#
# [수정 — processor/feature2_sector_cycle.py:run_sector_cycle dropna 추가 완화]
# 기존: macro[available_features].dropna() — 부분 NaN 행 모두 제거
# 변경: non_empty = [c for c in available_features if macro[c].notna().any()]
#       df_macro = macro[non_empty].dropna()  # 데이터 0행 컬럼은 처음부터 제외
#       feature_cols_used = non_empty  # 후속 단계 모두 이걸 사용 (X_df / state_to_phase /
#                                       macro_snapshot)
# 결과: ECOS 일부 시리즈 무효일 때도 가용 컬럼만으로 학습 성공.
#
# [수정 — feature2._map_states_to_phases momentum col fallback]
# 기존: feature_cols.index(mom_col) ValueError 시 fallback 없음
# 변경: mom_col not in feature_cols 면 level only 점수 (model.means_[:, i_level])
# KR 환경에서 indpro_chg3m 가용 — 정상 작동, 안전망.
#
# [검증 — production 1차 실행 결과]
# - sector_macro 246건 upsert (region=kr)
# - 가용 컬럼 13/14 (kr_income_yoy 만 NaN — KOSIS 가계동향 leaf tblId 미검증, 나머지 13개 OK)
# - HMM 학습 OK, LL/sample = -10.04 (컬럼 13개로 학습)
# - 결과: 2026-04-01 → 🍂 둔화 (100.0% 확률)
# - Top3: 139260 (TIGER 200 IT), 091160 (KODEX 반도체), 266420 (KODEX 헬스케어)
# - sector_cycle_result 1행 upsert (region=kr)
# - sector_valuation backfill — 이 개발 환경에서 KRX 차단으로 fetch 실패, production 환경에선
#   정상 작동 예상 (1차 fallback: KOSPI 시장 평균 PER/PBR 동일 적용)
#
# [추가 fix — kr_permit ECOS 코드 검증]
# 901Y105 / ALL / M (주택건설인허가실적 전국, 2007.01~2026.02). 901Y037 (건축허가현황) 은
# 데이터 시작 201901~로 짧아 부적합 — 901Y105 로 18년치 확보.
#
# [추가 fix — home.js KR_SUPPORTED_TILES 에 'macro' 추가]
# 사용자 보고: 홈 화면 KR 모드에서 "거시경제" 타일이 "준비 중" 회색 처리 — KR_SUPPORTED_TILES
# 에 'macro' 누락. [91] 에서 신호탭 ('signal') 추가했던 패턴 동일. home.js?v=30 + main.js?v=129
# + sector.js?v=6 (cache-bust).
#
# [추가 fix — KR 모드에서 ETF ticker(6자리) 숨기고 한글 이름 메인]
# 사용자 보고: Top Sectors 와 Sector Heatmap 헤더에 ticker(139260 등) 가 메인이고 한글 이름이
# 부제로 표시 — KR 사용자에겐 6자리 숫자 무의미. _isKr() 분기 추가:
# (1) Top3 sc-top-item: KR=label 만 (font-bold) / US=ticker + label
# (2) Heatmap 헤더 sc-hm-col: KR=한글 이름만 / US=ticker<br>한글 이름
# i18n 라벨 단순화: 'IT (TIGER 200 IT)' → 'IT', '반도체 (KODEX 반도체)' → '반도체' 등
# (Heatmap 셀 폭 좁아 짧을수록 보기 좋음). sector.js?v=7.
#
# [향후 작업 (별도 PR)]
# - kr_household_income (가계소득) — KOSIS 가계동향조사 (E_2_002_001 전국명목) leaf 통계표
#   ORG_ID/TBL_ID 검증 필요. KOSIS API explorer 깊이 깊어 추가 작업 — 분기 데이터라 노이즈
#   크고 학습 영향 작아 우선순위 낮음.
# - sector_valuation Stage 2 — pykrx get_etf_portfolio_deposit_file 가중평균 (별도 PR).


# ═══════════════════════════════════════════════════════════════════════════════
# [93] 2026-05-04 (UTC) — AI 해설 (5탭) DB 캐시 + 스케줄러 precompute
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자 보고: 거시경제 탭 (5번 탭) 진입 시 로딩이 느림. 진단 결과 데이터 endpoint
# (/api/sector-cycle/current/macro-history/valuation) 는 모두 DB SELECT 만 → 빠름. 느린 건
# /api/market-summary/ai-explain — in-memory 캐시만 있어 TTL 만료/재시작 시 LLM(Groq) 즉석 호출
# 1~3초. [88] 의 home-headline 패턴 (DB 캐시 + 스케줄러 precompute) 을 5탭 AI 해설에 미러링.
#
# [Why]
# - "Supabase 미리 적재 + 사용자 클릭은 단순 fetch" 구조가 일관되게 모든 endpoint 적용
# - 모든 5탭 (fundamental/signal/sector/sector-val/sector-mom) 의 AI 해설 첫 진입 즉시 응답
# - 서버 재시작 시 in-memory 증발 → DB 캐시가 fallback 보장
#
# [신규 — migrations/2026_05_04_add_ai_explain_cache.sql]
# ai_explain_cache 테이블 — UNIQUE (tab, lang, region). region='kr' 행과 region='us' 행 분리.
# sector-mom 은 region 무관이지만 region='us' 로 통일 (스키마 단순).
# 최대 5 tab × 2 lang × 2 region = 20 entry. 작음.
#
# [수정 — database/repositories.py]
# upsert_ai_explain(tab, lang, region, explanation, generated_at) — UNIQUE 충돌 시 update
# fetch_ai_explain(tab, lang, region) → dict | None
# 패턴: ai_headline 함수 동일 (region+lang → tab+lang+region 으로 키 1개 더).
#
# [수정 — api/routers/market_summary.py]
# 1) _generate_ai_explain(tab, lang, region) helper 추출 — _build_explain_text + _groq_call +
#    텍스트 정리 + generated_at 부착. 실패 시 None.
# 2) precompute_ai_explain(tab, lang, region) 신규 — 스케줄러용. _generate 결과를
#    upsert_ai_explain + in-memory 캐시 동시 채움.
# 3) get_ai_explain endpoint 3-tier fallback 으로 변경:
#    1차 in-memory cache (TTL 30분) → 2차 fetch_ai_explain DB → 3차 LLM 즉석 호출
#    3차 호출 시 DB + memory 모두 채워 다음 호출 hit. 응답에 generated_at 포함.
#
# [수정 — scheduler/job_kr.py Step 10 추가]
# 7) crash_surge 다음에 10) ai-explain precompute. KR × (fundamental/signal/sector) × (ko/en)
#    = 6 entry. region 무관 sector-val/sector-mom 은 US 파이프라인에서 담당.
#
# [수정 — scheduler/job.py Step 11 추가]
# 10) home-headline 다음에 11) ai-explain precompute. US × 5탭 × (ko/en) = 10 entry.
#    sector-val/sector-mom 포함 (전역).
#
# [검증]
# - python -c "import ast; ast.parse(open('...').read())" 4개 파일 OK
# - market_summary.py 2-tier (memory + DB) → 3-tier (memory + DB + LLM fallback) 변환 동작
#   3차 호출 시 upsert + memory 채움 → 다음 호출은 1차 hit (즉시).
#
# [사용자 액션]
# 1. Supabase SQL Editor 에서 마이그 실행:
#    migrations/2026_05_04_add_ai_explain_cache.sql
# 2. 다음 스케줄 사이클 (KST 16:00 KR job_kr / KST 09:00 US job) 부터 자동 적재
# 3. 수동 즉시 적재 원하면:
#    python -c "from api.routers.market_summary import precompute_ai_explain;
#               [precompute_ai_explain(t,l,r) for t in ['fundamental','signal','sector']
#                for l in ['ko','en'] for r in ['us','kr']]"
#
# [한계]
# - LLM 호출 비용은 그대로 (Groq) — 빈도만 줄임 (사용자 클릭마다 → 일별 1회)
# - 데이터 변경 (예: sector_cycle 결과 갱신) 후 24시간 동안은 이전 해설 표시 가능 — 실시간성
#   덜 중요한 영역이라 trade-off 수용
# - sector-mom 은 region 무관이라 region='us' 만 적재. KR 모드에서도 같은 해설 표시.


# ════════════════════════════════════════════════════════════════════════════
# [94] 2026-05-04 (UTC) — KR 섹터 밸류에이션 PDF 가중평균 (1차 fallback → 정확)
# ════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자: "국내주식 섹터 밸루에이션 구현". 기존 fetch_sector_etf_per_pbr_kr 가
# 모든 10개 ETF 에 같은 KOSPI 평균 PER/PBR 적용 (1차 fallback) → z-score 가
# 가격 비율로만 차이나 변별력 부족. 'sector-val' 타일도 KR 비활성.
#
# 사용자 결정 (AskUserQuestion):
#   - PER/PBR 산출: PDF 가중평균 (pykrx.get_etf_portfolio_deposit_file → 종목별 PER → 비중 가중)
#   - holdings 갱신: 주 1회 (TTL 7일 JSON 캐시)
#
# [신규 — collector/etf_holdings_kr.py]
# - fetch_etf_holdings_kr(force_refresh=False) — 10 ETF holdings 캐시 (models/etf_holdings_kr.json)
#     · _is_fresh: TTL 7일 검증
#     · _fetch_pdf_for_ticker: pykrx.get_etf_portfolio_deposit_file 호출, '비중' 컬럼 우선
#       (없으면 계약수×종가 시총 추정 fallback)
# - get_holdings_for_etf(ticker) — 헬퍼
#
# [수정 — collector/sector_etf_kr.py]
# - 신규 _fetch_kospi_market_per_pbr() — fallback 시장 평균
# - 신규 _fetch_all_stock_fundamentals(ref_date) — pykrx.get_market_fundamental(KOSPI/KOSDAQ)
#   2회 호출로 전체 종목 PER/PBR 1번에 fetch (적자 per≤0 미포함)
# - 신규 _weighted_avg(holdings, stock_fund, key) — 비중 가중평균 + 부재/적자 비중 재정규화
#   coverage = Σ(w_valid) / Σ(w_all) 반환
# - 교체 fetch_sector_etf_per_pbr_kr() — 가중평균 산출, coverage<50% 또는 빈 holdings 면
#   per_ticker fallback (KOSPI 평균). 로그 "PDF 가중평균 N건 / fallback N건 / coverage avg X%"
#
# [수정 — static/js/home.js]
# - KR_SUPPORTED_TILES 에 'sector-val' 추가 — 'sector-val' 타일 KR 모드 활성
# - home.js?v=30 → ?v=31
#
# [scheduler 변경 없음]
# job_kr.py Step 9 호출부 그대로 — 내부 로직만 정확 가중평균으로 교체.
#
# [검증]
# - python -c "from collector.etf_holdings_kr import fetch_etf_holdings_kr" OK
# - _weighted_avg unit test: holdings=[50,30,20], fund={001:10, 002:20} → PER=13.75, cov=80% ✓
# - 이 환경 KRX 차단 → 종목 fundamental 0개 → 10건 모두 fallback 동작 정상
# - node --check home.js OK
#
# [사용자 액션 (production)]
# 1. 첫 실행 시 holdings 캐시 자동 생성 (10 ETF PDF fetch, ~30초)
# 2. 다음 스케줄 (KST 16:00 KR job_kr) 부터 매일 ETF 별 다른 PER/PBR 적재
# 3. 브라우저 hard refresh → 홈탭 'sector-val' 타일 활성 + 변별력 있는 z-score 표시
#
# [한계]
# - 이 환경 KRX 차단 → fallback 만 동작 (테스트는 코드 구조 검증 수준)
# - 적자 종목 多한 섹터 (헬스케어 등) 는 covered 비중 낮아질 수 있음 → 50% 미만이면 fallback
# - 우선주·해외 ADR 종목은 pykrx fundamental 부재 — 같은 fallback
# - holdings TTL 7일 → ETF 재구성 (분기 1회) 직후 며칠 지연 가능
# - z-score 5년 history 사용 — 새 가중평균 적재 후 1~2주 흔들림, 한 달 후 안정화


# ═══════════════════════════════════════════════════════════════════════════════
# [94] 2026-05-04 (UTC) — KR 섹터 모멘텀 (sector-mom) 별 탭 KR 포팅
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 미국 sector-mom 별 탭 (홈 "섹터 모멘텀" 타일 → tab-sector-mom) 의 KR 포팅. 11종 SPDR 의
# 1주일·1개월 누적 수익률 + 랭킹 → KR 모드에선 KODEX/TIGER 10종 (139260 IT 등) 매핑.
# index_price_raw region='kr' 데이터가 매일 적재 중이라 (job_kr.py Step 5) 백엔드 region
# 분기만 추가하면 즉시 동작. 5 파일 ~55 LOC 변경.
#
# [Why]
# 사용자 요청 — KR 사용자에게도 섹터 모멘텀 랭킹 표시. 인프라 (DB region='kr' 행 + region.js
# fetch monkey-patch + ai_explain_cache [93]) 거의 갖춰져 백엔드 region 분기 + 프론트 ticker
# 한글 매핑만 하면 완성.
#
# [수정 — processor/feature7_sector_momentum.py]
# - import 변경: SECTOR_VALUATION_ETFS 모듈 상단 import 제거 (region 별 동적 import)
# - _ticker_map_for_region(region) helper 신규 — 'us' → SECTOR_VALUATION_ETFS, 'kr' → SECTOR_ETF_KR
# - compute_sector_momentum(region: str = 'us') 시그니처 변경
#   * DB query 에 .eq("region", region) 필터 추가 — us/kr 분리 조회
#   * ticker_map 으로 영문/한글 sector_name 분기
#   * 반환 dict 에 'region' 필드 추가
#
# [수정 — api/routers/sector_cycle.py:/momentum]
# - get_momentum(region: str = Query('us')) 시그니처 변경 + _norm_region 정규화
# - _momentum_cache 를 region 별 dict 분리: {region: {data, ts}} (이전 단일 캐시 → us 첫 호출이
#   kr 응답 덮어쓰는 버그 방지)
#
# [수정 — api/routers/market_summary.py:_build_explain_text]
# - 'sector-mom' 탭의 compute_sector_momentum() 호출 → compute_sector_momentum(region=region)
# - tab + lang + region 별 ai_explain_cache 자동 분리 ([93] 적용)
#
# [수정 — static/js/home.js]
# - SECTOR_KR dict 에 KR 10 ticker 한글 매핑 추가 (139260: 'IT' / 091160: '반도체' 등)
# - krSector(ticker, fallback) 헬퍼 변경 없음 — US/KR 같은 dict 에서 lookup
# - KR_SUPPORTED_TILES 에 'sector-mom' 추가 (signal/macro/sector-val 패턴 동일)
# - 미적용 시 KR 모드에서 sector-mom 타일 회색 처리 ("준비 중")
#
# [수정 — scheduler/job_kr.py Step 10]
# - ai-explain precompute 탭 리스트: ('fundamental', 'signal', 'sector') →
#   ('fundamental', 'signal', 'sector', 'sector-mom')
# - KR × 4탭 × 2lang = 8 entry 매일 적재
#
# [수정 — templates/stocks.html]
# - home.js v=31 → v=32 cache-bust
#
# [검증]
# - python -m ast 4개 파일 OK
# - 백엔드 단위 테스트 (Stage D.1):
#   compute_sector_momentum('kr')['momentum'] → KR ticker (139260, '반도체') 등
#   compute_sector_momentum('us')['momentum'] → SPDR (XLK, 'Technology') 등
#
# [사용자 액션]
# 1. 브라우저 hard refresh — momentum 데이터는 이미 DB 적재 중이라 즉시 응답
# 2. KR 모드 → 홈 "섹터 모멘텀" 타일 활성 → 클릭 → 한글 라벨 + 랭킹 표시
# 3. AI 해설 1차 진입은 LLM fallback ([93] 3-tier), 다음 KST 16:00 KR 스케줄러 사이클 후 즉시
#
# [한계]
# - KR sector ETF 중 일부 (341850 리츠 등) 상장 후 21 거래일 미만이면 1M return None 표시
#   (정상 동작 — index_price_raw 누적 21일 이후 자동 채워짐)
# - sector-mom AI 해설은 [93] 의 ai_explain_cache 에 저장 — 24시간 캐시 (TTL)


# ═══════════════════════════════════════════════════════════════════════════════
# [95] 2026-05-04 (UTC) — region 토글 임시 숨김 + AI 해설 에러 멘트 통일
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자 요청 두 건:
# 1. 국내주식 탭이 미완성 상태이므로 헤더의 US/KR 토글을 일단 숨기고 강제 'us' 모드로 고정
# 2. Groq 토큰 소진 등으로 AI 해설이 실패할 때 모든 에러 메시지를 "해설 서비스 개선중." 로 통일
#
# [수정 — 1. region 토글 숨김]
# - templates/stocks.html: <div id="btn-region"> 에 style="display:none;" 추가 (HTML 임시 숨김)
# - static/js/region.js: const _FORCE_US_ONLY = true; flag 추가 → getRegion() 이 무조건 'us'
#   반환. localStorage 에 'kr' 잔여 값이 있어도 무시. 토글 클릭 핸들러는 동작하지만 버튼 안
#   보여서 무관.
# - 복원 방법: HTML style 제거 + region.js _FORCE_US_ONLY = false 두 줄 변경
# - cache-bust: region.js v=3 → v=4
#
# [수정 — 2. AI 해설 에러 멘트 통일]
# - api/routers/market_summary.py:_EXPLAIN_ERR
#   ko: no_data/no_service/fail = '해설 서비스 개선중.'
#   en: no_data/no_service/fail = 'Commentary service is being improved.'
#   bad_tab 만 별도 (잘못된 호출 — 사용자가 볼 일 없음)
# - static/js/i18n.js:'ai.explainError' (frontend catch 블록 fallback) 도 같은 멘트로 통일
# - 결과: 토큰 소진 → endpoint 'fail' → frontend 가 d.explanation 표시 → "해설 서비스 개선중."
#         네트워크 에러 → frontend catch → t('ai.explainError') → 같은 멘트
# - cache-bust: i18n.js v=5 → v=6
#
# [Why]
# - region 토글: KR 모드 진입 시 미구현 화면 다수 (홈 일부 타일 회색, 탭 컨텐츠 빈 영역) →
#   사용자에게 노출되면 미완성 인상. KR 인프라 80% 완성될 때까지 임시 숨김.
# - 에러 멘트 통일: "AI 해설을 생성할 수 없습니다" 같은 기술적 메시지 대신 "개선중" 으로 부드럽게.
#   토큰 소진 / API 다운 등 사용자가 알 필요 없는 내부 상황을 일관되게 처리.
#
# [검증]
# - python -m ast market_summary.py OK
# - 브라우저 hard refresh: 헤더에서 US/KR 토글 사라짐 (settings/lang/theme 만 남음)
# - localStorage region='kr' 인 사용자도 자동 'us' 데이터 호출 (region.js getRegion 강제)
# - AI 해설 실패 시: 본문 "해설 서비스 개선중." (회색 sub 색상)


# ═══════════════════════════════════════════════════════════════════════════════
# [96] 2026-05-05 (UTC) — UI 디자인 워크스페이스 분리 + Stop hook 자동 미러
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 디자인 시안 작업을 본 레포와 격리된 별도 폴더("/root/UI 디자인")에서 진행하기 위한 인프라
# 구축. 본 레포 → 디자인 폴더 단방향 미러를 Stop hook 으로 자동화. 디자인 폴더는
# 시안·실험장이며 본 레포 변경분이 다음 턴 종료 시 자동 흘러옴.
#
# [신규 파일]
# - scripts/sync_ui_design.sh : 본 → 디자인 단방향 rsync (--delete, node_modules 제외)
#     SRC=/root/Passive-Financial-Data-Analysis
#     DST=/root/UI 디자인
#     rsync -a --delete --exclude=node_modules --exclude=dist --exclude=.next \
#       "$SRC/static" "$SRC/templates" "$SRC/frontend-realestate" "$DST/"
# - .claude/settings.json : Stop hook 등록
#     "hooks": { "Stop": [{ "matcher": "", "hooks": [{
#       "type": "command",
#       "command": "bash /root/Passive-Financial-Data-Analysis/scripts/sync_ui_design.sh",
#       "timeout": 30,
#       "statusMessage": "UI 디자인 폴더 동기화 중..."
#     }] }] }
# - /root/UI 디자인/CLAUDE.md : 디자인 폴더 워크플로우 안내 (단방향 미러, 시안 확정 후 본
#   레포에 사람이 옮김, node_modules 는 심링크 또는 본폴더 dev 활용)
# - 초기 미러본: /root/UI 디자인/{static,templates,frontend-realestate} 약 3.2MB
#   (node_modules 제외 — 본 레포 frontend-realestate 97MB 중 96MB가 node_modules)
#
# [수정 파일]
# - logic/structure.md : UI 디자인 워크스페이스 섹션 신규 추가
#
# [동작 흐름]
# Claude Code 턴 종료 → Stop hook 발동 → sync_ui_design.sh 실행 →
# rsync 가 본 레포 static/templates/frontend-realestate 를 /root/UI 디자인/ 에 미러 →
# 디자인 폴더는 늘 최신 상태에서 시안 시작
#
# [Why — 단방향 vs 양방향]
# 양방향 sync 는 동시 편집 시 충돌·오버라이트 위험. 단방향이 명확:
# - 본 레포 = 진실의 소스 (production 코드)
# - 디자인 폴더 = 시안·실험장 (확정 후 사람이 본 레포로 옮김)
# 시안이 오버라이트되더라도 git history (본 레포) + 작업자 메모리에 남아있어 재구성 가능.
#
# [Why — Stop hook vs 수동 sync]
# 매 턴 종료 시 자동 실행 → 사용자/Claude 가 동기화를 잊어버릴 여지 없음. rsync 는
# 변경분만 전송하므로 매번 실행해도 부담 없음 (3MB 규모, --delete 포함 1초 미만).
#
# [Why — node_modules 제외]
# 본 레포 frontend-realestate node_modules 96MB → 동기화 부담만 늘리고 실익 없음.
# 디자인 폴더에서 dev 서버를 띄우려면 본 레포 node_modules 를 심링크하거나
# 본 레포에서 dev 띄우고 디자인 폴더는 코드 비교용으로만 사용 (CLAUDE.md 에 명시).
#
# [검증 결과]
# - 초기 rsync 수동 실행: 3.2MB 미러 완료
#     /root/UI 디자인/static (2.5M), templates (80K), frontend-realestate (600K)
# - sync 스크립트 파이프 테스트: echo '{}' | bash sync_ui_design.sh → exit=0
# - settings.json 스키마 검증: Stop matcher="" command 인식 OK
# - CLAUDE.md 보존 확인: rsync --delete 는 sub-디렉토리 단위만 정리, 최상위 미보호 파일 유지
#
# [한계 / 후속 조치]
# - 이번 세션 시작 시점에 .claude/settings.json 이 존재하지 않았음. Claude Code watcher 가
#   디렉토리를 감시 중이 아니라면 hook 이 다음 세션부터 활성화될 수 있음. 사용자가 한 번
#   /hooks 메뉴를 열거나 Claude Code 재시작하면 즉시 적용.
# - 백엔드 변경(api/, processor/, scheduler/, models/, database/, scripts/, notebooks/,
#   logic/) 은 디자인 폴더로 미러되지 않음 — 의도적. 디자인 폴더는 프론트만.
# - 디자인 폴더에서 직접 코드 수정 후 본 레포에 반영하려면 사람이 수동으로 옮겨야 함 (양방향
#   금지 규약).


# ═══════════════════════════════════════════════════════════════════════════════
# [97] 2026-05-05 (UTC) — 홈 헤드라인 에러 멘트도 [95] 와 동일하게 통일
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# [95] 에서 _EXPLAIN_ERR (5탭 AI 해설) 만 "해설 서비스 개선중." 으로 통일했는데, 사용자 보고
# 홈 화면 "오늘의 종합 판단" 카드가 여전히 "AI 요약을 생성할 수 없습니다." 로 표시됨. 이건
# 별도 dict (_ERR_MSGS, home-headline endpoint) 라서 [95] 변경 영향권 밖이었음.
#
# [수정 — api/routers/market_summary.py:_ERR_MSGS]
# - ko: no_data/no_service/fail = '해설 서비스 개선중.'
# - en: no_data/no_service/fail = 'Commentary service is being improved.'
# - 패턴 [95] 의 _EXPLAIN_ERR 와 동일.
#
# [Why]
# 사용자 입장에서 "토큰 소진" 등 내부 사정은 알 필요 없음. 홈 헤드라인이든 5탭 AI 해설이든
# 모든 LLM 실패 케이스를 동일 멘트로 보여주는 게 일관됨.
#
# [효과]
# - Groq 토큰 소진 → home-headline endpoint 'fail' 반환 → 카드에 "해설 서비스 개선중."
# - ai_headline_cache 의 기존 정상 헤드라인은 그대로 표시 (캐시 hit) — 토큰 소진 시점 이후
#   캐시 만료 호출에서만 fail 메시지.
#
# [검증]
# - python -m ast market_summary.py OK
# - 사용자 화면 새로고침 시 즉시 적용 (frontend cache-bust 불필요 — 백엔드 응답만 변경)


# ═══════════════════════════════════════════════════════════════════════════════
# [98] 2026-05-05 (UTC) — UI 디자인 워크스페이스 워크플로우 재정의 (Stop hook 해제)
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# [96] 에서 도입한 Stop hook 자동 미러가 사용자 의도와 안 맞아 해제. 사용자 명시:
# "디자인(프론트) 를 그대로 본 폴더에서 클론해오는거야. 그리고 이후에 내가 너에게 디자인
# 변경점을 말하면 그 부분만 바꾸는거지" — 즉 디자인 폴더는 단순 미러가 아니라 디자인
# 변경 작업장. 매 턴 종료 시 자동 미러는 디자인 폴더의 작업물을 본폴더 버전으로
# 덮어쓰므로 충돌.
#
# [수정 파일]
# - .claude/settings.json : hooks 키 제거, schema 키만 남김
#     {
#       "$schema": "https://json.schemastore.org/claude-code-settings.json"
#     }
# - /root/UI 디자인/CLAUDE.md : 워크플로우 재작성
#     · "단방향 미러" 표현 → "클론 + 디자인 변경 작업장"
#     · 자동 sync 없음 명시
#     · 본폴더 반영은 사용자 명시 요청 시에만 ("이거 본폴더에도 넣어")
#     · 본폴더가 변경되면 사용자가 "sync 시켜" 요청 시 sync_ui_design.sh 수동 실행
#     · sync_ui_design.sh 는 --delete 옵션이라 디자인 작업 중 실행 시 작업물 손실 경고
# - logic/structure.md : 마지막 갱신 시점 추가
#
# [수정 안 한 파일]
# - scripts/sync_ui_design.sh : 그대로 보존 — 사용자가 "sync 시켜" 요청 시 수동 실행용
#
# [Why — Stop hook 자동 미러의 문제]
# 사용자 시나리오: "home.css hover 효과를 더 화려하게 바꿔줘" → Claude 가 디자인 폴더의
# static/css/home.css 수정 → 사용자 확인 → 마음에 들면 본폴더에 반영. 자동 Stop hook 이
# 켜져 있으면 매 턴 종료 시 본폴더(미수정) → 디자인 폴더(수정됨) rsync --delete 로 디자인
# 작업이 즉시 사라짐. 양방향 sync 는 충돌 위험으로 [96] 단계에서 사용자가 거부했음 →
# 결국 자동 sync 자체를 빼는 것이 가장 깔끔.
#
# [Why — sync_ui_design.sh 는 보존]
# 본폴더 프론트가 바뀐 후 (예: 새 페이지 추가, 컴포넌트 신규) 디자인 폴더를 다시 동기화하고
# 싶을 때 사용자가 "sync 시켜" 한 마디로 호출 가능. 자동이 아니라 명시 호출이라 안전.
#
# [Why — 디자인 폴더 작업물의 본폴더 반영도 수동]
# 사용자가 시안을 충분히 본 후 "이게 좋다"고 판단했을 때만 본폴더에 적용. Claude 가 임의로
# 본폴더를 건드리면 production 영향 위험. 사용자 페르소나(개발자) 가 결정 게이트키퍼.
#
# [동작 흐름 (수정 후)]
# 1. 본폴더 프론트 변경 → 사용자가 "sync 시켜" → Claude 가 sync_ui_design.sh 실행
# 2. 사용자 디자인 변경 요청 → Claude 가 디자인 폴더 (예: static/css/home.css) 직접 수정
# 3. 사용자 확인 → "이거 본폴더에도 넣어" → Claude 가 본폴더 동일 파일 수정
# 4. 매 턴 종료 시 아무 자동 sync 도 일어나지 않음
#
# [검증]
# - python3 -c 'import json; json.load(open(".../settings.json"))' OK (스키마만 남음)
# - sync_ui_design.sh 그대로 동작 (수동 호출 시): rsync -a --delete static/templates/
#   frontend-realestate "/root/UI 디자인/"
# - /root/UI 디자인/sandbox/ 는 sync 대상 source 가 아니므로 수동 sync 실행 시에도 안전
#   ([96] sandbox 파일 home_tiles_micro_v1.html 보존)


# ═══════════════════════════════════════════════════════════════════════════════
# [99] 2026-05-05 (UTC) — 디자인 전용 호스트 서버 (포트 8001) + STATIC/TEMPLATES env
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자 명시 "디자인 전용으로 따른 호스트 서버 사용하길 원함". [98] 의 "디자인 폴더는 코드
# 보관소로만, 화면은 본 레포 8000 만" 은 사용자 의도와 안 맞음 (디자인 작업 화면을 별도
# 서버에서 즉시 확인하고 싶음) → 본 레포 api/app.py 의 static/templates 디렉토리를
# 환경변수로 받게 수정. 디자인 서버는 cwd=본 레포 (백엔드 의존성 .env/models/ 그대로) +
# STATIC_DIR/TEMPLATES_DIR 만 디자인 폴더로 오버라이드.
#
# [수정 파일]
# - api/app.py — 3곳:
#     # line ~140
#     _STATIC_DIR = os.getenv('STATIC_DIR', 'static')
#     _TEMPLATES_DIR = os.getenv('TEMPLATES_DIR', 'templates')
#     app.mount('/static', StaticFiles(directory=_STATIC_DIR), name='static')
#     templates = Jinja2Templates(directory=_TEMPLATES_DIR)
#     # line ~178 (realestate SPA fallback)
#     return FileResponse(os.path.join(_STATIC_DIR, 'realestate/index.html'))
#     # line ~270 (TikTok verify file)
#     file_path = os.path.join(_STATIC_DIR, 'tiktokPFHpLA0MzDof0SYGfC4gfqJEhsk65ZrR.txt')
#
# - /root/UI 디자인/CLAUDE.md — 워크플로우에 디자인 서버 8001 안내 추가
# - logic/structure.md — 마지막 갱신 시점 추가
#
# [실행 명령]
# 본 레포 (production):
#   uvicorn api.app:app --reload  # port 8000, env 미지정 → 'static'/'templates' 기본값
#
# 디자인 서버 (port 8001):
#   cd /root/Passive-Financial-Data-Analysis
#   RUN_SCHEDULER=false \
#     STATIC_DIR='/root/UI 디자인/static' \
#     TEMPLATES_DIR='/root/UI 디자인/templates' \
#     .venv/bin/uvicorn api.app:app --reload --port 8001 \
#       --reload-dir '/root/UI 디자인/static' \
#       --reload-dir '/root/UI 디자인/templates'
#
# [Why — 두 서버 동시 운영]
# - 8000 (본 레포) = production, 사용자 검증·메인 화면
# - 8001 (디자인) = 디자인 폴더 hot reload, 시안 즉시 확인
# 사용자 워크플로우:
#   "X 바꿔" → Claude 가 디자인 폴더 수정 → 8001 hot reload → F5 로 즉시 확인
#   "본폴더에도 넣어" → Claude 가 본 레포 수정 → 8000 reload → production 반영
#
# [Why — env 오버라이드 방식]
# 백엔드 의존성(.env, models/, catboost_info/, supabase 클라이언트 등) 은 cwd 기반이라
# cwd=본 레포 유지. STATIC_DIR/TEMPLATES_DIR 만 디자인 폴더로 가리키면 화면 자원만
# 분기. env 미지정 시 기본값 'static'/'templates' 라 production 동작 동일 (안전).
#
# [Why — RUN_SCHEDULER=false]
# 디자인 서버에서 스케줄러 중복 실행 방지 (8000 본 레포가 이미 스케줄링).
#
# [검증]
# - python3 -m py_compile api/app.py OK
# - 디자인 서버 부팅: "Will watch for changes in these directories:
#     ['/root/UI 디자인/static', '/root/UI 디자인/templates']" 한글 경로 watch OK
# - curl http://127.0.0.1:8001/stocks → 200 OK (디자인 폴더 templates/stocks.html 서빙)
# - 8000 (본 레포) 도 그대로 200 (env 미지정 기본값)
# - hot reload: 디자인 폴더 파일 변경 시 uvicorn 자동 재시작 → 브라우저 F5 즉시 반영
#
# [한계]
# - frontend-realestate (Vite React) 는 빌드 산출물(static/realestate/) 만 서빙되므로
#   부동산 SPA 디자인은 별도 vite dev (5173) 또는 디자인 폴더에서 npm run build 필요
# - models/ 모델 .pkl 은 본 레포 절대 경로(cwd) 기반이라 디자인 폴더 변경 영향 없음


# ═══════════════════════════════════════════════════════════════════════════════
# [100] 2026-05-05 (UTC) — AI 해설 프롬프트: "단순 나열" → "메커니즘 한 줄"
# ═══════════════════════════════════════════════════════════════════════════════
#
# [개요]
# 사용자 피드백: 현재 AI 해설이 "VIX 30 기여도 +0.4" 식으로 요인을 단순 나열만 함. 사용자가
# 원하는 건 "왜 그 요인이 모델 결과에 영향을 미치는지" 메커니즘을 단순 요약. 5탭 모두
# (fundamental/signal/sector/sector-val/sector-mom) 의 system prompt 수정.
#
# [수정 — api/routers/market_summary.py:_EXPLAIN_PROMPTS]
# 핵심 원칙:
#   나쁨: "VIX 30 기여도 +0.4, 신용 스프레드 +0.3" (단순 나열)
#   좋음: "VIX 30(공포 확대)→이성 약화 +0.4, 신용 스프레드↑=자금 경색→이성 약화 +0.3"
#         (메커니즘이 결과에 어떻게 작용하는지 한 줄)
#
# 5탭 KR (≤160자/180자) + EN (≤200자/220자) 모두 동일 패턴:
#   "단순 나열 X — 왜 그 요인이 [방향]에 작용하는지 메커니즘 한 줄 (예: ...)"
#
# 각 탭별 메커니즘 예시 (LLM 이 패턴 모방):
#   - fundamental: 'VIX↑=공포 확대→이성 약화'
#   - signal: '신용 스프레드↑=자금 경색→하락 압력'
#   - sector: '확장 국면=수요 회복→경기소비재 수혜'
#   - sector-val: '가격이 EPS 보다 빨리 상승→밸류 부담'
#   - sector-mom: '침체국면+상승=회복 기대 선반영'
#
# [Why]
# 단순 숫자 나열은 사용자가 직접 데이터 화면을 보면 알 수 있음. AI 해설의 가치는 "이 숫자가
# 왜 이 의미를 가지는지" 인과를 압축 설명. 메커니즘을 한 줄로 풀어주면 비전문 투자자도
# 신호의 본질을 빠르게 이해.
#
# [한계 / 후속]
# - ai_explain_cache 의 기존 행은 옛 프롬프트로 생성된 텍스트 — 다음 KST 16:00 (KR 파이프라인)
#   / 09:00 (US 파이프라인) 자동 갱신 시 새 메커니즘 해설로 덮어씀.
# - 즉시 갱신 원하면: DELETE FROM ai_explain_cache;  (또는 서버 재시작)
# - 토큰 비용: 시스템 프롬프트 +30~40 토큰 (메커니즘 가이드). max_tokens 150 그대로.
#   하루 호출 빈도 (5탭 × 2lang × 2region = 20) 기준 미미.

