/* 홈 뷰 라우터 + 데이터 로딩.
   - DOMContentLoaded 시 home-view 보이고 기존 tab-bar/scroll-wrap 숨김
   - 타일 클릭 → 탭 인덱스 매핑 → 기존 .tab.click() 트리거 + home-view 숨김
   - 섹터 신기능 2개는 모달 오버레이 (탭 시스템과 분리)
   - "← 홈" 버튼으로 home-view 복귀
*/
(function () {
  // 타일 → (action: 'tab' | 'sector-tab', target)
  // 'tab' 은 main.js 가 관리하는 5개 탭 (data-idx 매핑)
  // 'sector-tab' 은 home.js 가 직접 관리하는 신규 탭 (.scroll-wrap 안의 main.content id)
  const TILE_MAP = {
    'ai-chart':    { action: 'tab',        idx: 0 },
    'market':      { action: 'tab',        idx: 1 },
    'fundamental': { action: 'tab',        idx: 2 },
    'signal':      { action: 'tab',        idx: 3 },
    'macro':       { action: 'tab',        idx: 4 },
    'sector-val':       { action: 'sector-tab', id: 'tab-sector-val' },
    'sector-mom':       { action: 'sector-tab', id: 'tab-sector-mom' },
    'market-valuation': { action: 'sector-tab', id: 'tab-market-valuation' },
  };

  // 탭 바와 conveyor (.feed-section) 는 홈/탭 양쪽에서 항상 표시.
  // 홈 ↔ 탭 토글은 .scroll-wrap (탭 콘텐츠) 와 #home-view 두 가지만 swap.
  function showHome() {
    document.getElementById('home-view').style.display = '';
    const sw = document.querySelector('.scroll-wrap');
    if (sw) sw.style.display = 'none';
    document.getElementById('back-to-home').hidden = true;
    document.body.classList.remove('with-back');
    // 탭 active 표시 해제 — 홈으로 돌아왔으니 어떤 탭도 선택된 상태가 아님
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  }

  function showTab(idx) {
    document.getElementById('home-view').style.display = 'none';
    const sw = document.querySelector('.scroll-wrap');
    if (sw) sw.style.display = '';
    document.getElementById('back-to-home').hidden = false;
    document.body.classList.add('with-back');
    // main.js switchTab 은 TAB_IDS 5개만 토글하므로 sector-val/mom 은 직접 hide
    ['tab-sector-val', 'tab-sector-mom'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    // 기존 탭 트리거 — main.js 가 처리
    const tabBtn = document.querySelector(`.tab[data-idx="${idx}"]`);
    if (tabBtn) tabBtn.click();
    // 차트가 home active 상태에서 0 폭으로 그려졌을 가능성 → next tick 에 재렌더
    if (idx === 0) {
      setTimeout(() => {
        if (typeof loadCandleChart === 'function') loadCandleChart();
      }, 60);
    }
  }

  // 섹터 탭 (home.js 가 직접 관리). 다른 5개 탭과 같은 .scroll-wrap 안 main.content.
  function showSectorTab(id) {
    document.getElementById('home-view').style.display = 'none';
    const sw = document.querySelector('.scroll-wrap');
    if (sw) sw.style.display = '';
    document.getElementById('back-to-home').hidden = false;
    document.body.classList.add('with-back');
    history.pushState({ view: 'sector-tab', id: id }, '');     // 시스템 뒤로가기로 home 복귀
    // .scroll-wrap 안의 모든 main.content 를 숨기고 target 만 표시
    document.querySelectorAll('.scroll-wrap > main.content').forEach(el => {
      el.style.display = 'none';
    });
    const target = document.getElementById(id);
    if (target) {
      target.style.display = '';
      target.querySelectorAll('.fade-target').forEach(ft => ft.classList.add('visible'));
    }
    if (id === 'tab-sector-val') {
      loadSectorValuation();
      if (typeof window.loadAiExplain === 'function') window.loadAiExplain('sector-val');
    }
    if (id === 'tab-sector-mom') {
      loadSectorMomentum();
      if (typeof window.loadAiExplain === 'function') window.loadAiExplain('sector-mom');
    }
    if (id === 'tab-market-valuation') {
      loadMarketValuation();
    }
    // main.js 가 관리하는 .tab active 표시 해제 (탭 바는 안 보이지만 깔끔하게)
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  }

  // 5개 지수는 컨베이어(.feed-section) 가 main.js loadFeed() 로 채움 — 별도 정적 카드 불필요

  // AI 종합판단 카드
  async function loadAiCard() {
    try {
      const r = await fetch('/api/market-summary/ai-summary');
      const data = await r.json();
      const body = document.getElementById('home-ai-body');
      if (data.summary) {
        // 핵심 헤드라인 1줄만 (대시·콜론으로 끊어서 첫 의미 단위)
        const lines = data.summary.split('\n').filter(l => l.trim());
        const headline = (lines[0] || '').replace(/^[^\w가-힣]*/, '').slice(0, 60);
        body.textContent = headline;
      }
    } catch (e) { console.error('[home] AI 카드 로드 실패', e); }

    // 메타라인: 심리 / 간극 (surge-crash) / 국면 — 3 endpoint 병렬
    try {
      const [fg, cycle, today] = await Promise.all([
        fetch('/api/macro/fear-greed').then(r => r.json()).catch(() => null),
        fetch('/api/sector-cycle/current').then(r => r.json()).catch(() => null),
        fetch('/api/market-summary/today').then(r => r.json()).catch(() => null),
      ]);
      const meta = document.getElementById('home-ai-meta');
      const parts = [];
      if (fg && fg.score != null) {
        parts.push(`<span class="meta-item"><span class="meta-key">심리</span><span class="meta-val">${fg.rating || ''} ${Math.round(fg.score)}</span></span>`);
      }
      // surge - crash gap → 상승 신호 (초록) / 하락 신호 (빨강)
      if (today && today.crash_surge && today.crash_surge.gap != null) {
        const g = today.crash_surge.gap;
        const cls = g > 0 ? 'up' : (g < 0 ? 'down' : '');
        const label = g > 0 ? '상승 신호' : (g < 0 ? '하락 신호' : '신호');
        const sign = g > 0 ? '+' : '';
        parts.push(`<span class="meta-item"><span class="meta-key">${label}</span><span class="meta-val ${cls}">${sign}${g.toFixed(1)}</span></span>`);
      }
      if (cycle && cycle.phase_name) {
        parts.push(`<span class="meta-item"><span class="meta-key">국면</span><span class="meta-val">${cycle.phase_name}</span></span>`);
      }
      meta.innerHTML = parts.join('');
    } catch (e) { console.error('[home] AI 메타 로드 실패', e); }
  }

  // 섹터 밸류 히트맵 — z-score 절대값으로 색상 (양수=빨강 비쌈, 음수=파랑 쌈)
  async function loadSectorValuation() {
    const target = document.getElementById('sector-val-content');
    target.innerHTML = '<div class="loading-placeholder"><div class="loading-spinner sm"></div></div>';
    try {
      const r = await fetch('/api/sector-cycle/valuation');
      const data = await r.json();
      if (!data.valuations || !data.valuations.length) {
        target.innerHTML = '<div style="color:#9ca3af;font-size:13px;">데이터 미수집 (sector_valuation 테이블 비어있음). 다음 스케줄 사이클 후 표시됩니다.</div>';
        return;
      }
      const minN = data.hist_min_n ?? 5;
      const sampleCounts = data.valuations.map(v => v.hist_n ?? 0);
      const minSamples = Math.min(...sampleCounts);
      const phaseLine = data.phase_name
        ? `<div class="sv-phase">현재 국면: <strong>${data.phase_name}</strong></div>` : '';
      const histLine = minSamples < minN
        ? `<div class="sv-phase" style="color:#f59e0b;">⏳ 히스토리 누적 중 — 표본 ${minSamples}/${minN}점. ${minN}점 이상 쌓이면 각 ETF 의 historical 평균 대비 z-score 로 색상이 칠해집니다.</div>`
        : '';
      // fundamental_gap (per 컬럼에 저장됨) — 양수=가격이 EPS 보다 빨리 성장 (비싸짐)
      const rows = data.valuations.map(v => {
        const fgCol = colorByZ(v.per_z);
        const fgPct = v.per != null ? (v.per * 100).toFixed(1) + '%' : '-';
        const sign = v.per != null && v.per >= 0 ? '+' : '';
        return `
          <div class="sv-name">${v.sector_name} <span style="color:#9ca3af;font-size:10px;">${v.ticker}</span></div>
          <div class="sv-cell" style="background:${fgCol};">${sign}${fgPct}</div>`;
      }).join('');
      const sourceLine = data.as_of_date
        ? `<div class="sv-phase" style="font-size:11px;line-height:1.5;">Fundamental Gap = log(P_t/P_{t-12}) − log(EPS_t/EPS_{t-12}) = 12개월 가격 성장률 − 12개월 EPS 성장률. <strong style="color:#ef4444;">양수=가격이 EPS 보다 빨리</strong> (비싸짐) / <strong style="color:#3b82f6;">음수=EPS 가 가격보다 빨리</strong> (싸짐). as of <strong>${data.as_of_date}</strong>.</div>`
        : '';
      target.innerHTML = phaseLine + histLine + sourceLine + `
        <div class="sv-grid" style="grid-template-columns: 1fr auto;">
          <div class="sv-h">섹터</div>
          <div class="sv-h" style="text-align:right;">갭 (가격 − EPS)</div>
          ${rows}
        </div>`;
    } catch (e) {
      target.innerHTML = '<div style="color:#ef4444;">로드 실패: ' + e + '</div>';
    }
  }

  function colorByZ(z) {
    if (z == null) return 'rgba(75, 85, 99, 0.2)';
    // z 양수 = 평균보다 높음 = 비쌈 (빨강), 음수 = 쌈 (파랑)
    const a = Math.min(Math.abs(z) * 0.4, 0.7);
    if (z > 0)  return `rgba(220, 38, 38, ${a})`;
    if (z < 0)  return `rgba(37, 99, 235, ${a})`;
    return 'rgba(156, 163, 175, 0.2)';
  }

  // 섹터 모멘텀 랭킹 테이블 (1주일 수익률 기준 랭킹)
  async function loadSectorMomentum() {
    const target = document.getElementById('sector-mom-content');
    target.innerHTML = '<div class="loading-placeholder"><div class="loading-spinner sm"></div></div>';
    try {
      const r = await fetch('/api/sector-cycle/momentum');
      const data = await r.json();
      const fmt = v => (v != null ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '-');
      const colorOf = v => v == null ? '#9ca3af' : v >= 0 ? '#10b981' : '#ef4444';
      const rows = data.momentum.map(m => `
        <tr>
          <td>${escapeHtml(m.sector_name)}<br><span style="color:#9ca3af;font-size:10px;">${m.ticker}</span></td>
          <td class="num" style="color:${colorOf(m.return_1w)};">${fmt(m.return_1w)}</td>
          <td class="num" style="color:${colorOf(m.return_1m)};">${fmt(m.return_1m)}</td>
          <td class="num"><strong>${m.rank ?? '-'}</strong></td>
        </tr>`).join('');
      target.innerHTML = `
        <table class="sm-table">
          <thead><tr><th>섹터</th><th class="num">1주일</th><th class="num">1개월</th><th class="num">랭킹</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div style="margin-top:12px;font-size:11px;color:#9ca3af;line-height:1.5;">
          랭킹은 <strong>1주일 수익률</strong> 기준 (큰 게 1위). 단기 모멘텀 추적용.
        </div>`;
    } catch (e) {
      target.innerHTML = '<div style="color:#ef4444;">로드 실패: ' + e + '</div>';
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // 스플래시 종료 후 동작 (기존 main.js 의 스플래시 로직과 충돌 안 하게 약간 늦게)
  function init() {
    showHome();
    loadAiCard();

    // conveyor ticker — main.js 의 loadFeed 가 #feed-list 채움 + setupTickerDrift 시작
    if (typeof window.loadFeed === 'function') window.loadFeed();

    document.querySelectorAll('.home-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        if (tile.disabled) return;
        const t = tile.dataset.tile;
        const m = TILE_MAP[t];
        if (!m) return;
        if (m.action === 'tab') showTab(m.idx);
        else if (m.action === 'sector-tab') showSectorTab(m.id);
      });
    });

    // 탭 바를 직접 클릭해도 home-view 가 자동으로 숨겨지도록 hook
    // (main.js 의 switchTab 이 .scroll-wrap 만 만지므로 home-view 를 별도로 처리)
    document.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.getElementById('home-view').style.display = 'none';
        const sw = document.querySelector('.scroll-wrap');
        if (sw) sw.style.display = '';
        document.getElementById('back-to-home').hidden = false;
        document.body.classList.add('with-back');
      });
    });

    document.getElementById('back-to-home').addEventListener('click', showHome);
  }

  // ─────────────────────────────────────────────────────────────
  // 시장 밸류 (ERP / Fed Model) 페이지
  // ─────────────────────────────────────────────────────────────
  async function loadMarketValuation() {
    const fEl = document.getElementById('market-valuation-formula');
    const gEl = document.getElementById('market-valuation-gauge');
    const dEl = document.getElementById('market-valuation-decompose');
    const hEl = document.getElementById('market-valuation-history');
    const iEl = document.getElementById('market-valuation-interpretation');
    fEl.textContent = '로딩 중...';
    [gEl, dEl, hEl, iEl].forEach(el => el && (el.innerHTML = ''));
    try {
      const r = await fetch('/api/macro/valuation-signal');
      const d = await r.json();
      if (d.error || !d.today) {
        const detail = d.detail ? ` — ${escapeHtml(d.detail)}` : '';
        const code   = d.error || 'no data';
        fEl.innerHTML = `<span style="color:#ef4444;">데이터 로드 실패: ${escapeHtml(code)}${detail}</span>`;
        return;
      }
      const t = d.today;
      const bs = d.baselines_5y || { erp:{mean:0,std:0,n:0}, vix:{mean:0,std:0,n:0}, dd:{mean:0,std:0,n:0}, weights:{erp:0.4,vix:0.3,dd:0.3} };
      const ey  = (t.earnings_yield * 100).toFixed(2);
      const ty  = (t.tnx_yield * 100).toFixed(2);
      const erp = (t.erp * 100).toFixed(2);
      const dd  = ((t.dd_60d ?? 0) * 100).toFixed(2);
      const vix = (t.vix ?? 0).toFixed(2);
      const erpSign = t.erp >= 0 ? '+' : '';
      const zErp = t.z_erp ?? 0, zVix = t.z_vix ?? 0, zDd = t.z_dd ?? 0, zComp = t.z_comp ?? 0;
      const W = bs.weights || { erp: 0.4, vix: 0.3, dd: 0.3 };
      const sgn = v => (v >= 0 ? '+' : '');
      const wPct = w => Math.round(w * 100);

      // z → 평어 변환 (component 별 의미 방향 다름)
      const zPhrase = (z, kind) => {
        const high = z > 0.5, low = z < -0.5;
        if (kind === 'erp') return high ? '평소보다 쌈'  : low ? '평소보다 비쌈' : '평소와 비슷';
        if (kind === 'vix') return high ? '평소보다 불안' : low ? '평소보다 평온' : '평소와 비슷';
        if (kind === 'dd')  return high ? '평소보다 큰 하락' : low ? '평소보다 안정' : '평소와 비슷';
        return '';
      };

      // 1) 수식 — 일반어
      fEl.innerHTML = `5년 평균과 비교한 <b>종합 점수</b> = 주식 매력도(${wPct(W.erp)}%) <span style="color:#6b7280;">+</span> 공포(${wPct(W.vix)}%) <span style="color:#6b7280;">+</span> 하락충격(${wPct(W.dd)}%)`;

      // 2) 게이지 — composite z 기반
      gEl.innerHTML = renderGauge(zComp, t.label);

      // 3) 분해 — Raw 5행 + 가중 점수 4행 (구분선)
      dEl.innerHTML = `
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>S&amp;P 500 주가수익비율 (PER)</span>
          <span class="mv-val">${(t.spy_per || 0).toFixed(1)}배</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">−</span>10년 미국 국채 금리</span>
          <span class="mv-val" style="color:#f59e0b;">${ty}%</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">=</span><span>주식 매력도 <small style="color:#6b7280;font-weight:400;">(1÷PER − 국채금리, 양수면 주식 우위)</small></span></span>
          <span class="mv-val" style="color:${t.erp >= 0 ? '#10b981' : '#ef4444'};">${erpSign}${erp}%</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span><span>월가 공포지수 (VIX) <small style="color:#6b7280;font-weight:400;">(20↑ 불안 · 30↑ 패닉)</small></span></span>
          <span class="mv-val" style="color:#7c3aed;">${vix}</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>최근 60일 고점 대비 하락</span>
          <span class="mv-val" style="color:${(t.dd_60d ?? 0) >= -0.03 ? '#10b981' : '#ef4444'};">${dd}%</span>
        </div>
        <div class="mv-row" style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px;">
          <span class="mv-key"><span class="mv-op">${wPct(W.erp)}%</span><span>주식 매력도 점수 <small style="color:#6b7280;font-weight:400;">(${zPhrase(zErp, 'erp')})</small></span></span>
          <span class="mv-val" style="color:${zErp >= 0 ? '#10b981' : '#ef4444'};">${sgn(zErp)}${zErp.toFixed(2)}σ</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">${wPct(W.vix)}%</span><span>공포 점수 <small style="color:#6b7280;font-weight:400;">(${zPhrase(zVix, 'vix')})</small></span></span>
          <span class="mv-val" style="color:${zVix >= 0 ? '#10b981' : '#ef4444'};">${sgn(zVix)}${zVix.toFixed(2)}σ</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">${wPct(W.dd)}%</span><span>하락 충격 점수 <small style="color:#6b7280;font-weight:400;">(${zPhrase(zDd, 'dd')})</small></span></span>
          <span class="mv-val" style="color:${zDd >= 0 ? '#10b981' : '#ef4444'};">${sgn(zDd)}${zDd.toFixed(2)}σ</span>
        </div>
        <div class="mv-row mv-highlight">
          <span class="mv-key"><span class="mv-op">=</span>종합 점수 → ${escapeHtml(t.label || '-')}</span>
          <span class="mv-val" style="color:${zComp >= 0 ? '#10b981' : '#ef4444'};">${sgn(zComp)}${zComp.toFixed(2)}σ</span>
        </div>`;

      // 4) 60일 추이 — z_comp 시계열 + ±1σ 가이드
      hEl.innerHTML = renderCompositeHistory(d.history || []);

      // 5) 해석 — 한글화한 5년 평균 + 오늘 종합 점수
      const erpMean = (bs.erp.mean * 100).toFixed(2);
      const ddMean  = (bs.dd.mean  * 100).toFixed(2);
      iEl.innerHTML = `
        ${escapeHtml(d.interpretation || '')}
        <span class="mv-avg">최근 5년 평균 — 주식 매력도 ${bs.erp.mean >= 0 ? '+' : ''}${erpMean}% · 공포지수 ${bs.vix.mean.toFixed(1)} · 60일 하락폭 ${ddMean}% / 오늘 종합 점수 ${sgn(zComp)}${zComp.toFixed(2)}σ</span>`;
    } catch (e) {
      fEl.innerHTML = `<span style="color:#ef4444;">로드 실패: ${e}</span>`;
    }
  }

  // 반원 게이지 — z-score 기반 (±2σ 를 반원에 매핑)
  // 180° = z=-2σ (왼쪽 끝, 가장 고평가), 0° = z=+2σ (오른쪽 끝, 가장 저평가)
  function renderGauge(z, label) {
    const minZ = -2, maxZ = 2;
    const clamped = Math.max(minZ, Math.min(maxZ, z));
    const ratio = (clamped - minZ) / (maxZ - minZ);    // 0 ~ 1
    const angle = 180 - ratio * 180;                     // 180 → 0
    const cx = 110, cy = 110, r = 90;
    const rad = (angle * Math.PI) / 180;
    const x = cx + r * Math.cos(rad);
    const y = cy - r * Math.sin(rad);

    // ±1σ 경계 색상 — 4 segment (z=-2~-1 빨강, -1~0 주황, 0~+1 초록, +1~+2 파랑)
    const segs = [
      { from: 180, to: 135, color: '#ef4444' },  // z < -1 명확한 고평가
      { from: 135, to: 90,  color: '#f59e0b' },  // -1 < z < 0 다소 고평가
      { from: 90,  to: 45,  color: '#10b981' },  // 0 < z < +1 다소 저평가
      { from: 45,  to: 0,   color: '#3b82f6' },  // z > +1 명확한 저평가
    ];
    const arcs = segs.map(s => arcPath(cx, cy, r, s.from, s.to, s.color)).join('');

    return `
      <svg viewBox="0 0 220 130">
        ${arcs}
        <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="6" fill="#fff" stroke="#1c1c1e" stroke-width="2"/>
      </svg>
      <span class="mv-label">${escapeHtml(label || '-')}</span>`;
  }

  // 게이지 호 그리기 (선형 stroke)
  function arcPath(cx, cy, r, fromDeg, toDeg, color) {
    const fr = (fromDeg * Math.PI) / 180;
    const tr = (toDeg * Math.PI) / 180;
    const x1 = cx + r * Math.cos(fr);
    const y1 = cy - r * Math.sin(fr);
    const x2 = cx + r * Math.cos(tr);
    const y2 = cy - r * Math.sin(tr);
    const large = Math.abs(fromDeg - toDeg) > 180 ? 1 : 0;
    return `<path d="M${x1.toFixed(1)} ${y1.toFixed(1)} A${r} ${r} 0 ${large} 1 ${x2.toFixed(1)} ${y2.toFixed(1)}"
                  stroke="${color}" stroke-width="14" fill="none" stroke-linecap="butt"/>`;
  }

  // 60일 composite z-score 추이 + ±1σ / 0 / 5년 평균 가이드 라인
  function renderCompositeHistory(history) {
    if (!history.length) return '<div style="color:#6b7280;font-size:12px;text-align:center;padding:30px;">데이터 누적 중...</div>';
    const W = 320, H = 120, pad = { l: 30, r: 8, t: 10, b: 18 };
    const innerW = W - pad.l - pad.r, innerH = H - pad.t - pad.b;

    const zs = history.map(h => h.z_comp != null ? h.z_comp : 0);
    // y축 범위: ±1σ 가 항상 보이도록, 그리고 데이터 min/max 포함
    const yMin = Math.min(...zs, -1.2);
    const yMax = Math.max(...zs, 1.2);
    const yRange = yMax - yMin || 1;
    const xPos = i => pad.l + (i / Math.max(1, history.length - 1)) * innerW;
    const yPos = v => pad.t + (1 - (v - yMin) / yRange) * innerH;

    const linePts = history.map((h, i) => `${xPos(i).toFixed(1)},${yPos(zs[i]).toFixed(1)}`).join(' L');
    const areaPts = `${pad.l},${(pad.t + innerH).toFixed(1)} L${linePts} L${(pad.l + innerW).toFixed(1)},${(pad.t + innerH).toFixed(1)} Z`;
    const lastZ = zs[zs.length - 1];
    const lineColor = lastZ >= 0 ? '#10b981' : '#ef4444';
    const fillColor = lastZ >= 0 ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)';
    const lastX = xPos(history.length - 1);
    const lastY = yPos(lastZ);

    // 가이드 라인 — z=0 (15년 평균), z=±1σ
    const y0 = yPos(0);
    const yPlus1 = yPos(1);
    const yMinus1 = yPos(-1);

    return `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <line x1="${pad.l}" y1="${yPlus1}" x2="${pad.l + innerW}" y2="${yPlus1}" stroke="#3b82f6" stroke-width="0.5" stroke-dasharray="2 3"/>
        <line x1="${pad.l}" y1="${y0}" x2="${pad.l + innerW}" y2="${y0}" stroke="#9ca3af" stroke-width="0.6" stroke-dasharray="3 3"/>
        <line x1="${pad.l}" y1="${yMinus1}" x2="${pad.l + innerW}" y2="${yMinus1}" stroke="#ef4444" stroke-width="0.5" stroke-dasharray="2 3"/>
        <text x="${pad.l - 4}" y="${yPlus1 + 3}" text-anchor="end" font-size="9" fill="#3b82f6">저평가</text>
        <text x="${pad.l - 4}" y="${y0 + 3}" text-anchor="end" font-size="9" fill="#9ca3af">평균</text>
        <text x="${pad.l - 4}" y="${yMinus1 + 3}" text-anchor="end" font-size="9" fill="#ef4444">고평가</text>
        <path d="M${areaPts}" fill="${fillColor}" stroke="none"/>
        <path d="M${linePts}" fill="none" stroke="${lineColor}" stroke-width="1.5" stroke-linejoin="round"/>
        <circle cx="${lastX}" cy="${lastY}" r="3" fill="${lineColor}"/>
        <text x="${pad.l}" y="${H - 3}" font-size="9" fill="#6b7280">2개월 전</text>
        <text x="${pad.l + innerW}" y="${H - 3}" text-anchor="end" font-size="9" fill="#6b7280">오늘</text>
      </svg>`;
  }

  // main.js popstate 가 호출할 수 있도록 window 에 노출
  window.showHome = showHome;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
