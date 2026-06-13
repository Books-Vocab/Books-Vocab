/**
 * shared/icons.js — inline SVG icon set replacing emoji so the chrome surfaces
 * speak the same SF-Symbols-style visual language as the iOS app (emoji render
 * differently per-OS and clash with the native look; line-weight geometric
 * glyphs do not).
 *
 * Each glyph: 24×24 grid, fill:none, stroke:currentColor (inherits the element's
 * color — e.g. --tint on the theme button), regular line weight ≈ SF Symbols.
 * Glyphs are decorative (aria-hidden); the accessible label lives on the button.
 *
 * Loaded as a classic script (exposes the `KGIcons` global), mirroring pure.js.
 * Also CommonJS-exported so shared/icons.test.js can require it under node:test.
 */

(function (root) {
  'use strict';

  // Shared <svg> open-tag attributes — one source for grid + stroke contract.
  const ATTRS =
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ' +
    'aria-hidden="true" focusable="false"';

  // name → inner path markup. Hand-drawn geometric line glyphs (no SF Symbols
  // assets — those are Apple-proprietary; these are plain primitives that match
  // the visual language). Sources chosen to mirror iOS intent:
  //   source-local ↔ iOS WordRow `book.closed`; source-web ↔ globe.
  const PATHS = {
    // sun.max — light theme
    'theme-light':
      '<circle cx="12" cy="12" r="4"/>' +
      '<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4' +
      'M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
    // moon — dark theme
    'theme-dark':
      '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
    // open book — sepia (reading) theme
    'theme-sepia':
      '<path d="M12 6.5C10.5 5.5 8 5 4 5v13c4 0 6.5.5 8 1.5 ' +
      '1.5-1 4-1.5 8-1.5V5c-4 0-6.5.5-8 1.5z"/><path d="M12 6.5v13"/>',
    // gearshape — settings
    'settings':
      '<circle cx="12" cy="12" r="3"/>' +
      '<path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1' +
      'a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1A1.6 1.6 0 0 0 9 19.4' +
      'a1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0-1.1-2.7H3' +
      'a2 2 0 0 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1' +
      'a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3' +
      'a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1' +
      'a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21' +
      'a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
    // globe — web source
    'source-web':
      '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/>' +
      '<path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/>',
    // book.closed — local (book) source; mirrors iOS WordRow book.closed
    'source-local':
      '<path d="M5 4.5h12.5a1 1 0 0 1 1 1V20a1 1 0 0 1-1 1H6.5' +
      'A1.5 1.5 0 0 1 5 19.5z"/><path d="M5 17.5h13.5"/><path d="M8.5 4.5V17"/>',

    // magnifyingglass — search field leading icon (mirrors iOS AppSearchField)
    'search':
      '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.2-4.2"/>',
    // iOS KGVocabEmptyState.systemImage: magnifyingglass
    'magnifyingglass':
      '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.2-4.2"/>',
    // xmark.circle — clear the search field (mirrors iOS xmark.circle.fill, outline)
    'clear':
      '<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>',
    // checkmark — active item in the sort menu (mirrors iOS Menu selection check)
    'check':
      '<path d="M5 13l4 4L19 7"/>',
    // plus — create notebook
    'plus':
      '<path d="M12 5v14M5 12h14"/>',
    // pencil — rename/edit notebook
    'pencil':
      '<path d="M4 20l4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10z"/>' +
      '<path d="M13.5 6.5l4 4"/>',
    // trash — delete notebook
    'trash':
      '<path d="M4 7h16M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7"/>' +
      '<path d="M6.5 7l.8 13h9.4l.8-13M10 11v5M14 11v5"/>',

    // --- Word-detail / navigation / popup glyphs ---
    // speaker.wave.2 — pronounce (TTS via Web Speech); mirrors iOS detail speaker
    'speaker':
      '<path d="M4 9.5v5h3.5L13 19V5L7.5 9.5H4z"/>' +
      '<path d="M16.5 9a4 4 0 0 1 0 6"/><path d="M19 6.5a7.5 7.5 0 0 1 0 11"/>',
    // chevron.left — back navigation (detail panel → list)
    'chevron-left':
      '<path d="M15 5l-7 7 7 7"/>',
    // arrow.up.right — navigable knowledge-link accessory (mirrors iOS detail link row)
    'arrow-up-right':
      '<path d="M7 17L17 7"/><path d="M8 7h9v9"/>',
    // square.and.arrow.up — word-detail share action (mirrors iOS ShareLink)
    'square.and.arrow.up':
      '<path d="M12 15V4"/><path d="M8 8l4-4 4 4"/>' +
      '<path d="M5 11v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8"/>',
    // doc.on.doc — clipboard fallback / copied state
    'doc.on.doc':
      '<rect x="8" y="7" width="10" height="13" rx="2"/>' +
      '<path d="M6 17H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"/>',
    // xmark — explicit popup close
    'xmark':
      '<path d="M6 6l12 12M18 6L6 18"/>',
    // arrow.clockwise — manual refresh of the vocab list
    'refresh':
      '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 4v5h-5"/>',
    // link — knowledge-link section header + metadata "N links" chip
    'link':
      '<path d="M10.5 13.5a4 4 0 0 0 5.7 0l3-3a4 4 0 1 0-5.7-5.7L11 6.3"/>' +
      '<path d="M13.5 10.5a4 4 0 0 0-5.7 0l-3 3a4 4 0 1 0 5.7 5.7L13 17.7"/>',
    // iOS KGVocabEmptyState.systemImage: books.vertical
    'books.vertical':
      '<path d="M5 4.5h5.5v15H5a1.5 1.5 0 0 1-1.5-1.5V6A1.5 1.5 0 0 1 5 4.5z"/>' +
      '<path d="M13.5 4.5H19A1.5 1.5 0 0 1 20.5 6v12a1.5 1.5 0 0 1-1.5 1.5h-5.5z"/>' +
      '<path d="M10.5 4.5v15M13.5 4.5v15M6.5 8h2M15.5 8h2"/>',
    // iOS KGVocabEmptyState.systemImage: sparkles
    'sparkles':
      '<path d="M12 3l1.5 4.2L18 9l-4.5 1.8L12 15l-1.5-4.2L6 9l4.5-1.8z"/>' +
      '<path d="M5 14l.8 2.2L8 17l-2.2.8L5 20l-.8-2.2L2 17l2.2-.8z"/>' +
      '<path d="M19 13l.7 1.8 1.8.7-1.8.7L19 18l-.7-1.8-1.8-.7 1.8-.7z"/>',
    // iOS KGVocabEmptyState.systemImage: checkmark.seal
    'checkmark.seal':
      '<path d="M12 3.5l2.2 1.3 2.5-.2 1.1 2.2 2.2 1.1-.2 2.5L21 12l-1.3 2.2.2 2.5-2.2 1.1-1.1 2.2-2.5-.2L12 21l-2.2-1.3-2.5.2-1.1-2.2-2.2-1.1.2-2.5L3 12l1.3-2.2-.2-2.5 2.2-1.1 1.1-2.2 2.5.2z"/>' +
      '<path d="M8.5 12.3l2.3 2.3 4.7-5.2"/>',
    // iOS KGVocabEmptyState.systemImage: leaf
    'leaf':
      '<path d="M20 4c-7.5.4-12.5 3.4-14.7 8.1-1.6 3.4.1 6.6 3.5 7.4 4.9 1.1 9.5-3.3 11.2-15.5z"/>' +
      '<path d="M5 20c3.5-5.8 7-8.8 12-11"/>',
    // iOS KGVocabEmptyState.systemImage: line.3.horizontal.decrease.circle
    'line.3.horizontal.decrease.circle':
      '<circle cx="12" cy="12" r="9"/>' +
      '<path d="M7 8h10M9 12h6M11 16h2"/>',
    // calendar — metadata footer date chip
    'calendar':
      '<rect x="4" y="5.5" width="16" height="15" rx="2"/>' +
      '<path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',

    // --- Word-detail section-label leading icons (mirror iOS CardSectionLabel) ---
    // text.word.spacing — 搭配 (collocation): two adjacent word blocks
    'detail-collocation':
      '<rect x="3" y="7.5" width="8" height="9" rx="1.8"/>' +
      '<rect x="13" y="7.5" width="8" height="9" rx="1.8"/>',
    // text.badge.plus — 變化形 (inflections): text lines + a plus badge (derived forms)
    'detail-forms':
      '<path d="M4 8h10M4 12.5h7M4 17h10"/><path d="M18.5 5.5v5M16 8h5"/>',

    // --- Settings grouped-list section-header leading icons (mirror iOS) ---
    // person.crop.circle — 帳號 (account)
    'account':
      '<circle cx="12" cy="8" r="3.5"/><path d="M5.5 19a6.5 6.5 0 0 1 13 0"/>',
    // slider.horizontal.3 — 偏好 (preferences)
    'preferences':
      '<path d="M4 8.5h16M4 15.5h16"/>' +
      '<circle cx="9" cy="8.5" r="2.2"/><circle cx="15" cy="15.5" r="2.2"/>',
    // info.circle — 關於 (about)
    'about':
      '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5h.01"/>',

    // --- Error-state glyphs (side-panel error UI; rendered via classifyError) ---
    // lock — auth/login error
    'error-login':
      '<rect x="5" y="11" width="14" height="9" rx="2"/>' +
      '<path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    // hourglass — quota / rate limit
    'error-quota':
      '<path d="M7 3h10M7 21h10M8 3c0 4 3 5.5 4 7 1-1.5 4-3 4-7' +
      'M8 21c0-4 3-5.5 4-7 1 1.5 4 3 4 7"/>',
    // wifi.slash — no connection (round-cap dot for the base node)
    'error-network':
      '<path d="M2 8.8a16 16 0 0 1 20 0M5 12.5a11 11 0 0 1 14 0' +
      'M8.5 16a6 6 0 0 1 7 0M12 19.5h.01"/><path d="M3 3l18 18"/>',
    // wrench — server busy / maintenance
    'error-server':
      '<path d="M14.7 6.3a4 4 0 0 0-5.2 5.2L4 17l3 3 5.5-5.5' +
      'a4 4 0 0 0 5.2-5.2l-2.6 2.6-2.5-.7-.7-2.5z"/>',
    // exclamationmark.triangle — generic error (round-cap dot under the stem)
    'error-generic':
      '<path d="M10.3 4 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4' +
      'a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z"/>' +
      '<path d="M12 9v4M12 16.5h.01"/>',
  };

  /** Return the full <svg> markup for `name`, or '' for an unknown name. */
  function svg(name) {
    const inner = PATHS[name];
    if (!inner) return '';
    return '<svg ' + ATTRS + '>' + inner + '</svg>';
  }

  /**
   * Replace `el`'s content with the named icon. Returns true on success.
   * The markup is a module-internal constant (never user data), so assigning it
   * to innerHTML carries no injection risk; empty/unknown names clear the node.
   */
  function setIcon(el, name) {
    if (!el) return false;
    const markup = svg(name);
    if (!markup) {
      if (typeof el.replaceChildren === 'function') el.replaceChildren();
      else el.textContent = '';
      return false;
    }
    el.innerHTML = markup;
    return true;
  }

  const api = { svg, setIcon, NAMES: Object.keys(PATHS) };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.KGIcons = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
