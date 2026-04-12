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

# ──────────────────────────────────────────────────────────
# 파일 4: collector/crash_surge_data.py  fetch_crash_surge_light() (line 244~258)
#   - SPY OHLCV 다운로드에 3회 재시도 로직 추가
# ──────────────────────────────────────────────────────────

CRASH_SURGE_DATA_SPY_RETRY = """
    # 1) SPY OHLCV — 장 중이면 실시간 가격 포함 (재시도 포함)
    print('  [CrashSurge-Light] SPY OHLCV 수집...')
    spy = None
    for attempt in range(3):
        try:
            spy_raw = yf.Ticker('SPY').history(period=f'{lookback_days}d', auto_adjust=True)
            spy_raw = _strip_tz(spy_raw)
            if not spy_raw.empty and len(spy_raw) >= 2:
                spy = spy_raw[['Open', 'High', 'Low', 'Close', 'Volume']]
                break
        except Exception as e:
            print(f'  [CrashSurge-Light] SPY 수집 시도 {attempt+1}/3 실패: {e}')
        if attempt < 2:
            time.sleep(2)
    if spy is None or spy.empty:
        raise RuntimeError('SPY OHLCV 수집 실패 (3회 재시도 후)')
"""

# ──────────────────────────────────────────────────────────
# 파일 5: api/routers/crash_surge.py  /refresh 엔드포인트 (line 125~170)
#   - 수동 데이터 새로고침 API 추가
#   - 스케줄러 없이도 crash_surge 예측을 즉시 재실행 가능
# ──────────────────────────────────────────────────────────

CRASH_SURGE_REFRESH_API = """
@router.get('/refresh')
def refresh_crash_surge():
    global _refresh_running
    if _refresh_running:
        return {'status': 'already_running'}

    _refresh_running = True
    try:
        import numpy as np
        from collector.crash_surge_data import (
            fetch_crash_surge_light, compute_features,
            ALL_FEATURES, CORE_FEATURES, AUX_FEATURES,
        )
        from processor.feature3_crash_surge import (
            load_model as load_crash_surge_model, predict_crash_surge,
        )

        cs_model = load_crash_surge_model()
        if cs_model is None:
            return {'status': 'error', 'message': 'no model available'}

        raw = fetch_crash_surge_light()
        features = compute_features(raw['spy'], raw['fred'], raw['cboe'], raw['yahoo_macro'])
        feat_row = features[ALL_FEATURES].copy()
        feat_row = feat_row.ffill()
        feat_row = feat_row.dropna(subset=CORE_FEATURES)
        feat_row[AUX_FEATURES] = feat_row[AUX_FEATURES].fillna(0)
        feat_row = feat_row.replace([np.inf, -np.inf], np.nan).dropna(subset=ALL_FEATURES)

        if len(feat_row) == 0:
            return {'status': 'error', 'message': 'no valid feature rows'}

        latest_row = feat_row.iloc[[-1]].values
        result = predict_crash_surge(latest_row, cs_model)
        upsert_crash_surge(result)

        return {'status': 'ok', 'date': result.get('date'),
                'crash_score': result.get('crash_score'),
                'surge_score': result.get('surge_score')}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}
    finally:
        _refresh_running = False
"""


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
# api/routers/market_summary.py  _EXPLAIN_PROMPTS 한국어 핵심 부분
# ──────────────────────────────────────────────────────────

EXPLAIN_PROMPT_KO = """
배경 지식:
- "펀더멘털 주가 괴리 점수"는 주가가 펀더멘털에서 얼마나 벗어났는지를 나타내는 점수다
- 음수(-): 주가가 펀더멘털(기업 가치)을 잘 반영 (이성적 시장)
- 양수(+): 주가가 펀더멘털에서 벗어나 감정/유동성에 의해 움직임 (감정적 시장)
- 양수가 클수록 괴리가 심함 (0~2: 약간 괴리, 2+: 큰 괴리)
"""

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
