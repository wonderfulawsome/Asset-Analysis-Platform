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
    'crash-surge':      { action: 'sector-tab', id: 'tab-crash-surge' },
  };

  // KR 모드 지원 타일 (Stage 3.x). 나머지는 데이터 미적재 → 비활성화.
  // 'signal' / 'macro' / 'sector-val' / 'sector-mom' 활성화 — DB 의 crash_surge_result /
  // sector_cycle_result / sector_valuation / index_price_raw region='kr' 적재 시 자동 표시.
  // 사용자 환경에서 train_kr_crash_surge / train_kr_sector_cycle 1회 실행 + 매일 스케줄러 자동 적재.
  const KR_SUPPORTED_TILES = new Set([
    'ai-chart', 'market', 'fundamental', 'market-valuation', 'signal', 'macro', 'sector-val', 'sector-mom',
    'crash-surge',
  ]);

  function _isKrMode() {
    return (typeof window.getRegion === 'function') && window.getRegion() === 'kr';
  }

  // KR 모드 진입 시 미지원 타일 비활성화 + "준비 중" 라벨
  function applyKrTileGuards() {
    const isKr = _isKrMode();
    document.querySelectorAll('.home-tile[data-tile]').forEach(el => {
      const tile = el.dataset.tile;
      const supported = !isKr || KR_SUPPORTED_TILES.has(tile);
      el.classList.toggle('tile-disabled', !supported);
      // "준비 중" 라벨 토글
      let badge = el.querySelector('.tile-soon');
      if (!supported) {
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'tile-soon';
          badge.textContent = '준비 중';
          el.appendChild(badge);
        }
      } else if (badge) {
        badge.remove();
      }
    });
  }

  // 섹터 ETF ticker → 한국어 표시명 (DB·API 는 영어 그대로, 화면 표시만 번역)
  // US (SPDR 13종) + KR (KODEX/TIGER 10종, 6자리 숫자라 자체로는 의미 없어 한글 매핑 필수)
  const SECTOR_KR = {
    // US — SPDR 섹터 ETF
    XLK:  '기술',
    IGV:  '소프트웨어',
    SOXX: '반도체',
    XLF:  '금융',
    XLE:  '에너지',
    XLV:  '헬스케어',
    XLY:  '경기소비재',
    XLI:  '산업재',
    XLB:  '소재',
    XLU:  '유틸리티',
    XLRE: '부동산',
    XLC:  '커뮤니케이션',
    XLP:  '필수소비재',
    // KR — KODEX/TIGER 섹터 ETF (기존 10개)
    '139260': 'IT',
    '091160': '반도체',
    '300610': '게임',
    '091170': '은행',
    '139250': '에너지화학',
    '266420': '헬스케어',
    '091180': '자동차',
    '117680': '철강',
    '341850': '리츠',
    '227560': '필수소비재',
    // KR — 한국 특유 신규 8개 (2026-05-14)
    '401170': '방산',
    '305720': '2차전지',
    '466920': '조선',
    '244620': '바이오',
    '228810': '미디어',
    '117700': '건설',
    '098560': '통신',
    '445290': '로봇',
  };
  const krSector = (ticker, fallback) => SECTOR_KR[ticker] || fallback || ticker;

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
    // main.js switchTab 은 TAB_IDS 5개만 토글하므로 sector-val/mom/market-valuation 은 직접 hide
    ['tab-sector-val', 'tab-sector-mom', 'tab-market-valuation', 'tab-crash-surge'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    // 기존 탭 트리거 — main.js 가 처리
    const tabBtn = document.querySelector(`.tab[data-idx="${idx}"]`);
    if (tabBtn) tabBtn.click();
    // AI차트 (idx 0) — 기본 list 뷰로 진입
    if (idx === 0) {
      showAiChartList();
    }
  }

  // ─── AI차트 (tab-chart) — Coinbase 스타일 list ↔ detail 토글 ──────
  // 본 프로젝트 AI차트 모델 학습 종목 = chart.py CHART_TICKERS (ETF 16종)
  const AI_TICKERS_US = [
    { t:'SPY',  s:'SPDR S&P 500',      ico:'SPY',  bg:'#FDEBDC', fg:'#C44A12' },
    { t:'QQQ',  s:'Invesco QQQ',       ico:'QQQ',  bg:'#EDE9FE', fg:'#7C3AED' },
    { t:'DIA',  s:'Dow Jones ETF',     ico:'DIA',  bg:'#D1FAE5', fg:'#047857' },
    { t:'IWM',  s:'Russell 2000',      ico:'IWM',  bg:'#E0E7FF', fg:'#4338CA' },
    { t:'VTI',  s:'Vanguard Total',    ico:'VTI',  bg:'#FCE7F3', fg:'#BE185D' },
    { t:'VOO',  s:'Vanguard S&P 500',  ico:'VOO',  bg:'#DBEAFE', fg:'#1D4ED8' },
    { t:'SOXX', s:'iShares Semi',      ico:'SOX',  bg:'#DCFCE7', fg:'#16A34A' },
    { t:'SMH',  s:'VanEck Semi',       ico:'SMH',  bg:'#FED7AA', fg:'#EA580C' },
    { t:'XLK',  s:'Tech Sector',       ico:'XLK',  bg:'#DBEAFE', fg:'#2563EB' },
    { t:'XLF',  s:'Financial Sector',  ico:'XLF',  bg:'#DCFCE7', fg:'#16A34A' },
    { t:'XLE',  s:'Energy Sector',     ico:'XLE',  bg:'#FFEDD5', fg:'#EA580C' },
    { t:'XLV',  s:'Health Sector',     ico:'XLV',  bg:'#CFFAFE', fg:'#0891B2' },
    { t:'ARKK', s:'ARK Innovation',    ico:'ARK',  bg:'#FAE8FF', fg:'#A21CAF' },
    { t:'GLD',  s:'SPDR Gold',         ico:'GLD',  bg:'#FEF9C3', fg:'#CA8A04' },
    { t:'TLT',  s:'20+Y T-Bond',       ico:'TLT',  bg:'#E0F2FE', fg:'#0369A1' },
    { t:'SCHD', s:'Schwab Dividend',   ico:'SCH',  bg:'#D1FAE5', fg:'#059669' },
  ];
  const AI_TICKERS_KR = [
    { t:'069500', s:'KODEX 200',           ico:'200', bg:'#FDEBDC', fg:'#C44A12' },
    { t:'232080', s:'TIGER 코스닥150',     ico:'KQ',  bg:'#EDE9FE', fg:'#7C3AED' },
    { t:'229200', s:'KODEX 코스닥150',     ico:'KQ',  bg:'#D1FAE5', fg:'#047857' },
    { t:'091160', s:'KODEX 반도체',        ico:'반',  bg:'#E0E7FF', fg:'#4338CA' },
    { t:'139260', s:'TIGER 200 IT',        ico:'IT',  bg:'#FCE7F3', fg:'#BE185D' },
    { t:'091170', s:'KODEX 은행',          ico:'은',  bg:'#DBEAFE', fg:'#1D4ED8' },
    { t:'266420', s:'KODEX 헬스케어',      ico:'헬',  bg:'#CFFAFE', fg:'#0891B2' },
    { t:'139250', s:'TIGER 200 에너지화학', ico:'에', bg:'#FFEDD5', fg:'#EA580C' },
    { t:'091180', s:'KODEX 자동차',        ico:'차',  bg:'#DCFCE7', fg:'#16A34A' },
    { t:'117680', s:'KODEX 철강',          ico:'철',  bg:'#FEF9C3', fg:'#CA8A04' },
    { t:'341850', s:'TIGER 리츠부동산',    ico:'리',  bg:'#FAE8FF', fg:'#A21CAF' },
  ];
  function getAiTickers() {
    return (typeof window.getRegion === 'function' && window.getRegion() === 'kr') ? AI_TICKERS_KR : AI_TICKERS_US;
  }

  let _aiListBuilt = false;
  let _aiListRegion = null;

  function _aiClearAnimClasses(el) {
    if (!el) return;
    el.classList.remove('ai-anim-in-right', 'ai-anim-in-left', 'ai-anim-out-left', 'ai-anim-out-right');
  }
  function _aiPlayAnim(el, cls) {
    if (!el) return Promise.resolve();
    _aiClearAnimClasses(el);
    // 강제 reflow → 동일 animation 재실행 가능
    void el.offsetWidth;
    el.classList.add(cls);
    return new Promise(res => {
      const done = () => { el.removeEventListener('animationend', done); res(); };
      el.addEventListener('animationend', done);
      setTimeout(done, 400); // safety fallback
    });
  }

  function showAiChartList(force) {
    const list = document.getElementById('ai-chart-list-view');
    const detail = document.getElementById('ai-chart-detail-view');
    const region = (typeof window.getRegion === 'function') ? window.getRegion() : 'us';
    const needBuild = force || !_aiListBuilt || _aiListRegion !== region;
    const detailVisible = detail && detail.style.display !== 'none';

    const reveal = () => {
      if (list) {
        list.style.display = '';
        _aiPlayAnim(list, 'ai-anim-in-left');
        if (needBuild) {
          _aiListBuilt = true;
          _aiListRegion = region;
          buildAiChartList();
        }
      }
    };

    if (detailVisible) {
      _aiPlayAnim(detail, 'ai-anim-out-right').then(() => {
        detail.style.display = 'none';
        _aiClearAnimClasses(detail);
        reveal();
      });
    } else {
      if (detail) detail.style.display = 'none';
      reveal();
    }
  }

  function showAiChartDetail(ticker) {
    const list = document.getElementById('ai-chart-list-view');
    const detail = document.getElementById('ai-chart-detail-view');
    const listVisible = list && list.style.display !== 'none';

    const reveal = () => {
      if (detail) {
        detail.style.display = '';
        _aiPlayAnim(detail, 'ai-anim-in-right');
        // 디자인 사양 캐스케이드 (chips/price/strip/chart-card 등) 재트리거
        detail.classList.remove('aiv-replay');
        void detail.offsetWidth;
        detail.classList.add('aiv-replay');
      }
      // chart.js renderTickerChips: class="chart-tk-chip" data-tk="${ticker}"
      const chip = document.querySelector(`.chart-tk-chip[data-tk="${ticker}"]`);
      if (chip) { chip.click(); return; }
      if (typeof window.selectChartTicker === 'function') window.selectChartTicker(ticker);
    };

    if (listVisible) {
      _aiPlayAnim(list, 'ai-anim-out-left').then(() => {
        list.style.display = 'none';
        _aiClearAnimClasses(list);
        reveal();
      });
    } else {
      if (list) list.style.display = 'none';
      reveal();
    }
  }

  const AI_LIST_INITIAL = 10;
  let _aiListExpanded = false;
  let _aiSortMode = 'mcap';  // 'mcap' | 'value' | 'up' | 'down'
  const _aiMetrics = {};      // ticker → { last, pct, value, mcap }
  const AI_SORT_LABEL = { mcap: '시가총액', value: '거래대금', up: '상승률', down: '하락률' };
  // 시가총액 추정용 룩업 (단위: 십억 $, KR 십억 ₩). 정확값 아님 — 상대 정렬용.
  const AI_MCAP_HINT = {
    // US ETF AUM (B$, 2025 근사)
    SPY: 600, VOO: 580, QQQ: 320, VTI: 480, DIA: 38, IWM: 65,
    SOXX: 16, SMH: 24, XLK: 75, XLF: 50, XLE: 38, XLV: 38,
    ARKK: 7, GLD: 78, TLT: 47, SCHD: 65,
    // KR ETF AUM (B₩ 근사)
    '069500': 8000, '232080': 2500, '229200': 2200, '091160': 1800,
    '139260': 1500, '091170': 1200, '266420': 900, '139250': 1000,
    '091180': 800, '117680': 600, '341850': 700,
  };
  function _sortedTickers() {
    const tickers = getAiTickers().slice();
    const mode = _aiSortMode;
    tickers.sort((a, b) => {
      const ma = _aiMetrics[a.t] || {};
      const mb = _aiMetrics[b.t] || {};
      if (mode === 'mcap') {
        return (AI_MCAP_HINT[b.t] || 0) - (AI_MCAP_HINT[a.t] || 0);
      }
      if (mode === 'value') {
        return (mb.value || 0) - (ma.value || 0);
      }
      if (mode === 'up') {
        return (mb.pct ?? -Infinity) - (ma.pct ?? -Infinity);
      }
      if (mode === 'down') {
        return (ma.pct ?? Infinity) - (mb.pct ?? Infinity);
      }
      return 0;
    });
    return tickers;
  }

  async function buildAiChartList() {
    const list = document.getElementById('ai-chart-cb-list');
    if (!list) return;
    const tickers = _sortedTickers();
    list.innerHTML = tickers.map((t, i) => {
      const hidden = !_aiListExpanded && i >= AI_LIST_INITIAL ? ' aichart-hidden' : '';
      return `
      <a class="cb-tk${hidden}" data-ticker="${t.t}" data-idx="${i}" style="animation-delay:${Math.min((i + 1) * 60, 600)}ms;">
        <span class="cb-ico" style="background:${t.bg};color:${t.fg}">${t.ico}</span>
        <span class="cb-nm"><span class="cb-t">${t.s}</span><span class="cb-s">${t.t}</span></span>
        <svg class="cb-spark" id="ai-sp-${t.t}" viewBox="0 0 80 34" preserveAspectRatio="none"><polyline fill="none" stroke="${t.fg}" stroke-width="1.8" points=""/></svg>
        <span class="cb-price"><span class="cb-p" id="ai-p-${t.t}">—</span><span class="cb-d" id="ai-d-${t.t}">—</span></span>
      </a>`;
    }).join('');
    _updateSeeAllLabel();
    // ticker = chart.py CHART_TICKERS (US ETF or KR ETF code) — 직접 호출
    let _doneCount = 0;
    const _total = tickers.length;
    tickers.forEach(async (t) => {
      try {
        const r = await fetch('/api/chart/ohlc?ticker=' + encodeURIComponent(t.t) + '&interval=1d');
        const j = await r.json();
        const c = j.candles || [];
        if (c.length < 2) return;
        const last = Number(c[c.length-1].c);
        const prev = Number(c[c.length-2].c);
        const pct = (last - prev) / prev * 100;
        const vol = Number(c[c.length-1].v) || 0;
        _aiMetrics[t.t] = { last, pct, value: last * vol };
        const pEl = document.getElementById('ai-p-' + t.t);
        const dEl = document.getElementById('ai-d-' + t.t);
        if (pEl) pEl.textContent = last.toLocaleString(undefined, { maximumFractionDigits: 2 });
        if (dEl) {
          const up = pct >= 0;
          dEl.className = 'cb-d ' + (up ? 'up' : 'down');
          dEl.textContent = (up ? '↗ ' : '↘ ') + Math.abs(pct).toFixed(2) + '%';
        }
        const recent = c.slice(-30).map(x => Number(x.c)).filter(v => isFinite(v));
        if (recent.length >= 2) {
          const lo = Math.min(...recent), hi = Math.max(...recent), span = (hi - lo) || 1;
          const w = 80, h = 34, pad = 2;
          const pts = recent.map((v, i) => {
            const x = pad + (w - pad*2) * i / (recent.length - 1);
            const y = pad + (h - pad*2) - ((v - lo) / span) * (h - pad*2);
            return x.toFixed(1) + ',' + y.toFixed(1);
          }).join(' ');
          const sp = document.querySelector('#ai-sp-' + t.t + ' polyline');
          if (sp) {
            sp.setAttribute('points', pts);
            // 비동기 fetch → row stagger 완료 후 sparkline 시각 draw 발동
            // 행 idx 기반 delay 로 위→아래 순차. row fade-up 끝나는 즈음 시작.
            const row = sp.closest('.cb-tk');
            const idx = row ? Number(row.dataset.idx || 0) : 0;
            const delayMs = 200 + Math.min(idx * 50, 500);
            // 인라인 shorthand 로 전체 애니메이션 재정의 → 매번 재트리거
            sp.style.animation = 'none';
            void sp.getBoundingClientRect();
            sp.style.animation = `ai-spark-draw 1.3s cubic-bezier(.2,.7,.2,1) ${delayMs}ms forwards`;
          }
        }
      } catch(_) {}
      finally {
        _doneCount++;
        // 모든 fetch 완료 → 정렬 모드가 metric 의존(value/up/down) 이면 재정렬
        if (_doneCount >= _total && (_aiSortMode === 'value' || _aiSortMode === 'up' || _aiSortMode === 'down')) {
          _reorderAiList();
        }
      }
    });
  }

  let _aiSearchQuery = '';
  function _applyAiSearchFilter() {
    const list = document.getElementById('ai-chart-cb-list');
    if (!list) return;
    const q = _aiSearchQuery.trim().toLowerCase();
    const rows = list.querySelectorAll('.cb-tk');
    let shown = 0;
    rows.forEach(row => {
      const tk = (row.getAttribute('data-ticker') || '').toLowerCase();
      const nm = (row.querySelector('.cb-t')?.textContent || '').toLowerCase();
      const match = !q || tk.includes(q) || nm.includes(q);
      row.classList.toggle('aichart-filtered', !match);
      if (match) shown++;
    });
    // 검색 중에는 모두 보기 / 접기 무시하고 매치된 것 전부 노출
    if (q) {
      rows.forEach(row => row.classList.remove('aichart-hidden'));
    } else {
      // 검색 해제 시 expand 상태에 맞춰 hidden 복원
      rows.forEach((row, i) => {
        const idx = Number(row.dataset.idx);
        row.classList.toggle('aichart-hidden', !_aiListExpanded && idx >= AI_LIST_INITIAL);
      });
    }
    // 결과 없음 메시지
    let empty = list.querySelector('.cb-no-result');
    if (q && shown === 0) {
      if (!empty) {
        empty = document.createElement('div');
        empty.className = 'cb-no-result';
        list.appendChild(empty);
      }
      empty.textContent = `"${_aiSearchQuery}" 결과 없음`;
    } else if (empty) {
      empty.remove();
    }
    // see-all 버튼은 검색 중에는 숨김
    const seeAllBtn = document.getElementById('ai-chart-see-all');
    if (seeAllBtn) {
      const total = getAiTickers().length;
      seeAllBtn.style.display = q ? 'none' : (total > AI_LIST_INITIAL ? '' : 'none');
    }
  }

  // DOM 재생성 없이 row 순서만 재배치 (애니메이션 부담 ↓)
  function _reorderAiList() {
    const list = document.getElementById('ai-chart-cb-list');
    if (!list) return;
    const sorted = _sortedTickers();
    sorted.forEach((t, i) => {
      const row = list.querySelector(`.cb-tk[data-ticker="${t.t}"]`);
      if (!row) return;
      list.appendChild(row);
      row.dataset.idx = i;
      row.classList.toggle('aichart-hidden', !_aiListExpanded && i >= AI_LIST_INITIAL);
    });
  }

  function _updateSeeAllLabel() {
    const btn = document.getElementById('ai-chart-see-all');
    if (!btn) return;
    const total = getAiTickers().length;
    if (total <= AI_LIST_INITIAL) {
      btn.style.display = 'none';
      return;
    }
    btn.style.display = '';
    btn.textContent = _aiListExpanded ? '접기' : `모두 보기 (${total})`;
  }

  // 검색 input — delegated (DOM 늦게 마운트돼도 동작)
  document.addEventListener('input', function(e) {
    if (e.target && e.target.id === 'ai-search-input') {
      _aiSearchQuery = e.target.value || '';
      _applyAiSearchFilter();
    }
  });

  // 클릭 라우팅: 리스트 row → detail, "← 목록" → list, "모두 보기" → 나머지 expand, sort dropdown
  document.addEventListener('click', function(e) {
    // sort dropdown trigger
    const sortBtn = e.target.closest('#ai-sort-trigger');
    if (sortBtn) {
      e.preventDefault();
      const menu = document.getElementById('ai-sort-menu');
      if (menu) {
        const open = menu.hasAttribute('hidden') ? false : true;
        if (open) { menu.setAttribute('hidden', ''); sortBtn.setAttribute('aria-expanded', 'false'); }
        else { menu.removeAttribute('hidden'); sortBtn.setAttribute('aria-expanded', 'true'); }
      }
      return;
    }
    // sort menu item
    const sortItem = e.target.closest('#ai-sort-menu li[data-sort]');
    if (sortItem) {
      e.preventDefault();
      const mode = sortItem.dataset.sort;
      if (mode && mode !== _aiSortMode) {
        _aiSortMode = mode;
        document.querySelectorAll('#ai-sort-menu li').forEach(li => {
          li.classList.toggle('on', li.dataset.sort === mode);
        });
        const trigger = document.getElementById('ai-sort-trigger');
        if (trigger) trigger.firstChild ? trigger.childNodes[0].nodeValue = AI_SORT_LABEL[mode] : (trigger.textContent = AI_SORT_LABEL[mode]);
        if (trigger) trigger.textContent = AI_SORT_LABEL[mode];
        _reorderAiList();
      }
      const menu = document.getElementById('ai-sort-menu');
      if (menu) menu.setAttribute('hidden', '');
      const trig = document.getElementById('ai-sort-trigger');
      if (trig) trig.setAttribute('aria-expanded', 'false');
      return;
    }
    // 외부 클릭 시 dropdown 닫기
    const menuEl = document.getElementById('ai-sort-menu');
    if (menuEl && !menuEl.hasAttribute('hidden') && !e.target.closest('.cb-sort-wrap')) {
      menuEl.setAttribute('hidden', '');
      const trig = document.getElementById('ai-sort-trigger');
      if (trig) trig.setAttribute('aria-expanded', 'false');
    }

    const tk = e.target.closest('#ai-chart-cb-list .cb-tk');
    if (tk) {
      e.preventDefault();
      showAiChartDetail(tk.getAttribute('data-ticker'));
      return;
    }
    const back = e.target.closest('#ai-chart-back');
    if (back) {
      e.preventDefault();
      showAiChartList();
      return;
    }
    const seeAll = e.target.closest('#ai-chart-see-all');
    if (seeAll) {
      e.preventDefault();
      _aiListExpanded = !_aiListExpanded;
      const rows = document.querySelectorAll('#ai-chart-cb-list .cb-tk');
      rows.forEach((row, i) => {
        if (i < AI_LIST_INITIAL) return;
        if (_aiListExpanded) {
          row.classList.remove('aichart-hidden');
          // expand 시 stagger 재트리거 (인덱스 - INITIAL 기반)
          row.style.animationDelay = Math.min((i - AI_LIST_INITIAL + 1) * 60, 400) + 'ms';
          row.style.animation = 'none';
          void row.offsetWidth;
          row.style.animation = '';
        } else {
          row.classList.add('aichart-hidden');
        }
      });
      _updateSeeAllLabel();
      return;
    }
  });

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
    if (id === 'tab-crash-surge') {
      loadCrashSurge();
    }
    // main.js 가 관리하는 .tab active 표시 해제 (탭 바는 안 보이지만 깔끔하게)
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  }

  // 5개 지수는 컨베이어(.feed-section) 가 main.js loadFeed() 로 채움 — 별도 정적 카드 불필요

  // ── AI 브리핑 ── 네이버 스타일: 진입 바(타임스탬프+헤드라인) + 클릭 시 상세 모달
  function _esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function _openBriefModal(data) {
    let overlay = document.getElementById('brief-modal');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'brief-modal';
      overlay.className = 'brief-modal';
      document.body.appendChild(overlay);
    }
    const summaryHtml = (data.summary && data.summary.length)
      ? `<div class="bm-summary"><div class="bm-summary-label">요약</div><ul>${data.summary.map(s=>`<li>${_esc(s)}</li>`).join('')}</ul></div>` : '';
    const sectionsHtml = (data.sections && data.sections.length)
      ? data.sections.map(sec=>`<div class="bm-section"><h3 class="bm-sec-title">${_esc(sec.emoji)} ${_esc(sec.title)}</h3><p class="bm-sec-body">${_esc(sec.body)}</p></div>`).join('') : '';
    const srcHtml = (data.sources && data.sources.length)
      ? `<div class="bm-sources"><div class="bm-sources-label">출처 ${data.sources.length}건</div><ul>${data.sources.map(s=>`<li><a href="${_esc(s.url)}" target="_blank" rel="noopener"><span class="bm-src-name">${_esc(s.source)}</span><span class="bm-src-title">${_esc(s.title)}</span></a></li>`).join('')}</ul></div>` : '';
    overlay.innerHTML = `
      <div class="bm-sheet" role="dialog" aria-modal="true">
        <header class="bm-head">
          <span class="bm-head-title">AI 브리핑</span>
          <button type="button" class="bm-close" aria-label="닫기">✕</button>
        </header>
        <div class="bm-scroll">
          <div class="bm-meta">📌 ${_esc(data.updated_at)}에 주요 뉴스를 요약했어요.</div>
          <h2 class="bm-headline">${_esc(data.headline)}</h2>
          ${summaryHtml}
          ${sectionsHtml}
          ${srcHtml}
          <div class="bm-disclaimer">본 정보는 투자자문이 아니며 투자 판단과 책임은 사용자에게 있습니다.</div>
        </div>
      </div>`;
    overlay.querySelector('.bm-close').addEventListener('click', _closeBriefModal);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) _closeBriefModal(); });
    requestAnimationFrame(() => overlay.classList.add('open'));
    document.body.classList.add('brief-modal-open');
    history.pushState({ briefModal: true }, '');
    window._briefStates = (window._briefStates || 0) + 1;
  }

  function _closeBriefModal() {
    const overlay = document.getElementById('brief-modal');
    if (!overlay) return;
    overlay.classList.remove('open');
    document.body.classList.remove('brief-modal-open');
    setTimeout(() => { if (overlay) overlay.remove(); }, 240);
  }
  window._closeBriefModal = _closeBriefModal;

  // 시스템 뒤로가기 — 브리핑 모달 열려있으면 닫기만
  window.addEventListener('popstate', () => {
    if (window._briefStates > 0 && document.getElementById('brief-modal')) {
      window._briefStates--;
      _closeBriefModal();
    }
  });

  // AI 종합판단 카드 → AI 브리핑 진입 바 (클릭 시 상세 모달)
  async function loadAiCard() {
    try {
      const region = (typeof window.getRegion === 'function') ? window.getRegion() : 'us';
      const r = await fetch(`/api/market-summary/market-brief?region=${region}`);
      const data = await r.json();
      const body = document.getElementById('home-ai-body');
      if (data.headline) {
        let pmTag = '';
        if (typeof data.premarket_pct === 'number') {
          const up = data.premarket_pct > 0;
          pmTag = `<span class="brief-pm ${up ? 'up' : 'down'}">프리장 ${up ? '상승' : '하락'} ${data.premarket_pct > 0 ? '+' : ''}${data.premarket_pct.toFixed(2)}%</span>`;
        }
        body.innerHTML = `
          <button type="button" class="brief-bar">
            <span class="brief-bar-time">${_esc(data.updated_at)} ›${pmTag}</span>
            <span class="brief-bar-line"><span class="brief-bar-badge">AI 브리핑</span>${_esc(data.headline)}</span>
            <span class="brief-bar-hint">자세히 보려면 클릭 ›</span>
          </button>`;
        body.querySelector('.brief-bar').addEventListener('click', () => _openBriefModal(data));
      }
    } catch (e) { console.error('[home] AI 브리핑 로드 실패', e); }

    // 메타라인: 심리 / 이상도 (anomaly percentile) / 국면 — 3 endpoint 병렬
    try {
      const _wr = (typeof window.withRegion === 'function') ? window.withRegion : (u => u);
      const [fg, cycle, anomaly] = await Promise.all([
        fetch('/api/macro/fear-greed').then(r => r.json()).catch(() => null),
        fetch('/api/sector-cycle/current').then(r => r.json()).catch(() => null),
        fetch(_wr('/api/anomaly/current')).then(r => r.json()).catch(() => null),
      ]);
      const meta = document.getElementById('home-ai-meta');
      const parts = [];
      if (fg && fg.score != null) {
        parts.push(`<span class="meta-item"><span class="meta-key">심리</span><span class="meta-val">${fg.rating || ''} ${Math.round(fg.score)}</span></span>`);
      }
      // 이상도 — 10년 분포 내 percentile (descriptive only, 자문 리스크 없는 표현)
      if (anomaly && !anomaly.empty && anomaly.percentile_10y != null) {
        const p = anomaly.percentile_10y;
        const cls = p >= 80 ? 'down' : (p <= 20 ? 'up' : '');   // 시각 단서만, 위험/안전 라벨 X
        parts.push(`<span class="meta-item"><span class="meta-key">이상도</span><span class="meta-val ${cls}">상위 ${(100 - p).toFixed(0)}%</span></span>`);
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
      const url = (typeof window.withRegion === 'function')
        ? window.withRegion('/api/sector-cycle/valuation')
        : '/api/sector-cycle/valuation';
      const r = await fetch(url);
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
      // 컬럼 구성:
      //   US: 섹터 / 갭 (fundamental_gap %) / PER (가중평균) / PER 10Y 평균
      //   KR: 섹터 / PER 가중평균 (배수) / 10Y 평균   ← 갭 컬럼 없음 (US 만 적용)
      const isKr = (typeof window.getRegion === 'function') && window.getRegion() === 'kr';
      const fmtGap = (p) => {
        if (p == null) return '–';
        const sign = p >= 0 ? '+' : '';
        return `${sign}${(p * 100).toFixed(1)}%`;
      };
      const fmtPer = (p) => {
        if (p == null) return '–';
        return `${p.toFixed(1)}배`;
      };
      let headerHtml, rowsHtml, gridCols, sourceText;
      if (isKr) {
        headerHtml = `
          <div class="sv-h">섹터</div>
          <div class="sv-h" style="text-align:right;">10Y 평균</div>
          <div class="sv-h" style="text-align:right;">현재</div>`;
        gridCols = '1fr auto auto';
        sourceText = `PER 가중평균 = ETF 보유 종목별 PER 을 비중 가중평균. 10년 평균과 현재값 비교.`;
        rowsHtml = data.valuations.map(v => {
          const fgCol = colorByZ(v.per_z);
          return `
            <div class="sv-name">${krSector(v.ticker, v.sector_name)} <span style="color:#9ca3af;font-size:10px;">${v.ticker}</span></div>
            <div class="sv-cell" style="text-align:right;color:#9ca3af;">${fmtPer(v.per_mean)}</div>
            <div class="sv-cell" style="background:${fgCol};">${fmtPer(v.per)}</div>`;
        }).join('');
      } else {
        headerHtml = `
          <div class="sv-h">섹터</div>
          <div class="sv-h" style="text-align:right;">갭 (가격−EPS)</div>
          <div class="sv-h" style="text-align:right;">PER (가중평균)</div>
          <div class="sv-h" style="text-align:right;">PER 10Y 평균</div>`;
        gridCols = '1fr auto auto auto';
        sourceText = `갭 = 12개월 가격성장률 − 12개월 EPS 성장률 (모멘텀). PER = ETF 보유 종목 PER 을 비중 가중평균 (절대 수준).`;
        rowsHtml = data.valuations.map(v => {
          const fgCol = colorByZ(v.per_z);
          const perwCol = colorByZ(v.per_weighted_z);
          return `
            <div class="sv-name">${krSector(v.ticker, v.sector_name)} <span style="color:#9ca3af;font-size:10px;">${v.ticker}</span></div>
            <div class="sv-cell" style="background:${fgCol};">${fmtGap(v.per)}</div>
            <div class="sv-cell" style="text-align:right;background:${perwCol};">${fmtPer(v.per_weighted)}</div>
            <div class="sv-cell" style="text-align:right;color:#9ca3af;">${fmtPer(v.per_weighted_mean)}</div>`;
        }).join('');
      }
      const sourceLine = data.as_of_date
        ? `<div class="sv-phase" style="font-size:11px;line-height:1.5;">${sourceText} as of <strong>${data.as_of_date}</strong>.</div>`
        : '';
      target.innerHTML = phaseLine + histLine + sourceLine + `
        <div class="sv-grid" style="grid-template-columns: ${gridCols}; gap:6px 10px;">
          ${headerHtml}
          ${rowsHtml}
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

  // z-score 5단계 라벨 — KR 모드용 (PER 배수 자체는 라벨 못 매기니 historical z 기준)
  function labelByZ(z) {
    if (z == null)   return { text: '–',          color: '#9ca3af' };
    if (z >=  1.0)   return { text: '고평가',     color: '#dc2626' };
    if (z >=  0.5)   return { text: '약간 고평가', color: '#f97316' };
    if (z >  -0.5)   return { text: '부합',       color: '#9ca3af' };
    if (z >  -1.0)   return { text: '약간 저평가', color: '#3b82f6' };
    return              { text: '저평가',     color: '#1d4ed8' };
  }

  // 갭 % (per 컬럼, 0.05 = 5%) 5단계 라벨 — 고평가/약간 고평가/부합/약간 저평가/저평가
  // 갭 절대값 기반 (직관) — z-score 의 historical 분포 보정은 색상으로만 반영.
  function labelByGap(p) {
    if (p == null)   return { text: '–',          color: '#9ca3af' };
    if (p >=  0.20)  return { text: '고평가',     color: '#dc2626' };
    if (p >=  0.05)  return { text: '약간 고평가', color: '#f97316' };
    if (p >  -0.05)  return { text: '부합',       color: '#9ca3af' };
    if (p >  -0.20)  return { text: '약간 저평가', color: '#3b82f6' };
    return              { text: '저평가',     color: '#1d4ed8' };
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
          <td>${escapeHtml(krSector(m.ticker, m.sector_name))}<br><span style="color:#9ca3af;font-size:10px;">${m.ticker}</span></td>
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

    // 초기 + region 토글 시 KR 미지원 타일 비활성화
    applyKrTileGuards();

    document.querySelectorAll('.home-tile').forEach(tile => {
      tile.addEventListener('click', () => {
        if (tile.disabled || tile.classList.contains('tile-disabled')) {
          // KR 모드 미지원 타일 클릭 시 토스트 (없으면 alert 폴백)
          if (_isKrMode()) {
            const msg = '한국 시장 데이터 준비 중입니다 (Stage 3 후속).';
            if (typeof window._showToast === 'function') window._showToast(msg);
            else console.info(msg);
          }
          return;
        }
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
  let _mvDays = 2520;
  async function loadMarketValuation(days) {
    if (typeof days === 'number') _mvDays = days;
    const fEl = document.getElementById('market-valuation-formula');
    const gEl = document.getElementById('market-valuation-gauge');
    const dEl = document.getElementById('market-valuation-decompose');
    const hEl = document.getElementById('market-valuation-history');
    const iEl = document.getElementById('market-valuation-interpretation');
    // 다른 탭과 동일한 loading-placeholder + spinner 사용 (재진입 시에도 일관 표시)
    const _SPIN = '<div class="loading-placeholder"><div class="loading-spinner sm"></div></div>';
    [fEl, gEl, dEl, hEl, iEl].forEach(el => el && (el.innerHTML = _SPIN));
    // history 차트 위에 기간 토글 attach (1회만)
    if (hEl && typeof window.attachPeriodToggle === 'function') {
      window.attachPeriodToggle(hEl, _mvDays, function(p) { loadMarketValuation(p); });
    }
    try {
      const url = (typeof window.withRegion === 'function')
        ? window.withRegion('/api/macro/valuation-signal?days=' + _mvDays)
        : '/api/macro/valuation-signal?days=' + _mvDays;
      const r = await fetch(url);
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
      const zPer = t.z_per ?? 0, zTrend = t.z_trend ?? 0;             // KR 5-comp / US trend
      const zCape = t.z_cape ?? 0, zBuffett = t.z_buffett ?? 0;       // US 6-comp
      const trendPct = ((t.price_vs_ma200 ?? 0) * 100).toFixed(1);    // 가격 vs 200d MA (%)
      const perVal = (t.spy_per ?? 0).toFixed(1);                     // KOSPI PER (KR) / SPY PER (US)
      const capeVal = (t.cape ?? 0).toFixed(1);                       // Shiller CAPE (US)
      const buffettPct = (t.buffett_ratio == null)
        ? null
        : (t.buffett_ratio * 100).toFixed(0);                          // Buffett 비율 (%) 또는 null
      const W = bs.weights || { erp: 0.4, vix: 0.3, dd: 0.3 };
      // 새 5-comp 스키마 (KR) — per_15y/trend 키 존재
      const has5Comp = !!(W.per_15y && W.trend && bs.per_15y && bs.trend);
      // 새 6-comp 스키마 (US) — cape/buffett/trend 키 존재
      const has6Comp = !!(W.cape && W.buffett && W.trend && bs.cape_15y && bs.buffett_15y && bs.trend);
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

      // region 별 라벨 (US: S&P500/미국 국채/VIX, KR: KOSPI/KR 국고채/VKOSPI)
      const isKr = (typeof window.getRegion === 'function') && window.getRegion() === 'kr';
      const L = isKr
        ? { per_label: 'KOSPI 주가수익비율 (PER)',
            tnx_label: '10년 KR 국고채 금리',
            vix_label: '한국 변동성지수 (VKOSPI)',
            vix_caption: '(20↑ 불안 · 30↑ 패닉)' }
        : { per_label: 'S&P 500 주가수익비율 (PER)',
            tnx_label: '10년 미국 국채 금리',
            vix_label: '월가 공포지수 (VIX)',
            vix_caption: '(20↑ 불안 · 30↑ 패닉)' };

      // 1) 수식 — 일반어. 5-comp 활성 시 PER + 추세 추가, 아니면 기존 3-comp.
      const _plus = '<span style="color:#6b7280;">+</span>';
      if (has6Comp) {
        fEl.innerHTML = `5/15년 분포와 비교한 <b>종합 점수</b> = `
          + `Shiller CAPE(${wPct(W.cape)}%) ${_plus} Buffett 비율(${wPct(W.buffett)}%) ${_plus} `
          + `추세 위치(${wPct(W.trend)}%) ${_plus} 주식 매력도(${wPct(W.erp)}%) ${_plus} `
          + `공포(${wPct(W.vix)}%) ${_plus} 하락충격(${wPct(W.dd)}%)`;
      } else if (has5Comp) {
        fEl.innerHTML = `5/15년 분포와 비교한 <b>종합 점수</b> = `
          + `PER 레벨(${wPct(W.per_15y)}%) ${_plus} 추세 위치(${wPct(W.trend)}%) ${_plus} `
          + `주식 매력도(${wPct(W.erp)}%) ${_plus} 공포(${wPct(W.vix)}%) ${_plus} 하락충격(${wPct(W.dd)}%)`;
      } else {
        fEl.innerHTML = `5년 평균과 비교한 <b>종합 점수</b> = 주식 매력도(${wPct(W.erp)}%) ${_plus} 공포(${wPct(W.vix)}%) ${_plus} 하락충격(${wPct(W.dd)}%)`;
      }

      // 2) 게이지 — composite z 기반
      gEl.innerHTML = renderGauge(zComp, t.label);

      // 3) 분해 — 별도 상세페이지로 이동, 메인엔 요약 + "자세히 보기" 트리거
      const decomposeHtml = `
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>${L.per_label}</span>
          <span class="mv-val">${(t.spy_per || 0).toFixed(1)}배</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">−</span>${L.tnx_label}</span>
          <span class="mv-val" style="color:#f59e0b;">${ty}%</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">=</span><span>주식 매력도 <small style="color:#6b7280;font-weight:400;">(1÷PER − 국채금리, 양수면 주식 우위)</small></span></span>
          <span class="mv-val" style="color:${t.erp >= 0 ? '#10b981' : '#ef4444'};">${erpSign}${erp}%</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span><span>${L.vix_label} <small style="color:#6b7280;font-weight:400;">${L.vix_caption}</small></span></span>
          <span class="mv-val" style="color:#7c3aed;">${vix}</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>최근 60일 고점 대비 하락</span>
          <span class="mv-val" style="color:${(t.dd_60d ?? 0) >= -0.03 ? '#10b981' : '#ef4444'};">${dd}%</span>
        </div>
        ${has5Comp ? `
        <div class="mv-row" style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px;">
          <span class="mv-key"><span class="mv-op"></span>${L.per_label} (15년 평균 ${bs.per_15y.mean ? bs.per_15y.mean.toFixed(1) : '?'}배 대비)</span>
          <span class="mv-val" style="color:#a855f7;">${perVal}배</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>가격 vs 200일 평균 (5년 평균 ${bs.trend.mean != null ? (bs.trend.mean * 100).toFixed(1) + '%' : '?'} 대비)</span>
          <span class="mv-val" style="color:${(t.price_vs_ma200 ?? 0) >= 0 ? '#10b981' : '#ef4444'};">${sgn(t.price_vs_ma200 ?? 0)}${trendPct}%</span>
        </div>
        ` : ''}
        ${has6Comp ? `
        <div class="mv-row" style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px;">
          <span class="mv-key"><span class="mv-op"></span>Shiller CAPE (15년 평균 ${bs.cape_15y.mean ? bs.cape_15y.mean.toFixed(1) : '?'}배 대비)</span>
          <span class="mv-val" style="color:#a855f7;">${capeVal}배</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>Buffett 비율 (시총÷GDP, 15년 평균 ${bs.buffett_15y.mean != null ? (bs.buffett_15y.mean*100).toFixed(0) + '%' : '?'} 대비)</span>
          <span class="mv-val" style="color:${buffettPct == null ? '#6b7280' : '#a855f7'};">${buffettPct == null ? '데이터 없음' : buffettPct + '%'}</span>
        </div>
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op"></span>가격 vs 200일 평균 (5년 평균 ${bs.trend.mean != null ? (bs.trend.mean * 100).toFixed(1) + '%' : '?'} 대비)</span>
          <span class="mv-val" style="color:${(t.price_vs_ma200 ?? 0) >= 0 ? '#10b981' : '#ef4444'};">${sgn(t.price_vs_ma200 ?? 0)}${trendPct}%</span>
        </div>
        ` : ''}
        <div class="mv-row" style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.05);padding-top:10px;">
          ${has5Comp ? `
          <span class="mv-key"><span class="mv-op">${wPct(W.per_15y)}%</span><span>PER 레벨 점수 <small style="color:#6b7280;font-weight:400;">(평균 대비 ${zPer < 0 ? '비쌈' : zPer > 0 ? '쌈' : '평소'})</small></span></span>
          <span class="mv-val" style="color:${zPer >= 0 ? '#10b981' : '#ef4444'};">${sgn(zPer)}${zPer.toFixed(2)}σ</span>
          ` : ''}
          ${has6Comp ? `
          <span class="mv-key"><span class="mv-op">${wPct(W.cape)}%</span><span>CAPE 점수 <small style="color:#6b7280;font-weight:400;">(15년 평균 대비 ${zCape < 0 ? '비쌈' : zCape > 0 ? '쌈' : '평소'})</small></span></span>
          <span class="mv-val" style="color:${zCape >= 0 ? '#10b981' : '#ef4444'};">${sgn(zCape)}${zCape.toFixed(2)}σ</span>
          ` : ''}
        </div>
        ${has6Comp ? `
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">${wPct(W.buffett)}%</span><span>Buffett 점수 <small style="color:#6b7280;font-weight:400;">(15년 평균 대비 ${zBuffett < 0 ? '비쌈' : zBuffett > 0 ? '쌈' : '평소'})</small></span></span>
          <span class="mv-val" style="color:${zBuffett >= 0 ? '#10b981' : '#ef4444'};">${sgn(zBuffett)}${zBuffett.toFixed(2)}σ</span>
        </div>
        ` : ''}
        ${(has5Comp || has6Comp) ? `
        <div class="mv-row">
          <span class="mv-key"><span class="mv-op">${wPct(W.trend)}%</span><span>추세 위치 점수 <small style="color:#6b7280;font-weight:400;">(평균 대비 ${zTrend < 0 ? '추세 위' : zTrend > 0 ? '추세 아래' : '평소'})</small></span></span>
          <span class="mv-val" style="color:${zTrend >= 0 ? '#10b981' : '#ef4444'};">${sgn(zTrend)}${zTrend.toFixed(2)}σ</span>
        </div>
        ` : ''}
        <div class="mv-row">
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
      dEl.innerHTML = `
        <button class="mv-detail-trigger" type="button">
          <span class="mv-trigger-label">분해 보기</span>
          <span class="mv-trigger-sub">PER · 국채 · 매력도 · ${L.vix_label.split(' ')[0]} · 60일 하락 + 가중 점수</span>
          <span class="mv-trigger-arrow">▸</span>
        </button>`;
      dEl.querySelector('.mv-detail-trigger').addEventListener('click', () => {
        if (typeof window.openDetail === 'function') {
          window.openDetail('시장 밸류 분해', body => { body.innerHTML = decomposeHtml; });
        }
      });

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
    // 게이지 범위 ±3σ — 사용자 보고 "z=-2.02 가 게이지 끝박힘". 5-comp 가
    // 절대 valuation 신호 강해 |z|>2 흔히 도달, ±2σ 클램프면 끝박힘 빈번.
    // ±3σ 로 늘려 -2.02 → 좌측 1/3 위치, 시각 여유 확보.
    const minZ = -3, maxZ = 3;
    const clamped = Math.max(minZ, Math.min(maxZ, z));
    const ratio = (clamped - minZ) / (maxZ - minZ);    // 0 ~ 1
    const angle = 180 - ratio * 180;                     // 180 → 0
    const cx = 110, cy = 110, r = 90;
    const rad = (angle * Math.PI) / 180;
    const x = cx + r * Math.cos(rad);
    const y = cy - r * Math.sin(rad);

    // 색 segment 경계도 ±3σ 매핑에 맞춰 조정 (label_from_z_comp 임계 ±1.0 기준):
    //   180° (z=-3) ~ 150° (z=-1) 빨강 = 명확한 고평가
    //   150° (z=-1) ~ 90°  (z=0)  주황 = 다소 고평가
    //   90°  (z=0)  ~ 30°  (z=+1) 초록 = 다소 저평가
    //   30°  (z=+1) ~ 0°   (z=+3) 파랑 = 명확한 저평가
    const segs = [
      { from: 180, to: 150, color: '#ef4444' },
      { from: 150, to: 90,  color: '#f59e0b' },
      { from: 90,  to: 30,  color: '#10b981' },
      { from: 30,  to: 0,   color: '#3b82f6' },
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
        <text x="${pad.l}" y="${H - 3}" font-size="9" fill="#6b7280">${_xLeftLabel(history)}</text>
        <text x="${pad.l + innerW}" y="${H - 3}" text-anchor="end" font-size="9" fill="#6b7280">오늘</text>
      </svg>`;
  }

  // history 첫 row 의 date 와 오늘 차이로 가변 라벨 ("10년 전" / "5년 전" / "3개월 전" 등)
  function _xLeftLabel(history) {
    if (!history || !history.length) return '';
    const first = history[0].date;
    if (!first) return '';
    const d0 = new Date(first), now = new Date();
    const days = Math.floor((now - d0) / 86400000);
    if (days >= 365 * 8)  return `${Math.round(days / 365)}년 전`;
    if (days >= 365 * 2)  return `${Math.round(days / 365)}년 전`;
    if (days >= 365)      return '1년 전';
    if (days >= 60)       return `${Math.round(days / 30)}개월 전`;
    return `${days}일 전`;
  }

  // ─────────────────────────────────────────────────────────────
  // 상승·하락 신호 (crash_surge regressor) — 신호 vs 가격 이중축
  // ─────────────────────────────────────────────────────────────
  let _csDays = 252;
  const CS_LEAD = 20;
  async function loadCrashSurge(days) {
    if (typeof days === 'number') _csDays = days;
    const sumEl = document.getElementById('cs-summary');
    const volEl = document.getElementById('cs-volatility');
    const chartEl = document.getElementById('cs-chart');
    const _SPIN = '<div class="loading-placeholder"><div class="loading-spinner sm"></div></div>';
    [sumEl, volEl, chartEl].forEach(el => el && (el.innerHTML = _SPIN));
    if (chartEl && typeof window.attachPeriodToggle === 'function') {
      window.attachPeriodToggle(chartEl, _csDays, p => loadCrashSurge(p));
    }
    const wr = (typeof window.withRegion === 'function') ? window.withRegion : (u => u);
    const isKr = (typeof window.getRegion === 'function') && window.getRegion() === 'kr';
    const ticker = isKr ? '069500' : 'SPY';
    const indexLabel = isKr ? 'KOSPI (069500)' : 'S&P 500 (SPY)';
    const interval = _csDays >= 1000 ? '1wk' : '1d';
    const leadBars = interval === '1wk' ? Math.round(CS_LEAD / 5) : CS_LEAD;
    const histDays = _csDays + leadBars + 5;
    try {
      const [curR, histR, macroR, ohlcR] = await Promise.all([
        fetch(wr('/api/crash-surge/current')).then(r => r.json()).catch(() => null),
        fetch(wr('/api/crash-surge/history?days=' + histDays)).then(r => r.json()).catch(() => []),
        fetch(wr('/api/macro/latest')).then(r => r.json()).catch(() => null),
        fetch('/api/chart/ohlc?ticker=' + ticker + '&interval=' + interval).then(r => r.json()).catch(() => null),
      ]);
      if (!curR || curR.crash_score == null || curR.surge_score == null) {
        sumEl.innerHTML = '<span style="color:#ef4444;">데이터 없음</span>';
        return;
      }
      const surge = Number(curR.surge_score) || 0;
      const crash = Number(curR.crash_score) || 0;
      const diff = surge - crash;
      const sign = diff >= 0 ? '+' : '';
      const dCol = diff > 5 ? '#10b981' : diff < -5 ? '#ef4444' : '#94a3b8';
      const dLab = diff > 10 ? '상승 우세' : diff > 3 ? '상승 약우세' : diff < -10 ? '하락 우세' : diff < -3 ? '하락 약우세' : '균형';
      sumEl.innerHTML = `
        <div style="display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:12px 16px">
          <div>
            <div style="font-size:12px;color:#94a3b8;margin-bottom:6px">향후 한달뒤 상승 확률 − 하락 확률</div>
            <div style="font-size:42px;font-weight:800;color:${dCol};line-height:1.05">${sign}${diff.toFixed(1)}<span style="font-size:18px;color:#64748b">p</span></div>
            <div style="font-size:13px;color:${dCol};margin-top:4px;font-weight:600">${dLab}</div>
          </div>
          <div style="display:flex;gap:18px;font-size:12px;color:#cbd5e1">
            <div><div style="color:#94a3b8;margin-bottom:2px">상승</div><div style="font-size:18px;font-weight:700;color:#10b981">${surge.toFixed(1)}</div></div>
            <div><div style="color:#94a3b8;margin-bottom:2px">하락</div><div style="font-size:18px;font-weight:700;color:#ef4444">${crash.toFixed(1)}</div></div>
          </div>
        </div>
        <div style="padding:0 16px 12px;font-size:11px;color:#64748b">기준일 ${escapeHtml(curR.date || '')}</div>`;
      // 변동성 칩
      const vix = macroR && macroR.vix != null ? Number(macroR.vix) : null;
      const volLabel = isKr ? 'VKOSPI' : 'VIX';
      let volCol = '#94a3b8', volTxt = '데이터 없음', volSub = '';
      if (vix != null) {
        if (vix < 15)      { volCol = '#10b981'; volTxt = '낮음';   volSub = '평온 (15 미만)'; }
        else if (vix < 20) { volCol = '#22c55e'; volTxt = '약낮음'; volSub = '정상 (15–20)'; }
        else if (vix < 25) { volCol = '#f59e0b'; volTxt = '보통';   volSub = '경계 (20–25)'; }
        else if (vix < 30) { volCol = '#fb923c'; volTxt = '높음';   volSub = '불안 (25–30)'; }
        else               { volCol = '#ef4444'; volTxt = '매우 높음'; volSub = '패닉 (30↑)'; }
      }
      const vixStr = vix != null ? vix.toFixed(2) : '—';
      volEl.innerHTML = `
        <div style="padding:12px 16px">
          <div style="font-size:12px;color:#94a3b8;margin-bottom:6px">향후 한달간 변동성 예상</div>
          <div style="display:flex;align-items:center;gap:10px">
            <span style="display:inline-block;padding:6px 14px;border-radius:999px;background:${volCol};color:#0b1220;font-weight:800;font-size:14px">${volTxt}</span>
            <span style="font-size:22px;font-weight:700;color:#e2e8f0">${vixStr}</span>
            <span style="font-size:12px;color:#94a3b8">${volLabel}</span>
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:6px">${volSub}</div>
        </div>`;
      // 차트
      const hist = Array.isArray(histR) ? histR.slice() : [];
      hist.sort((a, b) => a.date.localeCompare(b.date));
      const sigMap = new Map();
      hist.forEach(r => {
        if (r && r.date) sigMap.set(r.date, (Number(r.surge_score) || 0) - (Number(r.crash_score) || 0));
      });
      const candles = (ohlcR && Array.isArray(ohlcR.candles)) ? ohlcR.candles : [];
      candles.sort((a, b) => (a.d || '').localeCompare(b.d || ''));
      const wantBars = interval === '1wk' ? Math.ceil(_csDays / 5) : _csDays;
      const recent = candles.slice(-(wantBars + leadBars));
      const maxBack = interval === '1wk' ? 7 : 3;
      function lookup(d) {
        if (sigMap.has(d)) return sigMap.get(d);
        const base = new Date(d + 'T00:00:00');
        for (let k = 1; k <= maxBack; k++) {
          const t = new Date(base); t.setDate(base.getDate() - k);
          const key = t.toISOString().slice(0, 10);
          if (sigMap.has(key)) return sigMap.get(key);
        }
        return null;
      }
      const series = [];
      let nU = 0, nD = 0, hU = 0, hD = 0;
      const TH = 3;
      for (let i = 0; i < recent.length - leadBars; i++) {
        const sig = lookup(recent[i].d);
        const future = recent[i + leadBars];
        const cur = recent[i];
        const px = future && future.c != null ? Number(future.c) : null;
        if (sig != null && px != null) {
          series.push({ date: recent[i].d, price: px, signal: sig });
          const cP = cur && cur.c != null ? Number(cur.c) : null;
          if (cP > 0) {
            const ret = (px - cP) / cP;
            if (sig > TH) { nU++; if (ret > 0) hU++; }
            else if (sig < -TH) { nD++; if (ret < 0) hD++; }
          }
        }
      }
      const nS = nU + nD;
      const acc = nS ? Math.round((hU + hD) / nS * 1000) / 10 : null;
      const aU = nU ? Math.round(hU / nU * 1000) / 10 : null;
      const aD = nD ? Math.round(hD / nD * 1000) / 10 : null;
      if (series.length < 5) {
        chartEl.innerHTML = `<div style="color:#94a3b8;padding:20px;text-align:center">차트 데이터 부족</div>`;
        return;
      }
      const leadLab = interval === '1wk' ? '4주' : '20일';
      chartEl.innerHTML = renderCsChart(series, indexLabel, leadLab);
    } catch(e) {
      console.warn('[crash-surge] failed', e);
      sumEl.innerHTML = `<span style="color:#ef4444;">로드 실패</span>`;
    }
  }
  function renderCsChart(series, indexLabel, leadLab) {
    const W = 960, H = 440;
    const pad = { top: 44, right: 78, bottom: 52, left: 78 };
    const cW = W - pad.left - pad.right, cH = H - pad.top - pad.bottom;
    const n = series.length;
    const prices = series.map(r => r.price);
    const signals = series.map(r => r.signal);
    const pMin = Math.min.apply(null, prices), pMax = Math.max.apply(null, prices);
    const pSpan = (pMax - pMin) || 1;
    const sAbs = Math.max(Math.abs(Math.min.apply(null, signals)), Math.abs(Math.max.apply(null, signals)), 1);
    const sMin = -sAbs, sMax = sAbs, sSpan = sMax - sMin;
    const x = i => pad.left + (n <= 1 ? 0 : (cW * i) / (n - 1));
    const yP = v => pad.top + cH - ((v - pMin) / pSpan) * cH;
    const yS = v => pad.top + cH - ((v - sMin) / sSpan) * cH;
    let pricePath = '', sigPath = '';
    for (let i = 0; i < n; i++) {
      pricePath += (i === 0 ? 'M' : 'L') + x(i).toFixed(1) + ',' + yP(prices[i]).toFixed(1) + ' ';
      sigPath   += (i === 0 ? 'M' : 'L') + x(i).toFixed(1) + ',' + yS(signals[i]).toFixed(1) + ' ';
    }
    const zeroY = yS(0);
    const xLabels = [0, Math.floor(n / 2), n - 1].map(i =>
      `<text x="${x(i).toFixed(1)}" y="${H - 14}" fill="#cbd5e1" font-size="13" font-weight="600" text-anchor="middle">${escapeHtml(series[i].date)}</text>`).join('');
    const leftLabels = `
      <text x="${pad.left - 8}" y="${pad.top + 6}" fill="#10b981" font-size="13" font-weight="700" text-anchor="end">${pMax.toFixed(1)}</text>
      <text x="${pad.left - 8}" y="${pad.top + cH}" fill="#10b981" font-size="13" font-weight="700" text-anchor="end">${pMin.toFixed(1)}</text>`;
    const rightLabels = `
      <text x="${W - pad.right + 8}" y="${pad.top + 6}" fill="#f59e0b" font-size="13" font-weight="700" text-anchor="start">+${sAbs.toFixed(0)}</text>
      <text x="${W - pad.right + 8}" y="${zeroY + 5}" fill="#94a3b8" font-size="12" text-anchor="start">0</text>
      <text x="${W - pad.right + 8}" y="${pad.top + cH}" fill="#f59e0b" font-size="13" font-weight="700" text-anchor="start">−${sAbs.toFixed(0)}</text>`;
    return `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="width:100%;height:auto;max-height:560px">
        <g font-size="17" font-weight="700">
          <rect x="${pad.left}" y="10" width="28" height="7" fill="#10b981" rx="2"/>
          <text x="${pad.left + 36}" y="24" fill="#e2e8f0">${escapeHtml(indexLabel)} 종가 (좌)</text>
          <rect x="${pad.left + 330}" y="10" width="28" height="7" fill="#f59e0b" rx="2"/>
          <text x="${pad.left + 366}" y="24" fill="#e2e8f0">상승−하락 신호 (우)</text>
        </g>
        <text x="${W - pad.right}" y="24" fill="#94a3b8" font-size="13" text-anchor="end">가격 ${escapeHtml(leadLab)} 앞당김</text>
        <line x1="${pad.left}" y1="${zeroY}" x2="${W - pad.right}" y2="${zeroY}" stroke="#334155" stroke-dasharray="3 3"/>
        <path d="${pricePath}" fill="none" stroke="#10b981" stroke-width="4.5" stroke-linejoin="round" stroke-linecap="round"/>
        <path d="${sigPath}" fill="none" stroke="#f59e0b" stroke-width="4.5" stroke-linejoin="round" stroke-linecap="round" opacity="0.95"/>
        ${leftLabels}
        ${rightLabels}
        ${xLabels}
      </svg>
      <div style="font-size:12px;color:#64748b;margin-top:8px;text-align:center">최근 ${n} 봉 · 가격(녹)이 신호(주황)보다 ${escapeHtml(leadLab)} 앞으로 이동 — 두 선이 겹칠수록 신호가 미래 가격 선행</div>`;
  }

  // main.js popstate 가 호출할 수 있도록 window 에 노출
  window.showHome = showHome;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
