/**
 * Static DOM localization for sidepanel / options pages.
 *
 * Chrome auto-substitutes `__MSG_key__` only in manifest.json and CSS, never
 * in HTML text nodes. This helper localizes markup at load time via two
 * data-attributes (the original Chinese stays in the HTML as a fallback when a
 * key is missing):
 *
 *   <h1 data-i18n="vocabTitle">我的單字本</h1>
 *       → textContent = chrome.i18n.getMessage('vocabTitle')
 *
 *   <input data-i18n-attr="placeholder:searchPlaceholder;aria-label:searchClearAria">
 *       → setAttribute for each "attr:key" pair (semicolon-separated)
 *
 * Classic script (no module/import) so it can be dropped into any page before
 * its main logic. Content scripts do NOT use this — they call
 * chrome.i18n.getMessage directly since their UI is built in JS.
 */
(function () {
  'use strict';

  function localize(root) {
    root.querySelectorAll('[data-i18n]').forEach((el) => {
      const msg = chrome.i18n.getMessage(el.dataset.i18n);
      if (msg) el.textContent = msg;
    });
    root.querySelectorAll('[data-i18n-attr]').forEach((el) => {
      el.dataset.i18nAttr.split(';').forEach((pair) => {
        const idx = pair.indexOf(':');
        if (idx === -1) return;
        const attr = pair.slice(0, idx).trim();
        const key = pair.slice(idx + 1).trim();
        if (!attr || !key) return;
        const msg = chrome.i18n.getMessage(key);
        if (msg) el.setAttribute(attr, msg);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => localize(document));
  } else {
    localize(document);
  }
})();
