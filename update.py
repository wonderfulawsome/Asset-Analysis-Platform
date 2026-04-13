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

# 영어 배경 지식:
# - "Fundamental-Price Divergence Score" measures how far price has deviated from fundamentals
# - Negative (-): price reflects fundamentals well (rational market)
# - Positive (+): price deviated, driven by sentiment/liquidity (emotional market)
# - Higher positive = greater divergence (0~2: mild, 2+: significant)


# ══════════════════════════════════════════════════════════
# [4] 2026-04-12 (UTC)
#     30일 예측 지그재그 수정 + GARCH 전면 적용 + 신호 AI 해설 간극 분석
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
