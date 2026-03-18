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

    _chartData = data.candles; // 전체 데이터 (MA 계산용)

    renderCandlestickChart(chartEl, data.candles);
    if (volEl) renderVolumeChart(volEl, data.candles);
    if (sumEl) renderChartSummary(sumEl, data.candles);
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
      renderCandlestickChart(chartEl, _chartData);
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

// ── 캔들스틱 SVG 렌더링 (스크롤 가능) ──
function renderCandlestickChart(el, allCandles) {
  const containerW = el.clientWidth - 2;
  const H = 300;
  const yAxisW = 44;
  const pad = { top: 14, bottom: 24, left: 4 };
  const cH = H - pad.top - pad.bottom;
  const n = allCandles.length;

  // 캔들당 고정 너비 (간격 포함)
  const candleGap = _chartInterval === '1mo' ? 7 : (_chartInterval === '1wk' ? 5.5 : 4);
  const scrollW = Math.max(containerW - yAxisW, n * candleGap + pad.left + 4);
  const chartAreaW = scrollW - pad.left;

  const gap = chartAreaW / n;
  const candleW = Math.max(1, Math.min(gap * 0.6, 8));

  const x = i => pad.left + gap * i + gap / 2;

  // Y축 범위 (전체 데이터)
  let dataMin = Infinity, dataMax = -Infinity;
  allCandles.forEach(c => {
    if (c.l < dataMin) dataMin = c.l;
    if (c.h > dataMax) dataMax = c.h;
  });

  // MA 값 계산
  const maLines = {};
  MA_CONFIG.forEach(m => {
    if (!_maVisible[m.period]) return;
    const vals = calcMA(allCandles, m.period);
    maLines[m.period] = { values: vals, color: m.color };
    vals.forEach(v => {
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

  const y = v => pad.top + (1 - (v - yMin) / yRange) * cH;

  // 현재가 정보
  const lastC = allCandles[n - 1].c;
  const lastColor = allCandles[n - 1].c >= allCandles[n - 1].o ? '#10B981' : '#EF4444';
  const lastY = y(lastC);

  // 격자선 (스크롤 영역 내)
  let gridLines = '';
  scale.ticks.forEach(val => {
    const yPos = y(val);
    if (yPos < pad.top - 2 || yPos > pad.top + cH + 2) return;
    gridLines += `<line class="chart-grid-line" x1="0" y1="${yPos.toFixed(1)}" x2="${scrollW}" y2="${yPos.toFixed(1)}"/>`;
  });

  // 캔들 SVG
  let candleSvg = '';
  allCandles.forEach((c, i) => {
    const cx = x(i);
    const isUp = c.c >= c.o;
    const color = isUp ? '#10B981' : '#EF4444';
    const bodyTop = y(Math.max(c.o, c.c));
    const bodyBot = y(Math.min(c.o, c.c));
    const bodyH = Math.max(0.8, bodyBot - bodyTop);
    candleSvg += `<line x1="${cx.toFixed(1)}" y1="${y(c.h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${color}" stroke-width="0.8"/>`;
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

  // X축 라벨
  let xLabels = '';
  const labelEvery = Math.max(1, Math.round(20 / candleGap * 5));
  for (let i = 0; i < n; i += labelEvery) {
    const d = allCandles[i].d;
    const lbl = _chartInterval === '1mo' ? d.substring(2, 7) : d.substring(5);
    xLabels += `<text class="chart-label chart-x-label" x="${x(i).toFixed(1)}" y="${H - 5}" text-anchor="middle">${lbl}</text>`;
  }

  // 현재가 점선 (스크롤 영역 내)
  const priceDash = `<line x1="0" y1="${lastY.toFixed(1)}" x2="${scrollW}" y2="${lastY.toFixed(1)}" stroke="${lastColor}" stroke-width="0.6" stroke-dasharray="2 2" opacity="0.5"/>`;

  // 터치 영역
  let touchZones = '';
  allCandles.forEach((c, i) => {
    touchZones += `<rect x="${(x(i) - gap / 2).toFixed(1)}" y="${pad.top}" width="${gap.toFixed(1)}" height="${cH}" fill="transparent" data-idx="${i}" class="candle-touch"/>`;
  });

  // Y축 오버레이 (고정, 오른쪽)
  let yLabelsHtml = '';
  scale.ticks.forEach(val => {
    const yPos = y(val);
    if (yPos < pad.top - 2 || yPos > pad.top + cH + 2) return;
    const tooClose = Math.abs(yPos - lastY) < 14;
    if (!tooClose) {
      yLabelsHtml += `<text class="chart-label chart-y-label" x="6" y="${yPos.toFixed(1)}" text-anchor="start" dominant-baseline="middle">${fmtYLabel(val)}</text>`;
    }
  });

  const priceLabel = lastC >= 1000 ? lastC.toFixed(0) : lastC.toFixed(2);
  const priceLabelOverlay = `
    <rect x="2" y="${lastY - 7}" width="${yAxisW - 4}" height="14" rx="3" fill="${lastColor}"/>
    <text x="${yAxisW / 2}" y="${lastY + 0.5}" text-anchor="middle" dominant-baseline="middle" fill="#fff" font-size="8" font-weight="700">${priceLabel}</text>`;

  el.innerHTML = `<div class="candle-svg-wrap">
    <div class="candle-scroll" id="candle-scroll">
      <svg width="${scrollW}" height="${H}" viewBox="0 0 ${scrollW} ${H}">
        ${gridLines}
        ${priceDash}
        ${candleSvg}
        ${maSvg}
        ${xLabels}
        ${touchZones}
        <line id="candle-crosshair" class="candle-crosshair" x1="0" y1="0" x2="${scrollW}" y2="0" style="display:none"/>
      </svg>
    </div>
    <svg class="candle-yaxis" width="${yAxisW}" height="${H}" viewBox="0 0 ${yAxisW} ${H}">
      ${yLabelsHtml}
      ${priceLabelOverlay}
    </svg>
    <div class="candle-tooltip" id="candle-tip"></div>
  </div>`;

  // 오른쪽 끝으로 스크롤 (최신 데이터부터 보이기)
  const scrollEl = document.getElementById('candle-scroll');
  scrollEl.scrollLeft = scrollEl.scrollWidth;

  // 거래량 차트와 스크롤 동기화
  scrollEl.addEventListener('scroll', () => {
    const volScroll = document.getElementById('volume-scroll');
    if (volScroll) volScroll.scrollLeft = scrollEl.scrollLeft;
  }, { passive: true });

  // 터치/호버 이벤트
  const svg = scrollEl.querySelector('svg');
  const tip = document.getElementById('candle-tip');
  const crosshair = document.getElementById('candle-crosshair');

  function showCandleTip(idx) {
    const c = allCandles[idx];
    const chg = ((c.c - c.o) / c.o * 100).toFixed(2);
    const sign = chg > 0 ? '+' : '';
    const color = c.c >= c.o ? '#10B981' : '#EF4444';

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
    // Position tooltip relative to visible area
    const candleX = x(idx);
    const visibleX = candleX - scrollEl.scrollLeft;
    const tipW = 150;
    tip.style.left = visibleX > containerW * 0.5 ? `${visibleX - tipW - 8}px` : `${visibleX + 12}px`;
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
    const tx = e.touches[0].clientX - rect.left;
    const svgX = tx / rect.width * scrollW;
    let closest = 0, minDist = Infinity;
    allCandles.forEach((_, i) => { const d = Math.abs(x(i) - svgX); if (d < minDist) { minDist = d; closest = i; } });
    showCandleTip(closest);
  }, { passive: true });
  svg.addEventListener('touchend', () => setTimeout(hideCandleTip, 2000), { passive: true });
}

// ── 거래량 바 차트 (스크롤 가능) ──
function renderVolumeChart(el, allCandles) {
  const containerW = el.clientWidth - 2;
  const H = 60;
  const yAxisW = 44;
  const pad = { top: 2, bottom: 0, left: 4 };
  const cH = H - pad.top - pad.bottom;
  const n = allCandles.length;

  const candleGap = _chartInterval === '1mo' ? 7 : (_chartInterval === '1wk' ? 5.5 : 4);
  const scrollW = Math.max(containerW - yAxisW, n * candleGap + pad.left + 4);
  const chartAreaW = scrollW - pad.left;

  const gap = chartAreaW / n;
  const barW = Math.max(1, Math.min(gap * 0.6, 8));
  const x = i => pad.left + gap * i + gap / 2;

  const maxVol = Math.max(...allCandles.map(c => c.v)) || 1;

  let bars = '';
  allCandles.forEach((c, i) => {
    const h = (c.v / maxVol) * cH;
    const isUp = c.c >= c.o;
    const color = isUp ? 'rgba(16,185,129,0.45)' : 'rgba(239,68,68,0.45)';
    bars += `<rect x="${(x(i) - barW / 2).toFixed(1)}" y="${(pad.top + cH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(0.5, h).toFixed(1)}" fill="${color}" rx="0.3"/>`;
  });

  el.innerHTML = `<div class="vol-scroll-wrap">
    <div class="volume-scroll" id="volume-scroll">
      <svg width="${scrollW}" height="${H}" viewBox="0 0 ${scrollW} ${H}">${bars}</svg>
    </div>
    <div class="vol-yaxis-spacer" style="width:${yAxisW}px;min-width:${yAxisW}px"></div>
  </div>`;

  // 오른쪽 끝으로 스크롤
  const volScroll = document.getElementById('volume-scroll');
  volScroll.scrollLeft = volScroll.scrollWidth;

  // 캔들 차트와 스크롤 동기화
  volScroll.addEventListener('scroll', () => {
    const candleScroll = document.getElementById('candle-scroll');
    if (candleScroll) candleScroll.scrollLeft = volScroll.scrollLeft;
  }, { passive: true });
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
