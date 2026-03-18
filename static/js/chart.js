// ── 캔들스틱 차트 탭 ──
const CHART_MAIN_TICKERS = ['SPY','QQQ','DIA','IWM','VOO','SOXX','SMH','GLD','TLT','SCHD'];

// 이동평균선 설정 (기간, 색상)
const MA_CONFIG = [
  { period: 5,   color: '#FF6B6B', label: 'MA5' },
  { period: 20,  color: '#4ECDC4', label: 'MA20' },
  { period: 60,  color: '#FFD93D', label: 'MA60' },
  { period: 120, color: '#6C5CE7', label: 'MA120' },
];

let _chartTicker = 'SPY';
let _chartInterval = '1d';
let _chartData = null;
let _maVisible = { 5: true, 20: true, 60: true, 120: false };

// ── 차트 탭 초기화 ──
function initChartTab() {
  renderTickerChips();
  setupIntervalButtons();
  loadCandleChart();
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
    loadCandleChart();
  };
}

// ── 봉 간격 버튼 ──
function setupIntervalButtons() {
  const btns = document.querySelectorAll('.chart-iv-btn');
  btns.forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.iv === _chartInterval) return;
      _chartInterval = btn.dataset.iv;
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
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

  // 로딩 스켈레톤
  chartEl.innerHTML = '<div class="candle-loading"><div class="candle-skeleton"></div></div>';
  if (volEl) volEl.innerHTML = '';
  if (sumEl) sumEl.innerHTML = '';

  try {
    const res = await fetch(`/api/chart/ohlc?ticker=${_chartTicker}&interval=${_chartInterval}`);
    const data = await res.json();
    if (data.error || !data.candles || data.candles.length < 2) {
      chartEl.innerHTML = `<div class="candle-empty">${t('chart.noData')}</div>`;
      return;
    }

    const maxCandles = _chartInterval === '1mo' ? 60 : (_chartInterval === '1wk' ? 80 : 120);
    const candles = data.candles.slice(-maxCandles);
    _chartData = data.candles; // 전체 데이터 (MA 계산용)

    renderCandlestickChart(chartEl, candles, data.candles);
    if (volEl) renderVolumeChart(volEl, candles);
    if (sumEl) renderChartSummary(sumEl, candles);
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
    // 다시 그리기
    const chartEl = document.getElementById('candle-chart');
    if (chartEl && _chartData) {
      const maxCandles = _chartInterval === '1mo' ? 60 : (_chartInterval === '1wk' ? 80 : 120);
      const candles = _chartData.slice(-maxCandles);
      renderCandlestickChart(chartEl, candles, _chartData);
    }
    renderMALegend();
  };
}

// ── Y축 라벨 포맷 (깔끔한 정수 표시) ──
function fmtYLabel(val) {
  if (val >= 10000) return (val / 1000).toFixed(0) + 'k';
  if (val === Math.round(val)) return val.toFixed(0);       // 정수면 소수점 없이
  if (val >= 100) return val.toFixed(1);
  return val.toFixed(2);
}

// ── 캔들스틱 SVG 렌더링 ──
function renderCandlestickChart(el, candles, allCandles) {
  const W = el.clientWidth - 2;
  const H = 300;
  const pad = { top: 14, right: 48, bottom: 28, left: 8 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;
  const n = candles.length;

  // Y축 범위 (캔들 + 이동평균선 고려)
  let dataMin = Infinity, dataMax = -Infinity;
  candles.forEach(c => {
    if (c.l < dataMin) dataMin = c.l;
    if (c.h > dataMax) dataMax = c.h;
  });

  // MA 값 계산 (전체 데이터 기반, 표시 구간만 추출)
  const maLines = {};
  const offset = allCandles.length - n;
  MA_CONFIG.forEach(m => {
    if (!_maVisible[m.period]) return;
    const fullMA = calcMA(allCandles, m.period);
    const sliced = fullMA.slice(offset);
    maLines[m.period] = { values: sliced, color: m.color };
    sliced.forEach(v => {
      if (v !== null) {
        if (v < dataMin) dataMin = v;
        if (v > dataMax) dataMax = v;
      }
    });
  });

  // nice scale
  const scale = niceScale(dataMin, dataMax, 6);
  const yMin = scale.min;
  const yMax = scale.max;
  const yRange = yMax - yMin || 1;

  const gap = cW / n;
  const candleW = Math.max(1, Math.min(gap * 0.65, 8));

  const x = i => pad.left + gap * i + gap / 2;
  const y = v => pad.top + (1 - (v - yMin) / yRange) * cH;

  // 현재가 정보 (먼저 계산 → Y축 라벨 충돌 체크용)
  const lastC = candles[n - 1].c;
  const lastColor = candles[n - 1].c >= candles[n - 1].o ? '#10B981' : '#EF4444';
  const lastY = y(lastC);

  // Y축 격자 + 라벨 (오른쪽 배치, 현재가와 겹치는 tick 숨기기)
  let yLabels = '', gridLines = '';
  scale.ticks.forEach(val => {
    const yPos = y(val);
    if (yPos < pad.top - 2 || yPos > pad.top + cH + 2) return;
    // 현재가 라벨과 너무 가까우면 이 tick 라벨 숨기기 (격자선은 유지)
    const tooClose = Math.abs(yPos - lastY) < 14;
    gridLines += `<line class="chart-grid-line" x1="${pad.left}" y1="${yPos.toFixed(1)}" x2="${W - pad.right}" y2="${yPos.toFixed(1)}"/>`;
    if (!tooClose) {
      yLabels += `<text class="chart-label chart-y-label" x="${W - pad.right + 6}" y="${yPos.toFixed(1)}" text-anchor="start" dominant-baseline="middle">${fmtYLabel(val)}</text>`;
    }
  });

  // X축 라벨
  let xLabels = '';
  const labelCount = Math.min(5, n);
  const labelStep = Math.max(1, Math.floor((n - 1) / (labelCount - 1)));
  for (let i = 0; i < n; i += labelStep) {
    const d = candles[i].d;
    const lbl = _chartInterval === '1mo' ? d.substring(2, 7) : d.substring(5);
    xLabels += `<text class="chart-label chart-x-label" x="${x(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${lbl}</text>`;
  }

  // 캔들 SVG
  let candleSvg = '';
  candles.forEach((c, i) => {
    const cx = x(i);
    const isUp = c.c >= c.o;
    const color = isUp ? '#10B981' : '#EF4444';
    const bodyTop = y(Math.max(c.o, c.c));
    const bodyBot = y(Math.min(c.o, c.c));
    const bodyH = Math.max(0.8, bodyBot - bodyTop);

    // 심지
    candleSvg += `<line x1="${cx.toFixed(1)}" y1="${y(c.h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${color}" stroke-width="0.8"/>`;
    // 몸통
    candleSvg += `<rect x="${(cx - candleW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${candleW.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}" rx="0.3"/>`;
  });

  // 이동평균선 SVG
  let maSvg = '';
  Object.keys(maLines).forEach(period => {
    const ma = maLines[period];
    let path = '';
    ma.values.forEach((v, i) => {
      if (v === null) return;
      const cmd = path === '' ? 'M' : 'L';
      path += `${cmd}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
    });
    if (path) {
      maSvg += `<path d="${path}" fill="none" stroke="${ma.color}" stroke-width="1.2" stroke-linecap="round" class="ma-line"/>`;
    }
  });

  // 터치 영역
  let touchZones = '';
  candles.forEach((c, i) => {
    touchZones += `<rect x="${(x(i) - gap / 2).toFixed(1)}" y="${pad.top}" width="${gap.toFixed(1)}" height="${cH}" fill="transparent" data-idx="${i}" class="candle-touch"/>`;
  });

  // 현재가: 점선 + 오른쪽 작은 라벨
  const priceLabel = lastC >= 1000 ? lastC.toFixed(0) : lastC.toFixed(2);
  const priceLabelSvg = `
    <line x1="${pad.left}" y1="${lastY.toFixed(1)}" x2="${W - pad.right}" y2="${lastY.toFixed(1)}" stroke="${lastColor}" stroke-width="0.6" stroke-dasharray="2 2" opacity="0.6"/>
    <rect x="${W - pad.right + 2}" y="${lastY - 7}" width="${pad.right - 6}" height="14" rx="3" fill="${lastColor}"/>
    <text x="${W - pad.right + pad.right / 2 - 1}" y="${lastY + 0.5}" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-size="8" font-weight="700">${priceLabel}</text>`;

  el.innerHTML = `<div class="candle-svg-wrap">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
      ${gridLines}
      ${candleSvg}
      ${maSvg}
      ${priceLabelSvg}
      ${xLabels}
      ${yLabels}
      ${touchZones}
      <line id="candle-crosshair" class="candle-crosshair" x1="${pad.left}" y1="0" x2="${W - pad.right}" y2="0" style="display:none"/>
    </svg>
    <div class="candle-tooltip" id="candle-tip"></div>
  </div>`;

  // 터치/호버 이벤트
  const svg = el.querySelector('svg');
  const tip = document.getElementById('candle-tip');
  const crosshair = document.getElementById('candle-crosshair');

  function showCandleTip(idx) {
    const c = candles[idx];
    const chg = ((c.c - c.o) / c.o * 100).toFixed(2);
    const sign = chg > 0 ? '+' : '';
    const color = c.c >= c.o ? '#10B981' : '#EF4444';

    // MA 값 표시
    let maHtml = '';
    MA_CONFIG.forEach(m => {
      if (!_maVisible[m.period] || !maLines[m.period]) return;
      const v = maLines[m.period].values[idx];
      if (v !== null) {
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
    const cx = x(idx);
    const tipW = 150;
    tip.style.left = cx > W * 0.6 ? `${cx - tipW - 8}px` : `${cx + 12}px`;
    tip.style.top = `${pad.top}px`;
    tip.style.opacity = '1';

    crosshair.setAttribute('y1', y(c.c).toFixed(1));
    crosshair.setAttribute('y2', y(c.c).toFixed(1));
    crosshair.style.display = '';
  }
  function hideCandleTip() {
    tip.style.opacity = '0';
    crosshair.style.display = 'none';
  }

  svg.querySelectorAll('.candle-touch').forEach(zone => {
    zone.addEventListener('mouseenter', () => showCandleTip(+zone.dataset.idx));
    zone.addEventListener('mouseleave', hideCandleTip);
  });
  svg.addEventListener('touchstart', e => {
    const rect = svg.getBoundingClientRect();
    const tx = (e.touches[0].clientX - rect.left) / rect.width * W;
    let closest = 0, minDist = Infinity;
    candles.forEach((_, i) => { const d = Math.abs(x(i) - tx); if (d < minDist) { minDist = d; closest = i; } });
    showCandleTip(closest);
  }, { passive: true });
  svg.addEventListener('touchend', () => setTimeout(hideCandleTip, 2000), { passive: true });
}

// ── 거래량 바 차트 ──
function renderVolumeChart(el, candles) {
  const W = el.clientWidth - 2;
  const H = 60;
  const pad = { top: 2, right: 48, bottom: 0, left: 8 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;
  const n = candles.length;

  const maxVol = Math.max(...candles.map(c => c.v)) || 1;
  const gap = cW / n;
  const barW = Math.max(1, Math.min(gap * 0.65, 8));
  const x = i => pad.left + gap * i + gap / 2;

  let bars = '';
  candles.forEach((c, i) => {
    const h = (c.v / maxVol) * cH;
    const isUp = c.c >= c.o;
    const color = isUp ? 'rgba(16,185,129,0.45)' : 'rgba(239,68,68,0.45)';
    bars += `<rect x="${(x(i) - barW / 2).toFixed(1)}" y="${(pad.top + cH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.5, h).toFixed(1)}" fill="${color}" rx="0.3"/>`;
  });

  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${bars}</svg>`;
}

// ── 요약 정보 카드 ──
function renderChartSummary(el, candles) {
  if (candles.length < 2) { el.innerHTML = ''; return; }
  const latest = candles[candles.length - 1];
  const prev = candles[candles.length - 2];
  const first = candles[0];

  const dayChg = ((latest.c - prev.c) / prev.c * 100);
  const periodChg = ((latest.c - first.o) / first.o * 100);
  const high = Math.max(...candles.map(c => c.h));
  const low = Math.min(...candles.map(c => c.l));

  const periodLabel = _chartInterval === '1d' ? t('chart.period6m')
    : _chartInterval === '1wk' ? t('chart.period2y') : t('chart.period5y');

  function fmtChg(v) {
    const s = v > 0 ? '+' : '';
    const color = v > 0 ? '#10B981' : v < 0 ? '#EF4444' : 'var(--sub)';
    return `<span style="color:${color};font-weight:700">${s}${v.toFixed(2)}%</span>`;
  }

  el.innerHTML = `
    <div class="chart-sum-grid">
      <div class="chart-sum-item">
        <div class="chart-sum-label">${t('chart.lastClose')}</div>
        <div class="chart-sum-val">$${latest.c.toFixed(2)}</div>
      </div>
      <div class="chart-sum-item">
        <div class="chart-sum-label">${t('chart.prevChg')}</div>
        <div class="chart-sum-val">${fmtChg(dayChg)}</div>
      </div>
      <div class="chart-sum-item">
        <div class="chart-sum-label">${periodLabel}</div>
        <div class="chart-sum-val">${fmtChg(periodChg)}</div>
      </div>
      <div class="chart-sum-item">
        <div class="chart-sum-label">${t('chart.high')}</div>
        <div class="chart-sum-val" style="color:#10B981">$${high.toFixed(2)}</div>
      </div>
      <div class="chart-sum-item">
        <div class="chart-sum-label">${t('chart.low')}</div>
        <div class="chart-sum-val" style="color:#EF4444">$${low.toFixed(2)}</div>
      </div>
      <div class="chart-sum-item">
        <div class="chart-sum-label">${t('chart.range')}</div>
        <div class="chart-sum-val">${((high - low) / low * 100).toFixed(1)}%</div>
      </div>
    </div>`;
}
