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
    'sector-val':  { action: 'sector-tab', id: 'tab-sector-val' },
    'sector-mom':  { action: 'sector-tab', id: 'tab-sector-mom' },
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

  // 섹터 모멘텀 랭킹 테이블
  async function loadSectorMomentum() {
    const target = document.getElementById('sector-mom-content');
    target.innerHTML = '<div class="loading-placeholder"><div class="loading-spinner sm"></div></div>';
    try {
      const r = await fetch('/api/sector-cycle/momentum');
      const data = await r.json();
      const phaseLine = data.phase_name
        ? `<div class="sv-phase">현재 국면: <strong>${data.phase_name}</strong> · 예상 순위 = 과거 ${data.phase_name} 국면 평균 수익률 기준</div>` : '';
      const rows = data.momentum.map(m => {
        const r1 = m.return_1m != null ? m.return_1m.toFixed(1) + '%' : '-';
        const r3 = m.return_3m != null ? m.return_3m.toFixed(1) + '%' : '-';
        const r6 = m.return_6m != null ? m.return_6m.toFixed(1) + '%' : '-';
        let chip = '<span class="sm-chip flat">-</span>';
        if (m.rank_diff != null) {
          if (m.rank_diff > 0)  chip = `<span class="sm-chip over">+${m.rank_diff}</span>`;
          else if (m.rank_diff < 0) chip = `<span class="sm-chip under">${m.rank_diff}</span>`;
          else chip = '<span class="sm-chip flat">0</span>';
        }
        return `<tr>
          <td>${m.sector_name}<br><span style="color:#9ca3af;font-size:10px;">${m.ticker}</span></td>
          <td class="num">${r1}</td>
          <td class="num">${r3}</td>
          <td class="num">${r6}</td>
          <td class="num">${m.current_rank ?? '-'}</td>
          <td class="num">${m.expected_rank ?? '-'}</td>
          <td class="num">${chip}</td>
        </tr>`;
      }).join('');
      target.innerHTML = phaseLine + `
        <table class="sm-table">
          <thead><tr><th>섹터</th><th class="num">1M</th><th class="num">3M</th><th class="num">6M</th><th class="num">현재</th><th class="num">예상</th><th class="num">괴리</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div style="margin-top:12px;font-size:11px;color:#9ca3af;line-height:1.5;">
          <strong style="color:#60a5fa;">파란 칩</strong> = 예상보다 잘 가는 섹터 (오버퍼폼) /
          <strong style="color:#f87171;">빨간 칩</strong> = 예상보다 못 가는 섹터 (언더퍼폼)
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

  // main.js popstate 가 호출할 수 있도록 window 에 노출
  window.showHome = showHome;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
