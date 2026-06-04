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
