// Client-side interface translation for shared item pages; see src/components/SharedI18n.astro.
(() => {
  const me = document.currentScript;
  const dictBase = me.dataset.dict, base = me.dataset.base;

  (async () => {
    const lang = new URLSearchParams(location.search).get('lang');
    if (lang !== 'sv' && lang !== 'en') return;
    let dict;
    try { dict = await (await fetch(`${dictBase}${lang}.json`)).json(); } catch { return; }
    const fill = (key, vars) => (dict[key] ?? '').replace(/\{(\w+)\}/g, (_, n) => {
      const v = vars[n];
      return typeof v === 'string' && v.startsWith('@') ? (dict[v.slice(1)] ?? v) : String(v ?? '');
    });
    document.documentElement.lang = lang;
    for (const el of document.querySelectorAll('[data-t]')) {
      const text = fill(el.dataset.t, JSON.parse(el.dataset.tv || '{}'));
      if (text) el.textContent = text;
    }
    for (const el of document.querySelectorAll('[data-i18n-aria]')) {
      const text = dict[el.dataset.i18nAria];
      if (text) el.setAttribute('aria-label', text);
    }
    for (const a of document.querySelectorAll('a[href]')) {
      if (a.closest('[data-lang-switch]')) continue;
      const url = new URL(a.getAttribute('href'), location.href);
      if (url.origin !== location.origin || !url.pathname.startsWith(base)) continue;
      if (a.hasAttribute('data-shared')) url.searchParams.set('lang', lang);
      else url.pathname = `${base}${lang}/${url.pathname.slice(base.length)}`;
      a.setAttribute('href', url.pathname + url.search + url.hash);
    }
    for (const a of document.querySelectorAll('[data-lang-switch] a')) {
      if (a.hreflang === lang) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    }
    for (const el of document.querySelectorAll('[data-locale-only]')) el.hidden = false;
  })();
})();
