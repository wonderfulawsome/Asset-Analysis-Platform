/* 시장 이상 탐지 (Anomaly Detection) — 신호 탭 교체.
 *
 * /api/anomaly/current + /api/anomaly/history 를 받아 4개 카드 렌더:
 *   1. 메인 점수 (D² + percentile + 라벨)
 *   2. 10년 D² 시계열 SVG 차트
 *   3. 무엇이 이상한가 (top contributors 막대)
 *   4. 과거 같은 패턴 (k-NN 시점 리스트)
 *
 * 자문 리스크 차단 — descriptive 표현만:
 *   "현재 좌표는 historical 분포에서 X 위치", "비슷했던 과거 시점", 미래 단언 0.
 */
(function() {
  'use strict';

  const FEATURE_LABELS_KO = {
    fundamental_gap: '펀더멘털 괴리',
    erp_zscore:      '주식위험프리미엄',
    residual_corr:   '잔차 동조화',
    dispersion:      '종목 분산도',
    amihud:          '유동성 충격',
    vix_term:        'VIX 기간구조',
    hy_spread:       '하이일드 스프레드',
    realized_vol:    '실현 변동성',
    yield_curve:     '장단기 금리차',
    vix_abs:         'VIX 절대수준',
  };
  const FEATURE_LABELS_EN = {
    fundamental_gap: 'Fundamental Gap',
    erp_zscore:      'ERP Z-Score',
    residual_corr:   'Residual Correlation',
    dispersion:      'Stock Dispersion',
    amihud:          'Liquidity Impact',
    vix_term:        'VIX Term Structure',
    hy_spread:       'High-Yield Spread',
    realized_vol:    'Realized Volatility',
    yield_curve:     'Yield Curve',
    vix_abs:         'VIX Level',
  };

  function featLabel(name) {
    const isEn = (typeof window.t === 'function' && window.t('lang.code') === 'en');
    const map = isEn ? FEATURE_LABELS_EN : FEATURE_LABELS_KO;
    return map[name] || name;
  }

  // percentile_10y 기반 5단계 라벨 (descriptive only — 위험/안전 미사용)
  // "평소 이탈도" 프레이밍 — 강도만 표현, 방향성·매수매도 단어 없음.
  function percentileLabel(pct) {
    if (pct == null) return { text: '–', color: '#9ca3af', desc: '' };
    if (pct >= 95) return { text: '평소와 매우 다름', color: '#dc2626', desc: '10년 중 상위 5%' };
    if (pct >= 80) return { text: '평소와 다름', color: '#ef4444', desc: '10년 중 상위 20%' };
    if (pct >= 50) return { text: '평소보다 높은 편', color: '#f97316', desc: '중간 위쪽' };
    if (pct >= 20) return { text: '평소에 가까움', color: '#3b82f6', desc: '중간 아래쪽' };
    return { text: '평소에 매우 가까움', color: '#1d4ed8', desc: '10년 중 하위 20%' };
  }

  async function loadAnomaly() {
    const sumEl = document.getElementById('an-summary');
    const chartEl = document.getElementById('an-chart');
    const contribEl = document.getElementById('an-contribs');
    const knnEl = document.getElementById('an-knn');

    try {
      const [curRes, histRes] = await Promise.all([
        fetch('/api/anomaly/current?region=us'),
        fetch('/api/anomaly/history?days=2520&region=us'),
      ]);
      const cur = await curRes.json();
      const hist = await histRes.json();

      if (cur.empty || !cur.d2) {
        if (sumEl) sumEl.innerHTML = '<div style="color:#9ca3af;font-size:13px;">데이터 미수집. 다음 스케줄 사이클 후 표시됩니다.</div>';
        return;
      }

      renderSummary(sumEl, cur);
      renderChart(chartEl, hist.series || [], cur);
      renderContribs(contribEl, cur.top_contributors || []);
      renderKnn(knnEl, cur.knn_dates || []);
    } catch (e) {
      console.error('[anomaly] load fail', e);
      if (sumEl) sumEl.innerHTML = `<div style="color:#ef4444;font-size:13px;">로드 실패: ${e}</div>`;
    }
  }

  // ── 1. 메인 점수 카드 ──
  function renderSummary(el, d) {
    if (!el) return;
    const lbl = percentileLabel(d.percentile_10y);
    const pct10 = d.percentile_10y != null ? d.percentile_10y.toFixed(1) : '–';
    const pct90 = d.percentile_90d != null ? d.percentile_90d.toFixed(1) : '–';
    const pos = d.percentile_10y != null ? Math.max(0, Math.min(100, d.percentile_10y)) : 50;

    el.innerHTML = `
      <div style="text-align:center;padding:8px 0 16px">
        <div style="font-size:11px;color:var(--sub);letter-spacing:0.06em">과거 10년 기준 위치</div>
        <div style="font-size:36px;font-weight:800;color:${lbl.color};margin-top:6px">${pct10}<span style="font-size:18px;color:var(--sub);font-weight:600">%</span></div>
        <div style="font-size:13px;color:${lbl.color};font-weight:600;margin-top:2px">${lbl.text}</div>
        <div style="font-size:11px;color:var(--sub);margin-top:2px">${lbl.desc}</div>
      </div>

      <div style="position:relative;height:8px;border-radius:6px;background:linear-gradient(90deg,#1d4ed8,#9ca3af 50%,#dc2626);margin:0 8px 6px">
        <div style="position:absolute;top:-4px;left:${pos}%;transform:translateX(-50%);width:4px;height:16px;border-radius:2px;background:#fff;box-shadow:0 0 0 2px rgba(0,0,0,0.4)"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--sub);padding:0 8px">
        <span>평소에 가까움</span><span>보통</span><span>평소와 다름</span>
      </div>

      <div style="display:flex;gap:20px;justify-content:center;margin-top:18px;font-size:12px;color:var(--sub)">
        <div style="text-align:center">
          <div style="font-size:10px">평소와의 거리</div>
          <div style="font-size:18px;font-weight:700;color:var(--text)">${d.d2 != null ? d.d2.toFixed(2) : '–'}</div>
        </div>
        <div style="text-align:center">
          <div style="font-size:10px">최근 90일 기준 위치</div>
          <div style="font-size:18px;font-weight:700;color:var(--text)">${pct90}<span style="font-size:11px;color:var(--sub)">%</span></div>
        </div>
        <div style="text-align:center">
          <div style="font-size:10px">비교 일수</div>
          <div style="font-size:18px;font-weight:700;color:var(--text)">${d.n_history || '–'}</div>
        </div>
      </div>

      <div style="text-align:center;font-size:11px;color:var(--sub);margin-top:14px;line-height:1.6">
        여러 시장 지표를 한 번에 비교해, 현재 시장이 과거 10년의 평소 모습과 얼마나 다른지 계산합니다.<br/>
        과거 데이터 기준의 거리 측정이며, 미래 방향을 예측하지 않습니다.
      </div>
    `;
  }

  // ── 2. 10년 D² 시계열 SVG 차트 ──
  function renderChart(el, series, current) {
    if (!el || !series || series.length < 2) {
      if (el) el.innerHTML = '<div style="color:#9ca3af;font-size:13px;text-align:center;padding:40px">시계열 데이터 부족</div>';
      return;
    }
    const rawW = el.clientWidth - 2;
    const W = rawW > 50 ? rawW : (el.parentElement?.clientWidth || window.innerWidth - 40) - 2;
    const H = 200;
    const pad = { top: 12, right: 12, bottom: 28, left: 38 };
    const cW = W - pad.left - pad.right;
    const cH = H - pad.top - pad.bottom;

    const vals = series.map(s => s.d2 || 0).filter(v => v >= 0);
    // y 스케일은 log-like — D² 가 long-tail (대부분 < 30, 가끔 100+)
    // 단순 sqrt 변환으로 압축
    const yTransform = v => Math.sqrt(Math.max(v, 0));
    const yMin = 0;
    const yMaxRaw = Math.max(...vals);
    const yMax = yTransform(yMaxRaw);
    const yRange = yMax - yMin || 1;

    const x = i => pad.left + (i / (series.length - 1)) * cW;
    const y = v => pad.top + (1 - (yTransform(v) - yMin) / yRange) * cH;

    const path = series.map((s, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(s.d2 || 0).toFixed(1)}`).join(' ');
    const baseY = y(0).toFixed(1);
    const area = path + ` L${x(series.length - 1).toFixed(1)},${baseY} L${x(0).toFixed(1)},${baseY} Z`;

    // x축 라벨 — 연도만
    const yearTicks = [];
    let lastYear = '';
    series.forEach((s, i) => {
      const yr = s.date.slice(0, 4);
      if (yr !== lastYear) {
        yearTicks.push({ i, yr });
        lastYear = yr;
      }
    });
    const tickStep = Math.max(1, Math.ceil(yearTicks.length / 6));
    let xLabels = '';
    yearTicks.filter((_, k) => k % tickStep === 0).forEach(t => {
      xLabels += `<text class="chart-label" x="${x(t.i).toFixed(1)}" y="${H - 8}" text-anchor="middle" style="font-size:10px;fill:var(--sub)">${t.yr}</text>`;
    });

    // y축 라벨 (원래 D² 값 기준)
    let yLabels = '', gridLines = '';
    [0, 0.25, 0.5, 0.75, 1].forEach(frac => {
      const t = yMin + yRange * frac;
      const orig = t * t;
      const yPos = pad.top + (1 - frac) * cH;
      yLabels += `<text class="chart-label" x="${pad.left - 4}" y="${yPos.toFixed(1)}" text-anchor="end" dominant-baseline="middle" style="font-size:10px;fill:var(--sub)">${orig.toFixed(0)}</text>`;
      gridLines += `<line class="chart-grid-line" x1="${pad.left}" y1="${yPos.toFixed(1)}" x2="${W - pad.right}" y2="${yPos.toFixed(1)}" stroke="var(--border)" stroke-width="0.5" stroke-dasharray="2,3" opacity="0.5"/>`;
    });

    // 마지막 점 (오늘) 강조
    const lastIdx = series.length - 1;
    const lastVal = series[lastIdx].d2 || 0;
    const lastX = x(lastIdx).toFixed(1);
    const lastY = y(lastVal).toFixed(1);
    const lblColor = percentileLabel(current.percentile_10y).color;

    el.innerHTML = `
      <div style="display:flex;justify-content:center;gap:12px;margin-bottom:6px;font-size:11px;color:var(--sub)">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#3b82f6;vertical-align:middle"></span> 평소와의 거리 (시계열)</span>
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${lblColor};vertical-align:middle"></span> 오늘 (${(current.d2 || 0).toFixed(1)})</span>
      </div>
      <div class="line-chart-wrap">
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="an-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.35"/>
              <stop offset="100%" stop-color="#3b82f6" stop-opacity="0"/>
            </linearGradient>
          </defs>
          ${gridLines}
          <path d="${area}" fill="url(#an-grad)" stroke="none"/>
          <path d="${path}" fill="none" stroke="#3b82f6" stroke-width="1.2"/>
          <circle cx="${lastX}" cy="${lastY}" r="4" fill="${lblColor}" stroke="#fff" stroke-width="1.2"/>
          ${yLabels}
          ${xLabels}
        </svg>
      </div>
    `;
  }

  // ── 3. 무엇이 이상한가 (top contributors) ──
  function renderContribs(el, contribs) {
    if (!el) return;
    if (!contribs || !contribs.length) {
      el.innerHTML = '<div style="color:#9ca3af;font-size:13px;">기여 데이터 없음</div>';
      return;
    }
    const maxAbs = Math.max(...contribs.map(c => Math.abs(c.contribution || 0))) || 1;
    const rows = contribs.map((c, i) => {
      const v = c.contribution || 0;
      const pct = (Math.abs(v) / maxAbs) * 100;
      const isPos = v >= 0;
      const color = isPos ? '#dc2626' : '#3b82f6';
      const bar = `<div style="height:10px;width:${pct.toFixed(1)}%;background:${color};border-radius:5px;opacity:0.8"></div>`;
      return `
        <div style="display:grid;grid-template-columns:130px 1fr 60px;gap:10px;align-items:center;padding:6px 0">
          <div style="font-size:12px;color:var(--text)">${i+1}. ${featLabel(c.name)}</div>
          <div style="display:flex;justify-content:${isPos ? 'flex-start' : 'flex-end'}">
            <div style="width:${pct.toFixed(1)}%;height:10px;background:${color};border-radius:5px;opacity:0.85"></div>
          </div>
          <div style="font-size:11px;color:${color};font-weight:700;text-align:right">${isPos ? '+' : ''}${v.toFixed(2)}</div>
        </div>
      `;
    }).join('');
    el.innerHTML = `
      <div style="font-size:11px;color:var(--sub);margin-bottom:10px;line-height:1.5">
        오늘의 평소 이탈도 = 각 지표 기여의 합. 빨강은 평소보다 높음, 파랑은 평소보다 낮음. 절대값 큰 순.
      </div>
      ${rows}
    `;
  }

  // ── 4. 과거 같은 패턴 (k-NN) ──
  function renderKnn(el, knn) {
    if (!el) return;
    if (!knn || !knn.length) {
      el.innerHTML = '<div style="color:#9ca3af;font-size:13px;">유사 시점 없음</div>';
      return;
    }
    const rows = knn.map((k, i) => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:var(--card-bg-alt,rgba(255,255,255,0.02));border-radius:8px;margin-bottom:6px">
        <div>
          <div style="font-size:14px;font-weight:600;color:var(--text)">${k.date}</div>
          <div style="font-size:11px;color:var(--sub);margin-top:2px">평소 패턴 거리 ${k.distance != null ? k.distance.toFixed(2) : '–'}</div>
        </div>
        <div style="font-size:11px;color:var(--sub)">#${i+1} 가까움</div>
      </div>
    `).join('');
    el.innerHTML = `
      <div style="font-size:11px;color:var(--sub);margin-bottom:10px;line-height:1.5">
        오늘의 시장 지표 조합이 과거 어느 날과 가장 비슷했는지. 강도와 방향 모두 매칭. 최근 90일은 자명한 매칭이라 제외.
      </div>
      ${rows}
    `;
  }

  // expose
  window.loadAnomaly = loadAnomaly;
})();
