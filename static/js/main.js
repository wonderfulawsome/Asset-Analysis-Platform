// ── 상세페이지 캐시 ──
var _csData = null;
var _nrData = null;
var _fgData = null;  // 공포탐욕 데이터 캐시 (인사이트 연동용)

// ── 시장 이성 점수 인사이트 — 양수=이성적, 음수=감정적 (단순 2분할) ──
function _buildFgNoiseInsight(noiseScore) {
  if (noiseScore == null) return '';
  const fgPart = _fgData ? `심리 지수 ${_fgData.score} · ` : '';

  let tag, msg, color, tagColor;
  if (noiseScore >= 0) {
    tag = '이성적 상태';
    msg = `${fgPart}펀더멘털과 주가 흐름이 잘 일치하는 구간`;
    color = '#22C55E';
    tagColor = '#4ADE80';
  } else {
    tag = '감정적 상태';
    msg = `${fgPart}펀더멘털과 주가 사이 괴리가 두드러진 구간`;
    color = '#EF4444';
    tagColor = '#F87171';
  }

  return `<div class="nr-insight" style="margin-top:12px;padding:10px 12px;border-radius:8px;background:${color}08;border-left:3px solid ${color}">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
      <span style="font-size:11px;font-weight:700;color:${tagColor};padding:2px 8px;border:1px solid ${color}30;border-radius:3px">${tag}</span>
      <span style="font-size:10px;color:var(--sub2)">시장 이성 점수 ${noiseScore >= 0 ? '+' : ''}${noiseScore.toFixed(1)}</span>
    </div>
    <div style="font-size:12px;color:var(--sub);line-height:1.5">${msg}</div>
  </div>`;
}

// ── Lucide SVG Inline Icons ──
const LUCIDE_PATHS = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
  cloudDrizzle: '<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242M8 19v1M8 14v1M16 19v1M16 14v1M12 21v1M12 16v1"/>',
  cloudLightning: '<path d="M6 16.326A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 .5 8.973M13 12l-3 5h4l-3 5"/>',
};
function lucideIcon(name, size, sw) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw || 2}" stroke-linecap="round" stroke-linejoin="round">${LUCIDE_PATHS[name] || ''}</svg>`;
}

// NR 국면 데이터 (API 한글 키 기반, 표시 텍스트는 i18n에서 처리)
const NR_PHASES = ['펀더멘털 반영', '펀더멘털 약반영', '펀더멘털-주가 불일치', '센티멘트 지배']; // 국면 목록
// 부호 반전(2026-04-29): 이성적(펀더멘털 반영)=오른쪽, 감정적(센티멘트)=왼쪽
const NR_GAP_POS   = { '펀더멘털 반영': 88, '펀더멘털 약반영': 63, '펀더멘털-주가 불일치': 37, '센티멘트 지배': 12 }; // 갭바 위치 (이성=右)
const NR_GAP_COLOR = { '펀더멘털 반영': '#4CAF50', '펀더멘털 약반영': '#8BC34A', '펀더멘털-주가 불일치': '#FF9800', '센티멘트 지배': '#F44336' }; // 갭바 색상 (의미 기준 — 위치 무관)
const NR_BADGE = {                                // 뱃지 스타일 (텍스트는 i18n)
  '펀더멘털 반영':   { cls: 'badge-green', icon: 'sun' },
  '펀더멘털 약반영': { cls: 'badge-yellow', icon: 'cloud' },
  '펀더멘털-주가 불일치': { cls: 'badge-yellow', icon: 'cloudDrizzle' },
  '센티멘트 지배':   { cls: 'badge-red', icon: 'cloudLightning' },
};
const NR_ICON = {                                 // 아이콘 스타일
  '펀더멘털 반영':   { icon: 'sun',            color: '#10B981', softBg: 'rgba(16,185,129,0.1)' },
  '펀더멘털 약반영': { icon: 'cloud',          color: '#F59E0B', softBg: 'rgba(245,158,11,0.1)' },
  '펀더멘털-주가 불일치': { icon: 'cloudDrizzle',   color: '#F97316', softBg: 'rgba(249,115,22,0.1)' },
  '센티멘트 지배':   { icon: 'cloudLightning', color: '#EF4444', softBg: 'rgba(239,68,68,0.1)' },
};

// ── 피처 설명 사전 (i18n 동적 조회) ──
// getCSFeatureDesc(): 키별로 tFeatLabel/tFeatDesc 함수를 통해 번역 조회
const CS_FEATURE_KEYS = [                         // CS 피처 키 목록
  'SP500_LOGRET_1D','SP500_LOGRET_5D','SP500_LOGRET_10D','SP500_LOGRET_20D',
  'SP500_DRAWDOWN_60D','SP500_MA_GAP_50','SP500_MA_GAP_200','SP500_INTRADAY_RANGE',
  'RV_5D','RV_21D','EWMA_VOL_L94','VOL_OF_VOL_21D',
  'HY_OAS','BBB_OAS','CCC_OAS','DGS10_LEVEL','T10Y3M_SLOPE',
  'VIX_LEVEL','VIX_CHANGE_1D','VIX_PCTL_252D','VXV_MINUS_VIX','SKEW_LEVEL',
  'DTWEXBGS_RET_5D','WTI_RET_5D','VIX9D_MINUS_VIX','VVIX_LEVEL',
  'VARIANCE_RISK_PREMIUM','PARKINSON_VOL_21D','SP500_AMIHUD_ILLIQ_20D',
  'SP500_DOLLAR_VOLUME_Z_20D','DFII10_REAL10Y','T10YIE_BREAKEVEN',
  'SOFR_MINUS_EFFR','NFCI_LEVEL','CORR_EQ_DGS10_60D',
  'HY_OAS_CHG_5D','HY_OAS_CHG_20D','BBB_OAS_CHG_5D','BBB_OAS_CHG_20D',
  'CCC_OAS_CHG_5D','CCC_OAS_CHG_20D','VIX9D_VIX_RATIO','VIX_VIX3M_RATIO','VIX_CHG_5D',
];
// 동적 getter: 매번 현재 언어의 번역을 반환
function getCSFeatureDesc() {                     // CS 피처 설명 사전 생성
  const obj = {};
  CS_FEATURE_KEYS.forEach(k => {
    obj[k] = { label: tFeatLabel(k), desc: tFeatDesc(k) };
  });
  return obj;
}

// NR 피처 키 목록
const NR_FEATURE_KEYS = ['fundamental_gap','erp_zscore','residual_corr','dispersion','amihud','vix_term','hy_spread','realized_vol'];
// 동적 getter: 매번 현재 언어의 번역을 반환
function getNRFeatureDesc() {                     // NR 피처 설명 사전 생성
  const obj = {};
  NR_FEATURE_KEYS.forEach(k => {
    obj[k] = { label: tFeatLabel(k), desc: tFeatDesc(k) };
  });
  return obj;
}

// 하락 전조 등급 스타일 (높을수록 위험 = 빨강)
const CS_GRADE_STYLE = {
  '낮음': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '보통': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '주의': { cls: 'badge-yellow', color: '#F59E0B', bg: 'rgba(245,158,11,0.08)' },
  '경고': { cls: 'badge-red', color: '#EF4444', bg: 'rgba(239,68,68,0.08)' },
  '위험': { cls: 'badge-red', color: '#EF4444', bg: 'rgba(239,68,68,0.08)' },
};
// 상승 전조 등급 스타일 (높을수록 상승 기대 = 초록)
const SURGE_GRADE_STYLE = {
  '낮음': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '보통': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '주의': { cls: 'badge-yellow', color: '#22C55E', bg: 'rgba(34,197,94,0.08)' },
  '경고': { cls: 'badge-green', color: '#22C55E', bg: 'rgba(34,197,94,0.08)' },
  '위험': { cls: 'badge-green', color: '#16A34A', bg: 'rgba(22,163,74,0.08)' },
};

// 티커 라벨 (i18n 동적 조회)
function getTickerLabel(ticker) {                  // 티커명 번역 조회
  return t('ticker.' + ticker) || ticker;          // 번역 없으면 티커 코드 반환
}
// 시장 탭 컨베이어 — region 별 ticker 목록 (US: SPY/QQQ 등, KR: KODEX/TIGER)
const TICKER_LABELS_KEYS_US = ['SPY','QQQ','SOXX','BND','IWM','DIA'];
const TICKER_LABELS_KEYS_KR = ['069500','102110','232080','091160','266420','341850'];
function _curRegion() { return (typeof window.getRegion === 'function') ? window.getRegion() : 'us'; }
function TICKER_LABELS_KEYS_FN() {
  return _curRegion() === 'kr' ? TICKER_LABELS_KEYS_KR : TICKER_LABELS_KEYS_US;
}
// 하위호환 — 일부 코드가 const 로 참조하는 경우 대비
const TICKER_LABELS_KEYS = TICKER_LABELS_KEYS_US;
// 동적 getter: 매번 현재 언어 + region 의 라벨 반환
function getTickerLabels() {
  if (_curRegion() === 'kr') {
    return {
      '069500': 'KODEX 200', '102110': 'TIGER 200', '232080': 'TIGER 코스닥150',
      '091160': 'KODEX 반도체', '266420': 'KODEX 헬스케어', '341850': 'TIGER 리츠',
    };
  }
  return { SPY: 'S&P 500', QQQ: t('ticker.QQQ'), SOXX: t('ticker.SOXX'), BND: t('ticker.BND'), IWM: t('ticker.IWM'), DIA: t('ticker.DIA') };
}

const VIX_LABEL = (v) => v < 15 ? t('vix.low') : v < 25 ? t('vix.normal') : v < 35 ? t('vix.high') : t('vix.danger'); // VIX 등급 번역

function pct(p) { return Math.round(p * 100); }

// 날짜 표시 (i18n.js의 formatDate로 이미 처리됨, 여기서는 추가 설정 불필요)
const now = new Date();

// ── FadeIn Observer (Staggered) ──
const fadeObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
    }
  });
}, { threshold: 0.08 });

function initFadeTargets() {
  document.querySelectorAll('.fade-target').forEach((el, i) => {
    el.style.setProperty('--delay', `${i * 0.07}s`);
    fadeObserver.observe(el);
  });
}

// ── Animated Number Counter ──
function animateNumber(el, target, duration, delay, decimals, suffix) {
  duration = duration || 1200;
  delay = delay || 0;
  decimals = decimals != null ? decimals : 1;
  suffix = suffix || '';
  setTimeout(function() {
    const start = performance.now();
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 4);
      const val = target * ease;
      el.textContent = (decimals === 0 ? Math.round(val) : val.toFixed(decimals)) + suffix;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }, delay);
}

// ── 보유종목 관리 (localStorage) ──
// 보유종목 티커 목록 (이름은 i18n에서 동적 조회)
const AVAILABLE_TICKERS = ['SPY','QQQ','DIA','IWM','VTI','VOO','SOXX','SMH','XLK','XLF','XLE','XLV','XLB','XLP','XLU','XLI','XLRE','ARKK','GLD','SLV','TLT','BND','SCHD','VXUS'];
// 동적 getter: 매번 현재 언어의 이름 반환
function getAvailableHoldings() {                  // 보유종목 목록 + 번역된 이름
  return AVAILABLE_TICKERS.map(tk => ({ ticker: tk, name: t('hold.' + tk) }));
}

const DEFAULT_HOLDINGS = ['SPY', 'QQQ', 'SOXX', 'DIA'];

function getHoldings() {
  try {
    const data = localStorage.getItem('holdings');
    if (!data) {
      // 최초 방문: 기본 보유종목 설정 (설정 화면 스킵)
      setHoldings(DEFAULT_HOLDINGS);
      return DEFAULT_HOLDINGS;
    }
    const arr = JSON.parse(data);
    return Array.isArray(arr) && arr.length > 0 ? arr : null;
  } catch { return null; }
}

function setHoldings(arr) {
  localStorage.setItem('holdings', JSON.stringify(arr));
}

// ── 보유종목 설정 화면 ──
let _setupSelected = [];
// setup 화면 칩/선택 재렌더 (언어 변경 시 호출)
window._rerenderSetupChips = null;

function showHoldingsSetup() {
  const overlay = document.getElementById('holdings-setup');
  const chipsEl = document.getElementById('holdings-chips');
  const selectedEl = document.getElementById('holdings-selected');
  const searchEl = document.getElementById('holdings-search');
  const confirmBtn = document.getElementById('holdings-confirm');

  _setupSelected = getHoldings() || [];
  overlay.style.display = '';

  function renderChips(filter) {
    const q = (filter || '').toUpperCase().trim();
    const filtered = q
      ? getAvailableHoldings().filter(h => h.ticker.includes(q) || h.name.includes(q))
      : getAvailableHoldings();
    chipsEl.innerHTML = filtered.map(h => {
      const sel = _setupSelected.includes(h.ticker) ? ' selected' : '';
      return `<div class="h-chip${sel}" data-ticker="${h.ticker}">${h.ticker} <span style="font-weight:400;color:${sel ? 'rgba(255,255,255,0.7)' : 'var(--sub)'};font-size:11px">${h.name}</span></div>`;
    }).join('');
  }

  function renderSelected() {
    selectedEl.innerHTML = _setupSelected.length === 0
      ? `<span style="color:var(--sub2);font-size:12px">${t('holdings.selectPrompt')}</span>`
      : _setupSelected.map(t =>
          `<div class="h-sel-chip">${t}<span class="h-sel-remove" data-ticker="${t}">✕</span></div>`
        ).join('');
    confirmBtn.disabled = _setupSelected.length === 0;
  }

  // 전역 노출: 언어 전환 시 칩 재렌더
  window._rerenderSetupChips = function() {
    renderChips(searchEl.value);
    renderSelected();
  };

  renderChips('');
  renderSelected();

  searchEl.value = '';
  searchEl.oninput = () => renderChips(searchEl.value);

  chipsEl.onclick = (e) => {
    const chip = e.target.closest('.h-chip');
    if (!chip) return;
    const t = chip.dataset.ticker;
    if (_setupSelected.includes(t)) {
      _setupSelected = _setupSelected.filter(x => x !== t);
    } else {
      _setupSelected.push(t);
    }
    renderChips(searchEl.value);
    renderSelected();
  };

  selectedEl.onclick = (e) => {
    const rm = e.target.closest('.h-sel-remove');
    if (!rm) return;
    _setupSelected = _setupSelected.filter(x => x !== rm.dataset.ticker);
    renderChips(searchEl.value);
    renderSelected();
  };

  // 뒤로가기 버튼 클릭 시 설정 화면 닫기
  document.getElementById('holdings-back').onclick = () => {
    overlay.style.display = 'none';
    window._rerenderSetupChips = null;
  };

  confirmBtn.onclick = () => {
    if (_setupSelected.length === 0) return;
    setHoldings(_setupSelected);
    overlay.style.display = 'none';
    window._rerenderSetupChips = null;
    loadHoldingsSummary();
    loadMarketOverview();
    window._sectorLoaded = false;
  };
}

// 설정 아이콘 클릭
document.getElementById('btn-edit-holdings').addEventListener('click', showHoldingsSetup);

// ── AI 시장 요약 + 탭 해설 ──
let _aiSummaryLoaded = false;

const _aiIconSet = [
  { keys: ['심리','공포','탐욕','fear','greed'], icon: '◈', bg: 'rgba(68,138,255,0.12)', color: '#448aff' },
  { keys: ['방향','상승','하락','direction'],    icon: '▲', bg: 'rgba(0,210,106,0.12)', color: '#00d26a' },
  { keys: ['펀더멘털','noise','괴리','반영'],     icon: '◎', bg: 'rgba(255,140,0,0.12)', color: '#ff8c00' },
  { keys: ['종합','판단','결론','핵심'],          icon: '★', bg: 'rgba(139,92,246,0.12)', color: '#8b5cf6' },
];

function _cleanEmoji(str) {
  let s = str
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}]/gu, '')
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
  // 제목 키워드가 내용과 붙어있으면 강제로 " — " 삽입
  const titles = ['시장 심리', '방향성', '펀더멘털', '종합판단', '종합 판단'];
  for (const t of titles) {
    const idx = s.indexOf(t);
    if (idx !== -1) {
      const after = idx + t.length;
      // 이미 — 가 있으면 skip
      if (s.slice(after, after + 3).trim().startsWith('—')) continue;
      const rest = s.slice(after).trim();
      if (rest) { s = t + ' — ' + rest; break; }
    }
  }
  return s;
}

function _matchIcon(text, idx) {
  const lower = text.toLowerCase();
  for (const item of _aiIconSet) {
    if (item.keys.some(k => lower.includes(k))) return item;
  }
  return _aiIconSet[Math.min(idx, _aiIconSet.length - 1)];
}

function _buildLineHtml(clean, icon, textContent) {
  const content = textContent || clean;
  const badge = `<span class="ai-badge" style="background:${icon.bg};color:${icon.color};">${icon.icon}</span>`;
  // 1차: "제목 — 내용" 분리
  let sep = content.match(/^(.+?)\s*[—]\s*(.+)$/);
  // 2차: 키워드 기반 강제 분리 (LLM이 구분자를 안 넣었을 때)
  if (!sep) {
    const titleKeys = ['시장 심리','방향성','펀더멘털','종합판단','종합 판단'];
    for (const tk of titleKeys) {
      const idx = content.indexOf(tk);
      if (idx !== -1) {
        const afterTitle = idx + tk.length;
        const rest = content.slice(afterTitle).trim();
        if (rest) { sep = [null, tk, rest]; break; }
      }
    }
  }
  if (sep) {
    return `<div class="ai-line">${badge}<div class="ai-line-content"><strong style="color:var(--text-hi);">${sep[1].trim()}</strong> ${sep[2].trim()}</div></div>`;
  }
  return `<div class="ai-line">${badge}<div class="ai-line-content">${content}</div></div>`;
}

function _formatAiText(raw) {
  const lines = raw.split('\n').filter(l => l.trim());
  return lines.map((line, i) => {
    const clean = _cleanEmoji(line);
    if (!clean) return '';
    return _buildLineHtml(clean, _matchIcon(clean, i));
  }).join('');
}

async function loadAiSummary() {
  const el = document.getElementById('ai-summary-text');
  if (!el) return;
  try {
    const res = await fetch(`/api/market-summary/ai-summary?lang=${getLang()}`);
    const d = await res.json();
    if (d.error) {
      el.innerHTML = `<div style="color:var(--sub);font-size:13px;">${d.summary || t('ai.unavailable')}</div>`;
      return;
    }
    const raw = d.summary || '';
    const formatted = _formatAiText(raw);
    const timestamp = d.generated_at
      ? `<div style="font-size:10px;color:var(--sub);margin-top:8px;font-family:var(--mono);">${d.generated_at} KST${d.cached ? ' · cached' : ''}</div>`
      : '';

    if (!_aiSummaryLoaded) {
      _aiSummaryLoaded = true;
      el.innerHTML = '';

      // 줄별 데이터 준비
      const lines = raw.split('\n').filter(l => l.trim());
      const lineData = lines.map((line, i) => {
        const clean = _cleanEmoji(line);
        const icon = _matchIcon(clean, i);
        return { clean, icon };
      }).filter(d => d.clean);

      let lineIdx = 0;
      function nextLine() {
        if (lineIdx >= lineData.length) {
          el.insertAdjacentHTML('beforeend', timestamp);
          return;
        }
        const { clean, icon } = lineData[lineIdx];
        // 제목/내용 분리 (1차: — 구분자, 2차: 키워드 fallback)
        let sep = clean.match(/^(.+?)\s*[—]\s*(.+)$/);
        if (!sep) {
          const titleKeys = ['시장 심리','방향성','펀더멘털','종합판단','종합 판단'];
          for (const tk of titleKeys) {
            const idx = clean.indexOf(tk);
            if (idx !== -1 && clean.slice(idx + tk.length).trim()) {
              sep = [null, tk, clean.slice(idx + tk.length).trim()];
              break;
            }
          }
        }
        const title = sep ? sep[1].trim() : '';
        const body = sep ? sep[2].trim() : clean;
        const badge = `<span class="ai-badge" style="background:${icon.bg};color:${icon.color};">${icon.icon}</span>`;

        // 줄 컨테이너 생성
        const lineDiv = document.createElement('div');
        lineDiv.className = 'ai-line';
        lineDiv.innerHTML = badge + `<div class="ai-line-content">` + (title ? `<strong style="color:var(--text-hi);">${title}</strong> <span class="ai-line-text"></span>` : `<span class="ai-line-text"></span>`) + `</div>`;
        el.appendChild(lineDiv);

        const textSpan = lineDiv.querySelector('.ai-line-text');
        const chars = [...body]; // 유니코드 안전 분리
        let ci = 0;
        function typeChar() {
          if (ci < chars.length) {
            ci += 2;
            if (ci > chars.length) ci = chars.length;
            textSpan.textContent = chars.slice(0, ci).join('');
            setTimeout(typeChar, 10);
          } else {
            lineIdx++;
            setTimeout(nextLine, 150);
          }
        }
        typeChar();
      }
      nextLine();
    } else {
      el.innerHTML = formatted + timestamp;
    }
  } catch (e) {
    console.error('AI summary error:', e);
    el.innerHTML = `<div style="color:var(--sub);font-size:13px;">${t('ai.unavailable')}</div>`;
  }
}

// ── 각 탭 AI 해설 (타이핑 없음, 일반 문단) ──
function _formatExplainText(raw) {
  let text = raw
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
  // 기존 줄바꿈 유지
  text = text.replace(/\n/g, '<br>');
  // 줄바꿈이 없는 경우: 문장 끝(다. 요. 됩니다. 등) 뒤에 줄바꿈 삽입
  if (!text.includes('<br>')) {
    text = text.replace(/(다\.)\s*/g, '$1<br>');
  }
  return text;
}

async function loadAiExplain(tab) {
  const el = document.getElementById(`ai-explain-${tab}-text`);
  if (!el) return;
  try {
    const res = await fetch(`/api/market-summary/ai-explain?tab=${tab}&lang=${getLang()}`);
    const d = await res.json();
    if (d.error) {
      el.innerHTML = `<div style="color:var(--sub);font-size:13px;">${d.explanation || t('ai.explainError')}</div>`;
      return;
    }
    el.innerHTML = _formatExplainText(d.explanation || '');
  } catch (e) {
    console.error(`AI explain ${tab} error:`, e);
    el.innerHTML = `<div style="color:var(--sub);font-size:13px;">${t('ai.explainError')}</div>`;
  }
}

// ── Portfolio Summary Card (gradient) ──
async function loadMarketOverview() {
  // Market Overview 카드 엘리먼트 가져오기
  const el = document.getElementById('portfolio-summary');
  if (!el) return;
  // skeleton UI 초기화
  el.style.background = '';
  el.style.borderColor = '';
  el.style.boxShadow = '';
  // 로딩 중 스켈레톤 표시
  el.innerHTML = `<div class="mo-card">
    <div class="mo-title">${t('mo.title')}</div>
    <div class="mo-row"><span class="mo-label">${t('mo.fearGreed')}</span><span class="mo-value"><span class="mo-skeleton"></span></span></div>
    <div class="mo-row"><span class="mo-label">${t('mo.marketReturn')}</span><span class="mo-value"><span class="mo-skeleton"></span></span></div>
    <div class="mo-row"><span class="mo-label">${t('mo.rsi')}</span><span class="mo-value"><span class="mo-skeleton"></span></span></div>
  </div>`;

  try {
    // 마켓 서머리 API 호출
    const res = await fetch('/api/market-summary/today');
    const d = await res.json();

    // Fear & Greed 데이터 캐시 (인사이트 연동용)
    _fgData = d.fear_greed;

    // Fear & Greed 등급별 색상 결정 (탐욕=초록, 공포=빨강, 나머지=기본)
    const GREED_SET = new Set(['탐욕', '극도 탐욕']);    // API 한글 등급 비교용
    const FEAR_SET = new Set(['공포', '극도 공포']);    // API 한글 등급 비교용
    const fgColor = GREED_SET.has(d.fear_greed.rating) ? '#22C55E'
                  : FEAR_SET.has(d.fear_greed.rating) ? '#EF4444'
                  : '#F97316';

    // Market Return 색상 결정 (양수=초록, 음수=빨강)
    const retVal = d.market_return.value;
    const retColor = retVal >= 0 ? '#22C55E' : '#EF4444';
    const retSign = retVal >= 0 ? '+' : '';

    // RSI 색상/라벨 결정
    const rsi = d.rsi || 0;
    const rsiColor = rsi >= 60 ? '#EF4444' : rsi <= 40 ? '#22C55E' : '#F97316';  // 60 이상 과매수, 40 이하 과매도
    const rsiLabel = rsi >= 60 ? t('rsi.overbought') : rsi <= 40 ? t('rsi.oversold') : t('rsi.neutral'); // RSI 라벨 번역

    // 카드 렌더링
    el.innerHTML = `<div class="mo-card">
      <div class="mo-title">${t('mo.title')}</div>
      <div class="mo-row">
        <span class="mo-label">${t('mo.fearGreed')}</span>
        <span class="mo-value">
          <span class="mo-score" style="color:${fgColor}">${d.fear_greed.score}</span>
          <span class="mo-badge" style="background:${fgColor}20;color:${fgColor}">${tFgRating(d.fear_greed.rating)}</span>
        </span>
      </div>
      <div class="mo-row">
        <span class="mo-label">${t('mo.marketReturn')}</span>
        <span class="mo-value">
          <span class="mo-score" style="color:${retColor}">${retSign}${retVal.toFixed(2)}%</span>
        </span>
      </div>
      <div class="mo-row">
        <span class="mo-label">${t('mo.rsi')}</span>
        <span class="mo-value">
          <span class="mo-score" style="color:${rsiColor}">${rsi > 0 ? rsi.toFixed(1) : '--'}</span>
          <span class="mo-badge" style="background:${rsiColor}20;color:${rsiColor}">${rsi > 0 ? rsiLabel : '-'}</span>
        </span>
      </div>
    </div>`;
    // 공포탐욕 로드 완료 → 인사이트 갱신 (regime이 먼저 로드됐을 경우 대비)
    _tryUpdateFgInsight();
  } catch (e) {
    // API 실패 시 대체 표시
    el.innerHTML = `<div class="mo-card">
      <div class="mo-title">${t('mo.title')}</div>
      <div class="mo-row"><span class="mo-label">${t('mo.fearGreed')}</span><span class="mo-value">-</span></div>
      <div class="mo-row"><span class="mo-label">${t('mo.marketReturn')}</span><span class="mo-value">-</span></div>
      <div class="mo-row"><span class="mo-label">${t('mo.rsi')}</span><span class="mo-value">-</span></div>
    </div>`;
  }
}

// 인사이트 갱신: 두 데이터 모두 있을 때 regime 카드에 삽입
function _tryUpdateFgInsight() {
  if (!_fgData || !_nrData) return;
  const existing = document.querySelector('.nr-insight');
  if (existing) return;  // 이미 있으면 스킵
  const container = document.getElementById('regime-card');
  if (!container) return;
  const ns = _nrData.noise_score ?? null;
  const html = _buildFgNoiseInsight(ns);
  if (html) container.insertAdjacentHTML('beforeend', html);
}

// ── Holdings Summary (시장 탭 하단) ──
async function loadHoldingsSummary() {
  const el = document.getElementById('holdings-summary');
  const holdings = getHoldings();
  if (!holdings) {
    el.innerHTML = `<div class="holdings-empty" id="holdings-empty-prompt">${t('holdings.setPrompt')}</div>`;
    document.getElementById('holdings-empty-prompt').addEventListener('click', showHoldingsSetup);
    return;
  }
  try {
    const res = await fetch('/api/index/latest');
    const list = await res.json();
    if (!Array.isArray(list) || list.length === 0) {
      el.innerHTML = `<div class="loading-placeholder"><div class="loading-spinner sm"></div><span class="loading-text">${t('holdings.loading')}</span></div>`;
      return;
    }
    const priceMap = {};
    list.forEach(item => { priceMap[item.ticker] = item.change_pct; });
    const matched = holdings.filter(t => priceMap[t] !== undefined);
    if (matched.length === 0) {
      el.innerHTML = `<div class="holdings-empty">${t('holdings.noData')}</div>`;
      return;
    }

    // 개별 종목 목록만 표시 (전체수익률 제거)
    let html = '<div class="hs-items">';
    matched.forEach(t => {
      const v = priceMap[t];
      const color = v >= 0 ? 'var(--green)' : 'var(--red)';
      const sign = v >= 0 ? '+' : '';
      html += `<div class="hs-item">
        <span class="hs-ticker">${t}</span>
        <span class="hs-ret" style="color:${color}">${sign}${v.toFixed(2)}%</span>
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
    // Staggered row animation
    el.querySelectorAll('.hs-item').forEach((item, i) => {
      item.style.setProperty('--row-delay', `${i * 0.07}s`);
      setTimeout(() => item.classList.add('row-visible'), 50);
    });
  } catch {
    el.innerHTML = `<div class="holdings-empty">${t('holdings.loadError')}</div>`;
  }
}

// ── Regime (Noise vs Signal) ──
async function loadRegime() {
  let res, data;
  try {
    res  = await fetch('/api/regime/current');
    data = await res.json();
  } catch (e) { console.error('loadRegime error:', e); return; }
  if (!data) return;

  const name  = data.regime_name ?? '';              // API 한글 국면명
  // noise_score 기반 동적 위치 계산 (범위: 5%~95%)
  // 분포 기반 기준: min=-5(P01), mid=0(P50 중앙값), max=10(~P93)
  // 중심점(mid=0)을 50%로, 양쪽 대칭 스케일링
  const ns = data.noise_score ?? null;
  // 부호 반전 후: 양수=이성, 음수=감정. 좌(감정)~우(이성) 게이지에 그대로 매핑.
  let pos;
  if (ns != null) {
    const mid = 0;
    if (ns <= mid) { pos = 5 + ((ns - (-10)) / (mid - (-10))) * 45; }  // -10→5%, 0→50%
    else           { pos = 50 + ((ns - mid) / (5 - mid)) * 45; }       // 0→50%, +5→95%
    pos = Math.max(5, Math.min(95, pos));
  } else { pos = NR_GAP_POS[name] ?? 50; }
  const color = NR_GAP_COLOR[name] ?? '#999';        // 갭바 색상
  const sub   = tNrSub(name);                        // 국면 설명 (i18n)

  // Update badge (i18n)
  const badgeEl = document.getElementById('nr-badge');
  const badgeInfo = NR_BADGE[name];
  if (badgeEl && badgeInfo) {
    badgeEl.className = `badge ${badgeInfo.cls}`;
    badgeEl.textContent = tNrBadge(name);            // 뱃지 텍스트 번역
  }

  _nrData = data;  // 상세페이지용 캐시

  const container = document.getElementById('regime-card');
  const nrIcon = NR_ICON[name] || { icon: 'cloud', color: '#999', softBg: 'rgba(0,0,0,0.05)' };
  container.innerHTML = `
    <div class="nr-status">
      <div class="nr-icon-box" style="background:${nrIcon.softBg};color:${nrIcon.color}">
        ${lucideIcon(nrIcon.icon, 30, 1.8)}
      </div>
      <span class="nr-name">${tNrPhase(name)}</span>
    </div>
    <div class="nr-sub">${sub}</div>
    <div class="nr-gap">
      <div class="nr-gap-labels">
        <span>${t('nr.fundamental')}</span>
        <span>${t('nr.price')}</span>
      </div>
      <div class="nr-gap-track">
        <div class="nr-gap-fill" style="width:${pos}%;background:linear-gradient(to right,#F44336,#FF9800,#8BC34A,#4CAF50)"></div>
        <div class="nr-gap-dot" style="left:${pos}%;border-color:${color}"></div>
      </div>
      <div class="nr-gap-ticks">
        <span>${t('nr.match')}</span>
        <span>${t('nr.gap')}</span>
      </div>
    </div>
    ${_buildFgNoiseInsight(ns)}`;

  // 카드 터치 → 상세페이지
  const card = container.closest('.card');
  if (card && !card.classList.contains('card-tappable')) {
    card.classList.add('card-tappable');
    card.addEventListener('click', () => openDetail('Noise vs Signal', renderNoiseDetail)); // 제목은 영문 고정
  }
}

// ── Macro ──
function deltaArrow(cur, prev, invert) {
  if (prev == null) return '';
  const diff = cur - prev;
  if (Math.abs(diff) < 0.01) return '';
  const arrow = diff > 0 ? '▲' : '▼';
  const up = invert ? 'var(--green)' : 'var(--red)';
  const dn = invert ? 'var(--red)' : 'var(--green)';
  const color = diff > 0 ? up : dn;
  return `<span class="ind-delta" style="color:${color}">${arrow}</span>`;
}

// region 별 정적 라벨 텍스트 갱신 — KR 모드면 VIX→VKOSPI 등
function _applyRegionMarketLabels() {
  const isKr = _curRegion() === 'kr';
  const vixCard = document.querySelector('.ind-card .ind-label');
  // VIX 라벨 (첫 번째 ind-label)
  document.querySelectorAll('.ind-card .ind-label').forEach(el => {
    if (el.textContent.trim() === 'VIX') el.textContent = isKr ? 'VKOSPI' : 'VIX';
    // VKOSPI → VIX 복원 (region 전환 안전망)
    if (el.textContent.trim() === 'VKOSPI' && !isKr) el.textContent = 'VIX';
  });
}


async function loadMacro() {
  let macro, fg;
  try {
    const [macroRes, fgRes] = await Promise.all([
      fetch('/api/macro/latest'),
      fetch('/api/macro/fear-greed'),
    ]);
    macro = await macroRes.json();
    fg    = await fgRes.json();
  } catch (e) { console.error('loadMacro error:', e); return; }
  if (!macro || !fg) return;
  _applyRegionMarketLabels();                         // VIX → VKOSPI 라벨 region 분기

  // VIX
  const vixVal = document.getElementById('vix-val');
  const vixSub = document.getElementById('vix-sub');
  const vixArrow = deltaArrow(macro.vix, macro.prev_vix);
  vixVal.innerHTML = `<span class="num-counter"></span>${vixArrow}`;
  animateNumber(vixVal.querySelector('.num-counter'), macro.vix, 1200, 200, 1);
  const vixLabel = VIX_LABEL(macro.vix);
  vixSub.textContent = vixLabel;
  vixSub.style.color = macro.vix >= 35 ? 'var(--red)'
                      : macro.vix >= 25 ? '#FF9800'
                      : '';

  // VOL
  const vol = macro.sp500_vol20 ?? 0;
  const volVal = document.getElementById('vol-val');
  const volSub = document.getElementById('vol-sub');
  const volArrow = deltaArrow(vol, macro.prev_sp500_vol20);
  volVal.innerHTML = `<span class="num-counter"></span>x${volArrow}`;
  animateNumber(volVal.querySelector('.num-counter'), vol, 1200, 400, 2);
  const volLabel = vol >= 1.5 ? t('vol.surge')    // 거래 급증
                 : vol >= 1.1 ? t('vol.above')    // 평균 이상
                 : vol >= 0.9 ? t('vol.avg')      // 평균
                 : t('vol.low');                   // 거래 감소
  volSub.textContent = volLabel;
  volSub.style.color = vol >= 1.5 ? 'var(--red)'
                     : vol >= 1.1 ? '#FF9800'
                     : '';

  // PUT/CALL Ratio
  const pcVal = document.getElementById('pc-val');
  const pcSub = document.getElementById('pc-sub');
  // macro_raw에서 putcall_ratio 컬럼 가져오기
  const pcRatio = macro.putcall_ratio ?? 0;
  if (pcRatio > 0) {
    // 숫자 애니메이션으로 PUT/CALL ratio 표시
    pcVal.innerHTML = `<span class="num-counter"></span>`;
    animateNumber(pcVal.querySelector('.num-counter'), pcRatio, 1200, 500, 2);
    // 1.1 이상이면 하방 옵션(풋 우세), 0.9 이하면 상방 옵션(콜 우세)
    const pcLabel = pcRatio >= 1.1 ? t('pc.bearish') : pcRatio <= 0.9 ? t('pc.bullish') : t('pc.neutral'); // P/C 라벨 번역
    pcSub.textContent = pcLabel;
    // 하방=빨강, 상방=초록
    pcSub.style.color = pcRatio >= 1.1 ? 'var(--red)' : pcRatio <= 0.9 ? 'var(--green)' : '';
  } else {
    // 데이터 없으면 대시 표시
    pcVal.textContent = '--';
    pcSub.textContent = '--';
  }

}

// ── Ticker Feed ──
function setupTickerDrift() {
  const section   = document.querySelector('.feed-section');
  const container = document.getElementById('feed-list');
  if (!section || !container) return;

  const PX_PER_SEC = 9;
  const RAMP_MS    = 400;
  const IDLE_MS    = 5500;
  const FRICTION   = 0.85;

  let half      = 0;
  let offset    = 0;
  let running   = true;
  let rampStart = null;
  let lastTs    = null;
  let idleTimer = null;

  let isDragging = false;
  let dragLastX  = 0;
  let velocity   = 0;
  let inertia    = false;

  function smoothstep(t) { return t * t * (3 - 2 * t); }
  function wrap(v)       { return ((v % half) + half) % half; }

  function setOffset(v) {
    offset = wrap(v);
    container.style.transform = `translateX(${-offset}px)`;
  }

  function frame(ts) {
    if (!half) half = container.scrollWidth / 2;
    if (lastTs === null) lastTs = ts;
    const dt = Math.min((ts - lastTs) / 1000, 0.05);
    lastTs = ts;

    if (isDragging) {
      // pointer event handles it
    } else if (inertia) {
      velocity *= FRICTION;
      setOffset(offset + velocity);
      if (Math.abs(velocity) < 0.3) { inertia = false; velocity = 0; }
    } else if (running && half > 0) {
      if (rampStart === null) rampStart = ts;
      const factor = smoothstep(Math.min((ts - rampStart) / RAMP_MS, 1));
      setOffset(offset + PX_PER_SEC * dt * factor);
    }

    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);

  function stopAuto() {
    running = false;
    rampStart = null;
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
  }

  function scheduleResume() {
    idleTimer = setTimeout(() => {
      running = true; rampStart = null; lastTs = null;
    }, IDLE_MS);
  }

  section.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    isDragging = true;
    inertia    = false;
    velocity   = 0;
    dragLastX  = e.clientX;
    section.setPointerCapture(e.pointerId);
    stopAuto();
  });

  section.addEventListener('pointermove', (e) => {
    if (!isDragging) return;
    const dx = dragLastX - e.clientX;
    velocity = dx * 0.5 + velocity * 0.5;
    setOffset(offset + dx);
    dragLastX = e.clientX;
  });

  function onUp() {
    if (!isDragging) return;
    isDragging = false;
    inertia = Math.abs(velocity) > 0.8;
    if (!inertia) velocity = 0;
    scheduleResume();
  }

  section.addEventListener('pointerup',     onUp);
  section.addEventListener('pointercancel', onUp);
}

async function loadFeed() {
  let res, list;
  try {
    res  = await fetch('/api/index/latest');
    list = await res.json();
  } catch (e) { console.error('loadFeed error:', e); return; }
  if (!Array.isArray(list)) return;
  const container = document.getElementById('feed-list');

  const feed = list.filter(({ ticker }) => getTickerLabels()[ticker]);
  const html = feed.map(({ ticker, change_pct }) => {
    const sign  = change_pct >= 0 ? '+' : '';
    const cls   = change_pct >= 0 ? 'pos' : 'neg';
    const label = getTickerLabels()[ticker] ?? ticker;
    return `<div class="feed-item">
        <div class="feed-ticker">${label}</div>
        <div class="feed-chg ${cls}">${sign}${change_pct.toFixed(2)}%</div>
      </div>`;
  }).join('');

  container.innerHTML = html + html;
  setupTickerDrift();
}

// ── 네비게이션 히스토리 관리 ──
let _currentTabIdx = 0;                                    // 현재 활성 탭 인덱스
let _lastBackTime = 0;                                     // 마지막 뒤로가기 시간 (앱 종료용)
const _isApp = /android|iphone|ipad/i.test(navigator.userAgent); // 앱/모바일 여부

// 탭 전환 함수 (pushState 옵션)
function switchTab(idx, addHistory) {
  const tabs = document.querySelectorAll('.tab');           // 탭 버튼들
  tabs.forEach(tb => tb.classList.remove('active'));         // 모든 탭 비활성화
  tabs[idx].classList.add('active');                        // 선택 탭 활성화
  TAB_IDS.forEach(id => {                                  // 모든 탭 컨텐츠 숨기기
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
  const target = TAB_IDS[idx];                             // 대상 탭 ID
  if (target) {
    const el = document.getElementById(target);
    if (el) {
      el.style.display = '';                               // 대상 탭 표시
      setTimeout(() => {                                   // 페이드인 애니메이션
        el.querySelectorAll('.fade-target').forEach(ft => ft.classList.add('visible'));
      }, 50);
    }
  }
  // AI차트 탭 최초 진입 시 초기화 (idx=0)
  if (idx === 0 && typeof initChartTab === 'function' && !window._chartLoaded) {
    window._chartLoaded = true;
    initChartTab();
  }
  // 시장 탭 진입 시 AI 요약 로드
  if (idx === 1) {
    if (typeof loadAiSummary === 'function') loadAiSummary();
  }
  // 펀더멘털 탭 진입 시 noise 차트 재렌더 + AI 해설
  if (idx === 2) {
    setTimeout(() => { if (typeof loadNoiseChart === 'function') loadNoiseChart(); }, 100);
    loadAiExplain('fundamental');
  }
  // 신호 탭 진입 시 차트 로드 + AI 해설
  if (idx === 3) {
    if (!window._signalLoaded) {
      window._signalLoaded = true;
      loadCrashSurge();
    }
    setTimeout(() => loadCrashSurgeChart(), 100);
    loadAiExplain('signal');
  }
  // 거시경제 탭 최초 진입 시 데이터 로드 + AI 해설
  if (idx === 4) {
    if (typeof loadSectorCycle === 'function' && !window._sectorLoaded) {
      window._sectorLoaded = true;
      loadSectorCycle();
    }
    loadAiExplain('sector');
  }
  // 히스토리에 상태 추가 (뒤로가기 지원)
  if (addHistory && idx !== _currentTabIdx) {
    history.pushState({ tab: idx }, '');
  }
  _currentTabIdx = idx;                                    // 현재 탭 인덱스 갱신
}

// ── 탭 전환 ──
const TAB_IDS = ['tab-chart', 'tab-market', 'tab-fundamental', 'tab-signal', 'tab-sector'];
const tabs = document.querySelectorAll('.tab');
tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const idx = parseInt(tab.dataset.idx, 10);             // 클릭한 탭 인덱스
    switchTab(idx, true);                                  // 히스토리 추가하며 전환
  });
});

// ── 뒤로가기(popstate) 처리 ──
// 변경된 동작:
//   1. detail overlay 열려있음 → 닫기
//   2. 탭 페이지 활성 (home view 숨김 상태) → home view 로 무조건 복귀 (탭 history 무시)
//   3. home view 활성 → 2초 내 두 번 누르면 종료
window.addEventListener('popstate', (e) => {
  const overlay = document.getElementById('detail-overlay');
  if (overlay && overlay.classList.contains('open')) {
    overlay.classList.remove('open');
    return;
  }
  const homeView = document.getElementById('home-view');
  const homeActive = homeView && homeView.style.display !== 'none' && !homeView.hidden;

  if (!homeActive) {
    // 탭 또는 sector-tab 활성 → home 으로 복귀
    if (typeof window.showHome === 'function') {
      window.showHome();
    } else if (homeView) {
      // fallback — home.js 미로딩 상황
      homeView.style.display = '';
      const sw = document.querySelector('.scroll-wrap');
      if (sw) sw.style.display = 'none';
      const bk = document.getElementById('back-to-home');
      if (bk) bk.hidden = true;
      document.body.classList.remove('with-back');
    }
    history.pushState({ view: 'home' }, '');               // 다음 뒤로가기 위한 history 보충
    return;
  }

  // home view 활성 → 2-tap 종료
  const now = Date.now();
  if (now - _lastBackTime < 2000) {
    return;                                                 // 브라우저 기본 (앱 종료)
  }
  _lastBackTime = now;
  history.pushState({ view: 'home' }, '');
  showBackToast();
});

// 초기 히스토리 상태 설정 — home 시작
history.replaceState({ view: 'home' }, '');

// ── 뒤로가기 토스트 메시지 ──
function showBackToast() {
  let toast = document.getElementById('back-toast');
  if (!toast) {                                            // 토스트 엘리먼트가 없으면 생성
    toast = document.createElement('div');
    toast.id = 'back-toast';
    toast.className = 'back-toast';
    toast.textContent = t('toast.backExit');          // 토스트 메시지 번역
    document.body.appendChild(toast);
  }
  toast.classList.add('show');                              // 토스트 표시
  setTimeout(() => toast.classList.remove('show'), 2000);  // 2초 후 숨기기
}

// ── 탭 스와이프 제스처 ──
// 횡스크롤 영역 판정 함수 (동적 요소 대응)
function _isHScrollArea(el) {
  if (!el || !el.closest) return false;
  // 클래스 기반 체크 (동적 생성 요소 포함)
  if (el.closest('.candle-scroll') || el.closest('.volume-scroll') ||
      el.closest('.chart-ticker-chips') || el.closest('.chart-ticker-bar') ||
      el.closest('.ma-legend')) return true;
  // overflow-x 스크롤 가능한 요소 체크
  let node = el;
  while (node && node !== document.body) {
    const style = window.getComputedStyle(node);
    if ((style.overflowX === 'auto' || style.overflowX === 'scroll') &&
        node.scrollWidth > node.clientWidth + 2) return true;
    node = node.parentElement;
  }
  return false;
}

function setupTabSwipe() {
  const wrap = document.querySelector('.scroll-wrap');       // 스크롤 영역
  if (!wrap) return;

  const THRESHOLD_X = 70;                                    // 스와이프 최소 거리 (px)
  const MAX_VISUAL  = 80;                                    // 드래그 시 최대 이동량 (px)
  const MAX_TIME    = 400;                                   // 스와이프 최대 시간 (ms)
  const DIR_LOCK_PX = 15;                                    // 방향 결정 최소 이동 (px)
  const MAX_VERT    = 30;                                    // 수직 스크롤 판정 임계 (px)

  let startX = 0, startY = 0, startTime = 0;                // 터치 시작 좌표/시간
  let dirLocked = false, isSwipe = null;                     // 방향 상태
  let activeEl = null, lastX = 0;                            // 활성 엘리먼트, 마지막 X

  wrap.addEventListener('touchstart', (e) => {
    const overlay = document.getElementById('detail-overlay');
    if (overlay && overlay.classList.contains('open')) { activeEl = null; return; }
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
    lastX = startX;
    startTime = Date.now();
    dirLocked = false;
    isSwipe = null;
    activeEl = null;
    // 횡스크롤 영역 안이면 탭 스와이프 비활성화
    if (_isHScrollArea(e.target)) {
      isSwipe = false;
      return;
    }
    activeEl = document.getElementById(TAB_IDS[_currentTabIdx]);
    if (activeEl) activeEl.style.transition = 'none';
  }, { passive: true });

  wrap.addEventListener('touchmove', (e) => {
    if (isSwipe === false || !activeEl) return;
    // 횡스크롤 영역 체크 (touchstart 이후 타겟 변경 방어)
    if (_isHScrollArea(e.target)) {
      isSwipe = false; activeEl = null; return;
    }
    const cx = e.touches[0].clientX;
    const cy = e.touches[0].clientY;
    lastX = cx;
    const dx = cx - startX, dy = cy - startY;
    const adx = Math.abs(dx), ady = Math.abs(dy);

    if (!dirLocked) {
      if (adx < DIR_LOCK_PX && ady < DIR_LOCK_PX) return;
      if (ady > MAX_VERT && adx < ady) { isSwipe = false; return; }
      // 수평이 수직보다 2.5배 이상이어야 스와이프 판정
      if (adx > ady * 2.5) { isSwipe = true; dirLocked = true; }
      else if (ady >= adx) { isSwipe = false; dirLocked = true; return; }
      else return;
    }

    e.preventDefault();
    let clampedDx = Math.max(-MAX_VISUAL, Math.min(MAX_VISUAL, dx));
    if ((_currentTabIdx === 0 && dx > 0) || (_currentTabIdx === TAB_IDS.length - 1 && dx < 0)) {
      clampedDx = clampedDx / 3;
    }
    activeEl.style.transform = `translateX(${clampedDx}px)`;
  }, { passive: false });

  wrap.addEventListener('touchend', () => {
    if (!activeEl) return;
    activeEl.style.transition = 'transform 0.2s ease-out';
    activeEl.style.transform = '';
    if (isSwipe !== true) return;

    const dx = lastX - startX;
    const elapsed = Date.now() - startTime;
    if (Math.abs(dx) >= THRESHOLD_X && elapsed < MAX_TIME) {
      const newIdx = dx < 0
        ? Math.min(_currentTabIdx + 1, TAB_IDS.length - 1)
        : Math.max(_currentTabIdx - 1, 0);
      if (newIdx !== _currentTabIdx) switchTab(newIdx, true);
    }
  }, { passive: true });

  let mStartX = 0, mStartY = 0, mStartTime = 0;
  let mDirLocked = false, mIsSwipe = null;
  let mActiveEl = null, mLastX = 0;

  wrap.addEventListener('mousedown', (e) => {
    const overlay = document.getElementById('detail-overlay');
    if (overlay && overlay.classList.contains('open')) { mActiveEl = null; return; }
    if (_isHScrollArea(e.target)) { mIsSwipe = false; return; }
    mStartX = e.clientX;
    mStartY = e.clientY;
    mLastX = mStartX;
    mStartTime = Date.now();
    mDirLocked = false;
    mIsSwipe = null;
    mActiveEl = document.getElementById(TAB_IDS[_currentTabIdx]);
    if (mActiveEl) mActiveEl.style.transition = 'none';
  });

  window.addEventListener('mousemove', (e) => {
    if (mIsSwipe === false || !mActiveEl) return;
    if (_isHScrollArea(e.target)) { mIsSwipe = false; mActiveEl = null; return; }
    const cx = e.clientX;
    const cy = e.clientY;
    mLastX = cx;
    const dx = cx - mStartX, dy = cy - mStartY;
    const adx = Math.abs(dx), ady = Math.abs(dy);

    if (!mDirLocked) {
      if (adx < DIR_LOCK_PX && ady < DIR_LOCK_PX) return;
      if (ady > MAX_VERT && adx < ady) { mIsSwipe = false; return; }
      if (adx > ady * 2.5) { mIsSwipe = true; mDirLocked = true; }
      else if (ady >= adx) { mIsSwipe = false; mDirLocked = true; return; }
      else return;
    }

    e.preventDefault();
    let clampedDx = Math.max(-MAX_VISUAL, Math.min(MAX_VISUAL, dx));
    if ((_currentTabIdx === 0 && dx > 0) || (_currentTabIdx === TAB_IDS.length - 1 && dx < 0)) {
      clampedDx = clampedDx / 3;
    }
    mActiveEl.style.transform = `translateX(${clampedDx}px)`;
  });

  window.addEventListener('mouseup', () => {
    if (!mActiveEl) return;
    mActiveEl.style.transition = 'transform 0.2s ease-out';
    mActiveEl.style.transform = '';
    if (mIsSwipe !== true) { mActiveEl = null; return; }

    const dx = mLastX - mStartX;
    const elapsed = Date.now() - mStartTime;
    if (Math.abs(dx) >= THRESHOLD_X && elapsed < MAX_TIME) {
      const newIdx = dx < 0
        ? Math.min(_currentTabIdx + 1, TAB_IDS.length - 1)
        : Math.max(_currentTabIdx - 1, 0);
      if (newIdx !== _currentTabIdx) switchTab(newIdx, true);
    }
    mActiveEl = null;
  });
}
setupTabSwipe();

// ── Crash/Surge 전조 탐지 ──
async function loadCrashSurge() {
  try {
    const res = await fetch('/api/crash-surge/current');
    const d = await res.json();
    if (!d) {
      document.getElementById('cs-card').innerHTML =
        `<div class="loading-placeholder"><div class="loading-spinner sm"></div><span class="loading-text">${t('holdings.loading')}</span></div>`;
      return;
    }

    _csData = d;  // 상세페이지용 캐시

    // 변동성 판정: 둘 다 60 미만이면 보통, 하나라도 60 이상이면 높음
    const isHighVol = d.crash_score >= 60 || d.surge_score >= 60;
    const volLabel = isHighVol ? t('cs.volHigh') : t('cs.volNormal');
    const volCls = isHighVol ? 'badge-red' : 'badge-green';

    const badge = document.getElementById('cs-badge');
    badge.className = `badge ${volCls}`;
    badge.textContent = volLabel;

    // 하락 가능성: 점수 기반 라벨 (경고 없음)
    const crashLabel = d.crash_score < 40 ? t('grade.low') : d.crash_score < 60 ? t('grade.normal') : t('grade.high');
    const crashS = d.crash_score < 40
      ? { cls: 'badge-green', color: '#10B981' }
      : d.crash_score < 60
      ? { cls: 'badge-yellow', color: '#F59E0B' }
      : { cls: 'badge-red', color: '#EF4444' };

    // 상승 기대도: 점수 기반 라벨 (낮음=빨강/보통=노랑/높음=초록)
    const surgeLabel = d.surge_score < 40 ? t('grade.low') : d.surge_score < 60 ? t('grade.normal') : t('grade.high');
    const surgeS = d.surge_score < 40
      ? { cls: 'badge-red', color: '#EF4444' }
      : d.surge_score < 60
      ? { cls: 'badge-yellow', color: '#F59E0B' }
      : { cls: 'badge-green', color: '#22C55E' };

    const el = document.getElementById('cs-card');
    el.innerHTML = `
      <div class="cs-row">
        <div class="cs-item">
          <div class="cs-item-header">
            <span class="cs-item-label">${t('cs.crashRisk')}</span>
            <span class="badge ${crashS.cls}" style="font-size:10px">${crashLabel}</span>
          </div>
          <div class="cs-score" style="color:${crashS.color}">
            <span class="cs-score-num" data-target="${d.crash_score}">0</span>
          </div>
          <div class="cs-bar-track">
            <div class="cs-bar-fill cs-bar-crash" style="width:0%;background:${crashS.color}"></div>
          </div>
        </div>
        <div class="cs-divider"></div>
        <div class="cs-item">
          <div class="cs-item-header">
            <span class="cs-item-label">${t('cs.surgeExpect')}</span>
            <span class="badge ${surgeS.cls}" style="font-size:10px">${surgeLabel}</span>
          </div>
          <div class="cs-score" style="color:${surgeS.color}">
            <span class="cs-score-num" data-target="${d.surge_score}">0</span>
          </div>
          <div class="cs-bar-track">
            <div class="cs-bar-fill cs-bar-surge" style="width:0%;background:${surgeS.color}"></div>
          </div>
        </div>
      </div>
      <div class="cs-date">${d.date} ${t('cs.asOf')}</div>`;

    el.querySelectorAll('.cs-score-num').forEach(num => {
      animateNumber(num, parseFloat(num.dataset.target), 1200, 100, 1);
    });

    setTimeout(() => {
      const crashBar = el.querySelector('.cs-bar-crash');
      const surgeBar = el.querySelector('.cs-bar-surge');
      if (crashBar) crashBar.style.width = `${d.crash_score}%`;
      if (surgeBar) surgeBar.style.width = `${d.surge_score}%`;
    }, 200);

    // 카드 터치 → 상세페이지
    const card = el.closest('.card');
    if (card && !card.classList.contains('card-tappable')) {
      card.classList.add('card-tappable');
      card.addEventListener('click', () => openDetail(t('cs.detailTitle'), renderCrashSurgeDetail));
    }
  } catch (e) {
    console.error('Crash/Surge load error:', e);
  }
}

// ── SVG 꺾은선 그래프 공용 함수 ──
function renderLineChart(containerId, points, options = {}) {
  const el = document.getElementById(containerId);                // 컨테이너 요소
  if (!el || points.length < 2) {                                  // 데이터 부족 시 안내
    if (el) el.innerHTML = `<div style="text-align:center;font-size:13px;color:var(--sub);padding:8px 0">${t('chart.noData')}</div>`;
    return;
  }

  const rawW = el.clientWidth - 2;
  const W = rawW > 50 ? rawW : (el.parentElement?.clientWidth || window.innerWidth - 40) - 2; // 숨겨진 탭 대비 fallback
  const H = options.height || 140;                                 // SVG 높이
  const hasYSideLabels = options.yTopLabel || options.yBottomLabel; // Y축 사이드 라벨 존재 여부
  const pad = { top: 12, right: 12, bottom: 22, left: hasYSideLabels ? 56 : 36 }; // 라벨 있으면 좌측 패딩 확장
  const cW = W - pad.left - pad.right;                             // 차트 영역 너비
  const cH = H - pad.top - pad.bottom;                             // 차트 영역 높이

  const vals = points.map(p => p.value);                           // Y값 배열 추출
  const rawMin = Math.min(...vals);                                // Y 최솟값
  const rawMax = Math.max(...vals);                                // Y 최댓값
  const hasZero = options.zeroLine !== false;                      // 0 기준선 표시 여부
  const yMin = rawMin;                                             // Y축 하한: 데이터 최솟값
  const yMax = rawMax;                                             // Y축 상한: 데이터 최댓값
  const yRange = yMax - yMin || 1;                                 // Y축 범위 (0 방지)

  const x = i => pad.left + (i / (points.length - 1)) * cW;       // X좌표 계산 함수
  const y = v => pad.top + (1 - (v - yMin) / yRange) * cH;        // Y좌표 계산 함수

  // 꺾은선 경로 생성
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(' ');
  // 영역 채우기 경로 (선 아래쪽)
  const zeroY = hasZero ? y(0) : y(yMin);                         // 기준선 Y좌표
  const areaPath = linePath + ` L${x(points.length - 1).toFixed(1)},${zeroY.toFixed(1)} L${x(0).toFixed(1)},${zeroY.toFixed(1)} Z`;

  const lineColor = options.color || 'var(--accent)';              // 선 색상
  const gradId = containerId + '-grad';                            // 그라데이션 ID

  // X축 라벨 (7개 균등 배치)
  const labelCount = Math.min(7, points.length);                   // 라벨 개수
  const labelStep = Math.max(1, Math.floor((points.length - 1) / (labelCount - 1))); // 라벨 간격
  let xLabels = '';                                                // X축 라벨 SVG
  for (let i = 0; i < points.length; i += labelStep) {
    xLabels += `<text class="chart-label" x="${x(i).toFixed(1)}" y="${H - 2}" text-anchor="middle">${points[i].label}</text>`;
  }

  // Y축 라벨 (5개 균등)
  let yLabels = '';                                                // Y축 라벨 SVG
  let gridLines = '';                                              // 격자선 SVG
  for (let i = 0; i <= 4; i++) {
    const val = yMin + (yRange * i) / 4;                           // Y값 계산
    const yPos = y(val);                                           // Y좌표
    yLabels += `<text class="chart-label" x="${pad.left - 4}" y="${yPos.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${val.toFixed(0)}</text>`;
    gridLines += `<line class="chart-grid-line" x1="${pad.left}" y1="${yPos.toFixed(1)}" x2="${W - pad.right}" y2="${yPos.toFixed(1)}"/>`;
  }

  // 0 기준선
  let zeroLineStr = '';                                            // 0 기준선 SVG
  if (hasZero && yMin < 0 && yMax > 0) {
    zeroLineStr = `<line class="chart-zero-line" x1="${pad.left}" y1="${y(0).toFixed(1)}" x2="${W - pad.right}" y2="${y(0).toFixed(1)}"/>`;
  }

  // Y축 상단/하단 라벨 — Y축 숫자 자리에 표시 (옵션)
  let yAxisSideLabels = '';                                        // Y축 라벨 SVG
  if (options.yTopLabel) {                                         // 상단 라벨: Y축 최상단 위치
    yAxisSideLabels += `<text class="chart-side-label" x="${pad.left - 4}" y="${pad.top}" text-anchor="end" dominant-baseline="middle">${options.yTopLabel}</text>`;
  }
  if (options.yBottomLabel) {                                      // 하단 라벨: Y축 최하단 위치
    yAxisSideLabels += `<text class="chart-side-label" x="${pad.left - 4}" y="${pad.top + cH}" text-anchor="end" dominant-baseline="middle">${options.yBottomLabel}</text>`;
  }

  // 데이터 포인트 (점)
  const dots = points.map((p, i) => {
    const dotColor = options.dotColor ? options.dotColor(p.value) : lineColor;  // 점 색상
    return `<circle class="chart-dot" cx="${x(i).toFixed(1)}" cy="${y(p.value).toFixed(1)}" fill="${dotColor}" data-idx="${i}"/>`;
  }).join('');

  // SVG 조립
  el.innerHTML = `<div class="line-chart-wrap">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
      <defs><linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${lineColor}" stop-opacity="0.3"/>
        <stop offset="100%" stop-color="${lineColor}" stop-opacity="0"/>
      </linearGradient></defs>
      ${gridLines}
      ${zeroLineStr}
      <path class="chart-area" d="${areaPath}" fill="url(#${gradId})"/>
      <path class="chart-line" d="${linePath}" stroke="${lineColor}"/>
      ${dots}
      ${xLabels}
      ${yLabels}
      ${yAxisSideLabels}
    </svg>
    <div class="chart-tooltip" id="${containerId}-tip"></div>
  </div>`;

  // 터치/호버 툴팁
  const wrap = el.querySelector('.line-chart-wrap');                // 래퍼 요소
  const tip = document.getElementById(containerId + '-tip');       // 툴팁 요소
  const svg = wrap.querySelector('svg');                           // SVG 요소
  const showTip = (idx) => {                                       // 툴팁 표시 함수
    const p = points[idx];                                         // 해당 데이터
    const sign = p.value > 0 ? '+' : '';                           // 양수 부호
    tip.textContent = `${p.fullLabel || p.label}: ${sign}${p.value.toFixed(1)}`;  // 텍스트
    const cx = x(idx);                                             // X좌표
    tip.style.left = `${cx}px`;                                    // 위치 지정
    tip.style.top = `${y(p.value) - 28}px`;                        // 점 위에 표시
    tip.style.transform = 'translateX(-50%)';                      // 중앙 정렬
    tip.style.opacity = '1';                                       // 표시
  };
  const hideTip = () => { tip.style.opacity = '0'; };             // 툴팁 숨김
  svg.querySelectorAll('.chart-dot').forEach(dot => {              // 각 점에 이벤트
    dot.addEventListener('mouseenter', () => showTip(+dot.dataset.idx));  // 마우스 진입
    dot.addEventListener('mouseleave', hideTip);                          // 마우스 이탈
  });
  svg.addEventListener('touchstart', e => {                        // 터치 이벤트
    const rect = svg.getBoundingClientRect();                      // SVG 위치
    const tx = (e.touches[0].clientX - rect.left) / rect.width * W;  // 터치 X좌표
    let closest = 0, minDist = Infinity;                           // 가장 가까운 점 탐색
    points.forEach((_, i) => { const d = Math.abs(x(i) - tx); if (d < minDist) { minDist = d; closest = i; } });
    showTip(closest);                                              // 가장 가까운 점 툴팁
  }, { passive: true });
  svg.addEventListener('touchend', () => setTimeout(hideTip, 1500), { passive: true });  // 터치 종료 후 숨김
}

// ── Crash/Surge 이중 그래프 (하락 가능성 vs 상승 가능성) ──
async function loadCrashSurgeChart() {
  try {
    const res = await fetch('/api/crash-surge/history?days=90');
    const list = await res.json();
    if (!Array.isArray(list) || list.length < 2) return;

    const sorted = list.slice()
      .sort((a, b) => a.date.localeCompare(b.date))
      .filter(r => { const d = new Date(r.date + 'T00:00:00').getDay(); return d !== 0 && d !== 6; });

    const labels = sorted.map(r => ({ label: r.date.slice(5), fullLabel: r.date }));
    const crashVals = sorted.map(r => r.crash_score || 0);
    const surgeVals = sorted.map(r => r.surge_score || 0);

    renderDualLineChart('cs-chart', labels, crashVals, surgeVals);
  } catch (e) {
    console.error('CS chart error:', e);
  }
}

function renderDualLineChart(containerId, labels, crashVals, surgeVals) {
  const el = document.getElementById(containerId);
  if (!el || labels.length < 2) return;

  const rawW = el.clientWidth - 2;
  const W = rawW > 50 ? rawW : (el.parentElement?.clientWidth || window.innerWidth - 40) - 2;
  const H = 180;
  const pad = { top: 16, right: 14, bottom: 32, left: 38 };
  const cW = W - pad.left - pad.right;
  const cH = H - pad.top - pad.bottom;

  const allVals = [...crashVals, ...surgeVals];
  const yMin = Math.min(...allVals);
  const yMax = Math.max(...allVals);
  const yRange = yMax - yMin || 1;

  const x = i => pad.left + (i / (labels.length - 1)) * cW;
  const y = v => pad.top + (1 - (v - yMin) / yRange) * cH;

  const makePath = vals => vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const crashPath = makePath(crashVals);
  const surgePath = makePath(surgeVals);

  // 영역 채우기 (선 아래 → yMax 라인까지)
  const baseY = y(yMin).toFixed(1);
  const crashArea = crashPath + ` L${x(labels.length-1).toFixed(1)},${baseY} L${x(0).toFixed(1)},${baseY} Z`;
  const surgeArea = surgePath + ` L${x(labels.length-1).toFixed(1)},${baseY} L${x(0).toFixed(1)},${baseY} Z`;

  const crashColor = '#EF4444';
  const surgeColor = '#22C55E';

  // X축 라벨
  const labelCount = Math.min(7, labels.length);
  const labelStep = Math.max(1, Math.floor((labels.length - 1) / (labelCount - 1)));
  let xLabels = '';
  for (let i = 0; i < labels.length; i += labelStep) {
    xLabels += `<text class="chart-label" x="${x(i).toFixed(1)}" y="${H - 4}" text-anchor="middle">${labels[i].label}</text>`;
  }

  // Y축 라벨 + 격자
  let yLabels = '', gridLines = '';
  for (let i = 0; i <= 4; i++) {
    const val = yMin + (yRange * i) / 4;
    const yPos = y(val);
    yLabels += `<text class="chart-label" x="${pad.left - 4}" y="${yPos.toFixed(1)}" text-anchor="end" dominant-baseline="middle">${val.toFixed(0)}</text>`;
    gridLines += `<line class="chart-grid-line" x1="${pad.left}" y1="${yPos.toFixed(1)}" x2="${W - pad.right}" y2="${yPos.toFixed(1)}"/>`;
  }

  // 마지막 값 포인트
  const lastCrash = crashVals[crashVals.length - 1];
  const lastSurge = surgeVals[surgeVals.length - 1];
  const lastX = x(labels.length - 1).toFixed(1);

  el.innerHTML = `
    <div style="display:flex;justify-content:center;gap:16px;margin-bottom:6px">
      <span style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--sub)">
        <span style="width:12px;height:3px;border-radius:2px;background:${crashColor};display:inline-block"></span>
        하락 가능성 <b style="color:${crashColor}">${lastCrash.toFixed(0)}</b>
      </span>
      <span style="display:flex;align-items:center;gap:5px;font-size:11px;color:var(--sub)">
        <span style="width:12px;height:3px;border-radius:2px;background:${surgeColor};display:inline-block"></span>
        상승 가능성 <b style="color:${surgeColor}">${lastSurge.toFixed(0)}</b>
      </span>
    </div>
    <div class="line-chart-wrap">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="${containerId}-cg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${crashColor}" stop-opacity="0.15"/>
            <stop offset="100%" stop-color="${crashColor}" stop-opacity="0"/>
          </linearGradient>
          <linearGradient id="${containerId}-sg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${surgeColor}" stop-opacity="0.15"/>
            <stop offset="100%" stop-color="${surgeColor}" stop-opacity="0"/>
          </linearGradient>
        </defs>
        ${gridLines}
        <path d="${crashArea}" fill="url(#${containerId}-cg)"/>
        <path d="${surgeArea}" fill="url(#${containerId}-sg)"/>
        <path d="${crashPath}" fill="none" stroke="${crashColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="${surgePath}" fill="none" stroke="${surgeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="${lastX}" cy="${y(lastCrash).toFixed(1)}" r="4" fill="${crashColor}" stroke="var(--card)" stroke-width="1.5"/>
        <circle cx="${lastX}" cy="${y(lastSurge).toFixed(1)}" r="4" fill="${surgeColor}" stroke="var(--card)" stroke-width="1.5"/>
        ${xLabels}
        ${yLabels}
      </svg>
      <div class="chart-tooltip" id="${containerId}-tip"></div>
    </div>`;

  // 터치/호버 툴팁
  const wrap = el.querySelector('.line-chart-wrap');
  const tip = document.getElementById(containerId + '-tip');
  const svg = wrap.querySelector('svg');
  const showTip = (idx) => {
    const lb = labels[idx];
    const cv = crashVals[idx], sv = surgeVals[idx];
    tip.innerHTML = `<b>${lb.fullLabel || lb.label}</b><br><span style="color:${crashColor}">${t('hist.crash')} ${cv.toFixed(1)}</span> · <span style="color:${surgeColor}">${t('hist.surge')} ${sv.toFixed(1)}</span>`;
    tip.style.left = `${x(idx)}px`;
    tip.style.top = `${Math.min(y(cv), y(sv)) - 36}px`;
    tip.style.transform = 'translateX(-50%)';
    tip.style.opacity = '1';
  };
  const hideTip = () => { tip.style.opacity = '0'; };
  svg.addEventListener('touchstart', e => {
    const rect = svg.getBoundingClientRect();
    const tx = (e.touches[0].clientX - rect.left) / rect.width * W;
    let closest = 0, minDist = Infinity;
    labels.forEach((_, i) => { const d = Math.abs(x(i) - tx); if (d < minDist) { minDist = d; closest = i; } });
    showTip(closest);
  }, { passive: true });
  svg.addEventListener('mousemove', e => {
    const rect = svg.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width * W;
    let closest = 0, minDist = Infinity;
    labels.forEach((_, i) => { const d = Math.abs(x(i) - mx); if (d < minDist) { minDist = d; closest = i; } });
    showTip(closest);
  });
  svg.addEventListener('mouseleave', hideTip);
  svg.addEventListener('touchend', () => setTimeout(hideTip, 1500), { passive: true });
}

// ── Noise Score 90일(3개월) 그래프 ──
async function loadNoiseChart() {
  try {
    const res = await fetch('/api/regime/history?days=90');         // 90일(3개월) 국면 히스토리 요청
    const list = await res.json();                                  // JSON 파싱
    if (!Array.isArray(list) || list.length < 2) return;            // 데이터 부족 시 종료

    const sorted = list.slice()
      .sort((a, b) => a.date.localeCompare(b.date))                // 날짜 오름차순 정렬
      .filter(r => { const d = new Date(r.date + 'T00:00:00').getDay(); return d !== 0 && d !== 6; });  // 주말 제외 (0=일, 6=토)
    const points = sorted.map(r => ({                              // 그래프 포인트 변환
      label: r.date.slice(5),                                      // MM-DD 형식 라벨
      fullLabel: r.date,                                           // 전체 날짜 (툴팁용)
      value: r.noise_score != null ? r.noise_score : 0,            // noise_score 값
    }));

    renderLineChart('nr-chart', points, {                          // 그래프 렌더링
      color: 'var(--accent)',                                      // 보라색 선
      zeroLine: true,                                              // 0 기준선 표시
      dotColor: v => v >= 0 ? 'var(--green)' : 'var(--red)',       // 양수(이성적) 초록, 음수(감정적) 빨강
      yTopLabel: t('chart.yTop'),                                     // Y축 상단: 이성적 (양수)
      yBottomLabel: t('chart.yBottom'),                              // Y축 하단: 감정적 (음수)
    });
  } catch (e) {
    console.error('NR chart error:', e);                           // 에러 로그
  }
}

// ── Crash/Surge 히스토리 ──
async function loadCrashSurgeHistory() {
  try {
    const res = await fetch('/api/crash-surge/history?days=10');
    const list = await res.json();
    const el = document.getElementById('cs-history');
    if (!Array.isArray(list) || list.length === 0) {
      el.innerHTML = `<div style="text-align:center;font-size:13px;color:var(--sub);padding:8px 0">${t('chart.noData')}</div>`;
      return;
    }

    el.innerHTML = `<div class="cs-hist-table">
      <div class="cs-hist-header">
        <span class="cs-hist-cell cs-hist-date-col">${t('hist.date')}</span>
        <span class="cs-hist-cell">${t('hist.crash')}</span>
        <span class="cs-hist-cell">${t('hist.surge')}</span>
        <span class="cs-hist-cell">${t('hist.direction')}</span>
      </div>
      ${list.map((r, i) => {
        const cs = CS_GRADE_STYLE[r.crash_grade] || CS_GRADE_STYLE['보통'];
        const ss = SURGE_GRADE_STYLE[r.surge_grade] || SURGE_GRADE_STYLE['보통'];
        const ns = r.net_score || 0;                                          // 순방향 점수
        const arrow = ns > 5 ? '↑' : ns < -5 ? '↓' : '→';                   // 방향 화살표
        const dirColor = ns > 5 ? 'var(--green)' : ns < -5 ? 'var(--red)' : 'var(--sub)';  // 방향 색상
        const sign = ns > 0 ? '+' : '';                                       // 양수면 + 부호
        return `<div class="cs-hist-row" style="--row-delay:${i * 0.04}s">
          <span class="cs-hist-cell cs-hist-date-col">${r.date.slice(5)}</span>
          <span class="cs-hist-cell" style="color:${cs.color}">${r.crash_score.toFixed(1)} <small class="badge ${cs.cls}" style="font-size:9px;padding:1px 6px">${r.crash_grade}</small></span>
          <span class="cs-hist-cell" style="color:${ss.color}">${r.surge_score.toFixed(1)} <small class="badge ${ss.cls}" style="font-size:9px;padding:1px 6px">${r.surge_grade}</small></span>
          <span class="cs-hist-cell" style="color:${dirColor};font-weight:600">${sign}${ns.toFixed(1)} ${arrow}</span>
        </div>`;
      }).join('')}
    </div>`;
  } catch (e) {
    console.error('Crash/Surge history error:', e);
  }
}

// ── 방향성 분석 ──
async function loadDirection() {
  const el = document.getElementById('cs-direction');      // 방향성 컨테이너
  const badge = document.getElementById('dir-badge');      // 방향성 뱃지
  try {
    const res = await fetch('/api/crash-surge/direction');  // 방향성 API 호출
    const d = await res.json();
    if (!d || d.message) {                                  // 데이터 부족 시
      el.innerHTML = `<div class="loading-placeholder"><div class="loading-spinner sm"></div><span class="loading-text">${d?.message || t('dir.loading')}</span></div>`;
      badge.className = 'badge';
      badge.textContent = '';
      return;
    }

    // 방향 뱃지 스타일 결정
    const dirMap = {                                        // 방향별 스타일 매핑 (API 한글 키)
      '상승 우세': { cls: 'badge-green', color: 'var(--green)', icon: '▲' },
      '하락 우세': { cls: 'badge-red', color: 'var(--red)', icon: '▼' },
      '방향 불명': { cls: 'badge-gray', color: 'var(--sub)', icon: '―' },
      '데이터 부족': { cls: 'badge-gray', color: 'var(--sub)', icon: '?' },
    };
    const ds = dirMap[d.direction] || dirMap['데이터 부족']; // 기본값 설정
    badge.className = `badge ${ds.cls}`;                    // 뱃지 클래스 적용
    badge.textContent = tDirection(d.direction);             // 뱃지 텍스트 번역

    // net_score 표시
    const netColor = d.current_net_score > 0 ? 'var(--green)' : d.current_net_score < 0 ? 'var(--red)' : 'var(--sub)';
    const netSign = d.current_net_score > 0 ? '+' : '';     // 양수면 + 기호

    // 기간별 통계 테이블 생성
    let statsHtml = '';                                      // 통계 HTML
    const horizons = ['5d', '10d', '20d'];                  // 5일, 10일, 20일
    const hLabels = { '5d': t('dir.5d'), '10d': t('dir.10d'), '20d': t('dir.20d') }; // 기간 라벨 번역
    if (d.horizon_stats) {
      statsHtml = `<div class="dir-stats-table">
        <div class="dir-stats-header">
          <span class="dir-stats-cell">${t('dir.period')}</span>
          <span class="dir-stats-cell">${t('dir.avgReturn')}</span>
          <span class="dir-stats-cell">${t('dir.upProb')}</span>
          <span class="dir-stats-cell">${t('dir.sampleCount')}</span>
        </div>
        ${horizons.map(h => {
          const s = d.horizon_stats[h];                     // 해당 기간 통계
          if (!s) return '';                                 // 데이터 없으면 건너뜀
          const retColor = s.avg_return > 0 ? 'var(--green)' : s.avg_return < 0 ? 'var(--red)' : 'var(--sub)';
          const upColor = s.up_ratio >= 60 ? 'var(--green)' : s.up_ratio <= 40 ? 'var(--red)' : 'var(--sub)';
          return `<div class="dir-stats-row">
            <span class="dir-stats-cell">${hLabels[h]}</span>
            <span class="dir-stats-cell" style="color:${retColor}">${s.avg_return > 0 ? '+' : ''}${s.avg_return}%</span>
            <span class="dir-stats-cell" style="color:${upColor};font-weight:700">${s.up_ratio}%</span>
            <span class="dir-stats-cell" style="color:var(--sub)">${s.sample_count}${t('dir.cases')}</span>
          </div>`;
        }).join('')}
      </div>`;
    }

    // 백분위 텍스트 생성
    const pctl = d.net_score_percentile;                  // 백분위 값
    const pctlText = pctl != null
      ? `${t('dir.top')} ${(100 - pctl).toFixed(1)}%`     // "상위 XX%" 번역
      : '';                                               // 백분위 없으면 빈 문자열

    el.innerHTML = `
      <div style="text-align:center;padding:8px 0 4px">
        <div style="font-size:11px;color:var(--sub);margin-bottom:4px">${t('dir.netScore')}</div>
        <div style="font-size:28px;font-weight:800;color:${netColor}">${netSign}${d.current_net_score}</div>
        ${pctlText ? `<div style="font-size:12px;color:var(--sub);margin-top:2px">${t('dir.percentile')} <b style="color:${netColor}">${pctlText}</b></div>` : ''}
        <div style="font-size:20px;margin-top:2px">${ds.icon}</div>
      </div>
      <div style="padding:4px 0 8px;font-size:11px;color:var(--sub);text-align:center">
        ${t('dir.similarPeriod').replace('{margin}', d.margin)}
      </div>
      ${statsHtml}`;
  } catch (e) {
    console.error('Direction load error:', e);              // 에러 로그
    el.innerHTML = `<div style="text-align:center;font-size:13px;color:var(--sub);padding:12px 0">${t('dir.loadError')}</div>`;
  }
}

// ── Detail Overlay ──
function openDetail(title, renderFn) {
  const overlay = document.getElementById('detail-overlay');
  const titleEl = document.getElementById('detail-title');
  const body = document.getElementById('detail-body');
  titleEl.textContent = title;                             // 제목 설정
  document.getElementById('detail-subtitle').textContent = t('detail.mlLabel'); // 서브타이틀 설정
  body.innerHTML = '';                                     // 본문 초기화
  renderFn(body);                                          // 컨텐츠 렌더링
  history.pushState({ detail: true }, '');                  // 히스토리에 상세 상태 추가
  requestAnimationFrame(() => overlay.classList.add('open')); // 슬라이드인 애니메이션
}

function closeDetail() {
  document.getElementById('detail-overlay').classList.remove('open'); // 슬라이드아웃
}

document.getElementById('detail-back').addEventListener('click', () => {
  history.back();                                          // 뒤로가기로 상세 닫기 (popstate에서 처리)
});

// ── 바 차트 렌더 헬퍼 ──
function renderBarChart(container, items, maxAbs, descMap) {
  let html = '<div class="feat-bar-list">';
  items.forEach(item => {
    const info = descMap[item.name] || { label: item.name };
    const val = item.value != null ? item.value : item.contribution;
    const absVal = Math.abs(val);
    const pct = Math.min((absVal / maxAbs) * 100, 100);
    const cls = val > 0 ? 'positive' : val < 0 ? 'negative' : 'neutral';
    html += `<div class="feat-bar-row">
      <span class="feat-bar-label" title="${item.name}">${info.label}</span>
      <div class="feat-bar-track">
        <div class="feat-bar-fill ${cls}" style="width:0%" data-w="${pct}%"></div>
      </div>
      <span class="feat-bar-value" style="color:${val > 0 ? 'var(--red)' : val < 0 ? 'var(--green)' : 'var(--sub)'}">${val > 0 ? '+' : ''}${val.toFixed(4)}</span>
    </div>`;
  });
  html += '</div>';
  container.innerHTML += html;
  // Animate bars
  setTimeout(() => {
    container.querySelectorAll('.feat-bar-fill[data-w]').forEach(el => {
      el.style.width = el.dataset.w;
    });
  }, 50);
}

function renderDescCards(container, items, descMap) {
  const seen = new Set();
  items.forEach(item => {
    if (seen.has(item.name)) return;
    seen.add(item.name);
    const info = descMap[item.name];
    if (!info) return;
    container.innerHTML += `<div class="feat-desc-card">
      <div class="feat-desc-name">${info.label} <span style="font-size:10px;color:var(--sub2)">${item.name}</span></div>
      <div class="feat-desc-text">${info.desc}</div>
    </div>`;
  });
}

// ── 현재 지표값 2열 그리드 렌더 헬퍼 ──
function renderFeatureValuesGrid(container, featureValues, descMap) {
  // 피처값이 없으면 종료
  if (!featureValues || Object.keys(featureValues).length === 0) return;
  container.innerHTML += `<div class="feat-section-title">${t('detail.currentIndicators')}</div>`;
  let html = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:20px">';
  // 각 피처에 대해 라벨 + 값 + 방향 화살표 표시
  Object.entries(featureValues).forEach(([key, val]) => {
    const info = descMap[key] || { label: key };
    // 값 포맷: 절대값이 큰 값은 소수점 2자리, 작은 값은 4자리
    const absVal = Math.abs(val);
    const display = absVal >= 1 ? val.toFixed(2) : val.toFixed(4);
    // 양수면 초록 ▲, 음수면 빨강 ▼, 0이면 회색
    const arrow = val > 0 ? '▲' : val < 0 ? '▼' : '';
    const arrowColor = val > 0 ? '#10B981' : val < 0 ? '#EF4444' : 'var(--sub)';
    // % 형태의 피처인지 판별 (이름에 RET, YoY, CHG, GAP, DRAWDOWN 포함)
    const isPct = /RET|LOGRET|GAP|DRAWDOWN|CHG|PCTL/.test(key);
    const suffix = isPct ? '%' : '';
    const displayVal = isPct ? (val * 100).toFixed(2) + '%' : display;
    html += `<div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;
                          background:var(--card);border-radius:10px;box-shadow:var(--shadow)">
      <span style="font-size:11px;color:var(--sub);font-weight:500;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${info.label}</span>
      <span style="font-size:12px;font-weight:700;white-space:nowrap;margin-left:6px">${displayVal} <span style="color:${arrowColor};font-size:10px">${arrow}</span></span>
    </div>`;
  });
  html += '</div>';
  container.innerHTML += html;
}

// ── Crash/Surge 상세 ──
function renderCrashSurgeDetail(body) {
  if (!_csData) { body.innerHTML = `<p style="color:var(--sub)">${t('detail.noData')}</p>`; return; }
  const d = _csData;

  // 요약 — 본 페이지와 동일한 점수 기반 라벨 사용
  const crashLabel = d.crash_score < 40 ? '낮음' : d.crash_score < 60 ? '보통' : '높음';
  const crashS = d.crash_score < 40
    ? { cls: 'badge-green', color: '#10B981' }
    : d.crash_score < 60
    ? { cls: 'badge-yellow', color: '#F59E0B' }
    : { cls: 'badge-red', color: '#EF4444' };
  const surgeLabel = d.surge_score < 40 ? '낮음' : d.surge_score < 60 ? '보통' : '높음';
  const surgeS = d.surge_score < 40
    ? { cls: 'badge-red', color: '#EF4444' }
    : d.surge_score < 60
    ? { cls: 'badge-yellow', color: '#F59E0B' }
    : { cls: 'badge-green', color: '#22C55E' };
  body.innerHTML = `<div style="display:flex;gap:16px;margin-bottom:8px">
    <div style="flex:1;text-align:center">
      <div style="font-size:12px;color:var(--sub);font-weight:600">${t('cs.crashRisk')}</div>
      <div style="font-size:28px;font-weight:800;color:${crashS.color}">${d.crash_score.toFixed(1)}</div>
      <span class="badge ${crashS.cls}">${crashLabel}</span>
    </div>
    <div style="flex:1;text-align:center">
      <div style="font-size:12px;color:var(--sub);font-weight:600">${t('cs.surgeExpect')}</div>
      <div style="font-size:28px;font-weight:800;color:${surgeS.color}">${d.surge_score.toFixed(1)}</div>
      <span class="badge ${surgeS.cls}">${surgeLabel}</span>
    </div>
  </div>
  <div style="margin:12px 0 16px;padding:10px 14px;border-radius:10px;background:linear-gradient(135deg,rgba(255,140,0,0.08),rgba(255,140,0,0.02));border:1px solid rgba(255,140,0,0.15)">
    <div style="font-family:'SF Mono',Consolas,monospace;font-size:10px;font-weight:700;color:#FF8C00;letter-spacing:1px;margin-bottom:6px">ML MODEL INFO</div>
    <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--sub)">
      <span>기준일 <b style="color:var(--text)">${d.date}</b></span>
      <span>Macro F1 <b style="color:#FF8C00">${d.macro_f1}</b></span>
    </div>
  </div>`;


  // SHAP 값
  if (d.shap_values) {
    const mainType = d.crash_score >= d.surge_score ? 'crash' : 'surge';
    const shapItems = d.shap_values[mainType] || [];
    if (shapItems.length > 0) {
      const maxAbs = Math.max(...shapItems.map(s => Math.abs(s.value)), 0.001);
      body.innerHTML += `<div class="feat-section-title">${t('detail.shapTitle')} (${mainType === 'crash' ? t('detail.shapCrash') : t('detail.shapSurge')})</div>`;
      renderBarChart(body, shapItems, maxAbs, getCSFeatureDesc());
    }
  }

  // SHAP 없을 때 안내
  if (!d.shap_values) {
    body.innerHTML += `<div style="text-align:center;padding:24px 0;color:var(--sub);font-size:13px;line-height:1.6">
      ${t('detail.noShap').replace('\n', '<br>')}
    </div>`;
  }

  // 현재 지표값 그리드
  renderFeatureValuesGrid(body, d.feature_values, getCSFeatureDesc());

  // 분석에 사용된 지표
  const allItems = [
    ...(d.shap_values?.crash || []),
    ...(d.shap_values?.surge || []),
  ];
  if (allItems.length > 0) {
    body.innerHTML += `<div class="feat-section-title">${t('detail.usedIndicators')}</div>`;
    renderDescCards(body, allItems, getCSFeatureDesc());
  }
}

// ── Noise vs Signal 상세 ──
function renderNoiseDetail(body) {
  if (!_nrData) { body.innerHTML = `<p style="color:var(--sub)">${t('detail.noData')}</p>`; return; }
  const d = _nrData;

  const nrIcon = NR_ICON[d.regime_name] || { color: '#999' };
  body.innerHTML = `<div style="text-align:center;margin-bottom:16px">
    <div style="font-size:14px;color:var(--sub);font-weight:600">${t('detail.currentPhase')}</div>
    <div style="font-size:24px;font-weight:800;color:${nrIcon.color};display:flex;align-items:center;justify-content:center;gap:8px">${nrIcon.icon ? lucideIcon(nrIcon.icon, 28, 1.8) : ''} ${tNrPhase(d.regime_name)}</div>
    <div style="font-size:13px;color:var(--sub);margin-top:4px">${t('detail.noiseScore')} ${d.noise_score?.toFixed(4) ?? '--'}</div>
  </div>
  <div style="margin:0 0 16px;padding:10px 14px;border-radius:10px;background:linear-gradient(135deg,rgba(255,140,0,0.08),rgba(255,140,0,0.02));border:1px solid rgba(255,140,0,0.15)">
    <div style="font-family:'SF Mono',Consolas,monospace;font-size:10px;font-weight:700;color:#FF8C00;letter-spacing:1px;margin-bottom:6px">ML MODEL INFO</div>
    <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--sub)">
      <span>기준일 <b style="color:var(--text)">${d.date}</b></span>
      <span>모델 <b style="color:#FF8C00">4-State HMM</b></span>
    </div>
  </div>`;

  // 피처 기여도
  if (d.feature_contributions && d.feature_contributions.length > 0) {
    const maxAbs = Math.max(...d.feature_contributions.map(c => Math.abs(c.contribution)), 0.001);
    body.innerHTML += `<div class="feat-section-title">${t('detail.noiseComposition')}</div>`;
    const items = d.feature_contributions.map(c => ({ name: c.name, value: c.contribution }));
    renderBarChart(body, items, maxAbs, getNRFeatureDesc());
  }

  // 현재 지표 수치 (2열 그리드 + 화살표)
  renderFeatureValuesGrid(body, d.feature_values, getNRFeatureDesc());

  // 피처 데이터 없을 때 안내
  if (!d.feature_contributions && !d.feature_values) {
    body.innerHTML += `<div style="text-align:center;padding:24px 0;color:var(--sub);font-size:13px;line-height:1.6">
      ${t('detail.noFeature').replace('\n', '<br>')}
    </div>`;
  }

  // 분석에 사용된 지표
  const allItems = [
    ...(d.feature_contributions || []),
    ...Object.keys(d.feature_values || {}).map(k => ({ name: k })),
  ];
  if (allItems.length > 0) {
    body.innerHTML += `<div class="feat-section-title">${t('detail.usedIndicators')}</div>`;
    renderDescCards(body, allItems, getNRFeatureDesc());
  }
}

// ── 현재 탭 데이터 새로고침 ──
async function refreshCurrentTab() {
  const idx = _currentTabIdx;
  if (idx === 0) {
    // AI차트 탭
    if (typeof loadCandleChart === 'function') await loadCandleChart();
  } else if (idx === 1) {
    // 시장 탭
    await Promise.allSettled([
      loadAiSummary(), loadMacro(), loadFeed(),
      loadMarketOverview(), loadHoldingsSummary()
    ]);
  } else if (idx === 2) {
    // 펀더멘털 탭
    await Promise.allSettled([
      loadRegime(), loadNoiseChart(), loadAiExplain('fundamental')
    ]);
  } else if (idx === 3) {
    // 신호 탭
    await Promise.allSettled([
      loadCrashSurge(), loadCrashSurgeChart(), loadAiExplain('signal')
    ]);
  } else if (idx === 4) {
    // 거시경제 탭
    await Promise.allSettled([
      typeof loadSectorCycle === 'function' ? loadSectorCycle() : Promise.resolve(),
      loadAiExplain('sector')
    ]);
  }
}

// ── Pull-to-refresh ──
// 스크롤이 최상단에 도달한 후 추가로 한번 더 당겨야 새로고침
function setupPullToRefresh() {
  const indicator = document.getElementById('ptr-indicator');
  const spinner = document.getElementById('ptr-spinner');
  if (!indicator || !spinner) return;

  let pulling = false, refreshing = false;
  let startY = 0;
  let atTopOnStart = false;   // 터치 시작 시 최상단이었는지
  let overscrollStartY = 0;   // 최상단 도달 후 추가 당김 시작점
  let overscrolling = false;  // 실제 overscroll 구간 진입
  const THRESHOLD = 80;       // 새로고침 트리거 거리

  const scrollWrap = document.querySelector('.scroll-wrap');
  const getScrollTop = () => scrollWrap ? scrollWrap.scrollTop : window.scrollY;

  document.addEventListener('touchstart', e => {
    if (refreshing) return;
    // 횡스크롤 영역이면 무시
    if (_isHScrollArea(e.target)) return;
    const overlay = document.getElementById('detail-overlay');
    if (overlay && overlay.classList.contains('open')) return;

    startY = e.touches[0].clientY;
    atTopOnStart = (getScrollTop() <= 0);
    overscrolling = false;
    overscrollStartY = 0;
    pulling = true;
  }, { passive: true });

  document.addEventListener('touchmove', e => {
    if (!pulling || refreshing) return;
    const cy = e.touches[0].clientY;
    const dy = cy - startY;

    // 위로 스와이프면 취소
    if (dy < 0) {
      pulling = false;
      resetIndicator();
      return;
    }

    // 터치 시작 시 최상단이 아니었으면 → 이 터치에서는 새로고침 불가
    // (스크롤해서 올라온 뒤 한 번 손 떼고 다시 당겨야 함)
    if (!atTopOnStart) return;

    // 최상단이 아니면 무시 (혹시 약간 스크롤된 경우 방어)
    if (getScrollTop() > 0) return;

    // 최상단 도달! 이제부터 overscroll 추적 시작
    if (!overscrolling) {
      overscrolling = true;
      overscrollStartY = cy;
      return;
    }

    // overscroll 거리 (최상단 도달 이후 추가로 당긴 거리)
    const overDy = cy - overscrollStartY;
    if (overDy <= 0) return;

    const progress = Math.min(overDy / THRESHOLD, 1);
    const topPos = Math.min(overDy * 0.35, 50);
    indicator.style.top = `${topPos}px`;
    indicator.classList.add('visible');
    spinner.style.transform = `rotate(${progress * 360}deg)`;
    spinner.className = 'ptr-spinner pulling';
    spinner.style.opacity = `${0.3 + progress * 0.7}`;
  }, { passive: true });

  document.addEventListener('touchend', async () => {
    if (!pulling || refreshing) { pulling = false; return; }
    if (!overscrolling) { pulling = false; resetIndicator(); return; }

    const topPos = parseInt(indicator.style.top) || 0;
    if (topPos >= 28) {  // 충분히 당겼으면 새로고침
      refreshing = true;
      spinner.className = 'ptr-spinner refreshing';
      spinner.style.transform = '';
      spinner.style.opacity = '1';
      indicator.style.top = '16px';

      await refreshCurrentTab();

      resetIndicator();
      refreshing = false;
    } else {
      resetIndicator();
    }
    pulling = false;
    overscrolling = false;
  }, { passive: true });

  function resetIndicator() {
    indicator.style.top = '-50px';
    indicator.classList.remove('visible');
  }
}
setupPullToRefresh();

// ── 초기화 ──
function dismissSplash() {
  const splash = document.getElementById('splash');
  if (!splash) return;
  splash.classList.add('fade-out');
  const onEnd = () => {
    splash.remove();
    if (!getHoldings()) {
      showHoldingsSetup();
    } else {
      loadHoldingsSummary();
    }
    // Initialize fade-in animations for market tab (visible by default)
    const marketTab = document.getElementById('tab-market');
    if (marketTab) {
      marketTab.querySelectorAll('.fade-target').forEach((ft, i) => {
        ft.style.setProperty('--delay', `${i * 0.07}s`);
        ft.classList.add('visible');
      });
    }
    initFadeTargets();
  };
  splash.addEventListener('transitionend', onEnd);
  setTimeout(onEnd, 600);
}

// ── 사용자 추적 (익명 해시) ──
function getOrCreateUserHash() {
  // WebView에서 localStorage/crypto 접근이 제한될 수 있으므로 단계별 fallback
  try {
    const stored = localStorage.getItem('user_hash');
    if (stored) return stored;
  } catch (e) { /* localStorage 접근 불가 */ }

  let hash;
  try {
    hash = crypto.randomUUID();
  } catch (e) {
    hash = 'xxxx-xxxx-xxxx-xxxx'.replace(/x/g, () =>
      Math.floor(Math.random() * 16).toString(16));
  }

  try { localStorage.setItem('user_hash', hash); } catch (e) { /* 저장 실패 무시 */ }
  return hash;
}

function trackVisit() {
  try {
    const userHash = getOrCreateUserHash();
    const baseUrl = window.location.origin || 'https://dinsightlab.com';
    fetch(baseUrl + '/api/tracking/visit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_hash: userHash }),
    }).catch(() => {});
  } catch (e) { /* 추적 실패해도 앱 동작에 영향 없음 */ }
}

(async () => {
  // 페이지 로드 시 방문 기록 전송
  trackVisit();

  const splashStart = Date.now();
  let splashDismissed = false;
  function safeDismiss() {
    if (splashDismissed) return;
    splashDismissed = true;
    dismissSplash();
  }

  // 최대 6초 안전 타임아웃 — API 실패해도 스플래시는 닫힘
  const safetyTimer = setTimeout(safeDismiss, 6000);

  try {
    // AI차트(idx=0)가 기본 탭이므로 차트 초기화 + fade-target 활성화
    const chartTab = document.getElementById('tab-chart');
    if (chartTab) {
      chartTab.querySelectorAll('.fade-target').forEach(ft => ft.classList.add('visible'));
    }
    // home view 가 활성 (scroll-wrap display:none) 상태면 차트 init 스킵 —
    // 0 폭 컨테이너에서 SVG 그리면 빈 차트가 됨. 탭 클릭 시 init 되게 둠.
    const homeView = document.getElementById('home-view');
    const homeActive = homeView && homeView.style.display !== 'none' && !homeView.hidden;
    if (typeof initChartTab === 'function' && !window._chartLoaded && !homeActive) {
      window._chartLoaded = true;
      initChartTab();
    }
    await Promise.allSettled([loadRegime(), loadMacro(), loadFeed(), loadMarketOverview(), loadNoiseChart()]);
  } catch (e) {
    console.error('Init load error:', e);
  }

  clearTimeout(safetyTimer);
  const elapsed = Date.now() - splashStart;
  const remaining = Math.max(0, 2200 - elapsed);

  setTimeout(safeDismiss, remaining);
})();
