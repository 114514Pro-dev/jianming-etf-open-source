'use strict';

(() => {
  const key = 'etf-dashboard-theme';
  const root = document.documentElement;
  const toggles = document.querySelectorAll('[data-theme-toggle]');
  const themeColor = document.querySelector('meta[name="theme-color"]');
  let dark = false;
  function setTheme(next) {
    dark = next;
    root.dataset.theme = dark ? 'dark' : 'light';
    themeColor?.setAttribute('content', dark ? '#111113' : '#f4f2ec');
    for (const toggle of toggles) toggle.setAttribute('aria-pressed', String(dark));
  }
  try { setTheme(localStorage.getItem(key) === 'dark'); } catch { setTheme(false); }
  for (const toggle of toggles) toggle.addEventListener('click', () => {
    setTheme(!dark);
    try { localStorage.setItem(key, root.dataset.theme); } catch { /* preference is optional */ }
  });
  window.addEventListener('storage', event => { if (event.key === key) setTheme(event.newValue === 'dark'); });
})();
