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
const PHASE_SUB = {
  '회복': '경기 저점을 지나 반등이 시작되는 구간',
  '확장': '경기가 활발하게 성장하는 구간',
  '둔화': '성장 속도가 줄어들기 시작하는 구간',
  '침체': '경기가 위축되고 수요가 감소하는 구간',
};

const MACRO_LABELS = {
  pmi:              'PMI',
  yield_spread:     '금리차 (10Y-3M)',
  anfci:            '금융환경 (ANFCI)',
  icsa_yoy:         '실업급여 YoY',
  permit_yoy:       '건축허가 YoY',
  real_retail_yoy:  '실질소매판매 YoY',
  capex_yoy:        '자본재주문 YoY',
  real_income_yoy:  '실질소득 YoY',
  pmi_chg3m:        'PMI 3개월변화',
  capex_yoy_chg3m:  '자본재 3개월변화',
};

const SECTOR_LABELS = {
  XLF:  '금융',
  XLE:  '에너지',
  XLK:  '기술',
  XLV:  '헬스케어',
  XLB:  '소재',
  XLP:  '필수소비재',
  XLU:  '유틸리티',
  XLI:  '산업재',
  XLRE: '부동산',
  SOXX: '반도체',
};

function signStr(v) { return v >= 0 ? `+${v.toFixed(2)}` : v.toFixed(2); }

function heatColor(val) {
  if (val > 0) {
    const t = Math.min(val / 4, 1);
    const g = Math.round(200 + 55 * (1 - t));
    return `rgba(76, ${g}, 80, ${0.15 + t * 0.55})`;
  } else {
    const t = Math.min(Math.abs(val) / 3, 1);
    return `rgba(255, 59, 48, ${0.1 + t * 0.5})`;
  }
}

async function loadSectorCycle() {
  const res = await fetch('/api/sector-cycle/current');
  const d   = await res.json();
  if (!d) return;

  // ── 현재 경기국면 갭 바 ──
  const phaseEl = document.getElementById('sc-phase-card');
  const phases = ['회복', '확장', '둔화', '침체'];
  const color = PHASE_COLORS[d.phase_name] || '#999';
  const pos   = PHASE_GAP_POS[d.phase_name] ?? 50;
  const sub   = PHASE_SUB[d.phase_name] || '';
  const softBg = PHASE_SOFT_BG[d.phase_name] || 'rgba(0,0,0,0.05)';
  phaseEl.innerHTML = `
    <div class="sc-phase-status">
      <div class="sc-phase-icon-box" style="background:${softBg};color:${color}">
        ${phaseIcon(d.phase_name, 26, 2.2)}
      </div>
      <div>
        <div class="sc-phase-name">${d.phase_name}</div>
        <div class="sc-phase-date">${d.date} 기준</div>
      </div>
    </div>
    <div class="sc-phase-sub">${sub}</div>
    <div class="sc-phase-gap">
      <div class="sc-phase-gap-labels">
        <span>회복</span>
        <span>확장</span>
        <span>둔화</span>
        <span>침체</span>
      </div>
      <div class="sc-phase-gap-track">
        <div class="sc-phase-gap-fill" style="width:${pos}%;background:${color}"></div>
        <div class="sc-phase-gap-dot" style="left:${pos}%;border-color:${color}"></div>
      </div>
    </div>`;

  // ── TOP3 섹터 (숫자 뱃지) ──
  const topEl  = document.getElementById('sc-top3');
  const topSub = document.getElementById('sc-top-sub');
  topSub.innerHTML = `${phaseIcon(d.phase_name, 14, 2)} ${d.phase_name} 국면`;
  const perf = d.phase_sector_perf[d.phase_name] || {};
  topEl.innerHTML = (d.top3_sectors || []).map((s, i) => {
    const ret = perf[s] || 0;
    const label = SECTOR_LABELS[s] || s;
    const rankCls = i === 0 ? 'rank-1' : (i === 1 ? 'rank-2' : 'rank-3');
    return `
      <div class="sc-top-item">
        <div class="sc-rank-badge ${rankCls}">${i + 1}</div>
        <span class="sc-top-ticker">${s}</span>
        <span class="sc-top-name">${label}</span>
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
  const sectors = Object.keys(SECTOR_LABELS);
  let hmHTML = '<div class="sc-hm-table"><div class="sc-hm-row sc-hm-header"><div class="sc-hm-cell sc-hm-corner"></div>';
  sectors.forEach(s => { hmHTML += `<div class="sc-hm-cell sc-hm-col">${s}<br><span class="sc-hm-col-kr">${SECTOR_LABELS[s]}</span></div>`; });
  hmHTML += '</div>';
  phases.forEach(ph => {
    const row = d.phase_sector_perf[ph] || {};
    const phColor = PHASE_COLORS[ph] || '#999';
    const phSoftBg = PHASE_SOFT_BG[ph] || 'rgba(0,0,0,0.03)';
    hmHTML += `<div class="sc-hm-row"><div class="sc-hm-cell sc-hm-rowlabel"><span class="sc-icon-sm" style="background:${phSoftBg};color:${phColor};margin-right:4px">${phaseIcon(ph, 15, 2)}</span>${ph}</div>`;
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
    phaseCard.addEventListener('click', () => openDetail('거시경제 상세', renderSectorDetail));
  }

  // ── 보유 종목 성과 ──
  const holdEl = document.getElementById('sc-holdings');
  const holdPerf = d.phase_holding_perf || {};
  let userHoldings;
  try {
    userHoldings = JSON.parse(localStorage.getItem('holdings') || 'null');
  } catch { userHoldings = null; }

  if (!userHoldings || userHoldings.length === 0) {
    holdEl.innerHTML = '<div style="text-align:center;padding:16px;color:var(--sub);font-size:13px">보유종목을 설정하면 현재 국면 성과를 확인할 수 있습니다</div>';
  } else {
    const currentPhase = d.phase_name;
    const row = holdPerf[currentPhase] || {};
    const holdTickers = userHoldings.filter(t => row[t] !== undefined);

    if (holdTickers.length === 0) {
      holdEl.innerHTML = '<div style="text-align:center;padding:16px;color:var(--sub);font-size:13px">현재 국면의 보유종목 데이터가 없습니다</div>';
    } else {
      let maxAbs = 0;
      holdTickers.forEach(t => { maxAbs = Math.max(maxAbs, Math.abs(row[t] || 0)); });
      if (maxAbs < 0.1) maxAbs = 1;

      const phSoftBg = PHASE_SOFT_BG[currentPhase] || 'rgba(0,0,0,0.03)';
      const phColor = PHASE_COLORS[currentPhase] || '#999';
      let holdHTML = `<div class="sc-hold-phase-name"><span class="sc-icon-sm" style="background:${phSoftBg};color:${phColor};margin-right:4px">${phaseIcon(currentPhase, 15, 2)}</span>${currentPhase} 국면 평균 수익률</div>`;
      holdHTML += '<div class="sc-hold-items">';
      holdTickers.forEach(t => {
        const v = row[t] || 0;
        const w = Math.round(Math.abs(v) / maxAbs * 100);
        const barColor = v >= 0 ? 'var(--green)' : 'var(--red)';
        holdHTML += `<div class="sc-hold-bar-row">
          <span class="sc-hold-ticker">${t}</span>
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


// ── 매크로 지표별 양호 기준 (높을수록 좋은지 여부) ──
const MACRO_GOOD_HIGH = {
  pmi: true, yield_spread: true, permit_yoy: true,
  real_retail_yoy: true, capex_yoy: true, real_income_yoy: true,
  pmi_chg3m: true, capex_yoy_chg3m: true,
  anfci: false, icsa_yoy: false,
};
// ── 매크로 지표별 중립값 기준 ──
const MACRO_NEUTRAL = {
  pmi: 50, yield_spread: 0, anfci: 0, icsa_yoy: 0,
  permit_yoy: 0, real_retail_yoy: 0, capex_yoy: 0, real_income_yoy: 0,
  pmi_chg3m: 0, capex_yoy_chg3m: 0,
};

// ── 매크로 지표 설명 (상세 페이지에서 표시) ──
const MACRO_DESC = {
  pmi:              '제조업 경기를 나타내는 구매관리자지수 (50 이상 확장)',
  yield_spread:     '장단기 금리차 (10년-3개월, 역전 시 침체 신호)',
  anfci:            '시카고 연준 금융환경지수 (음수=완화, 양수=긴축)',
  icsa_yoy:         '신규 실업급여 청구건수 전년비 변화율',
  permit_yoy:       '건축허가 전년비 변화율 (부동산 선행지표)',
  real_retail_yoy:  '실질 소매판매 전년비 변화율 (소비 지표)',
  capex_yoy:        '비국방 자본재 주문 전년비 변화율 (기업투자)',
  real_income_yoy:  '실질 개인소득 전년비 변화율',
  pmi_chg3m:        'PMI 3개월 변화량 (모멘텀)',
  capex_yoy_chg3m:  '자본재 주문 YoY 3개월 변화량',
};


// ── 거시경제 상세페이지 렌더 ──
function renderSectorDetail(body) {
  // 캐시된 섹터 데이터 확인
  const d = window._sectorData;
  if (!d) { body.innerHTML = '<p style="color:var(--sub)">데이터 없음</p>'; return; }

  // 현재 경기국면 색상·아이콘 설정
  const color = PHASE_COLORS[d.phase_name] || '#999';
  const softBg = PHASE_SOFT_BG[d.phase_name] || 'rgba(0,0,0,0.05)';
  const sub = PHASE_SUB[d.phase_name] || '';
  const pos = PHASE_GAP_POS[d.phase_name] ?? 50;

  // ── 1) 현재 국면 요약 ──
  body.innerHTML = `<div style="text-align:center;margin-bottom:20px">
    <div style="display:inline-flex;align-items:center;justify-content:center;gap:8px;
                background:${softBg};color:${color};padding:10px 20px;border-radius:14px;margin-bottom:8px">
      ${phaseIcon(d.phase_name, 28, 2.2)}
      <span style="font-size:24px;font-weight:800">${d.phase_name}</span>
    </div>
    <div style="font-size:13px;color:var(--sub);margin-top:6px">${sub}</div>
    <div style="font-size:11px;color:var(--sub2);margin-top:2px">${d.date} 기준</div>
  </div>`;

  // ── 2) 경기국면 갭 바 ──
  body.innerHTML += `<div style="margin-bottom:24px;padding:0 8px">
    <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--sub);margin-bottom:6px">
      <span>회복</span><span>확장</span><span>둔화</span><span>침체</span>
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
  const macroKeys = Object.keys(MACRO_LABELS).filter(k => snap[k] !== undefined);
  if (macroKeys.length > 0) {
    body.innerHTML += `<div class="feat-section-title">매크로 스냅샷</div>`;
    // 그리드 레이아웃으로 매크로 지표 표시
    let macroHtml = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:20px">';
    macroKeys.forEach(key => {
      // 지표 값 추출
      const val = snap[key];
      const label = MACRO_LABELS[key];
      // 표시 형식 결정 (PMI: 소수1자리, ANFCI: 소수2자리, 나머지: ±%형식)
      const display = key === 'pmi' ? val.toFixed(1)
                    : key === 'anfci' ? val.toFixed(2)
                    : `${signStr(val)}%`;
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

  // ── 4) 매크로 지표 설명 ──
  if (macroKeys.length > 0) {
    body.innerHTML += `<div class="feat-section-title">매크로 지표 설명</div>`;
    let descHtml = '<div style="display:flex;flex-direction:column;gap:6px;margin-bottom:20px">';
    macroKeys.forEach(key => {
      const label = MACRO_LABELS[key];
      const desc = MACRO_DESC[key] || '';
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
  const sectors = Object.keys(SECTOR_LABELS);
  body.innerHTML += `<div class="feat-section-title">국면별 섹터 수익률</div>`;
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
        <span style="font-size:13px;font-weight:700;color:var(--text)">${ph}</span>
        ${ph === d.phase_name ? '<span style="font-size:10px;color:' + phColor + ';font-weight:600;background:' + phSoftBg + ';padding:2px 8px;border-radius:8px">현재</span>' : ''}
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
    body.innerHTML += `<div class="feat-section-title">현재 국면 추천 섹터</div>`;
    let topHtml = '<div style="display:flex;flex-direction:column;gap:8px;margin-bottom:20px">';
    d.top3_sectors.forEach((s, i) => {
      const ret = perf[s] || 0;
      const label = SECTOR_LABELS[s] || s;
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
