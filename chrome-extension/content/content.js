/**
 * KG Chrome Extension — Content Script
 *
 * Detects text selection on web pages, creates a Shadow DOM popup
 * for translation and vocabulary capture.
 */

(() => {
  'use strict';

  const HOST_ID = 'kg-popup-host';
  const MAX_LEN = 200;
  const MIN_LEN = 1;
  // Selection length above which a translation is treated as a phrase (not a
  // single word). Must track the 50-char phrase threshold (formerly mirrored by
  // KGPure.isPhrase, now content-script-local) — content scripts run in an
  // isolated world and cannot import KGPure.
  const PHRASE_MIN_LEN = 50;
  // Cap on extracted surrounding-sentence context sent to the backend.
  const MAX_CONTEXT_LEN = 500;

  // Popup geometry — pairs with the popup.css layout contract.
  const POPUP_MAX_WIDTH = 360;
  const POPUP_EST_HEIGHT = 220;

  // Short i18n accessor. Content scripts read chrome.i18n directly — their UI
  // is built in JS (not HTML), so shared/i18n.js does not apply here.
  const t = (key, subs) => chrome.i18n.getMessage(key, subs);

  // Shown when this content script is orphaned by an extension reload/update
  // (see extensionContextValid). Resolved ONCE at load time (context still
  // valid) and cached, so the invalidated-context path never calls getMessage
  // on a dead runtime — which would itself throw.
  const CONTEXT_INVALIDATED_MSG = t('popupContextInvalidated');

  /** Currently active host element (only one popup at a time). */
  let activeHost = null;

  /** Cached tokens.css + kg-components.css + popup.css text for shadow roots. */
  let cachedStyles = null;

  /**
   * Cached KG theme (light|dark|sepia) for the shadow popup. tokens.css is
   * injected into a closed shadow root where `:root` matches nothing; the
   * popup root carries [data-theme] so themed vars resolve (default light comes
   * from the sheet's `:host` block). Mirrors shared/theme.js storage contract.
   */
  const THEME_KEY = 'kg_theme';
  const VALID_THEMES = ['light', 'dark', 'sepia'];
  let cachedTheme = 'light';

  const resolveTheme = (value) => (VALID_THEMES.includes(value) ? value : 'light');

  /**
   * Master on/off switch (options page). Default ON: a missing key (fresh
   * install, or storage read failure) leaves selection-to-translate enabled,
   * so the extension keeps working if storage is unavailable. Only an explicit
   * stored `false` disables the popup. Mirrors the THEME_KEY storage contract.
   */
  const ENABLED_KEY = 'kg_enabled';
  let cachedEnabled = true;

  const resolveEnabled = (value) => value !== false;

  if (chrome?.storage?.local) {
    chrome.storage.local
      .get([THEME_KEY, ENABLED_KEY])
      .then((r) => {
        cachedTheme = resolveTheme(r[THEME_KEY]);
        cachedEnabled = resolveEnabled(r[ENABLED_KEY]);
      })
      .catch(() => {});
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local') return;
      if (changes[THEME_KEY]) {
        cachedTheme = resolveTheme(changes[THEME_KEY].newValue);
      }
      if (changes[ENABLED_KEY]) {
        cachedEnabled = resolveEnabled(changes[ENABLED_KEY].newValue);
      }
    });
  }

  // -------------------------------------------------------------------------
  // Extension context guards
  // -------------------------------------------------------------------------

  /**
   * True while this content script's extension context is still alive.
   *
   * When the extension is reloaded or updated, content scripts already
   * injected into open tabs become orphaned: they keep running, but their
   * `chrome.runtime` loses its `id` and every `chrome.runtime.*` call throws
   * "Extension context invalidated". Guard `chrome.runtime` access with this so
   * an orphaned script degrades to a reload prompt instead of an uncaught
   * TypeError (e.g. `Cannot read properties of undefined (reading 'getURL')`).
   */
  function extensionContextValid() {
    return Boolean(chrome.runtime && chrome.runtime.id);
  }

  /**
   * `chrome.runtime.sendMessage` that tolerates an invalidated context.
   *
   * Invokes `onResponse` on success; if the context is gone (orphaned script
   * after a reload), skips the call and runs `onUnavailable` so the UI can
   * prompt a page reload. Never throws — replaces the bare `sendMessage` calls
   * whose synchronous throw surfaced as `Uncaught (in promise) ... reading
   * 'sendMessage'`.
   */
  function sendMessageSafe(msg, onResponse, onUnavailable) {
    if (!extensionContextValid()) {
      onUnavailable();
      return;
    }
    try {
      chrome.runtime.sendMessage(msg, onResponse);
    } catch (_err) {
      // Context invalidated in the gap between the guard and the call.
      onUnavailable();
    }
  }

  // -------------------------------------------------------------------------
  // Style loading
  // -------------------------------------------------------------------------

  async function loadStyles() {
    if (cachedStyles) return cachedStyles;
    // Orphaned content script: `getURL` would throw. Skip silently — callers
    // already tolerate an empty stylesheet (popup renders unstyled).
    if (!extensionContextValid()) return '';
    try {
      const [fontsRes, tokensRes, componentsRes, popupRes] = await Promise.all([
        fetch(chrome.runtime.getURL('shared/fonts.css')),
        fetch(chrome.runtime.getURL('shared/tokens.css')),
        fetch(chrome.runtime.getURL('shared/kg-components.css')),
        fetch(chrome.runtime.getURL('content/popup.css')),
      ]);
      if (!fontsRes.ok || !tokensRes.ok || !componentsRes.ok || !popupRes.ok) {
        throw new Error('stylesheet fetch returned non-OK status');
      }
      const [fontsText, tokensText, componentsText, popupText] = await Promise.all([
        fontsRes.text(),
        tokensRes.text(),
        componentsRes.text(),
        popupRes.text(),
      ]);
      // Concat order is load-bearing: tokens (vars) → kg-components (base
      // .kg-btn/.kg-card/.kg-chip) → popup (BEM layout-only overrides last).
      cachedStyles =
        fontsText + '\n' + tokensText + '\n' + componentsText + '\n' + popupText;
      return cachedStyles;
    } catch (err) {
      // Extension context invalidated, or packaged CSS missing. Return '' so
      // the popup still renders (unstyled) instead of hanging on a rejected
      // await — callers must tolerate an empty stylesheet.
      console.error('[KG] loadStyles failed:', err);
      return '';
    }
  }

  // -------------------------------------------------------------------------
  // Context extraction
  // -------------------------------------------------------------------------

  /** Extract the surrounding sentence from the selection's anchor node. */
  function extractContext(selection) {
    if (!selection.rangeCount) return '';
    const range = selection.getRangeAt(0);
    const container = range.startContainer;
    const text =
      container.nodeType === Node.TEXT_NODE
        ? container.textContent
        : container.innerText || container.textContent || '';
    if (!text) return '';

    // `range.startOffset` is only a character offset into `text` when the
    // start container is a text node. For an Element container it is a
    // child-node *index*, so convert it to a character offset by summing the
    // text length of the children preceding that index (matching `innerText`/
    // `textContent` used above). Falls back to 0 when conversion is impossible.
    let offset;
    if (container.nodeType === Node.TEXT_NODE) {
      offset = range.startOffset;
    } else {
      const childIndex = range.startOffset;
      let charOffset = 0;
      const children = container.childNodes;
      for (let i = 0; i < childIndex && i < children.length; i++) {
        charOffset += (children[i].textContent || '').length;
      }
      offset = charOffset;
    }

    // Find sentence boundaries around the selection
    const sentenceBreaks = /[.!?\u3002\uff01\uff1f\n]/;
    let start = offset;
    while (start > 0 && !sentenceBreaks.test(text[start - 1])) start--;
    let end = offset;
    while (end < text.length && !sentenceBreaks.test(text[end])) end++;

    return text.slice(start, end).trim().substring(0, MAX_CONTEXT_LEN);
  }

  /** Build source metadata. */
  function buildSource() {
    return { type: 'web', title: document.title, url: location.href };
  }

  // -------------------------------------------------------------------------
  // Popup positioning
  // -------------------------------------------------------------------------

  function computePosition(range) {
    const rect = range.getBoundingClientRect();
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const vpW = window.innerWidth;
    const vpH = window.innerHeight;

    const popupMaxW = POPUP_MAX_WIDTH;
    const popupEstH = POPUP_EST_HEIGHT;
    const gap = 8;

    // Horizontal: center on selection, clamp to viewport
    let left = rect.left + scrollX + rect.width / 2 - popupMaxW / 2;
    left = Math.max(scrollX + gap, Math.min(left, scrollX + vpW - popupMaxW - gap));

    // Vertical: prefer below selection, flip above if not enough space
    let top;
    if (rect.bottom + gap + popupEstH < vpH) {
      top = rect.bottom + scrollY + gap;
    } else {
      top = rect.top + scrollY - popupEstH - gap;
    }

    return { top, left };
  }

  // -------------------------------------------------------------------------
  // Popup lifecycle
  // -------------------------------------------------------------------------

  function removePopup() {
    if (activeHost) {
      activeHost.remove();
      activeHost = null;
    }
  }

  async function showPopup(word, context, source, range) {
    removePopup();

    const styles = await loadStyles();
    const pos = computePosition(range);

    // Host element
    const host = document.createElement('div');
    host.id = HOST_ID;
    host.style.cssText = `
      position: absolute;
      top: ${pos.top}px;
      left: ${pos.left}px;
      z-index: 2147483647;
    `;

    const shadow = host.attachShadow({ mode: 'closed' });

    // Inject styles
    const styleEl = document.createElement('style');
    styleEl.textContent = styles;
    shadow.appendChild(styleEl);

    // Popup container
    const popup = document.createElement('div');
    popup.className = 'kg-popup kg-popup--loading';
    popup.setAttribute('data-theme', cachedTheme);
    shadow.appendChild(popup);

    document.body.appendChild(host);
    activeHost = host;

    // Delegate to popup logic
    createPopup(shadow, popup, { word, context, source });
  }

  // -------------------------------------------------------------------------
  // Selection handler
  // -------------------------------------------------------------------------

  document.addEventListener('mouseup', (e) => {
    // Master switch (toggled in the options page) is off: never surface the popup.
    if (!cachedEnabled) return;

    // Ignore clicks inside our own popup host
    if (activeHost && activeHost.contains(e.target)) return;

    // Small delay to let the selection finalize
    setTimeout(() => {
      const selection = window.getSelection();
      const text = selection ? selection.toString().trim() : '';

      if (text.length < MIN_LEN || text.length > MAX_LEN) {
        return;
      }

      if (!selection.rangeCount) return;
      const range = selection.getRangeAt(0);
      const context = extractContext(selection);
      const source = buildSource();

      showPopup(text, context, source, range);
    }, 10);
  });

  // -------------------------------------------------------------------------
  // Dismiss handlers
  // -------------------------------------------------------------------------

  document.addEventListener('mousedown', (e) => {
    if (activeHost && !activeHost.contains(e.target)) {
      removePopup();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && activeHost) {
      removePopup();
    }
  });

  // =========================================================================
  // Popup logic (inlined — runs inside content script context)
  // =========================================================================

  /**
   * Populate the popup shadow DOM with translation UI.
   * @param {ShadowRoot} shadow
   * @param {HTMLElement} popup — the .kg-popup container
   * @param {{ word: string, context: string, source: object }} data
   */
  function createPopup(shadow, popup, { word, context, source }) {
    // --- Loading state ---
    popup.innerHTML = `
      <div class="kg-popup__word">${escapeHtml(word)}</div>
      <div class="kg-popup__skeleton"></div>
      <div class="kg-popup__skeleton kg-popup__skeleton--short"></div>
    `;

    // Determine message type based on word length
    const isPhrase = word.length > PHRASE_MIN_LEN;
    const msg = isPhrase
      ? { type: 'translatePhrase', text: word, context }
      : { type: 'translate', word, context };

    sendMessageSafe(
      msg,
      (response) => {
        if (!shadow.host || !shadow.host.isConnected) return; // popup dismissed

        // Background service worker unreachable: the callback fires with
        // `response === undefined` and lastError set.
        if (chrome.runtime.lastError || response == null) {
          renderError(popup, t('popupErrorNetwork'));
          return;
        }

        if (response.error) {
          if (response.status === 401 || response.code === 'auth_expired') {
            renderLoginPrompt(popup);
          } else {
            renderError(popup, response.message || t('popupErrorTranslate'));
          }
          return;
        }

        renderTranslation(popup, word, response, isPhrase, context, source);
      },
      () => {
        if (!shadow.host || !shadow.host.isConnected) return;
        renderError(popup, CONTEXT_INVALIDATED_MSG);
      }
    );
  }

  // -------------------------------------------------------------------------
  // Render functions
  // -------------------------------------------------------------------------

  function renderTranslation(popup, word, data, isPhrase, context, source) {
    popup.className = 'kg-popup kg-popup--translated';

    let html = `<div class="kg-popup__word">${escapeHtml(word)}</div>`;

    // Pronunciation
    if (data.p) {
      html += `<div class="kg-popup__pronunciation">${escapeHtml(data.p)}</div>`;
    }

    // POS chip
    if (data.r) {
      html += `<span class="kg-chip kg-popup__chip">${escapeHtml(data.r)}</span>`;
    }

    // Translation
    html += `<div class="kg-popup__translation">${escapeHtml(data.t)}</div>`;

    // Action row
    html += `<div class="kg-popup__actions">`;
    html += `<button class="kg-btn kg-btn--ghost kg-popup__btn kg-popup__btn--expand" data-action="explain" aria-label="${escapeHtml(t('popupActionExpandAria'))}">${escapeHtml(t('popupActionExpand'))}</button>`;
    html += `<button class="kg-btn kg-btn--primary" data-action="add" aria-label="${escapeHtml(t('popupBtnAdd'))}">${escapeHtml(t('popupBtnAdd'))}</button>`;
    html += `</div>`;

    // Explanation placeholder
    html += `<div class="kg-popup__explanation" hidden></div>`;

    popup.innerHTML = html;

    // --- Event delegation ---
    popup.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;

      const action = btn.dataset.action;

      if (action === 'explain') {
        handleExplain(popup, btn, word, context);
      } else if (action === 'add') {
        handleAddVocab(popup, btn, word, data, context, source);
      }
    });
  }

  function renderLoginPrompt(popup) {
    popup.className = 'kg-popup kg-popup--error';
    // `chrome.runtime.getURL` always returns a `chrome-extension://` URL,
    // so `safeUrl` is a no-op pass-through here — kept for defense-in-depth
    // consistency with the sidepanel renderer.
    const optionsUrl = safeUrl(chrome.runtime.getURL('options/options.html'));
    popup.innerHTML = `
      <div class="kg-popup__login">
        <p>${escapeHtml(t('popupLoginPrompt'))}</p>
        <a href="${escapeHtml(optionsUrl)}" target="_blank" class="kg-btn kg-btn--primary">${escapeHtml(t('popupLoginAction'))}</a>
      </div>
    `;
  }

  function renderError(popup, message) {
    popup.className = 'kg-popup kg-popup--error';
    popup.innerHTML = `
      <div class="kg-popup__error">${escapeHtml(message)}</div>
    `;
  }

  // -------------------------------------------------------------------------
  // Action handlers
  // -------------------------------------------------------------------------

  function handleExplain(popup, btn, word, context) {
    const explanationEl = popup.querySelector('.kg-popup__explanation');
    if (!explanationEl) return;

    // Toggle off if already shown
    if (!explanationEl.hidden) {
      explanationEl.hidden = true;
      btn.textContent = t('popupActionExpand');
      return;
    }

    btn.disabled = true;
    btn.textContent = t('popupLoading');

    const showExplainError = (text) => {
      btn.disabled = false;
      explanationEl.textContent = text;
      explanationEl.hidden = false;
      btn.textContent = t('popupActionExpand');
    };

    sendMessageSafe(
      { type: 'explain', word, context },
      (response) => {
        btn.disabled = false;

        if (chrome.runtime.lastError || response == null) {
          showExplainError(t('popupErrorNetwork'));
          return;
        }

        if (response.error) {
          showExplainError(response.message || t('popupErrorExplain'));
          return;
        }

        explanationEl.textContent = response.e || '';
        explanationEl.hidden = false;
        btn.textContent = t('popupActionCollapse');
      },
      () => showExplainError(CONTEXT_INVALIDATED_MSG)
    );
  }

  function handleAddVocab(popup, btn, word, data, context, source) {
    btn.disabled = true;
    btn.textContent = t('popupBtnAdding');

    const entries = [
      {
        word,
        translation: data.t,
        context,
        source,
      },
    ];

    const showAddError = (text) => {
      btn.disabled = false;
      btn.textContent = t('popupBtnAdd');
      const errEl = popup.querySelector('.kg-popup__error');
      if (errEl) {
        errEl.textContent = text;
        errEl.hidden = false;
      } else {
        const el = document.createElement('div');
        el.className = 'kg-popup__error';
        el.textContent = text;
        popup.appendChild(el);
      }
    };

    sendMessageSafe(
      { type: 'addVocab', entries },
      (response) => {
        if (chrome.runtime.lastError || response == null) {
          showAddError(t('popupErrorNetwork'));
          return;
        }

        if (response.error) {
          if (response.status === 401 || response.code === 'auth_expired') {
            renderLoginPrompt(popup);
          } else {
            showAddError(response.message || t('popupErrorAdd'));
          }
          return;
        }

        popup.className = 'kg-popup kg-popup--saved';
        btn.className = 'kg-btn kg-popup__btn kg-popup__btn--success';
        btn.textContent = t('popupBtnAdded');
        btn.disabled = true;
      },
      () => showAddError(CONTEXT_INVALIDATED_MSG)
    );
  }

  // -------------------------------------------------------------------------
  // Utilities
  // -------------------------------------------------------------------------

  /**
   * Escape HTML to prevent XSS in popup markup. Mirrors
   * `shared/pure.js#escapeHtml` — content scripts run in an isolated world
   * without access to KGPure, so the implementation is inlined.
   *
   * Encodes `&`, `<`, `>`, `"` and `'`. The quotes are encoded so the output
   * is safe inside a `"`-wrapped attribute (e.g. `href="${escapeHtml(url)}"`)
   * — a raw `"` would otherwise break out of the attribute. Keep byte-for-byte
   * in sync with the pure version.
   */
  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * Defense-in-depth URL scheme allowlist for `href` / `src` rendered into
   * popup markup. Mirrors `shared/pure.js#safeUrl`, inlined here because
   * content scripts run in an isolated world without access to KGPure.
   *
   * Only `http:`, `https:`, and `chrome-extension:` pass through. Anything
   * else (notably `javascript:`, `data:`) collapses to `#`.
   */
  function safeUrl(raw, fallback = '#') {
    if (typeof raw !== 'string' || !raw) return fallback;
    // eslint-disable-next-line no-control-regex
    const trimmed = raw.replace(/^[\s\x00-\x1f\x7f]+|[\s\x00-\x1f\x7f]+$/g, '');
    if (!trimmed) return fallback;
    try {
      const parsed = new URL(trimmed, 'https://invalid.example/');
      const proto = parsed.protocol;
      if (proto === 'http:' || proto === 'https:' || proto === 'chrome-extension:') {
        // Return the normalized href (percent-encodes `"` etc.), mirroring
        // shared/pure.js#safeUrl — closes the attribute-breakout vector.
        return parsed.href;
      }
      return fallback;
    } catch (_err) {
      return fallback;
    }
  }
})();
