// ── 상세페이지 캐시 ──
var _csData = null;
var _nrData = null;

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

const NR_PHASES = ['펀더멘털 반영', '펀더멘털 약반영', '센티멘트 약반영', '센티멘트 지배'];
const NR_GAP_POS   = { '펀더멘털 반영': 12, '펀더멘털 약반영': 37, '센티멘트 약반영': 63, '센티멘트 지배': 88 };
const NR_GAP_COLOR = { '펀더멘털 반영': '#4CAF50', '펀더멘털 약반영': '#8BC34A', '센티멘트 약반영': '#FF9800', '센티멘트 지배': '#F44336' };
const NR_SUB = {
  '펀더멘털 반영':   '주가가 펀더멘털에 부합',
  '펀더멘털 약반영': '주가가 펀더멘털에 부합',
  '센티멘트 약반영': '주가가 펀더멘털에 부합하지 않음',
  '센티멘트 지배':   '주가가 펀더멘털에 부합하지 않음',
};
const NR_BADGE = {
  '펀더멘털 반영':   { cls: 'badge-green', text: '안정', icon: 'sun' },
  '펀더멘털 약반영': { cls: 'badge-yellow', text: '주의', icon: 'cloud' },
  '센티멘트 약반영': { cls: 'badge-yellow', text: '경계', icon: 'cloudDrizzle' },
  '센티멘트 지배':   { cls: 'badge-red', text: '위험', icon: 'cloudLightning' },
};
const NR_ICON = {
  '펀더멘털 반영':   { icon: 'sun',            color: '#10B981', softBg: 'rgba(16,185,129,0.1)' },
  '펀더멘털 약반영': { icon: 'cloud',          color: '#F59E0B', softBg: 'rgba(245,158,11,0.1)' },
  '센티멘트 약반영': { icon: 'cloudDrizzle',   color: '#F97316', softBg: 'rgba(249,115,22,0.1)' },
  '센티멘트 지배':   { icon: 'cloudLightning', color: '#EF4444', softBg: 'rgba(239,68,68,0.1)' },
};

// ── 피처 설명 사전 ──
const CS_FEATURE_DESC = {
  'SP500_LOGRET_1D':       { label: '1일 수익률', desc: '전일 종가 대비 등락. 하루 -2% 이상 급락은 투매 시작, +2% 이상은 숏커버링 반등일 가능성' },
  'SP500_LOGRET_5D':       { label: '5일 수익률', desc: '1주간 누적 수익률. 연속 하락 시 마진콜·펀드 환매 압력이 폭락을 가속' },
  'SP500_LOGRET_10D':      { label: '10일 수익률', desc: '2주간 추세. 10일 연속 하락은 시장 심리가 항복 단계에 진입했다는 의미' },
  'SP500_LOGRET_20D':      { label: '20일 수익률', desc: '한 달 모멘텀. 월간 -10% 이상이면 공식적 조정(correction) 영역' },
  'SP500_DRAWDOWN_60D':    { label: '60일 낙폭', desc: '분기 고점 대비 하락폭. -20% 이상이면 약세장(bear market) 진입 기준' },
  'SP500_MA_GAP_50':       { label: '50일선 괴리', desc: '50일 이평선은 기관 트레이더의 중기 추세 기준선. 이탈 시 추세추종 매도 발생' },
  'SP500_MA_GAP_200':      { label: '200일선 괴리', desc: '200일선은 강세/약세장 경계. 이탈 시 연기금·패시브 펀드의 리밸런싱 매도 촉발' },
  'SP500_INTRADAY_RANGE':  { label: '일중 변동폭', desc: '장중 고가-저가 차이. 평소 대비 2배 이상이면 대형 기관의 급박한 포지션 청산 진행 중' },
  'RV_5D':                 { label: '5일 실현변동성', desc: '최근 1주 실제 주가 변동. 갑자기 커지면 시장에 예상 못한 충격이 발생한 것' },
  'RV_21D':                { label: '21일 실현변동성', desc: '한 달간 실제 변동. 장기 고변동은 불확실성이 해소되지 않고 있다는 의미' },
  'EWMA_VOL_L94':          { label: 'EWMA 변동성', desc: '최근 움직임에 가중치를 둔 변동성. 갑작스런 상승은 새로운 리스크 출현 신호' },
  'VOL_OF_VOL_21D':        { label: '변동성의 변동성', desc: '변동성 자체가 요동치면 시장 참여자들이 리스크를 가늠하지 못하는 패닉 상태' },
  'HY_OAS':                { label: '하이일드 스프레드', desc: '정크본드와 국채의 금리 차. 확대 시 기업 부도 우려 → 주식에서도 자금 이탈' },
  'BBB_OAS':               { label: 'BBB 스프레드', desc: '투자등급 최하위. 이 스프레드가 뛰면 "투자부적격 강등" 도미노 우려 확산' },
  'CCC_OAS':               { label: 'CCC 스프레드', desc: '최저등급 채권 스프레드. 2008년, 2020년 폭락 직전 가장 먼저 급등한 지표' },
  'DGS10_LEVEL':           { label: '10년 금리', desc: '모든 자산 가격의 할인율. 급등하면 성장주 밸류에이션 하락, 급락하면 경기침체 공포' },
  'T10Y3M_SLOPE':          { label: '수익률곡선', desc: '장단기 금리 차. 역전(음수)되면 은행 수익성 악화 + 경기침체 6~18개월 전 경고' },
  'VIX_LEVEL':             { label: 'VIX', desc: 'S&P 500 옵션의 향후 30일 기대 변동성. 20 이하=평온, 30+=공포, 40+=패닉' },
  'VIX_CHANGE_1D':         { label: 'VIX 1일변화', desc: '하루 VIX 급등(+5pt 이상)은 대형 헤지펀드의 긴급 풋옵션 매수를 반영' },
  'VIX_PCTL_252D':         { label: 'VIX 백분위', desc: '1년 중 현재 VIX의 상대 위치. 90% 이상이면 역사적으로 극단적 공포 수준' },
  'VXV_MINUS_VIX':         { label: 'VIX 기간구조', desc: '3개월 VIX - 1개월 VIX. 음수(역전)면 "지금 당장"의 위험이 더 크다는 시장 합의' },
  'SKEW_LEVEL':            { label: 'SKEW', desc: '풋옵션의 꼬리위험 프리미엄. 높으면 월가가 "블랙스완" 이벤트에 보험을 사는 중' },
  'DTWEXBGS_RET_5D':       { label: '달러 5일수익', desc: '달러 강세 시 글로벌 달러 부채 부담 증가 → EM 자금 이탈 → 미국 주식에도 전이' },
  'WTI_RET_5D':            { label: '원유 5일수익', desc: '원유 급락은 수요 둔화(경기침체), 급등은 공급 쇼크(인플레). 양쪽 다 주식에 악재' },
  'VIX9D_MINUS_VIX':       { label: '9일-1개월 VIX', desc: '9일 VIX가 더 높으면 "며칠 내" 급변을 시장이 예상. 폭락 직전에 나타나는 패턴' },
  'VVIX_LEVEL':            { label: 'VVIX', desc: 'VIX 옵션의 변동성. 공포지수 자체가 요동치면 시장이 방향을 못 잡는 극단적 혼란' },
  'VARIANCE_RISK_PREMIUM': { label: '분산 리스크 프리미엄', desc: '옵션 내재 변동성 - 실현 변동성. 클수록 시장이 "앞으로 더 흔들릴 것"에 프리미엄 지불' },
  'PARKINSON_VOL_21D':     { label: '파킨슨 변동성', desc: '장중 고가-저가로 측정한 변동성. 종가만으로 놓치는 장중 급등락을 포착' },
  'SP500_AMIHUD_ILLIQ_20D':{ label: '비유동성', desc: '거래량 대비 가격 변동. 높으면 시장에 매수자가 부족해 소량 매도에도 가격이 급락' },
  'SP500_DOLLAR_VOLUME_Z_20D':{ label: '거래대금 Z', desc: '20일 평균 대비 거래대금 이상치. 폭증은 투매 또는 바닥 매수세 유입' },
  'DFII10_REAL10Y':        { label: '실질금리', desc: '인플레 차감 후 실제 자금조달 비용. 높으면 기업 이익 압박 → 주가 하방 압력' },
  'T10YIE_BREAKEVEN':      { label: '기대인플레', desc: '채권시장이 예상하는 10년 평균 물가상승률. 급등 시 연준 긴축 우려, 급락 시 디플레 공포' },
  'SOFR_MINUS_EFFR':       { label: 'SOFR-EFFR', desc: '단기 자금시장 금리 스프레드. 확대되면 은행 간 신뢰 저하(2008년·2019년 레포 위기)' },
  'NFCI_LEVEL':            { label: 'NFCI', desc: '시카고연은 금융상황지수. 0 이상이면 대출·채권·주식 시장 전반이 긴축적' },
  'CORR_EQ_DGS10_60D':     { label: '주식-금리 상관', desc: '양(+)이면 "금리↑=주가↓" 동조. 인플레 시대의 위험 체제를 나타냄' },
  'HY_OAS_CHG_5D':         { label: 'HY 5일변화', desc: '1주간 하이일드 스프레드 변화. 급확대는 채권 시장의 패닉이 주식보다 먼저 시작된 것' },
  'HY_OAS_CHG_20D':        { label: 'HY 20일변화', desc: '한 달간 추세적 확대는 일시적 충격이 아닌 구조적 신용경색 진행을 의미' },
  'BBB_OAS_CHG_5D':        { label: 'BBB 5일변화', desc: '투자등급 스프레드 급변은 대형 기관의 회사채 투매. 주식시장 폭락에 선행' },
  'BBB_OAS_CHG_20D':       { label: 'BBB 20일변화', desc: 'BBB 스프레드 추세적 확대 시 기업들의 차환(리파이낸싱) 비용 급증 → 실적 악화' },
  'CCC_OAS_CHG_5D':        { label: 'CCC 5일변화', desc: '최저등급 스프레드 급등은 부도 연쇄 우려. 리먼 사태 직전에 가장 먼저 반응한 지표' },
  'CCC_OAS_CHG_20D':       { label: 'CCC 20일변화', desc: '정크본드 시장의 추세적 악화. 장기 확대는 금융위기급 시스템 리스크' },
  'VIX9D_VIX_RATIO':       { label: '9일/1개월 VIX비', desc: '1 초과 시 "이번 주"의 공포가 "이번 달"보다 큼. 급락이 임박한 시장 구조' },
  'VIX_VIX3M_RATIO':       { label: 'VIX/3개월 비율', desc: '1 초과(기간구조 역전)면 시장이 단기 급변을 확신. 정상 복귀 시 최악은 지났다는 신호' },
  'VIX_CHG_5D':            { label: 'VIX 5일변화', desc: '1주간 VIX 추세. 한 번 튀고 바로 내려오면 일시 충격, 계속 오르면 위기 심화' },
};

const NR_FEATURE_DESC = {
  'fundamental_gap': { label: '펀더멘털 괴리', desc: 'Shiller CAPE 기반 적정가 대비 괴리. 괴리가 크면 시장이 펀더멘털이 아닌 투자심리로 움직이는 구간' },
  'erp_zscore':      { label: 'ERP Z점수', desc: '주식위험 프리미엄(기대수익-무위험수익)의 역사적 위치. 극단이면 시장 가격이 합리적 범위를 벗어남' },
  'residual_corr':   { label: '잔차 상관', desc: '펀더멘털로 설명되지 않는 주가 움직임의 동조화. 높으면 "뉴스·심리"가 시장을 지배하는 구간' },
  'dispersion':      { label: '분산도', desc: '종목 간 수익률 차이. 낮으면 시장 전체가 한 방향으로 쏠리는 센티멘트 장세, 높으면 종목별 펀더멘털이 반영되는 선별 장세' },
  'amihud':          { label: '비유동성', desc: '거래량 대비 가격 충격. 유동성이 마르면 소수 거래로 가격이 왜곡되어 펀더멘털에서 이탈하기 쉬움' },
  'vix_term':        { label: 'VIX 기간구조', desc: 'VIX 선물 원월물-근월물 차이. 역전되면 "지금 당장"의 공포가 극심해 심리 주도 장세' },
  'hy_spread':       { label: '하이일드 스프레드', desc: '정크본드 스프레드. 신용시장 공포가 주식까지 전이되면 펀더멘털과 무관하게 일괄 매도 발생' },
  'realized_vol':    { label: '실현 변동성', desc: '실제 주가 변동 크기. 변동성이 높은 구간은 투자자들이 이성보다 감정으로 거래하는 전형적 노이즈 국면' },
};

// 폭락 전조 등급 스타일 (높을수록 위험 = 빨강)
const CS_GRADE_STYLE = {
  '낮음': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '보통': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '주의': { cls: 'badge-yellow', color: '#F59E0B', bg: 'rgba(245,158,11,0.08)' },
  '경고': { cls: 'badge-red', color: '#EF4444', bg: 'rgba(239,68,68,0.08)' },
  '위험': { cls: 'badge-red', color: '#EF4444', bg: 'rgba(239,68,68,0.08)' },
};
// 급등 전조 등급 스타일 (높을수록 상승 기대 = 초록)
const SURGE_GRADE_STYLE = {
  '낮음': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '보통': { cls: 'badge-green', color: '#10B981', bg: 'rgba(16,185,129,0.08)' },
  '주의': { cls: 'badge-yellow', color: '#22C55E', bg: 'rgba(34,197,94,0.08)' },
  '경고': { cls: 'badge-green', color: '#22C55E', bg: 'rgba(34,197,94,0.08)' },
  '위험': { cls: 'badge-green', color: '#16A34A', bg: 'rgba(22,163,74,0.08)' },
};

const TICKER_LABELS = {
  SPY:  'S&P 500',
  QQQ:  '나스닥 100',
  SOXX: '필라델피아 반도체',
  BND:  '미국 채권',
  IWM:  '러셀 2000',
  DIA:  '다우존스',
};

const VIX_LABEL = (v) => v < 15 ? '낮음' : v < 25 ? '보통' : v < 35 ? '높음' : '위험';

function pct(p) { return Math.round(p * 100); }

// 날짜 표시
const now = new Date();
const dateEl = document.getElementById('app-date');
if (dateEl) dateEl.textContent = `${now.getMonth() + 1}월 ${now.getDate()}일`;

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
const AVAILABLE_HOLDINGS = [
  { ticker: 'SPY',  name: 'S&P 500' },
  { ticker: 'QQQ',  name: '나스닥 100' },
  { ticker: 'DIA',  name: '다우존스' },
  { ticker: 'IWM',  name: '러셀 2000' },
  { ticker: 'VTI',  name: '미국 전체' },
  { ticker: 'VOO',  name: 'S&P 500 (V)' },
  { ticker: 'SOXX', name: '반도체' },
  { ticker: 'SMH',  name: '반도체 (VN)' },
  { ticker: 'XLK',  name: '기술' },
  { ticker: 'XLF',  name: '금융' },
  { ticker: 'XLE',  name: '에너지' },
  { ticker: 'XLV',  name: '헬스케어' },
  { ticker: 'XLB',  name: '소재' },
  { ticker: 'XLP',  name: '필수소비재' },
  { ticker: 'XLU',  name: '유틸리티' },
  { ticker: 'XLI',  name: '산업재' },
  { ticker: 'XLRE', name: '부동산' },
  { ticker: 'ARKK', name: '혁신 기술' },
  { ticker: 'GLD',  name: '금' },
  { ticker: 'SLV',  name: '은' },
  { ticker: 'TLT',  name: '장기국채' },
  { ticker: 'BND',  name: '미국 채권' },
  { ticker: 'SCHD', name: '미국 배당' },
  { ticker: 'VXUS', name: '미국 외 주식' },
];

function getHoldings() {
  try {
    const data = localStorage.getItem('holdings');
    if (!data) return null;
    const arr = JSON.parse(data);
    return Array.isArray(arr) && arr.length > 0 ? arr : null;
  } catch { return null; }
}

function setHoldings(arr) {
  localStorage.setItem('holdings', JSON.stringify(arr));
}

// ── 보유종목 설정 화면 ──
let _setupSelected = [];

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
      ? AVAILABLE_HOLDINGS.filter(h => h.ticker.includes(q) || h.name.includes(q))
      : AVAILABLE_HOLDINGS;
    chipsEl.innerHTML = filtered.map(h => {
      const sel = _setupSelected.includes(h.ticker) ? ' selected' : '';
      return `<div class="h-chip${sel}" data-ticker="${h.ticker}">${h.ticker} <span style="font-weight:400;color:${sel ? 'rgba(255,255,255,0.7)' : 'var(--sub)'};font-size:11px">${h.name}</span></div>`;
    }).join('');
  }

  function renderSelected() {
    selectedEl.innerHTML = _setupSelected.length === 0
      ? '<span style="color:var(--sub2);font-size:12px">종목을 선택해주세요</span>'
      : _setupSelected.map(t =>
          `<div class="h-sel-chip">${t}<span class="h-sel-remove" data-ticker="${t}">✕</span></div>`
        ).join('');
    confirmBtn.disabled = _setupSelected.length === 0;
  }

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
  };

  confirmBtn.onclick = () => {
    if (_setupSelected.length === 0) return;
    setHoldings(_setupSelected);
    overlay.style.display = 'none';
    loadHoldingsSummary();
    loadMarketOverview();
    window._sectorLoaded = false;
  };
}

// 설정 아이콘 클릭
document.getElementById('btn-edit-holdings').addEventListener('click', showHoldingsSetup);

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
    <div class="mo-title">시장 요약</div>
    <div class="mo-row"><span class="mo-label">공포 · 탐욕 지수</span><span class="mo-value"><span class="mo-skeleton"></span></span></div>
    <div class="mo-row"><span class="mo-label">주요지수 수익률</span><span class="mo-value"><span class="mo-skeleton"></span></span></div>
    <div class="mo-row"><span class="mo-label">S&P500 RSI (14)</span><span class="mo-value"><span class="mo-skeleton"></span></span></div>
  </div>`;

  try {
    // 마켓 서머리 API 호출
    const res = await fetch('/api/market-summary/today');
    const d = await res.json();

    // Fear & Greed 등급별 색상 결정 (탐욕=초록, 공포=빨강, 나머지=기본)
    const GREED_SET = new Set(['탐욕', '극도 탐욕']);
    const FEAR_SET = new Set(['공포', '극도 공포']);
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
    const rsiLabel = rsi >= 60 ? '과매수' : rsi <= 40 ? '과매도' : '중립';      // 40~60 중립

    // 카드 렌더링
    el.innerHTML = `<div class="mo-card">
      <div class="mo-title">시장 요약</div>
      <div class="mo-row">
        <span class="mo-label">공포 · 탐욕 지수</span>
        <span class="mo-value">
          <span class="mo-score" style="color:${fgColor}">${d.fear_greed.score}</span>
          <span class="mo-badge" style="background:${fgColor}20;color:${fgColor}">${d.fear_greed.rating}</span>
        </span>
      </div>
      <div class="mo-row">
        <span class="mo-label">주요지수 수익률</span>
        <span class="mo-value">
          <span class="mo-score" style="color:${retColor}">${retSign}${retVal.toFixed(2)}%</span>
        </span>
      </div>
      <div class="mo-row">
        <span class="mo-label">S&P500 RSI (14)</span>
        <span class="mo-value">
          <span class="mo-score" style="color:${rsiColor}">${rsi > 0 ? rsi.toFixed(1) : '--'}</span>
          <span class="mo-badge" style="background:${rsiColor}20;color:${rsiColor}">${rsi > 0 ? rsiLabel : '-'}</span>
        </span>
      </div>
    </div>`;
  } catch (e) {
    // API 실패 시 대체 표시
    el.innerHTML = `<div class="mo-card">
      <div class="mo-title">시장 요약</div>
      <div class="mo-row"><span class="mo-label">공포 · 탐욕 지수</span><span class="mo-value">-</span></div>
      <div class="mo-row"><span class="mo-label">주요지수 수익률</span><span class="mo-value">-</span></div>
      <div class="mo-row"><span class="mo-label">S&P500 RSI (14)</span><span class="mo-value">-</span></div>
    </div>`;
  }
}

// ── Holdings Summary (시장 탭 하단) ──
async function loadHoldingsSummary() {
  const el = document.getElementById('holdings-summary');
  const holdings = getHoldings();
  if (!holdings) {
    el.innerHTML = '<div class="holdings-empty" id="holdings-empty-prompt">보유종목을 설정해주세요</div>';
    document.getElementById('holdings-empty-prompt').addEventListener('click', showHoldingsSetup);
    return;
  }
  try {
    const res = await fetch('/api/index/latest');
    const list = await res.json();
    if (!Array.isArray(list) || list.length === 0) {
      el.innerHTML = '<div class="holdings-empty">데이터 준비 중...</div>';
      return;
    }
    const priceMap = {};
    list.forEach(item => { priceMap[item.ticker] = item.change_pct; });
    const matched = holdings.filter(t => priceMap[t] !== undefined);
    if (matched.length === 0) {
      el.innerHTML = '<div class="holdings-empty">보유종목 가격 데이터가 없습니다</div>';
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
    el.innerHTML = '<div class="holdings-empty">데이터를 불러올 수 없습니다</div>';
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

  const name  = data.regime_name ?? '';
  const pos   = NR_GAP_POS[name] ?? 50;
  const color = NR_GAP_COLOR[name] ?? '#999';
  const sub   = NR_SUB[name] ?? '';

  // Update badge
  const badgeEl = document.getElementById('nr-badge');
  const badgeInfo = NR_BADGE[name];
  if (badgeEl && badgeInfo) {
    badgeEl.className = `badge ${badgeInfo.cls}`;
    badgeEl.textContent = badgeInfo.text;
  }

  _nrData = data;  // 상세페이지용 캐시

  const container = document.getElementById('regime-card');
  const nrIcon = NR_ICON[name] || { icon: 'cloud', color: '#999', softBg: 'rgba(0,0,0,0.05)' };
  container.innerHTML = `
    <div class="nr-status">
      <div class="nr-icon-box" style="background:${nrIcon.softBg};color:${nrIcon.color}">
        ${lucideIcon(nrIcon.icon, 30, 1.8)}
      </div>
      <span class="nr-name">${name}</span>
    </div>
    <div class="nr-sub">${sub}</div>
    <div class="nr-gap">
      <div class="nr-gap-labels">
        <span>펀더멘털</span>
        <span>주가</span>
      </div>
      <div class="nr-gap-track">
        <div class="nr-gap-fill" style="width:${pos}%;background:${color}"></div>
        <div class="nr-gap-dot" style="left:${pos}%;border-color:${color}"></div>
      </div>
      <div class="nr-gap-ticks">
        <span>일치</span>
        <span>괴리</span>
      </div>
    </div>`;

  // 카드 터치 → 상세페이지
  const card = container.closest('.card');
  if (card && !card.classList.contains('card-tappable')) {
    card.classList.add('card-tappable');
    card.addEventListener('click', () => openDetail('Noise vs Signal', renderNoiseDetail));
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
  const volLabel = vol >= 1.5 ? '거래 급증'
                 : vol >= 1.1 ? '평균 이상'
                 : vol >= 0.9 ? '평균'
                 : '거래 감소';
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
    const pcLabel = pcRatio >= 1.1 ? '하방 옵션' : pcRatio <= 0.9 ? '상방 옵션' : '중립';
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

  const feed = list.filter(({ ticker }) => TICKER_LABELS[ticker]);
  const html = feed.map(({ ticker, change_pct }) => {
    const sign  = change_pct >= 0 ? '+' : '';
    const cls   = change_pct >= 0 ? 'pos' : 'neg';
    const label = TICKER_LABELS[ticker] ?? ticker;
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
  tabs.forEach(t => t.classList.remove('active'));          // 모든 탭 비활성화
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
  // 신호 탭 최초 진입 시 데이터 로드
  if (idx === 1 && !window._signalLoaded) {
    window._signalLoaded = true;
    loadCrashSurge();
    loadDirection();
    loadCrashSurgeChart();
  }
  // 거시경제 탭 최초 진입 시 데이터 로드
  if (idx === 2 && typeof loadSectorCycle === 'function' && !window._sectorLoaded) {
    window._sectorLoaded = true;
    loadSectorCycle();
  }
  // 히스토리에 상태 추가 (뒤로가기 지원)
  if (addHistory && idx !== _currentTabIdx) {
    history.pushState({ tab: idx }, '');
  }
  _currentTabIdx = idx;                                    // 현재 탭 인덱스 갱신
}

// ── 탭 전환 ──
const TAB_IDS = ['tab-market', 'tab-signal', 'tab-sector'];
const tabs = document.querySelectorAll('.tab');
tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const idx = parseInt(tab.dataset.idx, 10);             // 클릭한 탭 인덱스
    switchTab(idx, true);                                  // 히스토리 추가하며 전환
  });
});

// ── 뒤로가기(popstate) 처리 ──
window.addEventListener('popstate', (e) => {
  const overlay = document.getElementById('detail-overlay');
  // 1. 상세 페이지가 열려있으면 닫기
  if (overlay && overlay.classList.contains('open')) {
    overlay.classList.remove('open');                       // 상세 페이지 닫기 (슬라이드 아웃)
    return;
  }
  // 2. 히스토리에 탭 상태가 있으면 복원
  if (e.state && e.state.tab !== undefined) {
    switchTab(e.state.tab, false);                         // 히스토리 추가 없이 탭 전환
    return;
  }
  // 3. 마지막 화면 (시장 탭)에서 뒤로가기
  if (_currentTabIdx !== 0) {
    switchTab(0, false);                                   // 시장 탭으로 이동
    history.pushState({ tab: 0 }, '');                     // 히스토리 보충
    return;
  }
  // 4. 시장 탭에서 뒤로가기 → 앱이면 2번 눌러야 종료
  if (_isApp) {
    const now = Date.now();
    if (now - _lastBackTime < 2000) {                      // 2초 이내 두 번째 뒤로가기
      return;                                              // 브라우저 기본 동작 (앱 종료)
    }
    _lastBackTime = now;                                   // 첫 번째 뒤로가기 시간 기록
    history.pushState({ tab: 0 }, '');                     // 히스토리 보충 (종료 방지)
    showBackToast();                                       // 토스트 메시지 표시
  }
  // 웹에서는 그대로 브라우저 기본 동작 (페이지 이탈)
});

// 초기 히스토리 상태 설정
history.replaceState({ tab: 0 }, '');

// ── 뒤로가기 토스트 메시지 ──
function showBackToast() {
  let toast = document.getElementById('back-toast');
  if (!toast) {                                            // 토스트 엘리먼트가 없으면 생성
    toast = document.createElement('div');
    toast.id = 'back-toast';
    toast.className = 'back-toast';
    toast.textContent = '한 번 더 누르면 종료됩니다';
    document.body.appendChild(toast);
  }
  toast.classList.add('show');                              // 토스트 표시
  setTimeout(() => toast.classList.remove('show'), 2000);  // 2초 후 숨기기
}

// ── Crash/Surge 전조 탐지 ──
async function loadCrashSurge() {
  try {
    const res = await fetch('/api/crash-surge/current');
    const d = await res.json();
    if (!d) {
      document.getElementById('cs-card').innerHTML =
        '<div style="text-align:center;font-size:13px;color:var(--sub);padding:12px 0">데이터 준비 중...</div>';
      return;
    }

    _csData = d;  // 상세페이지용 캐시

    const badge = document.getElementById('cs-badge');
    const maxGrade = d.crash_score >= d.surge_score ? d.crash_grade : d.surge_grade;
    const bs = CS_GRADE_STYLE[maxGrade] || CS_GRADE_STYLE['보통'];
    badge.className = `badge ${bs.cls}`;
    badge.textContent = maxGrade;

    const el = document.getElementById('cs-card');
    const crashS = CS_GRADE_STYLE[d.crash_grade] || CS_GRADE_STYLE['보통'];
    const surgeS = SURGE_GRADE_STYLE[d.surge_grade] || SURGE_GRADE_STYLE['보통'];

    el.innerHTML = `
      <div class="cs-row">
        <div class="cs-item">
          <div class="cs-item-header">
            <span class="cs-item-label">폭락 전조</span>
            <span class="badge ${crashS.cls}" style="font-size:10px">${d.crash_grade}</span>
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
            <span class="cs-item-label">급등 전조</span>
            <span class="badge ${surgeS.cls}" style="font-size:10px">${d.surge_grade}</span>
          </div>
          <div class="cs-score" style="color:${surgeS.color}">
            <span class="cs-score-num" data-target="${d.surge_score}">0</span>
          </div>
          <div class="cs-bar-track">
            <div class="cs-bar-fill cs-bar-surge" style="width:0%;background:${surgeS.color}"></div>
          </div>
        </div>
      </div>
      <div class="cs-date">${d.date} 기준</div>`;

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
      card.addEventListener('click', () => openDetail('폭락/급등 전조 분석', renderCrashSurgeDetail));
    }
  } catch (e) {
    console.error('Crash/Surge load error:', e);
  }
}

// ── SVG 꺾은선 그래프 공용 함수 ──
function renderLineChart(containerId, points, options = {}) {
  const el = document.getElementById(containerId);                // 컨테이너 요소
  if (!el || points.length < 2) {                                  // 데이터 부족 시 안내
    if (el) el.innerHTML = '<div style="text-align:center;font-size:13px;color:var(--sub);padding:8px 0">데이터 없음</div>';
    return;
  }

  const W = el.clientWidth - 2;                                    // SVG 너비 (패딩 고려)
  const H = options.height || 140;                                 // SVG 높이
  const pad = { top: 12, right: 12, bottom: 22, left: 36 };       // 축 라벨 여백
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

// ── Crash/Surge Net Score 30일 그래프 ──
async function loadCrashSurgeChart() {
  try {
    const res = await fetch('/api/crash-surge/history?days=30');    // 30일 히스토리 요청
    const list = await res.json();                                  // JSON 파싱
    if (!Array.isArray(list) || list.length < 2) return;            // 데이터 부족 시 종료

    const sorted = list.slice().sort((a, b) => a.date.localeCompare(b.date));  // 날짜 오름차순 정렬
    const points = sorted.map(r => ({                              // 그래프 포인트 변환
      label: r.date.slice(5),                                      // MM-DD 형식 라벨
      fullLabel: r.date,                                           // 전체 날짜 (툴팁용)
      value: r.net_score || 0,                                     // net_score 값
    }));

    const lastVal = points[points.length - 1].value;               // 최신 값
    const lineColor = lastVal >= 0 ? 'var(--green)' : 'var(--red)';  // 양수 초록, 음수 빨강

    renderLineChart('cs-chart', points, {                          // 그래프 렌더링
      color: lineColor,                                            // 선 색상
      zeroLine: true,                                              // 0 기준선 표시
      dotColor: v => v >= 0 ? 'var(--green)' : 'var(--red)',       // 점 색상 (값 기반)
    });
  } catch (e) {
    console.error('CS chart error:', e);                           // 에러 로그
  }
}

// ── Noise Score 30일 그래프 ──
async function loadNoiseChart() {
  try {
    const res = await fetch('/api/regime/history?days=30');         // 30일 국면 히스토리 요청
    const list = await res.json();                                  // JSON 파싱
    if (!Array.isArray(list) || list.length < 2) return;            // 데이터 부족 시 종료

    const sorted = list.slice().sort((a, b) => a.date.localeCompare(b.date));  // 날짜 오름차순 정렬
    const points = sorted.map(r => ({                              // 그래프 포인트 변환
      label: r.date.slice(5),                                      // MM-DD 형식 라벨
      fullLabel: r.date,                                           // 전체 날짜 (툴팁용)
      value: r.noise_score != null ? r.noise_score : 0,            // noise_score 값
    }));

    renderLineChart('nr-chart', points, {                          // 그래프 렌더링
      color: 'var(--accent)',                                      // 보라색 선
      zeroLine: true,                                              // 0 기준선 표시
      dotColor: v => v >= 0 ? 'var(--red)' : 'var(--green)',       // 양수(노이즈↑) 빨강, 음수(펀더멘털) 초록
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
      el.innerHTML = '<div style="text-align:center;font-size:13px;color:var(--sub);padding:8px 0">데이터 없음</div>';
      return;
    }

    el.innerHTML = `<div class="cs-hist-table">
      <div class="cs-hist-header">
        <span class="cs-hist-cell cs-hist-date-col">날짜</span>
        <span class="cs-hist-cell">폭락</span>
        <span class="cs-hist-cell">급등</span>
        <span class="cs-hist-cell">방향</span>
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
      el.innerHTML = `<div style="text-align:center;font-size:13px;color:var(--sub);padding:12px 0">${d?.message || '백필 데이터 대기 중...'}</div>`;
      badge.className = 'badge';
      badge.textContent = '';
      return;
    }

    // 방향 뱃지 스타일 결정
    const dirMap = {                                        // 방향별 스타일 매핑
      '상승 우세': { cls: 'badge-green', color: 'var(--green)', icon: '▲' },
      '하락 우세': { cls: 'badge-red', color: 'var(--red)', icon: '▼' },
      '방향 불명': { cls: 'badge-gray', color: 'var(--sub)', icon: '―' },
      '데이터 부족': { cls: 'badge-gray', color: 'var(--sub)', icon: '?' },
    };
    const ds = dirMap[d.direction] || dirMap['데이터 부족']; // 기본값 설정
    badge.className = `badge ${ds.cls}`;                    // 뱃지 클래스 적용
    badge.textContent = d.direction;                         // 뱃지 텍스트

    // net_score 표시
    const netColor = d.current_net_score > 0 ? 'var(--green)' : d.current_net_score < 0 ? 'var(--red)' : 'var(--sub)';
    const netSign = d.current_net_score > 0 ? '+' : '';     // 양수면 + 기호

    // 기간별 통계 테이블 생성
    let statsHtml = '';                                      // 통계 HTML
    const horizons = ['5d', '10d', '20d'];                  // 5일, 10일, 20일
    const hLabels = { '5d': '5일 후', '10d': '10일 후', '20d': '20일 후' };  // 한글 라벨
    if (d.horizon_stats) {
      statsHtml = `<div class="dir-stats-table">
        <div class="dir-stats-header">
          <span class="dir-stats-cell">기간</span>
          <span class="dir-stats-cell">평균</span>
          <span class="dir-stats-cell">상승확률</span>
          <span class="dir-stats-cell">표본</span>
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
            <span class="dir-stats-cell" style="color:var(--sub)">${s.sample_count}건</span>
          </div>`;
        }).join('')}
      </div>`;
    }

    // 백분위 텍스트 생성
    const pctl = d.net_score_percentile;                  // 백분위 값
    const pctlText = pctl != null
      ? `상위 ${(100 - pctl).toFixed(1)}%`
      : '';                                               // 백분위 없으면 빈 문자열

    el.innerHTML = `
      <div style="text-align:center;padding:8px 0 4px">
        <div style="font-size:11px;color:var(--sub);margin-bottom:4px">순방향 점수 (급등 − 폭락)</div>
        <div style="font-size:28px;font-weight:800;color:${netColor}">${netSign}${d.current_net_score}</div>
        ${pctlText ? `<div style="font-size:12px;color:var(--sub);margin-top:2px">과거 대비 <b style="color:${netColor}">${pctlText}</b></div>` : ''}
        <div style="font-size:20px;margin-top:2px">${ds.icon}</div>
      </div>
      <div style="padding:4px 0 8px;font-size:11px;color:var(--sub);text-align:center">
        과거 유사 구간(±${d.margin}) 기준 미래 수익률
      </div>
      ${statsHtml}`;
  } catch (e) {
    console.error('Direction load error:', e);              // 에러 로그
    el.innerHTML = '<div style="text-align:center;font-size:13px;color:var(--sub);padding:12px 0">방향성 분석 로딩 실패</div>';
  }
}

// ── Detail Overlay ──
function openDetail(title, renderFn) {
  const overlay = document.getElementById('detail-overlay');
  const titleEl = document.getElementById('detail-title');
  const body = document.getElementById('detail-body');
  titleEl.textContent = title;                             // 제목 설정
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
  container.innerHTML += `<div class="feat-section-title">현재 지표 수치</div>`;
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
  if (!_csData) { body.innerHTML = '<p style="color:var(--sub)">데이터 없음</p>'; return; }
  const d = _csData;

  // 요약
  const crashS = CS_GRADE_STYLE[d.crash_grade] || CS_GRADE_STYLE['보통'];
  const surgeS = SURGE_GRADE_STYLE[d.surge_grade] || SURGE_GRADE_STYLE['보통'];
  body.innerHTML = `<div style="display:flex;gap:16px;margin-bottom:8px">
    <div style="flex:1;text-align:center">
      <div style="font-size:12px;color:var(--sub);font-weight:600">폭락 전조</div>
      <div style="font-size:28px;font-weight:800;color:${crashS.color}">${d.crash_score.toFixed(1)}</div>
      <span class="badge ${crashS.cls}">${d.crash_grade}</span>
    </div>
    <div style="flex:1;text-align:center">
      <div style="font-size:12px;color:var(--sub);font-weight:600">급등 전조</div>
      <div style="font-size:28px;font-weight:800;color:${surgeS.color}">${d.surge_score.toFixed(1)}</div>
      <span class="badge ${surgeS.cls}">${d.surge_grade}</span>
    </div>
  </div>
  <div style="text-align:center;font-size:11px;color:var(--sub2);margin-bottom:16px">${d.date} 기준 · 모델 F1: ${d.macro_f1}</div>`;


  // SHAP 값
  if (d.shap_values) {
    const mainType = d.crash_score >= d.surge_score ? 'crash' : 'surge';
    const shapItems = d.shap_values[mainType] || [];
    if (shapItems.length > 0) {
      const maxAbs = Math.max(...shapItems.map(s => Math.abs(s.value)), 0.001);
      body.innerHTML += `<div class="feat-section-title">SHAP 기여도 (${mainType === 'crash' ? '폭락' : '급등'} 방향)</div>`;
      renderBarChart(body, shapItems, maxAbs, CS_FEATURE_DESC);
    }
  }

  // SHAP 없을 때 안내
  if (!d.shap_values) {
    body.innerHTML += `<div style="text-align:center;padding:24px 0;color:var(--sub);font-size:13px;line-height:1.6">
      SHAP 분석 데이터가 아직 없습니다.<br>파이프라인을 다시 실행하면 표시됩니다.
    </div>`;
  }

  // 현재 지표값 그리드
  renderFeatureValuesGrid(body, d.feature_values, CS_FEATURE_DESC);

  // 분석에 사용된 지표
  const allItems = [
    ...(d.shap_values?.crash || []),
    ...(d.shap_values?.surge || []),
  ];
  if (allItems.length > 0) {
    body.innerHTML += `<div class="feat-section-title">분석에 사용된 지표</div>`;
    renderDescCards(body, allItems, CS_FEATURE_DESC);
  }
}

// ── Noise vs Signal 상세 ──
function renderNoiseDetail(body) {
  if (!_nrData) { body.innerHTML = '<p style="color:var(--sub)">데이터 없음</p>'; return; }
  const d = _nrData;

  const nrIcon = NR_ICON[d.regime_name] || { color: '#999' };
  body.innerHTML = `<div style="text-align:center;margin-bottom:16px">
    <div style="font-size:14px;color:var(--sub);font-weight:600">현재 국면</div>
    <div style="font-size:24px;font-weight:800;color:${nrIcon.color};display:flex;align-items:center;justify-content:center;gap:8px">${nrIcon.icon ? lucideIcon(nrIcon.icon, 28, 1.8) : ''} ${d.regime_name}</div>
    <div style="font-size:13px;color:var(--sub);margin-top:4px">Noise Score: ${d.noise_score?.toFixed(4) ?? '--'}</div>
    <div style="font-size:11px;color:var(--sub2);margin-top:2px">${d.date} 기준</div>
  </div>`;

  // 피처 기여도
  if (d.feature_contributions && d.feature_contributions.length > 0) {
    const maxAbs = Math.max(...d.feature_contributions.map(c => Math.abs(c.contribution)), 0.001);
    body.innerHTML += `<div class="feat-section-title">노이즈 점수 구성</div>`;
    const items = d.feature_contributions.map(c => ({ name: c.name, value: c.contribution }));
    renderBarChart(body, items, maxAbs, NR_FEATURE_DESC);
  }

  // 현재 지표 수치 (2열 그리드 + 화살표)
  renderFeatureValuesGrid(body, d.feature_values, NR_FEATURE_DESC);

  // 피처 데이터 없을 때 안내
  if (!d.feature_contributions && !d.feature_values) {
    body.innerHTML += `<div style="text-align:center;padding:24px 0;color:var(--sub);font-size:13px;line-height:1.6">
      지표 분석 데이터가 아직 없습니다.<br>파이프라인을 다시 실행하면 표시됩니다.
    </div>`;
  }

  // 분석에 사용된 지표
  const allItems = [
    ...(d.feature_contributions || []),
    ...Object.keys(d.feature_values || {}).map(k => ({ name: k })),
  ];
  if (allItems.length > 0) {
    body.innerHTML += `<div class="feat-section-title">분석에 사용된 지표</div>`;
    renderDescCards(body, allItems, NR_FEATURE_DESC);
  }
}

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

(async () => {
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
    await Promise.allSettled([loadRegime(), loadMacro(), loadFeed(), loadMarketOverview(), loadNoiseChart()]);
  } catch (e) {
    console.error('Init load error:', e);
  }

  clearTimeout(safetyTimer);
  const elapsed = Date.now() - splashStart;
  const remaining = Math.max(0, 2200 - elapsed);

  setTimeout(safeDismiss, remaining);
})();
