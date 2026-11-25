'use strict';

(() => {
  const key = 'etf-dashboard-theme';
  const root = document.documentElement;
  const themeColor = document.querySelector('meta[name="theme-color"]');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  let dark = false;
  let toggles = [];
  let transition;

  function syncControls() {
    for (const toggle of toggles) {
      toggle.setAttribute('aria-pressed', String(dark));
      toggle.querySelector('[data-theme-icon]').textContent = dark ? '☾' : '☼';
      toggle.querySelector('[data-theme-label]').textContent = dark ? '深色' : '浅色';
    }
  }
  function setTheme(next) {
    dark = next;
    root.dataset.theme = dark ? 'dark' : 'light';
    themeColor?.setAttribute('content', dark ? '#161513' : '#f4f2ec');
    syncControls();
  }
  function switchTheme() {
    const next = !dark;
    const apply = () => {
      setTheme(next);
      try { localStorage.setItem(key, root.dataset.theme); } catch { /* preference is optional */ }
    };
    transition?.skipTransition();
    if (reducedMotion.matches || typeof document.startViewTransition !== 'function') {
      apply();
    } else {
      transition = document.startViewTransition(apply);
      transition.ready.catch(() => {}); // superseded by a second switch
    }
  }
  try { setTheme(localStorage.getItem(key) === 'dark'); } catch { setTheme(false); }
  document.addEventListener('DOMContentLoaded', () => {
    toggles = document.querySelectorAll('[data-theme-toggle]');
    syncControls();
    for (const toggle of toggles) toggle.addEventListener('click', switchTheme);
  }, {once: true});
  window.addEventListener('storage', event => { if (event.key === key) setTheme(event.newValue === 'dark'); });
})();
