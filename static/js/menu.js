// ── 좌측 햄버거 메뉴 드로어 ─────────────────────────────────────────────────
// stocks.html 의 #btn-menu / #menu-drawer / #menu-backdrop 토글.
// 외부 클릭(백드롭) / ESC / 메뉴 링크 클릭 시 자동 닫힘.
(function() {
  'use strict';

  function init() {
    var btnMenu = document.getElementById('btn-menu');
    var btnClose = document.getElementById('btn-menu-close');
    var drawer = document.getElementById('menu-drawer');
    var backdrop = document.getElementById('menu-backdrop');

    if (!btnMenu || !drawer || !backdrop) {
      console.warn('[menu.js] 마크업 누락 — btn-menu/menu-drawer/menu-backdrop 중 하나 없음', {
        btnMenu: !!btnMenu, drawer: !!drawer, backdrop: !!backdrop
      });
      return;
    }

    // 이미 init 됐으면 중복 attach 방지 (스크립트 두 번 로드 가드)
    if (btnMenu.dataset.menuInit === '1') return;
    btnMenu.dataset.menuInit = '1';

    function openDrawer() {
      drawer.classList.add('open');
      backdrop.classList.add('open');
      drawer.setAttribute('aria-hidden', 'false');
      backdrop.setAttribute('aria-hidden', 'false');
      btnMenu.setAttribute('aria-expanded', 'true');
      document.body.classList.add('menu-open');
      // 시스템 뒤로가기 처리 — 메뉴 닫기만, 직전 화면 유지
      try { history.pushState({ menuOpen: true }, ''); window._menuStates = (window._menuStates || 0) + 1; } catch (e) {}
    }
    function closeDrawer() {
      drawer.classList.remove('open');
      backdrop.classList.remove('open');
      drawer.setAttribute('aria-hidden', 'true');
      backdrop.setAttribute('aria-hidden', 'true');
      btnMenu.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('menu-open');
    }
    // window 노출 — popstate 핸들러에서 호출
    window._closeMenuDrawer = closeDrawer;
    window._isMenuOpen = function() { return drawer.classList.contains('open'); };

    btnMenu.addEventListener('click', function(e) {
      e.preventDefault();
      e.stopPropagation();
      if (drawer.classList.contains('open')) closeDrawer(); else openDrawer();
    });
    if (btnClose) btnClose.addEventListener('click', function(e) {
      e.preventDefault();
      closeDrawer();
    });
    backdrop.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
    });
    Array.prototype.forEach.call(drawer.querySelectorAll('a.menu-link'), function(a) {
      a.addEventListener('click', closeDrawer);
    });

    console.log('[menu.js] init OK');
  }

  // DOM 준비 후 실행 — script 태그 위치 무관하게 동작 보장.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
