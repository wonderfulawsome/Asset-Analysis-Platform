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
