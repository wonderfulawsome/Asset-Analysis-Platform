/* 시장 평소 이탈도 (Anomaly Detection) — 신호 탭 교체.
 *
 * /api/anomaly/current + /api/anomaly/history 를 받아 3개 카드 렌더:
 *   1. 10년 평소 이탈도 추이 차트 (메인, 맨 위)
 *   2. 과거 같은 패턴 (k-NN + 시기별 시장 이벤트 라벨)
 *   3. 무엇이 평소와 다른가 (top contributors 막대)
 *
 * 자문 리스크 차단 — descriptive 표현만:
 *   "현재 좌표는 historical 분포에서 X 위치", "비슷했던 과거 시점", 미래 단언 0.
 *   k-NN 이벤트 라벨도 사실(사건)만 — 결과·해석 단어 배제.
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

  // ── 큐레이팅된 시장 이벤트 사전 (사실만, 해석·감정 단어 배제) ──
  // 마할라노비스 거리가 보통 큰 시점 위주. 날짜 범위 매칭으로 k-NN 카드에 라벨 표시.
  // 새 이벤트 추가 시: { from, to, label } 형식, label 은 사건 사실만 (예측·평가 X).
  const MARKET_EVENTS_US = [
    { from: '2015-08-11', to: '2015-09-04', label: '중국 위안화 평가절하·세계 증시 급락' },
    { from: '2016-01-04', to: '2016-02-12', label: '중국 증시 서킷브레이커·유가 급락' },
    { from: '2016-06-23', to: '2016-07-08', label: '브렉시트 국민투표 가결' },
    { from: '2016-11-08', to: '2016-11-30', label: '미 대선 (트럼프 당선)' },
    { from: '2018-02-02', to: '2018-02-15', label: 'VIX 폭등 (Volmageddon)' },
    { from: '2018-10-01', to: '2018-12-26', label: '미·중 무역갈등 격화·연준 매파' },
    { from: '2019-08-14', to: '2019-08-30', label: '미국 2년/10년 수익률 곡선 역전' },
    { from: '2020-02-24', to: '2020-04-30', label: '코로나19 팬데믹·NYSE 서킷브레이커 4회' },
    { from: '2020-11-09', to: '2020-11-13', label: '화이자 백신 임상 성공 발표' },
    { from: '2021-01-25', to: '2021-02-05', label: '게임스톱 short squeeze' },
    { from: '2021-02-22', to: '2021-04-30', label: '미국 국채금리 급등·재오픈 트레이드 (가치주 rotation)' },
    { from: '2021-05-01', to: '2021-06-15', label: '미국 CPI 4~5%·인플레이션 우려 본격화' },
    { from: '2022-01-03', to: '2022-01-25', label: '연준 매파 회의록·빅테크 조정' },
    { from: '2022-01-26', to: '2022-02-23', label: '연준 매파 회견·우크라이나 긴장 고조' },
    { from: '2022-02-24', to: '2022-03-25', label: '러시아 우크라이나 침공' },
    { from: '2022-06-10', to: '2022-06-24', label: '미국 CPI 9.1%·연준 자이언트스텝' },
    { from: '2022-09-13', to: '2022-10-21', label: '영국 미니예산 위기·연준 자이언트스텝' },
    { from: '2023-03-08', to: '2023-03-24', label: 'SVB·시그니처은행 파산·CS 위기' },
    { from: '2023-10-07', to: '2023-10-31', label: '이스라엘-하마스 전쟁 발발' },
    { from: '2024-04-12', to: '2024-04-22', label: '이란-이스라엘 직접 군사충돌' },
    { from: '2024-04-25', to: '2024-05-15', label: '미국 FOMC 매파 보합·4월 고용 부진 (금리 경로 불확실성)' },
    { from: '2024-08-02', to: '2024-08-09', label: '일본 캐리트레이드 청산·VIX 65 폭등' },
    { from: '2024-11-05', to: '2024-11-15', label: '미 대선 (트럼프 재선)' },
    { from: '2024-12-18', to: '2025-01-03', label: '12월 FOMC 매파 dot plot·연말 변동성' },
    { from: '2025-01-20', to: '2025-01-24', label: '트럼프 2기 취임' },
    { from: '2025-02-01', to: '2025-03-15', label: '미국, 중국·캐나다·멕시코 관세 부과' },
    { from: '2025-04-02', to: '2025-04-08', label: '미국 상호관세 발표 ("Liberation Day")' },
    { from: '2025-04-09', to: '2025-04-15', label: '상호관세 90일 유예 발표·증시 반등' },
    { from: '2025-06-13', to: '2025-06-24', label: '이스라엘-이란 12일 전쟁' },
    { from: '2025-08-01', to: '2025-08-15', label: '미국 상호관세 발효일' },
  ];

  // YYYY-MM-DD 문자열 비교로 충분 (lex 정렬 = 시간 정렬)
  function findEvent(dateStr) {
    if (!dateStr) return null;
    const d = dateStr.slice(0, 10);
    for (const ev of MARKET_EVENTS_US) {
      if (d >= ev.from && d <= ev.to) return ev.label;
    }
    return null;
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
    // an-summary 카드는 사용자 요청으로 제거됨 — sumEl 없음.
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
        const msg = '<div style="color:#9ca3af;font-size:13px;text-align:center;padding:20px">데이터 미수집. 다음 스케줄 사이클 후 표시됩니다.</div>';
        if (chartEl) chartEl.innerHTML = msg;
        return;
      }

      renderChart(chartEl, hist.series || [], cur);
      renderKnn(knnEl, cur.knn_dates || []);
      renderContribs(contribEl, cur.top_contributors || []);
    } catch (e) {
      console.error('[anomaly] load fail', e);
      if (chartEl) chartEl.innerHTML = `<div style="color:#ef4444;font-size:13px;">로드 실패: ${e}</div>`;
    }
  }

  // ── 1. 10년 D² 시계열 SVG 차트 (메인) ──
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
    // y 스케일 — D² 가 long-tail (대부분 < 30, 코로나 등 극단치 100+)
    // log1p (= log(1+x)) 압축: 0 입력 안전, 극단치 강하게 눌러 평시 변동 가시화
    const yTransform = v => Math.log1p(Math.max(v, 0));
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
      const orig = Math.expm1(t);
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
    const rows = knn.map((k, i) => {
      const event = findEvent(k.date);
      const eventHtml = event
        ? `<div style="font-size:12px;color:var(--text);margin-top:4px;line-height:1.45">📌 ${event}</div>`
        : `<div style="font-size:11px;color:var(--sub2,#6b7280);margin-top:4px;line-height:1.45;font-style:italic">기록된 시장 이벤트 없음</div>`;
      return `
        <div style="padding:12px 14px;background:var(--card-bg-alt,rgba(255,255,255,0.02));border-radius:10px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div style="font-size:14px;font-weight:700;color:var(--text)">${k.date}</div>
            <div style="font-size:11px;color:var(--sub)">#${i+1} 가까움 · 거리 ${k.distance != null ? k.distance.toFixed(2) : '–'}</div>
          </div>
          ${eventHtml}
        </div>
      `;
    }).join('');
    el.innerHTML = `
      <div style="font-size:11px;color:var(--sub);margin-bottom:10px;line-height:1.5">
        오늘의 시장 지표 조합이 과거 어느 날과 가장 비슷했는지. 강도와 방향 모두 매칭. 최근 90일은 자명한 매칭이라 제외.<br/>
        📌 = 그 시기 주요 시장 이벤트 (사실 기록만, 결과 해석 없음).
      </div>
      ${rows}
    `;
  }

  // expose
  window.loadAnomaly = loadAnomaly;
})();
