// ── 캔들스틱 차트 탭 ──
const CHART_MAIN_TICKERS = ['VOO','QQQ','DIA','IWM','SOXX','SMH','GLD','TLT','SCHD'];
const TICKER_NAMES = {
  SPY:'S&P 500 ETF', QQQ:'Nasdaq 100', DIA:'Dow Jones', IWM:'Russell 2000',
  VOO:'S&P 500 (V)', SOXX:'Semiconductor', SMH:'Semiconductor (VN)',
  GLD:'Gold', TLT:'Treasury 20Y+', SCHD:'Dividend',
};

// 이동평균선 설정 (기간, 색상)
const MA_CONFIG = [
  { period: 5,   color: '#FF6B6B', label: 'MA5' },
  { period: 20,  color: '#4ECDC4', label: 'MA20' },
  { period: 60,  color: '#FFD93D', label: 'MA60' },
  { period: 120, color: '#6C5CE7', label: 'MA120' },
];

let _chartTicker = 'VOO';
let _chartInterval = '1d';
let _chartData = null;
let _maVisible = { 5: true, 20: true, 60: true, 120: false };
let _zoomLevel = 1.0;
const ZOOM_MIN = 0.3;
const ZOOM_MAX = 3.0;

// 전역 MA 캐시 (데이터/MA설정 바뀔 때만 재계산)
let _maCache = {};

// 예측 상태
let _predictVisible = false;
let _predictData = null;

// ── 차트 탭 초기화 ──
function initChartTab() {
  renderTickerChips();
  setupIntervalButtons();
  setupZoomButtons();
  setupPredictButton();
  updatePredictBtnVisibility();
  loadCandleChart();
}

// ── 줌 버튼 ──
function setupZoomButtons() {
  const inBtn = document.getElementById('zoom-in-btn');
  const outBtn = document.getElementById('zoom-out-btn');
  if (inBtn) inBtn.addEventListener('click', () => {
    _zoomLevel = Math.min(ZOOM_MAX, _zoomLevel * 1.3);
    _reRenderCharts(true);
  });
  if (outBtn) outBtn.addEventListener('click', () => {
    _zoomLevel = Math.max(ZOOM_MIN, _zoomLevel / 1.3);
    _reRenderCharts(true);
  });
}

// ── 티커 칩 렌더링 ──
function renderTickerChips() {
  const el = document.getElementById('chart-ticker-chips');
  if (!el) return;
  el.innerHTML = CHART_MAIN_TICKERS.map(tk => {
    const sel = tk === _chartTicker ? ' active' : '';
    return `<button class="chart-tk-chip${sel}" data-tk="${tk}">${tk}</button>`;
  }).join('');
  el.onclick = (e) => {
    const chip = e.target.closest('.chart-tk-chip');
    if (!chip || chip.dataset.tk === _chartTicker) return;
    _chartTicker = chip.dataset.tk;
    el.querySelectorAll('.chart-tk-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    hidePredictSection();
    loadCandleChart();
  };
}

// ── 봉 간격 버튼 ──
function setupIntervalButtons() {
  const btns = document.querySelectorAll('.chart-iv-btn');
  btns.forEach(btn => {
    if (!btn.dataset.iv) return;  // 예측 버튼 등 interval 아닌 버튼 제외
    btn.addEventListener('click', () => {
      if (btn.dataset.iv === _chartInterval) return;
      _chartInterval = btn.dataset.iv;
      _zoomLevel = 1.0;
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      hidePredictSection();
      updatePredictBtnVisibility();
      loadCandleChart();
    });
  });
}

// ── 이동평균선 계산 ──
function calcMA(candles, period) {
  const result = [];
  for (let i = 0; i < candles.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += candles[j].c;
    result.push(sum / period);
  }
  return result;
}

// ── Y축 "nice number" 계산 ──
function niceNum(range, round) {
  const exp = Math.floor(Math.log10(range));
  const frac = range / Math.pow(10, exp);
  let nice;
  if (round) {
    if (frac < 1.5) nice = 1;
    else if (frac < 3) nice = 2;
    else if (frac < 7) nice = 5;
    else nice = 10;
  } else {
    if (frac <= 1) nice = 1;
    else if (frac <= 2) nice = 2;
    else if (frac <= 5) nice = 5;
    else nice = 10;
  }
  return nice * Math.pow(10, exp);
}

function niceScale(dMin, dMax, maxTicks) {
  maxTicks = maxTicks || 6;
  if (dMax - dMin < 0.01) { dMin -= 1; dMax += 1; }
  const range = niceNum(dMax - dMin, false);
  const tickSpacing = niceNum(range / (maxTicks - 1), true);
  const niceMin = Math.floor(dMin / tickSpacing) * tickSpacing;
  const niceMax = Math.ceil(dMax / tickSpacing) * tickSpacing;
  const ticks = [];
  for (let v = niceMin; v <= niceMax + tickSpacing * 0.5; v += tickSpacing) {
    ticks.push(parseFloat(v.toPrecision(12)));
  }
  return { min: niceMin, max: niceMax, ticks, tickSpacing };
}

// ── OHLC 데이터 로드 ──
async function loadCandleChart() {
  const chartEl = document.getElementById('candle-chart');
  const volEl = document.getElementById('volume-chart');
  const sumEl = document.getElementById('chart-summary');
  if (!chartEl) return;

  chartEl.innerHTML = '<div class="candle-loading"><div class="loading-spinner"></div></div>';
  if (volEl) volEl.innerHTML = '';
  if (sumEl) sumEl.innerHTML = '';

  try {
    const res = await fetch(`/api/chart/ohlc?ticker=${_chartTicker}&interval=${_chartInterval}`);
    const data = await res.json();
    if (data.error || !data.candles || data.candles.length < 2) {
      chartEl.innerHTML = `<div class="candle-empty">${t('chart.noData')}</div>`;
      return;
    }

    _chartData = data.candles;
    _maCache = {};  // MA 캐시 초기화

    renderCandlestickChart(chartEl, data.candles);
    if (volEl) renderVolumeChart(volEl, data.candles);
    renderChartSummary(sumEl, data.candles);
    renderMALegend();
  } catch (err) {
    chartEl.innerHTML = `<div class="candle-empty">${t('chart.noData')}</div>`;
  }
}

// ── MA 범례 렌더/토글 ──
function renderMALegend() {
  const el = document.getElementById('ma-legend');
  if (!el) return;
  el.innerHTML = MA_CONFIG.map(m => {
    const on = _maVisible[m.period];
    return `<button class="ma-chip${on ? ' on' : ''}" data-ma="${m.period}" style="--ma-color:${m.color}">
      <span class="ma-dot"></span>${m.label}
    </button>`;
  }).join('');
  el.onclick = (e) => {
    const chip = e.target.closest('.ma-chip');
    if (!chip) return;
    const p = +chip.dataset.ma;
    _maVisible[p] = !_maVisible[p];
    const chartEl = document.getElementById('candle-chart');
    if (chartEl && _chartData) {
      renderCandlestickChart(chartEl, _chartData);
    }
    renderMALegend();
  };
}

// ── Y축 라벨 포맷 ──
function fmtYLabel(val) {
  if (val >= 10000) return (val / 1000).toFixed(0) + 'k';
  if (val === Math.round(val)) return val.toFixed(0);
  if (val >= 100) return val.toFixed(1);
  return val.toFixed(2);
}

// ── 줌 레벨 기반 캔들 간격 ──
function getBaseGap() {
  return _chartInterval === '1mo' ? 7 : (_chartInterval === '1wk' ? 5.5 : 4);
}

// ── MA 값 가져오기 (캐시) ──
function getMaLines(allCandles) {
  const maLines = {};
  MA_CONFIG.forEach(m => {
    if (!_maVisible[m.period]) return;
    if (!_maCache[m.period]) {
      _maCache[m.period] = calcMA(allCandles, m.period);
    }
    maLines[m.period] = { values: _maCache[m.period], color: m.color };
  });
  return maLines;
}

// ── 보이는 캔들의 Y축 범위 계산 ──
function getVisibleYRange(allCandles, maLines, startIdx, endIdx) {
  let dataMin = Infinity, dataMax = -Infinity;
  for (let i = startIdx; i <= endIdx; i++) {
    const c = allCandles[i];
    if (c.l < dataMin) dataMin = c.l;
    if (c.h > dataMax) dataMax = c.h;
  }
  // 보이는 구간의 MA 값도 포함
  Object.keys(maLines).forEach(period => {
    const vals = maLines[period].values;
    for (let i = startIdx; i <= endIdx; i++) {
      const v = vals[i];
      if (v !== null && v !== undefined) {
        if (v < dataMin) dataMin = v;
        if (v > dataMax) dataMax = v;
      }
    }
  });
  return { dataMin, dataMax };
}

// ── 차트 재렌더링 (줌/스크롤 유지) ──
function _reRenderCharts(keepScrollRatio) {
  const chartEl = document.getElementById('candle-chart');
  const volEl = document.getElementById('volume-chart');
  if (!chartEl || !_chartData) return;

  let scrollRatio = 1;
  if (keepScrollRatio) {
    const sc = document.getElementById('candle-scroll');
    if (sc && sc.scrollWidth > sc.clientWidth) {
      scrollRatio = (sc.scrollLeft + sc.clientWidth / 2) / sc.scrollWidth;
    }
  }

  renderCandlestickChart(chartEl, _chartData, scrollRatio);
  if (volEl) renderVolumeChart(volEl, _chartData, scrollRatio);
}

// ═══════════════════════════════════════════════
// ── 캔들스틱 SVG 렌더링 (동적 Y축 + 스크롤 + 줌) ──
// ═══════════════════════════════════════════════
function renderCandlestickChart(el, allCandles, scrollRatio) {
  const containerW = el.clientWidth - 2;
  const H = 300;
  const yAxisW = 44;
  const pad = { top: 14, bottom: 24, left: 4 };
  const cH = H - pad.top - pad.bottom;
  const realN = allCandles.length;

  // 예측 데이터 연장 (캔들 오른쪽에 이어서 표시)
  const predArr = (_predictVisible && _predictData) ? _predictData.predicted : [];
  const predPoints = [];
  if (predArr.length > 0 && realN > 0) {
    const lastDate = allCandles[realN - 1].d;
    predArr.forEach(p => {
      if (p.date > lastDate && p.yhat != null && p.lower != null && p.upper != null) {
        predPoints.push({
          d: p.date,
          o: p.yhat, h: p.upper, l: p.lower, c: p.yhat, v: 0,
          _pred: { yhat: p.yhat, lower: p.lower, upper: p.upper }
        });
      }
    });
  }
  const allPoints = [...allCandles, ...predPoints];
  const n = allPoints.length;

  // X축 레이아웃 (줌 적용)
  const baseGap = getBaseGap();
  const candleGap = baseGap * _zoomLevel;
  const visibleW = containerW - yAxisW;
  const scrollW = Math.max(visibleW, n * candleGap + pad.left + 4);
  const chartAreaW = scrollW - pad.left;
  const gap = chartAreaW / n;
  const candleW = Math.max(1, Math.min(gap * 0.6, 12));
  const wickW = Math.min(1.2, candleW * 0.15 + 0.5);

  const xPos = i => pad.left + gap * i + gap / 2;

  // MA 값 (캐시) — 실제 캔들만 사용
  const maLines = getMaLines(allCandles);

  // 보이는 캔들 인덱스 계산
  function getVisibleRange(scrollLeft) {
    const startPx = scrollLeft;
    const endPx = scrollLeft + visibleW;
    let si = Math.floor((startPx - pad.left) / gap) - 2;
    let ei = Math.ceil((endPx - pad.left) / gap) + 2;
    si = Math.max(0, si);
    ei = Math.min(n - 1, ei);
    return [si, ei];
  }

  // 초기 스크롤 위치 예측 (Y축 계산용)
  let initScrollLeft;
  if (typeof scrollRatio === 'number') {
    initScrollLeft = Math.max(0, scrollRatio * scrollW - visibleW / 2);
  } else {
    initScrollLeft = scrollW - visibleW;
  }
  const [initSI, initEI] = getVisibleRange(initScrollLeft);
  const { dataMin, dataMax } = getVisibleYRange(allPoints, maLines, initSI, initEI);

  // Y축 스케일
  let scale = niceScale(dataMin, dataMax, 6);
  let yMin = scale.min, yMax = scale.max, yRange = yMax - yMin || 1;
  const yFn = v => pad.top + (1 - (v - yMin) / yRange) * cH;

  // 현재가 정보 (실제 마지막 캔들 기준)
  const lastC = allCandles[realN - 1].c;
  const lastColor = allCandles[realN - 1].c >= allCandles[realN - 1].o ? '#10B981' : '#EF4444';

  // ── SVG 빌드 함수 (Y축 바뀔 때 재사용) ──
  function buildMainSvg(yFn) {
    let gridLines = '';
    scale.ticks.forEach(val => {
      const yPos = yFn(val);
      if (yPos < pad.top - 2 || yPos > pad.top + cH + 2) return;
      gridLines += `<line class="chart-grid-line" x1="0" y1="${yPos.toFixed(1)}" x2="${scrollW}" y2="${yPos.toFixed(1)}"/>`;
    });

    // 현재가 점선
    const lastY = yFn(lastC);
    const priceDash = `<line x1="0" y1="${lastY.toFixed(1)}" x2="${scrollW}" y2="${lastY.toFixed(1)}" stroke="${lastColor}" stroke-width="0.6" stroke-dasharray="2 2" opacity="0.5"/>`;

    // 캔들 (실제 데이터만)
    let candleSvg = '';
    allPoints.forEach((c, i) => {
      if (c._pred) return;
      const cx = xPos(i);
      const isUp = c.c >= c.o;
      const color = isUp ? '#10B981' : '#EF4444';
      const bodyTop = yFn(Math.max(c.o, c.c));
      const bodyBot = yFn(Math.min(c.o, c.c));
      const bodyH = Math.max(0.8, bodyBot - bodyTop);
      candleSvg += `<line x1="${cx.toFixed(1)}" y1="${yFn(c.h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${yFn(c.l).toFixed(1)}" stroke="${color}" stroke-width="${wickW.toFixed(1)}"/>`;
      candleSvg += `<rect x="${(cx - candleW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${candleW.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}" rx="0.3"/>`;
    });

    // 예측 오버레이 (신뢰구간 + 예측선 + 구분선 + 애니메이션)
    let predSvg = '';
    if (predPoints.length > 0) {
      // 구분선 (마지막 캔들과 첫 예측 사이)
      const divX = (xPos(realN - 1) + xPos(realN)) / 2;
      predSvg += `<line x1="${divX.toFixed(1)}" y1="${pad.top}" x2="${divX.toFixed(1)}" y2="${pad.top + cH}" stroke="var(--sub)" stroke-width="0.8" stroke-dasharray="3 3" opacity="0.5" class="pred-anim-fade"/>`;

      // 신뢰구간 영역
      const predIdxs = [];
      allPoints.forEach((p, i) => { if (p._pred) predIdxs.push(i); });
      if (predIdxs.length > 1) {
        let upper = predIdxs.map(i => `${xPos(i).toFixed(1)},${yFn(allPoints[i]._pred.upper).toFixed(1)}`).join(' L');
        let lower = predIdxs.slice().reverse().map(i => `${xPos(i).toFixed(1)},${yFn(allPoints[i]._pred.lower).toFixed(1)}`).join(' L');
        predSvg += `<path d="M${upper} L${lower} Z" fill="rgba(59,130,246,0.12)" stroke="none" class="pred-anim-fade"/>`;
      }

      // 예측선 (마지막 종가에서 연결) — stroke-dashoffset 애니메이션
      let predLinePts = [`${xPos(realN - 1).toFixed(1)},${yFn(lastC).toFixed(1)}`];
      predIdxs.forEach(i => {
        predLinePts.push(`${xPos(i).toFixed(1)},${yFn(allPoints[i]._pred.yhat).toFixed(1)}`);
      });
      predSvg += `<path d="M${predLinePts.join(' L')}" fill="none" stroke="#3B82F6" stroke-width="2" stroke-linecap="round" class="pred-anim-line"/>`;
    }

    // MA선
    let maSvg = '';
    Object.keys(maLines).forEach(period => {
      const ma = maLines[period];
      let path = '';
      ma.values.forEach((v, i) => {
        if (v === null) return;
        const cmd = path === '' ? 'M' : 'L';
        path += `${cmd}${xPos(i).toFixed(1)},${yFn(v).toFixed(1)} `;
      });
      if (path) {
        maSvg += `<path d="${path}" fill="none" stroke="${ma.color}" stroke-width="1.2" stroke-linecap="round" class="ma-line"/>`;
      }
    });

    // X축 라벨
    let xLabels = '';
    const targetPx = 55;
    const labelEvery = Math.max(1, Math.round(targetPx / candleGap));
    for (let i = 0; i < n; i += labelEvery) {
      const d = allPoints[i].d;
      const lbl = _chartInterval === '1mo' ? d.substring(2, 7) : d.substring(5);
      xLabels += `<text class="chart-label chart-x-label" x="${xPos(i).toFixed(1)}" y="${H - 5}" text-anchor="middle">${lbl}</text>`;
    }

    // 터치 영역 (캔들 + 예측 포인트 모두)
    let touchZones = '';
    const touchW = Math.max(gap * 0.8, candleW * 3, 12);
    const touchPadY = 10;
    allPoints.forEach((c, i) => {
      const cx = xPos(i);
      const yH = yFn(c.h);
      const yL = yFn(c.l);
      const ty = Math.max(pad.top, yH - touchPadY);
      const th = Math.min(pad.top + cH, yL + touchPadY) - ty;
      touchZones += `<rect x="${(cx - touchW / 2).toFixed(1)}" y="${ty.toFixed(1)}" width="${touchW.toFixed(1)}" height="${Math.max(20, th).toFixed(1)}" fill="transparent" data-idx="${i}" class="candle-touch" pointer-events="all"/>`;
    });

    return `${gridLines}${priceDash}${candleSvg}${predSvg}${maSvg}${xLabels}${touchZones}
      <line id="candle-crosshair" class="candle-crosshair" x1="0" y1="0" x2="${scrollW}" y2="0" style="display:none"/>`;
  }

  // Y축 오버레이 빌드
  function buildYAxisSvg(yFn) {
    const lastY = yFn(lastC);
    let yLabelsHtml = '';
    scale.ticks.forEach(val => {
      const yPos = yFn(val);
      if (yPos < pad.top - 2 || yPos > pad.top + cH + 2) return;
      const tooClose = Math.abs(yPos - lastY) < 14;
      if (!tooClose) {
        yLabelsHtml += `<text class="chart-label chart-y-label" x="6" y="${yPos.toFixed(1)}" text-anchor="start" dominant-baseline="middle">${fmtYLabel(val)}</text>`;
      }
    });
    const priceLabel = lastC >= 1000 ? lastC.toFixed(0) : lastC.toFixed(2);
    yLabelsHtml += `<rect x="2" y="${lastY - 7}" width="${yAxisW - 4}" height="14" rx="3" fill="${lastColor}"/>`;
    yLabelsHtml += `<text x="${yAxisW / 2}" y="${lastY + 0.5}" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-size="8" font-weight="700">${priceLabel}</text>`;
    return yLabelsHtml;
  }

  // ── 초기 렌더링 ──
  el.innerHTML = `<div class="candle-svg-wrap">
    <div class="candle-scroll" id="candle-scroll">
      <svg width="${scrollW}" height="${H}" viewBox="0 0 ${scrollW} ${H}">
        ${buildMainSvg(yFn)}
      </svg>
    </div>
    <svg class="candle-yaxis" id="candle-yaxis" width="${yAxisW}" height="${H}" viewBox="0 0 ${yAxisW} ${H}">
      ${buildYAxisSvg(yFn)}
    </svg>
    <div class="candle-tooltip" id="candle-tip"></div>
    <div class="chart-recalc-overlay" id="chart-recalc"><div class="loading-spinner sm"></div></div>
  </div>`;

  // 스크롤 위치 복원
  const scrollEl = document.getElementById('candle-scroll');
  if (typeof scrollRatio === 'number') {
    scrollEl.scrollLeft = scrollRatio * scrollW - visibleW / 2;
  } else {
    scrollEl.scrollLeft = scrollW;
  }

  // ── 스크롤 시 Y축 동적 재계산 ──
  let scrollTimer = null;
  let prevSI = initSI, prevEI = initEI;
  const recalcOverlay = document.getElementById('chart-recalc');

  function needsYUpdate() {
    const [si, ei] = getVisibleRange(scrollEl.scrollLeft);
    if (si === prevSI && ei === prevEI) return false;
    const { dataMin: newMin, dataMax: newMax } = getVisibleYRange(allPoints, maLines, si, ei);
    const newScale = niceScale(newMin, newMax, 6);
    return newScale.min !== scale.min || newScale.max !== scale.max;
  }

  function updateYAxisOnScroll() {
    const [si, ei] = getVisibleRange(scrollEl.scrollLeft);
    if (si === prevSI && ei === prevEI) { hideRecalc(); return; }
    prevSI = si; prevEI = ei;

    const { dataMin: newMin, dataMax: newMax } = getVisibleYRange(allPoints, maLines, si, ei);
    const newScale = niceScale(newMin, newMax, 6);

    if (newScale.min === scale.min && newScale.max === scale.max) { hideRecalc(); return; }
    scale = newScale;
    yMin = scale.min; yMax = scale.max; yRange = yMax - yMin || 1;

    const newYFn = v => pad.top + (1 - (v - yMin) / yRange) * cH;

    const mainSvg = scrollEl.querySelector('svg');
    mainSvg.innerHTML = buildMainSvg(newYFn);

    const yAxisSvg = document.getElementById('candle-yaxis');
    if (yAxisSvg) yAxisSvg.innerHTML = buildYAxisSvg(newYFn);

    rebindTouchEvents(newYFn);
    hideRecalc();
  }

  function showRecalc() { if (recalcOverlay) recalcOverlay.classList.add('active'); }
  function hideRecalc() { if (recalcOverlay) recalcOverlay.classList.remove('active'); }

  scrollEl.addEventListener('scroll', () => {
    const volScroll = document.getElementById('volume-scroll');
    if (volScroll) volScroll.scrollLeft = scrollEl.scrollLeft;

    if (needsYUpdate()) showRecalc();

    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(updateYAxisOnScroll, 150);
  }, { passive: true });

  // ── 핀치 줌 ──
  let pinchStartDist = 0, pinchStartZoom = 1, isPinching = false;

  scrollEl.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      isPinching = true;
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      pinchStartDist = Math.hypot(dx, dy);
      pinchStartZoom = _zoomLevel;
      e.preventDefault();
    } else if (e.touches.length === 1 && !isPinching) {
      // 캔들 터치 영역을 직접 터치한 경우에만 툴팁 표시
      const target = e.target;
      if (target.classList && target.classList.contains('candle-touch') && target.dataset.idx != null) {
        showCandleTip(+target.dataset.idx);
      } else {
        hideCandleTip();
      }
    }
  }, { passive: false });

  scrollEl.addEventListener('touchmove', e => {
    if (e.touches.length === 2 && isPinching) {
      e.preventDefault();
      const dx = e.touches[0].clientX - e.touches[1].clientX;
      const dy = e.touches[0].clientY - e.touches[1].clientY;
      const dist = Math.hypot(dx, dy);
      const ratio = dist / pinchStartDist;
      const newZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, pinchStartZoom * ratio));
      if (Math.abs(newZoom - _zoomLevel) > 0.02) {
        _zoomLevel = newZoom;
        _reRenderCharts(true);
      }
    }
  }, { passive: false });

  scrollEl.addEventListener('touchend', e => {
    if (e.touches.length < 2) {
      if (isPinching) { isPinching = false; }
      else { setTimeout(hideCandleTip, 2000); }
    }
  }, { passive: true });

  scrollEl.addEventListener('wheel', e => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, _zoomLevel * delta));
    if (newZoom !== _zoomLevel) { _zoomLevel = newZoom; _reRenderCharts(true); }
  }, { passive: false });

  // ── 마우스 드래그 스크롤 (데스크탑) ──
  let isDragging = false, dragStartX = 0, dragStartScroll = 0, hasMoved = false; // 드래그 상태 변수

  scrollEl.style.cursor = 'grab'; // 기본 커서를 grab으로 설정

  scrollEl.addEventListener('mousedown', e => {
    if (e.button !== 0) return; // 좌클릭만 허용
    isDragging = true; // 드래그 시작 플래그
    hasMoved = false; // 이동 여부 초기화
    dragStartX = e.clientX; // 시작 X 좌표 저장
    dragStartScroll = scrollEl.scrollLeft; // 시작 스크롤 위치 저장
    scrollEl.style.cursor = 'grabbing'; // 커서를 grabbing으로 변경
    e.preventDefault(); // 텍스트 선택 방지
  });

  const onMouseMove = e => {
    if (!isDragging) return; // 드래그 중이 아니면 무시
    const dx = e.clientX - dragStartX; // 이동 거리 계산
    if (!hasMoved && Math.abs(dx) < 5) return; // 5px 미만이면 클릭으로 간주하여 무시
    hasMoved = true; // 드래그 모드 진입
    scrollEl.scrollLeft = dragStartScroll - dx; // 스크롤 위치 업데이트 (반대 방향)
  };

  const onMouseUp = () => {
    if (!isDragging) return; // 드래그 중이 아니면 무시
    isDragging = false; // 드래그 종료
    scrollEl.style.cursor = 'grab'; // 커서 복원
  };

  window.addEventListener('mousemove', onMouseMove); // 윈도우 레벨에서 이동 감지 (영역 밖에서도 동작)
  window.addEventListener('mouseup', onMouseUp); // 윈도우 레벨에서 마우스 업 감지

  // ── 터치/호버 이벤트 ──
  const tip = document.getElementById('candle-tip');
  const getCrosshair = () => document.getElementById('candle-crosshair');

  function showCandleTip(idx) {
    const currentYFn = v => pad.top + (1 - (v - yMin) / yRange) * cH;
    const c = allPoints[idx];

    // 예측 포인트인 경우 별도 툴팁
    if (c._pred) {
      tip.innerHTML = `<div class="ct-date">${c.d}</div>
        <div style="color:#3B82F6;font-weight:700">${t('chart.predictForecast')}: $${c._pred.yhat.toFixed(2)}</div>
        <div style="color:var(--sub);font-size:10px">$${c._pred.lower.toFixed(2)} ~ $${c._pred.upper.toFixed(2)}</div>`;
      const candleX = xPos(idx);
      const visibleX = candleX - scrollEl.scrollLeft;
      const tipW = 150;
      tip.style.left = visibleX > containerW * 0.5 ? `${visibleX - tipW - 8}px` : `${visibleX + 12}px`;
      tip.style.top = `${pad.top}px`;
      tip.style.opacity = '1';
      const ch = getCrosshair();
      if (ch) {
        ch.setAttribute('y1', currentYFn(c._pred.yhat).toFixed(1));
        ch.setAttribute('y2', currentYFn(c._pred.yhat).toFixed(1));
        ch.style.display = '';
      }
      return;
    }

    const chg = ((c.c - c.o) / c.o * 100).toFixed(2);
    const sign = chg > 0 ? '+' : '';
    const color = c.c >= c.o ? '#10B981' : '#EF4444';

    let maHtml = '';
    MA_CONFIG.forEach(m => {
      if (!_maVisible[m.period] || !maLines[m.period]) return;
      const v = maLines[m.period].values[idx];
      if (v !== null && v !== undefined) {
        maHtml += `<div class="ct-row"><span style="color:${m.color}">${m.label}</span> <span>${v.toFixed(2)}</span></div>`;
      }
    });

    tip.innerHTML = `<div class="ct-date">${c.d}</div>
      <div class="ct-ohlc">
        <span>O ${c.o.toFixed(2)}</span>
        <span>H ${c.h.toFixed(2)}</span>
        <span>L ${c.l.toFixed(2)}</span>
        <span style="color:${color};font-weight:700">C ${c.c.toFixed(2)}</span>
      </div>
      <div class="ct-chg" style="color:${color}">${sign}${chg}%</div>
      ${maHtml}`;
    const candleX = xPos(idx);
    const visibleX = candleX - scrollEl.scrollLeft;
    const tipW = 150;
    tip.style.left = visibleX > containerW * 0.5 ? `${visibleX - tipW - 8}px` : `${visibleX + 12}px`;
    tip.style.top = `${pad.top}px`;
    tip.style.opacity = '1';
    const hint = document.getElementById('chart-hint');
    if (hint) hint.style.display = 'none';

    const ch = getCrosshair();
    if (ch) {
      ch.setAttribute('y1', currentYFn(c.c).toFixed(1));
      ch.setAttribute('y2', currentYFn(c.c).toFixed(1));
      ch.style.display = '';
    }
  }
  function hideCandleTip() {
    tip.style.opacity = '0';
    const ch = getCrosshair();
    if (ch) ch.style.display = 'none';
  }

  function rebindTouchEvents(currentYFn) {
    const svg = scrollEl.querySelector('svg');
    svg.querySelectorAll('.candle-touch').forEach(zone => {
      zone.addEventListener('mouseenter', () => showCandleTip(+zone.dataset.idx));
      zone.addEventListener('mouseleave', hideCandleTip);
    });
  }

  // 초기 바인딩
  rebindTouchEvents(yFn);
}

// ═════════════════════════════════
// ── 거래량 바 차트 (스크롤 + 줌) ──
// ═════════════════════════════════
function renderVolumeChart(el, allCandles, scrollRatio) {
  const containerW = el.clientWidth - 2;
  const H = 60;
  const yAxisW = 44;
  const pad = { top: 2, bottom: 0, left: 4 };
  const cH = H - pad.top - pad.bottom;
  const n = allCandles.length;

  const candleGap = getBaseGap() * _zoomLevel;
  const visibleW = containerW - yAxisW;
  const scrollW = Math.max(visibleW, n * candleGap + pad.left + 4);
  const chartAreaW = scrollW - pad.left;
  const gap = chartAreaW / n;
  const barW = Math.max(1, Math.min(gap * 0.6, 12));
  const xPos = i => pad.left + gap * i + gap / 2;

  const maxVol = Math.max(...allCandles.map(c => c.v)) || 1;

  let bars = '';
  allCandles.forEach((c, i) => {
    const h = (c.v / maxVol) * cH;
    const isUp = c.c >= c.o;
    const color = isUp ? 'rgba(16,185,129,0.45)' : 'rgba(239,68,68,0.45)';
    bars += `<rect x="${(xPos(i) - barW / 2).toFixed(1)}" y="${(pad.top + cH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.5, h).toFixed(1)}" fill="${color}" rx="0.3"/>`;
  });

  el.innerHTML = `<div class="vol-scroll-wrap">
    <div class="volume-scroll" id="volume-scroll">
      <svg width="${scrollW}" height="${H}" viewBox="0 0 ${scrollW} ${H}">${bars}</svg>
    </div>
    <div class="vol-yaxis-spacer" style="width:${yAxisW}px;min-width:${yAxisW}px"></div>
  </div>`;

  const volScroll = document.getElementById('volume-scroll');
  if (typeof scrollRatio === 'number') {
    volScroll.scrollLeft = scrollRatio * scrollW - visibleW / 2;
  } else {
    volScroll.scrollLeft = scrollW;
  }

  volScroll.addEventListener('scroll', () => {
    const candleScroll = document.getElementById('candle-scroll');
    if (candleScroll) candleScroll.scrollLeft = volScroll.scrollLeft;
  }, { passive: true });
}

// ── 요약 정보 (가격 헤더 + 상단 스탯 + 하단 범위 바) ──
function renderChartSummary(el, candles) {
  // el은 기존 chart-summary (미사용, 호환 유지)
  if (candles.length < 2) return;
  const latest = candles[candles.length - 1];
  const prev = candles[candles.length - 2];

  // 6개월치 캔들 수: 일봉=126, 주봉=26, 월봉=6
  const sixMonthCount = _chartInterval === '1mo' ? 6 : _chartInterval === '1wk' ? 26 : 126;
  const sixMonthIdx = Math.max(0, candles.length - sixMonthCount);
  const sixMonthBase = candles[sixMonthIdx];

  const dayChg = ((latest.c - prev.c) / prev.c * 100);
  const periodChg = ((latest.c - sixMonthBase.o) / sixMonthBase.o * 100);
  // 최고/최저도 6개월 범위에서 계산
  const recentCandles = candles.slice(sixMonthIdx);
  const high = Math.max(...recentCandles.map(c => c.h));
  const low = Math.min(...recentCandles.map(c => c.l));
  const range = low > 0 ? ((high - low) / low * 100) : 0;
  const pos = high > low ? ((latest.c - low) / (high - low) * 100) : 50;

  const periodLabel = '6개월';
  const chgColor = dayChg >= 0 ? '#10B981' : '#EF4444';
  const chgSign = dayChg >= 0 ? '+' : '';
  const pChgColor = periodChg >= 0 ? '#10B981' : '#EF4444';
  const pChgSign = periodChg >= 0 ? '+' : '';
  const name = TICKER_NAMES[_chartTicker] || _chartTicker;

  // ① 가격 헤더
  const headerEl = document.getElementById('chart-price-header');
  if (headerEl) {
    headerEl.innerHTML = `
      <div class="chart-price-row">
        <span class="chart-price-val">$${latest.c.toFixed(2)}</span>
        <span class="chart-price-chg" style="color:${chgColor}">${chgSign}${dayChg.toFixed(2)}%</span>
      </div>
      <div class="chart-price-name">${_chartTicker} · ${name}</div>`;
  }

  // ② 상단 3카드
  const statsEl = document.getElementById('chart-top-stats');
  if (statsEl) {
    statsEl.innerHTML = `
      <div class="chart-stats-grid">
        <div class="chart-stat-card">
          <div class="chart-stat-label">${periodLabel}</div>
          <div class="chart-stat-val" style="color:${pChgColor}">${pChgSign}${periodChg.toFixed(1)}%</div>
        </div>
        <div class="chart-stat-card">
          <div class="chart-stat-label">${t('chart.high')}</div>
          <div class="chart-stat-val">$${high.toFixed(1)}</div>
        </div>
        <div class="chart-stat-card">
          <div class="chart-stat-label">${t('chart.low')}</div>
          <div class="chart-stat-val">$${low.toFixed(1)}</div>
        </div>
      </div>`;
  }

  // ③ 하단 범위 바
  const rangeEl = document.getElementById('chart-range-bar');
  if (rangeEl) {
    rangeEl.innerHTML = `
      <div class="chart-range-card">
        <div class="chart-range-head">
          <span class="chart-range-label">${periodLabel} 가격 범위</span>
          <span class="chart-range-badge" style="color:${pChgColor}">${pChgSign}${periodChg.toFixed(1)}% 변동</span>
        </div>
        <div class="chart-range-track">
          <div class="chart-range-fill" style="width:${Math.min(pos, 100)}%;background:linear-gradient(90deg, ${periodChg >= 0 ? '#10B981' : '#EF4444'}, ${periodChg >= 0 ? '#06B6D4' : '#F97316'})"></div>
          <div class="chart-range-dot" style="left:${Math.min(Math.max(pos, 3), 97)}%;border-color:${periodChg >= 0 ? '#10B981' : '#EF4444'}"></div>
        </div>
        <div class="chart-range-minmax">
          <span>$${low.toFixed(1)}</span>
          <span>$${high.toFixed(1)}</span>
        </div>
      </div>`;
  }

  // 기존 chart-summary 비우기
  if (el) el.innerHTML = '';
}

// ═════════════════════════════════
// ── 30일 예측 (캔들차트 연장) ──
// ═════════════════════════════════

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
    try {
      let data = null;
      // 최대 3회 재시도 (백그라운드 재생성 대기)
      for (let attempt = 0; attempt < 3; attempt++) {
        const res = await fetch(`/api/chart/predict?ticker=${_chartTicker}`);
        data = await res.json();
        if (!data.error) break;
        if (attempt < 2) {
          btn.textContent = t('chart.predictLoading') + '..';
          await new Promise(r => setTimeout(r, 3000));
        }
      }
      if (!data || data.error) {
        _predictVisible = false;
        btn.classList.remove('active');
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
    } finally {
      btn.disabled = false;
      btn.textContent = t('chart.predictBtn');
    }
  });
}

function hidePredictSection() {
  _predictVisible = false;
  _predictData = null;
  const btn = document.getElementById('predict-toggle-btn');
  if (btn) btn.classList.remove('active');
  renderPredictLegend(false);
}

// 일봉일 때만 예측 버튼 표시
function updatePredictBtnVisibility() {
  const wrap = document.getElementById('predict-toggle-btn')?.parentElement;
  if (wrap) wrap.style.display = _chartInterval === '1d' ? '' : 'none';
}

function showPredictDisclaimer() {
  let toast = document.getElementById('predict-disclaimer-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'predict-disclaimer-toast';
    toast.className = 'predict-disclaimer-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = t('chart.predictDisclaimer');
  toast.classList.remove('hide');
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
    toast.classList.add('hide');
  }, 3000);
}

function renderPredictLegend(show) {
  const el = document.getElementById('predict-legend');
  if (!el) return;
  if (!show) { el.innerHTML = ''; return; }
  el.innerHTML = `
    <div class="predict-legend-item">
      <span class="predict-legend-dot" style="background:#3B82F6"></span>${t('chart.predictForecast')}
    </div>
    <div class="predict-legend-item">
      <span class="predict-legend-bar" style="background:rgba(59,130,246,0.15)"></span>${t('chart.predictConfidence')}
    </div>`;
}
