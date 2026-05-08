// ── 좌측 햄버거 메뉴 드로어 ─────────────────────────────────────────────────
// stocks.html 의 #btn-menu / #menu-drawer / #menu-backdrop 토글.
// 외부 클릭(백드롭) / ESC / 메뉴 링크 클릭 시 자동 닫힘.
(function() {
  'use strict';

  var btnMenu = document.getElementById('btn-menu');
  var btnClose = document.getElementById('btn-menu-close');
  var drawer = document.getElementById('menu-drawer');
  var backdrop = document.getElementById('menu-backdrop');
  if (!btnMenu || !drawer || !backdrop) return;                  // 마크업 누락 시 noop

  function openDrawer() {
    drawer.classList.add('open');
    backdrop.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    backdrop.setAttribute('aria-hidden', 'false');
    btnMenu.setAttribute('aria-expanded', 'true');
    document.body.classList.add('menu-open');
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    backdrop.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    backdrop.setAttribute('aria-hidden', 'true');
    btnMenu.setAttribute('aria-expanded', 'false');
    document.body.classList.remove('menu-open');
  }

  btnMenu.addEventListener('click', function(e) {
    e.stopPropagation();
    if (drawer.classList.contains('open')) closeDrawer(); else openDrawer();
  });
  if (btnClose) btnClose.addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
  });
  // 활성 링크(<a>) 클릭은 페이지 이동 → 닫지 않아도 자연 unmount, 하지만 SPA-like 라우트 추가 시 대비.
  Array.prototype.forEach.call(drawer.querySelectorAll('a.menu-link'), function(a) {
    a.addEventListener('click', closeDrawer);
  });
})();
