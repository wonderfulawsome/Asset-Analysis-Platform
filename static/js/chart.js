// ── 캔들스틱 차트 탭 ──
// 주요 ETF: SPY, QQQ, DIA, IWM, VOO, SOXX, SMH, GLD, TLT, SCHD
const CHART_MAIN_TICKERS = ['SPY','QQQ','DIA','IWM','VOO','SOXX','SMH','GLD','TLT','SCHD'];

let _chartTicker = 'SPY';
let _chartInterval = '1d';
let _chartData = null;

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

// ── OHLC 데이터 로드 ──
async function loadCandleChart() {
  const chartEl = document.getElementById('candle-chart');
  const volEl = document.getElementById('volume-chart');
  const sumEl = document.getElementById('chart-summary');
  if (!chartEl) return;

  chartEl.innerHTML = `<div style="text-align:center;padding:40px 0;color:var(--sub);font-size:13px">${t('holdings.loading')}</div>`;
  if (volEl) volEl.innerHTML = '';
  if (sumEl) sumEl.innerHTML = '';

  try {
    const res = await fetch(`/api/chart/ohlc?ticker=${_chartTicker}&interval=${_chartInterval}`);
    const data = await res.json();
    if (data.error || !data.candles || data.candles.length < 2) {
      chartEl.innerHTML = `<div style="text-align:center;padding:40px 0;color:var(--sub);font-size:13px">${t('chart.noData')}</div>`;
      return;
    }

    // 최근 N개만 표시
    const maxCandles = _chartInterval === '1mo' ? 60 : (_chartInterval === '1wk' ? 80 : 120);
    const candles = data.candles.slice(-maxCandles);
    _chartData = candles;

    renderCandlestickChart(chartEl, candles);
    if (volEl) renderVolumeChart(volEl, candles);
    if (sumEl) renderChartSummary(sumEl, candles);
  } catch (err) {
    chartEl.innerHTML = `<div style="text-align:center;padding:40px 0;color:var(--sub);font-size:13px">${t('chart.noData')}</div>`;
  }
}

// ── 캔들스틱 SVG 렌더링 ──
function renderCandlestickChart(el, candles) {
  const W = el.clientWidth - 2;
  const H = 280;
  const pad = { top: 16, right: 12, bottom: 24, left: 52 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;
  const n = candles.length;

  // Y축 범위
  let yMin = Infinity, yMax = -Infinity;
  candles.forEach(c => {
    if (c.l < yMin) yMin = c.l;
    if (c.h > yMax) yMax = c.h;
  });
  const yPad = (yMax - yMin) * 0.05;
  yMin -= yPad;
  yMax += yPad;
  const yRange = yMax - yMin || 1;

  const candleW = Math.max(1, (cW / n) * 0.7);
  const gap = cW / n;

  const x = i => pad.left + gap * i + gap / 2;
  const y = v => pad.top + (1 - (v - yMin) / yRange) * cH;

  // Y축 라벨 + 격자
  let yLabels = '', gridLines = '';
  const ySteps = 5;
  for (let i = 0; i <= ySteps; i++) {
    const val = yMin + (yRange * i) / ySteps;
    const yPos = y(val);
    const label = val >= 1000 ? val.toFixed(0) : val.toFixed(val >= 100 ? 1 : 2);
    yLabels += `<text class="chart-label" x="${pad.left - 4}" y="${yPos.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${label}</text>`;
    gridLines += `<line class="chart-grid-line" x1="${pad.left}" y1="${yPos.toFixed(1)}" x2="${W - pad.right}" y2="${yPos.toFixed(1)}"/>`;
  }

  // X축 라벨
  let xLabels = '';
  const labelCount = Math.min(7, n);
  const labelStep = Math.max(1, Math.floor((n - 1) / (labelCount - 1)));
  for (let i = 0; i < n; i += labelStep) {
    const d = candles[i].d;
    const lbl = _chartInterval === '1mo' ? d.substring(0, 7) : d.substring(5);
    xLabels += `<text class="chart-label" x="${x(i).toFixed(1)}" y="${H - 2}" text-anchor="middle">${lbl}</text>`;
  }

  // 캔들 SVG
  let candleSvg = '';
  candles.forEach((c, i) => {
    const cx = x(i);
    const isUp = c.c >= c.o;
    const color = isUp ? '#10B981' : '#EF4444';
    const bodyTop = y(Math.max(c.o, c.c));
    const bodyBot = y(Math.min(c.o, c.c));
    const bodyH = Math.max(1, bodyBot - bodyTop);

    // 심지 (위꼬리 + 아래꼬리)
    candleSvg += `<line x1="${cx.toFixed(1)}" y1="${y(c.h).toFixed(1)}" x2="${cx.toFixed(1)}" y2="${y(c.l).toFixed(1)}" stroke="${color}" stroke-width="1"/>`;
    // 몸통
    candleSvg += `<rect x="${(cx - candleW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${candleW.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${isUp ? color : color}" rx="0.5"/>`;
  });

  // 터치 영역 (투명 rect로 인덱스 감지)
  let touchZones = '';
  candles.forEach((c, i) => {
    touchZones += `<rect x="${(x(i) - gap / 2).toFixed(1)}" y="${pad.top}" width="${gap.toFixed(1)}" height="${cH}" fill="transparent" data-idx="${i}" class="candle-touch"/>`;
  });

  el.innerHTML = `<div class="candle-svg-wrap">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
      ${gridLines}
      ${candleSvg}
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
    tip.innerHTML = `<div class="ct-date">${c.d}</div>
      <div class="ct-row">O <span>${c.o.toFixed(2)}</span></div>
      <div class="ct-row">H <span>${c.h.toFixed(2)}</span></div>
      <div class="ct-row">L <span>${c.l.toFixed(2)}</span></div>
      <div class="ct-row">C <span style="color:${color};font-weight:700">${c.c.toFixed(2)} (${sign}${chg}%)</span></div>`;
    const cx = x(idx);
    tip.style.left = cx > W / 2 ? `${cx - 140}px` : `${cx + 10}px`;
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
  const H = 80;
  const pad = { top: 4, right: 12, bottom: 2, left: 52 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;
  const n = candles.length;

  const maxVol = Math.max(...candles.map(c => c.v)) || 1;
  const gap = cW / n;
  const barW = Math.max(1, gap * 0.7);
  const x = i => pad.left + gap * i + gap / 2;

  let bars = '';
  candles.forEach((c, i) => {
    const h = (c.v / maxVol) * cH;
    const isUp = c.c >= c.o;
    const color = isUp ? 'rgba(16,185,129,0.5)' : 'rgba(239,68,68,0.5)';
    bars += `<rect x="${(x(i) - barW / 2).toFixed(1)}" y="${(pad.top + cH - h).toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" fill="${color}" rx="0.5"/>`;
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
