// ── 섹터 경기국면 탭 JS ──

// ── Lucide SVG paths for phase icons ──
const PHASE_ICON_PATHS = {
  trendingUp: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  rocket: '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
  trendingDown: '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/><polyline points="16 17 22 17 22 11"/>',
  snowflake: '<line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/><path d="m20 16-4-4 4-4"/><path d="m4 8 4 4-4 4"/><path d="m16 4-4 4-4-4"/><path d="m8 20 4-4 4 4"/>',
};
const PHASE_ICON_MAP = { '회복': 'trendingUp', '확장': 'rocket', '둔화': 'trendingDown', '침체': 'snowflake' };
const PHASE_SOFT_BG = {
  '회복': 'rgba(76,175,80,0.1)',
  '확장': 'rgba(255,193,7,0.1)',
  '둔화': 'rgba(255,152,0,0.1)',
  '침체': 'rgba(33,150,243,0.1)',
};

function phaseIcon(phase, size, sw) {
  const name = PHASE_ICON_MAP[phase];
  const path = PHASE_ICON_PATHS[name] || '';
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw || 2}" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

const PHASE_COLORS = {
  '회복': '#4CAF50',
  '확장': '#FFC107',
  '둔화': '#FF9800',
  '침체': '#2196F3',
};
const PHASE_GAP_POS = { '회복': 12, '확장': 37, '둔화': 63, '침체': 88 };
// PHASE_SUB는 i18n에서 동적 조회 (tPhaseSub 함수 사용)

// region 분기 helper — region.js 의 getRegion() 재사용 (없으면 'us' fallback)
function _isKr() {
  return (typeof window.getRegion === 'function') && window.getRegion() === 'kr';
}

// region 별 거시 키 세트 (US 10 / KR 14)
const _MACRO_KEYS_US = ['pmi','yield_spread','anfci','icsa_yoy','permit_yoy','real_retail_yoy','capex_yoy','real_income_yoy','pmi_chg3m','capex_yoy_chg3m'];
const _MACRO_KEYS_KR = ['kr_indpro_yoy','kr_yield_spread','kr_credit_spread','kr_unemp_yoy','kr_unemp_rate','kr_permit_yoy','kr_retail_yoy','kr_capex_yoy','kr_income_yoy','kr_cpi_yoy','kr_gdp_yoy','kr_m2_yoy','kr_indpro_chg3m','kr_capex_yoy_chg3m'];

// region 별 sector ticker 세트 (US 10 SPDR / KR 10 KODEX·TIGER)
const _SECTOR_KEYS_US = ['XLF','XLE','XLK','XLV','XLB','XLP','XLU','XLI','XLRE','SOXX'];
const _SECTOR_KEYS_KR = ['139260','091160','300610','091170','139250','266420','091180','117680','341850','227560'];

// 매크로 라벨 (i18n 동적 조회) — region 분기
function getMacroLabels() {
  const keys = _isKr() ? _MACRO_KEYS_KR : _MACRO_KEYS_US;
  const obj = {};
  keys.forEach(k => { obj[k] = t('macro.' + k); });
  return obj;
}

// 섹터 라벨 (i18n 동적 조회) — region 분기
function getSectorLabels() {
  const keys = _isKr() ? _SECTOR_KEYS_KR : _SECTOR_KEYS_US;
  const obj = {};
  keys.forEach(k => { obj[k] = t('sector.' + k); });
  return obj;
}

function signStr(v) { return v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2); }

function heatColor(val) {                          // 히트맵 색상 계산
  if (val > 0) {
    const r = Math.min(val / 4, 1);                // 양수: 초록 강도
    const g = Math.round(200 + 55 * (1 - r));
    return `rgba(76, ${g}, 80, ${0.15 + r * 0.55})`;
  } else {
    const r = Math.min(Math.abs(val) / 3, 1);     // 음수: 빨강 강도
    return `rgba(255, 59, 48, ${0.1 + r * 0.5})`;
  }
}

async function loadSectorCycle() {
  const res = await fetch('/api/sector-cycle/current');
  const d   = await res.json();
  if (!d) return;

  // ── 현재 경기국면 갭 바 ──
  const phaseEl = document.getElementById('sc-phase-card');
  const phases = ['회복', '확장', '둔화', '침체'];    // API 한글 키 (내부 조회용)
  const color = PHASE_COLORS[d.phase_name] || '#999';
  const pos   = PHASE_GAP_POS[d.phase_name] ?? 50;
  const sub   = tPhaseSub(d.phase_name);             // 국면 설명 (i18n)
  const softBg = PHASE_SOFT_BG[d.phase_name] || 'rgba(0,0,0,0.05)';
  phaseEl.innerHTML = `
    <div class="sc-phase-status">
      <div class="sc-phase-icon-box" style="background:${softBg};color:${color}">
        ${phaseIcon(d.phase_name, 26, 2.2)}
      </div>
      <div>
        <div class="sc-phase-name">${tPhase(d.phase_name)}</div>
        <div class="sc-phase-date">${d.date} ${t('cs.asOf')}</div>
      </div>
    </div>
    <div class="sc-phase-sub">${sub}</div>
    <div class="sc-phase-gap">
      <div class="sc-phase-gap-labels">
        <span>${tPhase('회복')}</span>
        <span>${tPhase('확장')}</span>
        <span>${tPhase('둔화')}</span>
        <span>${tPhase('침체')}</span>
      </div>
      <div class="sc-phase-gap-track">
        <div class="sc-phase-gap-fill" style="width:${pos}%;background:${color}"></div>
        <div class="sc-phase-gap-dot" style="left:${pos}%;border-color:${color}"></div>
      </div>
    </div>`;

  // ── TOP3 섹터 (숫자 뱃지) ──
  const topEl  = document.getElementById('sc-top3');
  const topSub = document.getElementById('sc-top-sub');
  topSub.innerHTML = `${phaseIcon(d.phase_name, 14, 2)} ${tPhase(d.phase_name)} ${t('sector.phase')}`;
  const perf = d.phase_sector_perf[d.phase_name] || {};
  const isKr = _isKr();
  topEl.innerHTML = (d.top3_sectors || []).map((s, i) => {
    const ret = perf[s] || 0;
    const label = getSectorLabels()[s] || s;
    const rankCls = i === 0 ? 'rank-1' : (i === 1 ? 'rank-2' : 'rank-3');
    // KR: ticker(6자리 숫자) 무의미 → 한글 이름이 메인. US: ticker(XLK 등) 가 메인.
    const labelHtml = isKr
      ? `<span class="sc-top-name" style="font-weight:700;flex:1">${label}</span>`
      : `<span class="sc-top-ticker">${s}</span><span class="sc-top-name">${label}</span>`;
    return `
      <div class="sc-top-item">
        <div class="sc-rank-badge ${rankCls}">${i + 1}</div>
        ${labelHtml}
        <span class="sc-top-ret" style="color:${ret >= 0 ? 'var(--green)' : 'var(--red)'}">${signStr(ret)}%</span>
      </div>`;
  }).join('');
  // Staggered row animation for top3
  topEl.querySelectorAll('.sc-top-item').forEach((item, i) => {
    item.style.setProperty('--row-delay', `${i * 0.07}s`);
    setTimeout(() => item.classList.add('row-visible'), 50);
  });

  // ── 국면×섹터 히트맵 ──
  const hmEl = document.getElementById('sc-heatmap');
  const sectors = Object.keys(getSectorLabels());
  let hmHTML = '<div class="sc-hm-table"><div class="sc-hm-row sc-hm-header"><div class="sc-hm-cell sc-hm-corner"></div>';
  const _sLabels = getSectorLabels();                // 섹터 라벨 캐시
  // KR: ticker 숨기고 한글 이름만 (6자리 숫자가 의미 없음). US: ticker + 영문 이름.
  sectors.forEach(s => {
    if (isKr) {
      hmHTML += `<div class="sc-hm-cell sc-hm-col"><span class="sc-hm-col-kr">${_sLabels[s]}</span></div>`;
    } else {
      hmHTML += `<div class="sc-hm-cell sc-hm-col">${s}<br><span class="sc-hm-col-kr">${_sLabels[s]}</span></div>`;
    }
  });
  hmHTML += '</div>';
  phases.forEach(ph => {
    const row = d.phase_sector_perf[ph] || {};
    const phColor = PHASE_COLORS[ph] || '#999';
    const phSoftBg = PHASE_SOFT_BG[ph] || 'rgba(0,0,0,0.03)';
    hmHTML += `<div class="sc-hm-row"><div class="sc-hm-cell sc-hm-rowlabel"><span class="sc-icon-sm" style="background:${phSoftBg};color:${phColor};margin-right:4px">${phaseIcon(ph, 15, 2)}</span>${tPhase(ph)}</div>`;
    sectors.forEach(s => {
      const v = row[s] ?? 0;
      hmHTML += `<div class="sc-hm-cell sc-hm-val" style="background:${heatColor(v)}">${v.toFixed(1)}</div>`;
    });
    hmHTML += '</div>';
  });
  hmHTML += '</div>';
  hmEl.innerHTML = hmHTML;

  // ── 경기국면 상세페이지 데이터 캐시 ──
  window._sectorData = d;

  // ── 경기국면 카드 클릭 → 상세페이지 ──
  const phaseCard = document.getElementById('sc-phase-card');
  if (phaseCard && !phaseCard.classList.contains('card-tappable')) {
    // 터치 가능 힌트 + 클릭 이벤트 등록
    phaseCard.classList.add('card-tappable');
    phaseCard.addEventListener('click', () => openDetail(t('sector.detailTitle'), renderSectorDetail));
  }

  // ── 보유 종목 성과 ──
  const holdEl = document.getElementById('sc-holdings');
  const holdPerf = d.phase_holding_perf || {};
  let userHoldings;
  try {
    userHoldings = JSON.parse(localStorage.getItem('holdings') || 'null');
  } catch { userHoldings = null; }

  if (!userHoldings || userHoldings.length === 0) {
    holdEl.innerHTML = `<div style="text-align:center;padding:16px;color:var(--sub);font-size:13px">${t('sector.holdNoSetup')}</div>`;
  } else {
    const currentPhase = d.phase_name;
    const row = holdPerf[currentPhase] || {};
    const holdTickers = userHoldings.filter(tk => row[tk] !== undefined);

    if (holdTickers.length === 0) {
      holdEl.innerHTML = `<div style="text-align:center;padding:16px;color:var(--sub);font-size:13px">${t('sector.holdNoData')}</div>`;
    } else {
      let maxAbs = 0;
      holdTickers.forEach(tk => { maxAbs = Math.max(maxAbs, Math.abs(row[tk] || 0)); });
      if (maxAbs < 0.1) maxAbs = 1;

      const phSoftBg = PHASE_SOFT_BG[currentPhase] || 'rgba(0,0,0,0.03)';
      const phColor = PHASE_COLORS[currentPhase] || '#999';
      let holdHTML = `<div class="sc-hold-phase-name"><span class="sc-icon-sm" style="background:${phSoftBg};color:${phColor};margin-right:4px">${phaseIcon(currentPhase, 15, 2)}</span>${tPhase(currentPhase)} ${t('sector.phaseAvgReturn')}</div>`;
      holdHTML += '<div class="sc-hold-items">';
      holdTickers.forEach(tk => {
        const v = row[tk] || 0;
        const w = Math.round(Math.abs(v) / maxAbs * 100);
        const barColor = v >= 0 ? 'var(--green)' : 'var(--red)';
        holdHTML += `<div class="sc-hold-bar-row">
          <span class="sc-hold-ticker">${tk}</span>
          <div class="sc-hold-bar-track"><div class="sc-hold-bar-fill" style="width:${w}%;background:${barColor}"></div></div>
          <span class="sc-hold-ret" style="color:${barColor}">${signStr(v)}%</span>
        </div>`;
      });
      holdHTML += '</div>';
      holdEl.innerHTML = holdHTML;
      // Staggered row animation for holdings bars
      holdEl.querySelectorAll('.sc-hold-bar-row').forEach((row, i) => {
        row.style.setProperty('--row-delay', `${i * 0.07}s`);
        setTimeout(() => row.classList.add('row-visible'), 50);
      });
    }
  }
}


// ── 매크로 지표별 양호 기준 (높을수록 좋은지 여부) ── US + KR 통합
const MACRO_GOOD_HIGH = {
  // US 10
  pmi: true, yield_spread: true, permit_yoy: true,
  real_retail_yoy: true, capex_yoy: true, real_income_yoy: true,
  pmi_chg3m: true, capex_yoy_chg3m: true,
  anfci: false, icsa_yoy: false,
  // KR 14
  kr_indpro_yoy: true, kr_yield_spread: true,
  kr_permit_yoy: true, kr_retail_yoy: true, kr_capex_yoy: true,
  kr_income_yoy: true, kr_m2_yoy: true, kr_gdp_yoy: true,
  kr_indpro_chg3m: true, kr_capex_yoy_chg3m: true,
  kr_credit_spread: false, kr_unemp_yoy: false, kr_unemp_rate: false,
  kr_cpi_yoy: false,   // CPI 는 BOK 타깃 2% 초과 시 긴축 압력 → 낮을수록 양호
};
// ── 매크로 지표별 중립값 기준 ──
const MACRO_NEUTRAL = {
  // US
  pmi: 50, yield_spread: 0, anfci: 0, icsa_yoy: 0,
  permit_yoy: 0, real_retail_yoy: 0, capex_yoy: 0, real_income_yoy: 0,
  pmi_chg3m: 0, capex_yoy_chg3m: 0,
  // KR — CPI 는 BOK 타깃 2.0%, 실업률 은 KR 평균 3.0% 기준
  kr_indpro_yoy: 0, kr_yield_spread: 0, kr_credit_spread: 0,
  kr_unemp_yoy: 0, kr_unemp_rate: 3.0,
  kr_permit_yoy: 0, kr_retail_yoy: 0, kr_capex_yoy: 0, kr_income_yoy: 0,
  kr_cpi_yoy: 2.0, kr_gdp_yoy: 0, kr_m2_yoy: 0,
  kr_indpro_chg3m: 0, kr_capex_yoy_chg3m: 0,
};

// ── 매크로 지표 설명 (상세 페이지에서 표시) ──
// 매크로 설명 (i18n 동적 조회) — region 분기
function getMacroDesc() {
  const keys = _isKr() ? _MACRO_KEYS_KR : _MACRO_KEYS_US;
  const obj = {};
  keys.forEach(k => { obj[k] = t('macroDesc.' + k); });
  return obj;
}

// 지표별 표시 형식 — region 무관하게 키 자체로 분기.
// raw level (PMI 50, ANFCI -1.0, 실업률 3.0, yield spread 0.5%) → toFixed
// YoY% / 변화량 → signStr + '%'
const _RAW_LEVEL_KEYS = new Set([
  'pmi',           // US PMI level (50 기준)
  'anfci',         // US ANFCI level (0 기준, 음수=완화)
  'kr_unemp_rate', // KR 실업률 raw
  'kr_yield_spread', 'kr_credit_spread',  // % 차이 (raw)
  'yield_spread',  // US 동일
]);
function formatMacroValue(key, val) {
  if (val == null || isNaN(val)) return '--';
  if (key === 'pmi') return val.toFixed(1);
  if (_RAW_LEVEL_KEYS.has(key)) return val.toFixed(2);
  return signStr(val) + '%';
}


// ── 거시경제 상세페이지 렌더 ──
function renderSectorDetail(body) {
  // 캐시된 섹터 데이터 확인
  const d = window._sectorData;
  if (!d) { body.innerHTML = `<p style="color:var(--sub)">${t('detail.noData')}</p>`; return; }

  // 현재 경기국면 색상·아이콘 설정
  const color = PHASE_COLORS[d.phase_name] || '#999';
  const softBg = PHASE_SOFT_BG[d.phase_name] || 'rgba(0,0,0,0.05)';
  const sub = tPhaseSub(d.phase_name);                // 국면 설명 (i18n)
  const pos = PHASE_GAP_POS[d.phase_name] ?? 50;

  // ── 1) 현재 국면 요약 ──
  body.innerHTML = `<div style="text-align:center;margin-bottom:20px">
    <div style="display:inline-flex;align-items:center;justify-content:center;gap:8px;
                background:${softBg};color:${color};padding:10px 20px;border-radius:14px;margin-bottom:8px">
      ${phaseIcon(d.phase_name, 28, 2.2)}
      <span style="font-size:24px;font-weight:800">${tPhase(d.phase_name)}</span>
    </div>
    <div style="font-size:13px;color:var(--sub);margin-top:6px">${sub}</div>
    <div style="font-size:11px;color:var(--sub2);margin-top:2px">${d.date} ${t('cs.asOf')}</div>
  </div>`;

  // ── 2) 경기국면 갭 바 ──
  body.innerHTML += `<div style="margin-bottom:24px;padding:0 8px">
    <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--sub);margin-bottom:6px">
      <span>${tPhase('회복')}</span><span>${tPhase('확장')}</span><span>${tPhase('둔화')}</span><span>${tPhase('침체')}</span>
    </div>
    <div style="position:relative;height:6px;background:var(--bg2);border-radius:3px">
      <div style="position:absolute;left:0;top:0;height:100%;width:${pos}%;background:${color};border-radius:3px;transition:width 0.6s"></div>
      <div style="position:absolute;top:50%;left:${pos}%;transform:translate(-50%,-50%);width:14px;height:14px;
                  border-radius:50%;background:var(--card);border:3px solid ${color};box-shadow:0 0 6px ${color}40"></div>
    </div>
  </div>`;

  // ── 3) 매크로 스냅샷 ──
  const snap = d.macro_snapshot || {};
  // 스냅샷 데이터가 있는 경우에만 렌더링
  const macroKeys = Object.keys(getMacroLabels()).filter(k => snap[k] !== undefined);
  if (macroKeys.length > 0) {
    body.innerHTML += `<div class="feat-section-title">${t('sector.macroSnapshot')}</div>`;
    // 그리드 레이아웃으로 매크로 지표 표시
    let macroHtml = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:20px">';
    macroKeys.forEach(key => {
      // 지표 값 추출
      const val = snap[key];
      const label = getMacroLabels()[key];
      const display = formatMacroValue(key, val);
      // 중립 기준 대비 양호/불량 판단
      const neutral = MACRO_NEUTRAL[key] ?? 0;
      const goodHigh = MACRO_GOOD_HIGH[key] ?? true;
      const isGood = goodHigh ? val >= neutral : val <= neutral;
      // 양호면 초록 화살표, 불량이면 빨간 화살표
      const arrow = isGood ? '▲' : '▼';
      const arrowColor = isGood ? '#10B981' : '#EF4444';
      macroHtml += `<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;
                                background:var(--card);border-radius:10px;box-shadow:var(--shadow)">
        <span style="font-size:11px;color:var(--sub);font-weight:500">${label}</span>
        <span style="font-size:12px;font-weight:700">${display} <span style="color:${arrowColor};font-size:10px">${arrow}</span></span>
      </div>`;
    });
    macroHtml += '</div>';
    body.innerHTML += macroHtml;
  }

  // ── 3b) 매크로 10년 추세 차트 ──
  body.innerHTML += `<div class="feat-section-title">${t('sector.macroTrend')}</div>`;
  body.innerHTML += '<div id="macro-trend-charts" style="margin-bottom:20px"><div style="text-align:center;padding:16px"><div class="loading-spinner sm"></div></div></div>';

  fetch('/api/sector-cycle/macro-history')
    .then(r => r.json())
    .then(history => {
      const container = document.getElementById('macro-trend-charts');
      if (!history || history.length < 2) {
        container.innerHTML = `<div style="text-align:center;font-size:12px;color:var(--sub);padding:12px">${t('detail.noData')}</div>`;
        return;
      }
      // 8개 핵심 spark line — region 별 다른 키 세트
      const indicators = _isKr()
        ? ['kr_indpro_yoy','kr_yield_spread','kr_credit_spread','kr_unemp_rate',
           'kr_permit_yoy','kr_retail_yoy','kr_capex_yoy','kr_cpi_yoy']
        : ['pmi','yield_spread','anfci','icsa_yoy','permit_yoy','real_retail_yoy','capex_yoy','real_income_yoy'];
      const colors = ['#4CAF50','#2196F3','#FF9800','#EF4444','#9C27B0','#00BCD4','#FF5722','#607D8B'];
      let html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">';
      indicators.forEach((key, idx) => {
        const label = getMacroLabels()[key] || key;
        const values = history.map(r => r[key]);
        const latest = values.filter(v => v != null).slice(-1)[0];
        const display = formatMacroValue(key, latest);
        html += `<div style="padding:10px;background:var(--card);border-radius:10px;box-shadow:var(--shadow)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-size:10px;color:var(--sub);font-weight:600">${label}</span>
            <span style="font-size:11px;font-weight:700">${display}</span>
          </div>
          <div id="spark-${key}"></div>
        </div>`;
      });
      html += '</div>';
      container.innerHTML = html;
      indicators.forEach((key, idx) => {
        const el = document.getElementById('spark-' + key);
        if (el) _renderSparkline(el, history.map(r => r[key]), colors[idx]);
      });
    })
    .catch(() => {
      const c = document.getElementById('macro-trend-charts');
      if (c) c.innerHTML = '';
    });

  // ── 4) 매크로 지표 설명 ──
  if (macroKeys.length > 0) {
    body.innerHTML += `<div class="feat-section-title">${t('sector.macroDesc')}</div>`;
    let descHtml = '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:20px">';
    macroKeys.forEach(key => {
      const label = getMacroLabels()[key];
      const desc = getMacroDesc()[key] || '';
      descHtml += `<div style="padding:10px 12px;background:var(--card);border-radius:10px;box-shadow:var(--shadow)">
        <div style="font-size:12px;font-weight:700;color:var(--text);margin-bottom:2px">${label}</div>
        <div style="font-size:11px;color:var(--sub);line-height:1.5">${desc}</div>
      </div>`;
    });
    descHtml += '</div>';
    body.innerHTML += descHtml;
  }

  // ── 5) 국면별 섹터 히트맵 ──
  const phases = ['회복', '확장', '둔화', '침체'];
  const sectors = Object.keys(getSectorLabels());
  body.innerHTML += `<div class="feat-section-title">${t('sector.phasePerf')}</div>`;
  // 각 국면에 대해 가로 바 차트 렌더링
  let hmHtml = '<div style="margin-bottom:20px">';
  phases.forEach(ph => {
    const row = d.phase_sector_perf[ph] || {};
    const phColor = PHASE_COLORS[ph] || '#999';
    const phSoftBg = PHASE_SOFT_BG[ph] || 'rgba(0,0,0,0.03)';
    // 해당 국면의 최대 절대값 계산 (바 너비 비율용)
    let phMax = 0;
    sectors.forEach(s => { phMax = Math.max(phMax, Math.abs(row[s] || 0)); });
    if (phMax < 0.1) phMax = 1;

    // 국면 헤더
    hmHtml += `<div style="margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px">
        <span style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;
                      border-radius:6px;background:${phSoftBg};color:${phColor}">${phaseIcon(ph, 15, 2)}</span>
        <span style="font-size:13px;font-weight:700;color:var(--text)">${tPhase(ph)}</span>
        ${ph === d.phase_name ? `<span style="font-size:10px;color:${phColor};font-weight:600;background:${phSoftBg};padding:2px 8px;border-radius:8px">${t('sector.current')}</span>` : ''}
      </div>`;
    // 각 섹터별 바
    sectors.forEach(s => {
      const v = row[s] ?? 0;
      // 바 너비 퍼센트 계산
      const w = Math.round(Math.abs(v) / phMax * 100);
      const barColor = v >= 0 ? '#10B981' : '#EF4444';
      hmHtml += `<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
        <span style="font-size:10px;color:var(--sub);width:36px;text-align:right;flex-shrink:0">${s}</span>
        <div style="flex:1;height:12px;background:var(--bg2);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${w}%;background:${barColor};border-radius:3px;transition:width 0.4s"></div>
        </div>
        <span style="font-size:10px;font-weight:600;color:${barColor};width:48px;text-align:right">${signStr(v)}%</span>
      </div>`;
    });
    hmHtml += '</div>';
  });
  hmHtml += '</div>';
  body.innerHTML += hmHtml;

  // ── 6) TOP3 추천 섹터 ──
  if (d.top3_sectors && d.top3_sectors.length > 0) {
    const perf = d.phase_sector_perf[d.phase_name] || {};
    body.innerHTML += `<div class="feat-section-title">${t('sector.topSectors')}</div>`;
    let topHtml = '<div style="display:flex;flex-direction:column;gap:8px;margin-bottom:20px">';
    d.top3_sectors.forEach((s, i) => {
      const ret = perf[s] || 0;
      const label = getSectorLabels()[s] || s;
      // 순위별 배경색 (1위: 금, 2위: 은, 3위: 동)
      const rankColors = ['#FFD700', '#C0C0C0', '#CD7F32'];
      topHtml += `<div style="display:flex;align-items:center;gap:10px;padding:12px 14px;
                              background:var(--card);border-radius:12px;box-shadow:var(--shadow)">
        <div style="width:28px;height:28px;border-radius:50%;background:${rankColors[i]};color:#fff;
                    display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:800">${i + 1}</div>
        <div style="flex:1">
          <div style="font-size:13px;font-weight:700">${s} <span style="font-size:11px;color:var(--sub);font-weight:400">${label}</span></div>
        </div>
        <div style="font-size:14px;font-weight:800;color:${ret >= 0 ? '#10B981' : '#EF4444'}">${signStr(ret)}%</div>
      </div>`;
    });
    topHtml += '</div>';
    body.innerHTML += topHtml;
  }
}

// ── SVG 스파크라인 렌더링 ──
function _renderSparkline(container, values, color) {
  const W = 160, H = 48;
  const pad = 4;
  const filtered = values.map((v, i) => v != null ? { i, v } : null).filter(Boolean);
  if (filtered.length < 2) { container.innerHTML = '<span style="font-size:10px;color:var(--sub2)">N/A</span>'; return; }
  const vals = filtered.map(d => d.v);
  const yMin = Math.min(...vals), yMax = Math.max(...vals);
  const yRange = yMax - yMin || 1;
  const x = idx => pad + (idx / (values.length - 1)) * (W - pad * 2);
  const y = v => pad + (1 - (v - yMin) / yRange) * (H - pad * 2);
  const path = filtered.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(d.i).toFixed(1)},${y(d.v).toFixed(1)}`).join(' ');
  const last = filtered[filtered.length - 1];
  container.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
    <path d="${path}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round"/>
    <circle cx="${x(last.i).toFixed(1)}" cy="${y(last.v).toFixed(1)}" r="2.5" fill="${color}"/>
  </svg>`;
}
