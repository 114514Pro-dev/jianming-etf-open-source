'use strict';
(() => {
  // This file runs only in the three dedicated research pages, never in the
  // existing trading UI. It reuses its original session and CSRF endpoint.
  const originalFetch = window.fetch.bind(window);
  async function csrf() {
    const response = await originalFetch('/api/session', {credentials:'same-origin',cache:'no-store'});
    const state = await response.json();
    if (!state.authenticated || !state.csrf) {
      window.location.assign('/?sector_research=1');
      throw new Error('登录已过期，请在简明ETF重新登录。');
    }
    return state.csrf;
  }
  window.fetch = async function(input, options = {}) {
    const request = input instanceof Request ? input : null;
    const url = new URL(request ? request.url : String(input), window.location.href);
    const internal = url.origin === window.location.origin && url.pathname.startsWith('/api/') &&
      !['/api/session','/api/login','/api/logout'].includes(url.pathname);
    if (!internal) return originalFetch(input, options);
    if (!url.pathname.startsWith('/api/sector-research/')) {
      url.pathname = '/api/sector-research/' + url.pathname.slice('/api/'.length);
    }
    const method = String(options.method || request?.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || request?.headers || {});
    if (!['GET','HEAD','OPTIONS'].includes(method)) headers.set('X-CSRF-Token', await csrf());
    const mapped = request ? new Request(url.href, request) : url.href;
    const response = await originalFetch(mapped, {...options, method, headers, credentials:'same-origin',cache:'no-store'});
    if (response.status === 401) window.location.assign('/?sector_research=1');
    return response;
  };
})();
