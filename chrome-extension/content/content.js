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
  // single word). Must track KGPure.isPhrase's threshold in shared/pure.js —
  // content scripts run in an isolated world and cannot import KGPure.
  const PHRASE_MIN_LEN = 50;

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

  if (chrome?.storage?.local) {
    chrome.storage.local
      .get(THEME_KEY)
      .then((r) => { cachedTheme = resolveTheme(r[THEME_KEY]); })
      .catch(() => {});
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area === 'local' && changes[THEME_KEY]) {
        cachedTheme = resolveTheme(changes[THEME_KEY].newValue);
      }
    });
  }

  // -------------------------------------------------------------------------
  // Style loading
  // -------------------------------------------------------------------------

  async function loadStyles() {
    if (cachedStyles) return cachedStyles;
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

    return text.slice(start, end).trim().substring(0, 500);
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

    const popupMaxW = 360;
    const popupEstH = 220;
    const gap = 8;

    // Horizontal: center on selection, clamp to viewport
    let left = rect.left + scrollX + rect.width / 2 - popupMaxW / 2;
    left = Math.max(scrollX + 8, Math.min(left, scrollX + vpW - popupMaxW - 8));

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

    chrome.runtime.sendMessage(msg, (response) => {
      if (!shadow.host || !shadow.host.isConnected) return; // popup dismissed

      // Background service worker unreachable / extension context invalidated:
      // the callback fires with `response === undefined` and lastError set.
      if (chrome.runtime.lastError || response == null) {
        renderError(popup, '無法連線，請重試');
        return;
      }

      if (response.error) {
        if (response.status === 401 || response.code === 'auth_expired') {
          renderLoginPrompt(popup);
        } else {
          renderError(popup, response.message || '翻譯失敗');
        }
        return;
      }

      renderTranslation(popup, word, response, isPhrase, context, source);
    });
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
    html += `<button class="kg-btn kg-btn--ghost kg-popup__btn kg-popup__btn--expand" data-action="explain" aria-label="展開解釋">展開</button>`;
    html += `<button class="kg-btn kg-btn--primary" data-action="add" aria-label="加入詞彙">加入詞彙</button>`;
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
        <p>請先登入</p>
        <a href="${escapeHtml(optionsUrl)}" target="_blank" class="kg-btn kg-btn--primary">前往登入</a>
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
      btn.textContent = '展開';
      return;
    }

    btn.disabled = true;
    btn.textContent = '載入中...';

    chrome.runtime.sendMessage({ type: 'explain', word, context }, (response) => {
      btn.disabled = false;

      if (chrome.runtime.lastError || response == null) {
        explanationEl.textContent = '無法連線，請重試';
        explanationEl.hidden = false;
        btn.textContent = '展開';
        return;
      }

      if (response.error) {
        explanationEl.textContent = response.message || '解釋失敗';
        explanationEl.hidden = false;
        btn.textContent = '展開';
        return;
      }

      explanationEl.textContent = response.e || '';
      explanationEl.hidden = false;
      btn.textContent = '收起';
    });
  }

  function handleAddVocab(popup, btn, word, data, context, source) {
    btn.disabled = true;
    btn.textContent = '加入中...';

    const entries = [
      {
        word,
        translation: data.t,
        context,
        source,
      },
    ];

    chrome.runtime.sendMessage({ type: 'addVocab', entries }, (response) => {
      const showAddError = (text) => {
        btn.disabled = false;
        btn.textContent = '加入詞彙';
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

      if (chrome.runtime.lastError || response == null) {
        showAddError('無法連線，請重試');
        return;
      }

      if (response.error) {
        if (response.status === 401 || response.code === 'auth_expired') {
          renderLoginPrompt(popup);
        } else {
          showAddError(response.message || '加入失敗');
        }
        return;
      }

      popup.className = 'kg-popup kg-popup--saved';
      btn.className = 'kg-btn kg-popup__btn kg-popup__btn--success';
      btn.textContent = '已加入';
      btn.disabled = true;
    });
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
