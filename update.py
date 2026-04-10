"""
========================================================
  UPDATE LOG - 변경 이력 보관 파일
  (실행용이 아닌 코드 변경 내용 기록/보관용)
========================================================
"""

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

CHART_PY_GET_PREDICTION = """
@router.get('/predict')
def get_prediction(ticker: str = Query('SPY', description='ETF 티커')):
    \"\"\"5-모델 앙상블 30일 예측 결과를 DB에서 조회.
    DB에 없으면 백그라운드 재생성 후 폴링하여 완료를 대기한다.\"\"\"
    from database.repositories import fetch_chart_predict

    ticker = ticker.upper()
    if ticker not in CHART_TICKERS:
        return {'error': 'unsupported ticker'}

    def _fetch_valid(t):
        r = fetch_chart_predict(t)
        if r is not None:
            sp = _sanitize_floats(r.get('predicted', []))
            if _is_prediction_valid(sp):
                return r
            print(f'[Chart] {t} 예측 데이터 손상 감지')
        return None

    result = _fetch_valid(ticker)

    if result is None:
        # 백그라운드에서 재생성 트리거
        if ticker not in _predict_running:
            _predict_running.add(ticker)
            threading.Thread(target=_regenerate_in_background, args=(ticker,),
                             daemon=True).start()

        # 백그라운드 재생성 완료까지 폴링 대기 (최대 ~120초)
        _POLL_INTERVAL = 3   # 초
        _MAX_POLLS = 40      # 40 × 3초 = 120초
        for i in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)
            # 백그라운드 스레드 완료 확인
            if ticker not in _predict_running:
                result = _fetch_valid(ticker)
                break
            # 스레드 실행 중에도 주기적으로 DB 확인 (15초 간격)
            if i % 5 == 4:
                result = _fetch_valid(ticker)
                if result is not None:
                    break

        if result is None:
            return {'error': 'prediction generation failed, please try again later'}

    return {
        'ticker': result['ticker'],
        'actual': _sanitize_floats(result['actual']),
        'predicted': _sanitize_floats(result['predicted']),
    }
"""

# ──────────────────────────────────────────────────────────
# 파일 2: static/js/chart.js  (line 826~916)
# ──────────────────────────────────────────────────────────

CHART_JS_SETUP_PREDICT_BUTTON = """
function setupPredictButton() {
  const btn = document.getElementById('predict-toggle-btn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    if (_predictVisible) {
      _predictVisible = false;
      _predictData = null;
      btn.classList.remove('active');
      _reRenderCharts(false);
      renderPredictLegend(false);
      return;
    }
    _predictVisible = true;
    btn.classList.add('active');
    btn.disabled = true;
    btn.textContent = t('chart.predictLoading');
    showPredictDisclaimer();

    // 로딩 애니메이션: 점 개수가 변하는 텍스트
    let dotCount = 0;
    const loadingInterval = setInterval(() => {
      dotCount = (dotCount + 1) % 4;
      const dots = '.'.repeat(dotCount || 1);
      btn.textContent = t('chart.predictLoading') + dots;
    }, 600);

    try {
      // 서버가 최대 ~120초 대기하므로 타임아웃을 150초로 설정
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 150000);

      let data = null;
      try {
        const res = await fetch(`/api/chart/predict?ticker=${_chartTicker}`, {
          signal: controller.signal,
        });
        data = await res.json();
      } catch (e) {
        if (e.name === 'AbortError') {
          data = { error: 'timeout' };
        } else {
          throw e;
        }
      } finally {
        clearTimeout(timeoutId);
      }

      if (!data || data.error) {
        _predictVisible = false;
        btn.classList.remove('active');
        _showPredictError();
        return;
      }
      _predictData = data;
      _reRenderCharts(false);
      renderPredictLegend(true);
      // 예측 영역으로 부드럽게 스크롤
      setTimeout(() => {
        const sc = document.getElementById('candle-scroll');
        if (sc) sc.scrollTo({ left: sc.scrollWidth, behavior: 'smooth' });
      }, 50);
    } catch {
      _predictVisible = false;
      btn.classList.remove('active');
      _showPredictError();
    } finally {
      clearInterval(loadingInterval);
      btn.disabled = false;
      btn.textContent = t('chart.predictBtn');
    }
  });
}

function _showPredictError() {
  let toast = document.getElementById('predict-disclaimer-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'predict-disclaimer-toast';
    toast.className = 'predict-disclaimer-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = t('chart.predictError');
  toast.style.background = 'rgba(220,38,38,0.95)';
  toast.classList.remove('hide');
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    toast.classList.add('hide');
    toast.style.background = '';
  }, 4000);
}
"""

# ──────────────────────────────────────────────────────────
# 파일 3: static/js/i18n.js  (한국어 line 181~182, 영어 line 587~588)
# ──────────────────────────────────────────────────────────

I18N_KO = """
    'chart.predictLoading': '예측 모델 실행 중',
    'chart.predictError': '예측 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.',
"""

I18N_EN = """
    'chart.predictLoading': 'Running forecast model',
    'chart.predictError': 'Failed to load prediction. Please try again later.',
"""


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

JOB_PY_STEP7 = """
        # Step 7: XGBoost 폭락/급등 전조 탐지 (모델 학습 + 오늘 예측)
        print('\\n[Step 7] 폭락/급등 전조 탐지...')
        cs_datasets = None
        cs_model = None
        cs_should_retrain = False
        try:
            raw = fetch_crash_surge_raw(fred_cache=fred_cache)
            save_fred_cache(raw['fred'])
            features = compute_features(raw['spy'], raw['fred'], raw['cboe'],
                                                  raw['yahoo_macro'])
            labels = compute_labels(raw['spy']['Close'])
            cs_datasets = prepare_datasets(features, labels, raw['spy']['Close'])

            cs_model = load_crash_surge_model()
            current_month = datetime.date.today().strftime('%Y-%m')
            cs_should_retrain = (cs_model is None or
                                 cs_model.get('train_month') != current_month)
            if cs_should_retrain:
                try:
                    print('[Step 7] 모델 재학습 (Optuna 50 trials)...')
                    X_tr, y_tr = cs_datasets['train']
                    X_cal, y_cal = cs_datasets['calib']
                    X_te, y_te = cs_datasets['test']
                    X_dev, y_dev = cs_datasets['dev']
                    X_full = cs_datasets['df_full'][ALL_FEATURES].values
                    cs_model = train_crash_surge(X_tr, y_tr, X_cal, y_cal, X_te, y_te,
                                                 X_dev, y_dev, X_full, n_trials=50)
                except Exception as e:
                    print(f'[Step 7] 모델 재학습 실패, 기존 모델로 예측 계속: {e}')
                    traceback.print_exc()
                    cs_model = load_crash_surge_model()  # 기존 모델 다시 로드
            else:
                print(f'[Step 7] 기존 모델 사용 (학습 월: {cs_model["train_month"]})')

            # 예측은 재학습 성패와 무관하게 실행
            if cs_model is not None:
                latest_row = cs_datasets['df_full'][ALL_FEATURES].iloc[[-1]].values
                cs_result = predict_crash_surge(latest_row, cs_model)
                upsert_crash_surge(cs_result)
            else:
                print('[Step 7] 사용 가능한 모델 없음, 예측 건너뜀')
        except Exception as e:
            print(f'[Step 7] 폭락/급등 전조 실패, 경량 fallback 시도: {e}')
            traceback.print_exc()
            # Fallback: 경량 수집으로 예측 시도
            try:
                fallback_model = load_crash_surge_model()
                if fallback_model is not None:
                    import numpy as np
                    from collector.crash_surge_data import CORE_FEATURES, AUX_FEATURES
                    raw_light = fetch_crash_surge_light()
                    features_light = compute_features(raw_light['spy'], raw_light['fred'],
                                                      raw_light['cboe'], raw_light['yahoo_macro'])
                    feat_row = features_light[ALL_FEATURES].copy()
                    feat_row = feat_row.ffill()
                    feat_row = feat_row.dropna(subset=CORE_FEATURES)
                    feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)
                    feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)
                    if len(feat_row) > 0:
                        latest_row = feat_row.iloc[[-1]].values
                        cs_result = predict_crash_surge(latest_row, fallback_model)
                        upsert_crash_surge(cs_result)
                        print('[Step 7-fallback] 경량 수집으로 예측 성공')
                    else:
                        print('[Step 7-fallback] 유효한 피처 행 없음')
            except Exception as e2:
                print(f'[Step 7-fallback] 경량 fallback도 실패: {e2}')
"""

# ──────────────────────────────────────────────────────────
# 파일 2: scheduler/job.py  Step 5b (line 177)
#   - ffill() 추가: FRED/Yahoo 결측값을 직전 행 값으로 채움
# ──────────────────────────────────────────────────────────

JOB_PY_STEP5B_FFILL = """
                feat_row = features_light[ALL_FEATURES].copy()  # 피처만 추출
                feat_row = feat_row.ffill()  # FRED/Yahoo 결측 → 직전 값으로 채움  ← 추가됨
                feat_row = feat_row.dropna(subset=CORE_FEATURES)  # Core NaN 제거
                feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)  # Aux 결측 대체
                feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)  # inf 제거
"""

# ──────────────────────────────────────────────────────────
# 파일 3: collector/crash_surge_data.py  compute_features() (line 344~367)
#   - FRED 신용스프레드(HY_OAS, BBB_OAS, CCC_OAS) 빈 데이터 → 0 대체
#   - Yahoo ^TNX(DGS10), ^IRX(IRX_3M) 빈 데이터 → 0 대체
# ──────────────────────────────────────────────────────────

CRASH_SURGE_DATA_COMPUTE_FEATURES_CREDIT_RATE = """
    # ── 신용 (3개) — FRED 전용 ──
    for col in ['HY_OAS', 'BBB_OAS', 'CCC_OAS']:
        s = fred[col][col].reindex(spy.index).ffill()
        # FRED 데이터가 비어있으면 0으로 대체 (최신일 NaN 방지)
        if s.isna().all():
            print(f'  [compute_features] {col}: FRED 데이터 비어있음, 0으로 대체')
            s = s.fillna(0)
        feat[col] = s

    # ── 금리 (2개) — Yahoo ^TNX, ^IRX 사용 ──
    dgs10_s = yahoo_macro.get('DGS10', pd.Series(dtype=float))
    irx_s = yahoo_macro.get('IRX_3M', pd.Series(dtype=float))
    dgs10_ff = dgs10_s.reindex(spy.index).ffill()
    irx_ff = irx_s.reindex(spy.index).ffill()
    # Yahoo ^TNX/^IRX 수집 실패 시 0 대체 (최신일 NaN 방지)
    if dgs10_ff.isna().all():
        print('  [compute_features] DGS10: Yahoo ^TNX 데이터 비어있음, 0으로 대체')
        dgs10_ff = dgs10_ff.fillna(0)
    if irx_ff.isna().all():
        print('  [compute_features] IRX_3M: Yahoo ^IRX 데이터 비어있음, 0으로 대체')
        irx_ff = irx_ff.fillna(0)
    feat['DGS10_LEVEL'] = dgs10_ff
    feat['T10Y3M_SLOPE'] = dgs10_ff - irx_ff
"""
