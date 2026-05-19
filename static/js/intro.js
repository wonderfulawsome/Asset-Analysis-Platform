/* Intro 오버레이 — 첫 진입 1회만 노출.
   localStorage 'passive_intro_seen' = '1' 이면 skip.
   splash 제거 후 main.js dismissSplash 에서 window.showIntroIfNeeded(cb) 호출. */
(function() {
  'use strict';
  const STORAGE_KEY = 'passive_intro_seen';
  // 첫 방문자만 노출. true 로 두면 새로고침마다 노출 (개발용).
  const FORCE_ALWAYS_SHOW = false;
  let _idx = 0;
  let _slides = [];
  let _dots = [];
  let _onDone = null;
  let _overlay = null;
  let _btn = null;

  function _update() {
    _slides.forEach((s, i) => {
      s.classList.toggle('active', i === _idx);
      s.classList.toggle('prev', i < _idx);
    });
    _dots.forEach((d, i) => d.classList.toggle('active', i === _idx));
    if (_btn) _btn.textContent = (_idx === _slides.length - 1) ? '시작하기' : '다음';
  }

  function _next() {
    if (_idx < _slides.length - 1) {
      _idx++;
      _update();
    } else {
      _close();
    }
  }

  function _close() {
    if (!FORCE_ALWAYS_SHOW) {
      try { localStorage.setItem(STORAGE_KEY, '1'); } catch (_) {}
    }
    if (!_overlay) { if (_onDone) _onDone(); return; }
    _overlay.classList.remove('visible');
    _overlay.classList.add('fade-out');
    const cb = _onDone;
    setTimeout(() => {
      if (_overlay) _overlay.style.display = 'none';
      _overlay = null;
      if (cb) cb();
    }, 280);
  }

  function _bindEvents() {
    const next = document.getElementById('intro-next');
    const skip = document.getElementById('intro-skip');
    if (next) {
      _btn = next;
      next.addEventListener('click', _next);
    }
    if (skip) skip.addEventListener('click', _close);
    // 좌우 스와이프
    let startX = null;
    const stage = document.getElementById('intro-stage');
    if (stage) {
      stage.addEventListener('touchstart', (e) => { startX = e.touches[0].clientX; }, { passive: true });
      stage.addEventListener('touchend', (e) => {
        if (startX == null) return;
        const dx = e.changedTouches[0].clientX - startX;
        startX = null;
        if (dx < -40) _next();
        else if (dx > 40 && _idx > 0) { _idx--; _update(); }
      });
    }
    // 키보드 → / Enter
    document.addEventListener('keydown', _onKey);
  }
  function _onKey(e) {
    if (!_overlay || _overlay.style.display === 'none') return;
    if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); _next(); }
    else if (e.key === 'ArrowLeft' && _idx > 0) { e.preventDefault(); _idx--; _update(); }
    else if (e.key === 'Escape') { e.preventDefault(); _close(); }
  }

  function _buildDots() {
    const wrap = document.getElementById('intro-dots');
    if (!wrap) return;
    wrap.innerHTML = '';
    _dots = _slides.map((_, i) => {
      const d = document.createElement('span');
      d.className = 'dot' + (i === 0 ? ' active' : '');
      d.addEventListener('click', () => { _idx = i; _update(); });
      wrap.appendChild(d);
      return d;
    });
  }

  window.showIntroIfNeeded = function(onDone) {
    let seen = false;
    if (!FORCE_ALWAYS_SHOW) {
      try { seen = localStorage.getItem(STORAGE_KEY) === '1'; } catch (_) {}
    }
    if (seen) { if (onDone) onDone(); return; }
    _overlay = document.getElementById('intro-overlay');
    if (!_overlay) { if (onDone) onDone(); return; }
    _slides = Array.from(_overlay.querySelectorAll('.intro-slide'));
    if (_slides.length === 0) { if (onDone) onDone(); return; }
    _onDone = onDone;
    _idx = 0;
    _overlay.style.display = 'flex';
    _overlay.setAttribute('aria-hidden', 'false');
    // 강제 reflow 후 visible 클래스로 fade-in
    void _overlay.offsetWidth;
    _overlay.classList.add('visible');
    _buildDots();
    _bindEvents();
    _update();
  };

  // 디버그: 다시 보고 싶을 때 console 에서 호출
  window.resetPassiveIntro = function() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    console.log('[intro] reset — 다음 로드 시 다시 노출');
  };
})();
