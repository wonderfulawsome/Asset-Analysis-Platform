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






