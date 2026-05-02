/* Region (US/KR) 토글 상태 + API 헬퍼.
   - localStorage 'region' 에 저장 (default 'us')
   - 헤더 토글 클릭 → region 반전 → 페이지 새로고침
   - getRegion() / withRegion(url) 두 헬퍼 export (window 전역)
*/
(function () {
  const STORAGE_KEY = 'region';
  const VALID = new Set(['us', 'kr']);

  function getRegion() {
    const r = localStorage.getItem(STORAGE_KEY) || 'us';
    return VALID.has(r) ? r : 'us';
  }

  function setRegion(r) {
    if (!VALID.has(r)) return;
    localStorage.setItem(STORAGE_KEY, r);
  }

  // URL 에 region 쿼리 자동 부착 (이미 있으면 덮어쓰지 않음)
  function withRegion(url) {
    if (typeof url !== 'string') return url;
    if (url.indexOf('region=') >= 0) return url;
    const sep = url.indexOf('?') >= 0 ? '&' : '?';
    return url + sep + 'region=' + getRegion();
  }

  // 토글 UI 동기화
  function applyToggleClass() {
    const el = document.getElementById('btn-region');
    if (!el) return;
    const r = getRegion();
    el.classList.remove('region-mode-us', 'region-mode-kr');
    el.classList.add('region-mode-' + r);
  }

  // KR 모드일 때 안내 배너 삽입 (Stage 2 까지 노출용)
  function injectKrComingSoon() {
    if (getRegion() !== 'kr') return;
    if (document.querySelector('.kr-coming-soon')) return;
    const banner = document.createElement('div');
    banner.className = 'kr-coming-soon';
    banner.innerHTML = '<b>🇰🇷 한국 시장 데이터 준비 중</b><br>'
      + 'KOSPI · VKOSPI · KODEX/TIGER 섹터 ETF 데이터 수집 인프라 구축 완료. '
      + '실제 데이터 연결은 Stage 2 에서 진행됩니다.';
    const home = document.getElementById('home-view');
    if (home) {
      home.insertBefore(banner, home.firstChild);
    } else {
      document.body.insertBefore(banner, document.body.firstChild);
    }
  }

  // ── window.fetch 몽키패치 — /api/* 호출에 자동 region 파라미터 부착 ──
  // (URL 에 이미 region= 있으면 덮어쓰지 않음. 외부 도메인 호출은 영향 없음.)
  const _origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    try {
      let url = input;
      if (typeof input === 'string') {
        // 절대 URL 이거나 /api/ 로 시작하는 경우만 처리
        if (input.indexOf('/api/') === 0 || input.indexOf('://') > 0 && /\/api\//.test(input)) {
          if (input.indexOf('region=') < 0) {
            url = withRegion(input);
          }
        }
      } else if (input instanceof Request) {
        // Request 객체 전달 시는 그대로 (드물어 별도 처리 안 함)
      }
      return _origFetch(url, init);
    } catch (e) {
      return _origFetch(input, init);
    }
  };

  // 초기 적용
  document.addEventListener('DOMContentLoaded', function () {
    applyToggleClass();
    injectKrComingSoon();
    const btn = document.getElementById('btn-region');
    if (btn) {
      btn.addEventListener('click', function () {
        const next = getRegion() === 'us' ? 'kr' : 'us';
        setRegion(next);
        location.reload();
      });
    }
  });

  // 전역 노출
  window.getRegion = getRegion;
  window.setRegion = setRegion;
  window.withRegion = withRegion;
})();
