/**
 * Books & Vocab Chrome Extension — Content Script
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
  // Mirrors shared/pure.js ACTIVE_NOTEBOOK_KEY. Content scripts run in an
  // isolated world, so they cannot reach the shared classic-script global.
  const ACTIVE_NOTEBOOK_KEY = 'active_notebook_id';
  // Mirrors shared/pure.js ACTIVE_NOTEBOOK_UPDATED_KEY — LWW timestamp companion.
  const ACTIVE_NOTEBOOK_UPDATED_KEY = 'active_notebook_updated_at';
  // Cap on extracted surrounding-sentence context sent to the backend.
  const MAX_CONTEXT_LEN = 500;

  // Popup geometry — pairs with the popup.css layout contract.
  const POPUP_MAX_WIDTH = 360;
  const POPUP_EST_HEIGHT = 220;

  // Short i18n accessor. Content scripts read chrome.i18n directly — their UI
  // is built in JS (not HTML), so shared/i18n.js does not apply here. Guard it
  // because orphaned content scripts (after extension reload/update) may keep
  // running in the page after the extension context has died; in that state,
  // touching chrome.i18n can itself throw "Extension context invalidated".
  const I18N_FALLBACKS = {
    popupContextInvalidated: '擴充功能已更新，請重新整理頁面後再試一次。',
    popupSpeakAria: '朗讀',
    popupCloseAria: '關閉',
  };

  function i18nMessage(key, subs) {
    try {
      if (!globalThis.chrome?.runtime?.id || !globalThis.chrome?.i18n?.getMessage) {
        return '';
      }
      return chrome.i18n.getMessage(key, subs) || '';
    } catch (_err) {
      return '';
    }
  }

  const t = (key, subs) => {
    // Invalidated extension context — fall through to static fallback text.
    return i18nMessage(key, subs) || I18N_FALLBACKS[key] || '';
  };

  // Shown when this content script is orphaned by an extension reload/update
  // (see extensionContextValid). Resolved ONCE at load time (context still
  // valid) and cached, so the invalidated-context path never calls getMessage
  // on a dead runtime — which would itself throw.
  const CONTEXT_INVALIDATED_MSG = t('popupContextInvalidated');

  // Inline SVG glyphs. Content scripts run in an isolated world and cannot reach
  // shared/icons.js (KGIcons), so the markup is inlined here. Wrapper attributes
  // mirror KGIcons.svg (24×24 grid, fill:none, stroke:currentColor, 1.7 weight,
  // round caps) so popup icons match the rest of the UI; the paths are the same
  // as the 'speaker' / 'xmark' glyphs registered in shared/icons.js — keep both
  // copies in sync. Sized explicitly (18px) since shadow-DOM CSS can't be relied
  // on for an svg with no intrinsic size.
  const iconSvg = (paths) =>
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
    'stroke-linecap="round" stroke-linejoin="round" width="18" height="18" aria-hidden="true">' +
    paths + '</svg>';
  const SPEAKER_SVG = iconSvg(
    '<path d="M4 9.5v5h3.5L13 19V5L7.5 9.5H4z"/><path d="M16.5 9a4 4 0 0 1 0 6"/><path d="M19 6.5a7.5 7.5 0 0 1 0 11"/>'
  );
  const XMARK_SVG = iconSvg('<path d="M6 6l12 12M18 6L6 18"/>');

  /**
   * Popup head row: the word plus the always-available tool buttons (speak /
   * close). Shared by the loading and translated states so the speaker and the
   * explicit close affordance survive the loading→translated→saved transitions.
   * The buttons carry `data-action` and are handled by the delegated listener in
   * `showPopup` (not the per-render explain/add handler), so they work in every
   * state. Mirrors the iOS reading panel (word + speaker + close).
   * @param {string} word
   */
  function headHTML(word) {
    return (
      '<div class="kg-popup__head">' +
        `<div class="kg-popup__word">${escapeHtml(word)}</div>` +
        '<div class="kg-popup__tools">' +
          `<button class="kg-popup__icon-btn" type="button" data-action="speak" aria-label="${escapeHtml(t('popupSpeakAria'))}">${SPEAKER_SVG}</button>` +
          `<button class="kg-popup__icon-btn" type="button" data-action="close" aria-label="${escapeHtml(t('popupCloseAria'))}">${XMARK_SVG}</button>` +
        '</div>' +
      '</div>'
    );
  }

  /**
   * Choose the most natural TTS voice for `lang` from a `getVoices()` list.
   * INLINE MIRROR of shared/pure.js#pickPreferredVoice — content scripts run in
   * an isolated world and cannot reach KGPure. Keep this byte-for-byte in sync
   * with the pure version (enforced by shared/icons.test.js drift check).
   */
  function pickPreferredVoice(voices, lang = 'en-US') {
    if (!Array.isArray(voices) || voices.length === 0) return null;
    const norm = (s) => String(s == null ? '' : s).toLowerCase().replace(/_/g, '-');
    const target = norm(lang);
    const base = target.split('-')[0];
    if (!base) return null;
    const eligible = voices.filter((v) => norm(v && v.lang).split('-')[0] === base);
    if (eligible.length === 0) return null;
    const score = (v) => {
      const name = String((v && v.name) || '');
      let s = 0;
      if (/\bgoogle\b/i.test(name)) s += 100;
      if (/natural|neural|premium|enhanced/i.test(name)) s += 80;
      s += norm(v && v.lang) === target ? 40 : 20;
      if (v && v.localService === false) s += 10;
      if (v && v.default) s += 1;
      return s;
    };
    // Linear max keeps a score tie on the first-listed voice (stable, predictable).
    let best = eligible[0];
    let bestScore = score(best);
    for (let i = 1; i < eligible.length; i++) {
      const s = score(eligible[i]);
      if (s > bestScore) {
        best = eligible[i];
        bestScore = s;
      }
    }
    return best;
  }

  /**
   * Speak a word/phrase via the Web Speech API. Available to content scripts
   * (they share the page's `window`, where `speechSynthesis` lives). Best-effort:
   * silently no-ops if the API is unavailable. Cancels any in-flight utterance
   * first so rapid taps don't queue. Picks a natural voice (via
   * `pickPreferredVoice`) instead of the OS's robotic compact default; voices
   * load asynchronously, so on the first call we wait once for `voiceschanged`.
   * Mirrors the side panel's `speakWord`.
   * @param {string} word
   */
  function speakWord(word) {
    try {
      const synth = window.speechSynthesis;
      if (!synth || typeof SpeechSynthesisUtterance === 'undefined') return;
      synth.cancel();
      const u = new SpeechSynthesisUtterance(String(word || ''));
      u.lang = 'en-US';
      const speak = () => {
        const v = pickPreferredVoice(synth.getVoices(), 'en-US');
        if (v) {
          u.voice = v;
          u.lang = v.lang;
        }
        synth.speak(u);
      };
      if (synth.getVoices().length) speak();
      else synth.addEventListener('voiceschanged', speak, { once: true });
    } catch (_err) {
      // TTS unavailable in this context — no-op.
    }
  }

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
    try {
      return Boolean(globalThis.chrome?.runtime?.id);
    } catch (_err) {
      return false;
    }
  }

  function runtimeLastError() {
    try {
      return globalThis.chrome?.runtime?.lastError || null;
    } catch (_err) {
      return { message: 'Extension context invalidated.' };
    }
  }

  function extensionUrl(path) {
    if (!extensionContextValid()) return '';
    try {
      return chrome.runtime.getURL(path);
    } catch (_err) {
      return '';
    }
  }

  function storageLocalAvailable() {
    try {
      return Boolean(globalThis.chrome?.storage?.local);
    } catch (_err) {
      return false;
    }
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

  if (storageLocalAvailable()) {
    try {
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
    } catch (_err) {
      // Orphaned content script after extension reload — keep defaults.
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
      const urls = [
        extensionUrl('shared/fonts.css'),
        extensionUrl('shared/tokens.css'),
        extensionUrl('shared/kg-components.css'),
        extensionUrl('content/popup.css'),
      ];
      if (urls.some((url) => !url)) return '';
      const [fontsRes, tokensRes, componentsRes, popupRes] = await Promise.all([
        fetch(urls[0]),
        fetch(urls[1]),
        fetch(urls[2]),
        fetch(urls[3]),
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
      // Stop any in-flight TTS so audio doesn't outlive the dismissed popup.
      try {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
      } catch (_err) { /* speechSynthesis unavailable — nothing to cancel */ }
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

    // Always-on tool actions (speak / close). Attached once on the popup box so
    // they work in every render state (loading + translated + saved); the
    // per-render handler in `renderTranslation` owns explain / add. A click on
    // explain/add reaches this listener too but matches neither branch — no-op.
    popup.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      if (btn.dataset.action === 'close') removePopup();
      else if (btn.dataset.action === 'speak') speakWord(word);
    });

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
      ${headHTML(word)}
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
        if (runtimeLastError() || response == null) {
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

    let html = headHTML(word);

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

    // Target notebook picker. Mirrors the iOS Reader notebook picker at the
    // add-word chokepoint: the user can choose where this selection will land
    // without first opening the side panel. Populated asynchronously below.
    html += `
      <label class="kg-popup__notebook" hidden>
        <span class="kg-popup__notebook-label">${escapeHtml(t('popupNotebookTarget'))}</span>
        <select class="kg-popup__notebook-select" data-role="notebook-select" aria-label="${escapeHtml(t('popupNotebookTargetAria'))}"></select>
      </label>
    `;

    // Action row
    html += `<div class="kg-popup__actions">`;
    html += `<button class="kg-btn kg-btn--ghost kg-popup__btn kg-popup__btn--expand" data-action="explain" aria-label="${escapeHtml(t('popupActionExpandAria'))}">${escapeHtml(t('popupActionExpand'))}</button>`;
    html += `<button class="kg-btn kg-btn--primary" data-action="add" aria-label="${escapeHtml(t('popupBtnAdd'))}">${escapeHtml(t('popupBtnAdd'))}</button>`;
    html += `</div>`;

    // Explanation placeholder
    html += `<div class="kg-popup__explanation" hidden></div>`;

    popup.innerHTML = html;
    hydrateNotebookPicker(popup);

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

  function normalizePopupNotebook(item) {
    if (!item || typeof item !== 'object') return null;
    if (item.isDeleted || item.is_deleted) return null;
    const id = String(item.id || item.remoteId || item.remote_id || '').trim() || 'default';
    const name = String(item.name || '').trim() || t('notebookDefaultName');
    return { id, name };
  }

  function readActiveNotebook(callback) {
    if (!storageLocalAvailable()) {
      callback('default');
      return;
    }
    try {
      chrome.storage.local.get(ACTIVE_NOTEBOOK_KEY, (stored) => {
        callback((stored && stored[ACTIVE_NOTEBOOK_KEY]) || 'default');
      });
    } catch (_err) {
      callback('default');
    }
  }

  function setActiveNotebook(notebookId) {
    if (!storageLocalAvailable()) return;
    const id = notebookId || 'default';
    const updatedAt = Date.now() / 1000;
    try {
      // Write id + LWW timestamp together (atomic group, mirrors the side panel's
      // persistActiveNotebook and iOS setActive).
      chrome.storage.local.set({
        [ACTIVE_NOTEBOOK_KEY]: id,
        [ACTIVE_NOTEBOOK_UPDATED_KEY]: updatedAt,
      });
    } catch (_err) {
      // Orphaned content script after extension reload — ignore the write.
      return;
    }
    // Best-effort push to the backend vocab_ui group so iOS / web / side panel
    // converge. Routes through sendMessageSafe (like every other content-script
    // sender) so a torn-down worker no-ops instead of leaking an unhandled promise
    // rejection. No rollback — storage.local already holds the local source of truth.
    sendMessageSafe(
      {
        type: 'updateUserConfig',
        config: { vocab_ui: { active_notebook_id: id, updated_at: updatedAt } },
      },
      () => {},
      () => {},
    );
  }

  function hydrateNotebookPicker(popup) {
    const wrap = popup.querySelector('.kg-popup__notebook');
    const select = popup.querySelector('[data-role="notebook-select"]');
    if (!wrap || !select) return;

    const renderOptions = (items, activeId) => {
      const notebooks = Array.isArray(items)
        ? items.map(normalizePopupNotebook).filter(Boolean)
        : [];
      if (notebooks.length === 0) return;
      const hasActive = notebooks.some((n) => n.id === activeId);
      const selectedId = hasActive ? activeId : (notebooks.find((n) => n.id === 'default')?.id || notebooks[0].id);
      select.innerHTML = notebooks
        .map((n) => `<option value="${escapeHtml(n.id)}">${escapeHtml(n.name)}</option>`)
        .join('');
      select.value = selectedId;
      if (selectedId !== activeId) setActiveNotebook(selectedId);
      wrap.hidden = false;
    };

    readActiveNotebook((activeId) => {
      sendMessageSafe(
        { type: 'listNotebooks' },
        (response) => {
          if (runtimeLastError() || response == null || response.error) return;
          renderOptions(response.items || response.data || response, activeId);
        },
        () => {}
      );
    });

    select.addEventListener('change', () => {
      setActiveNotebook(select.value || 'default');
    });
  }

  function renderLoginPrompt(popup) {
    popup.className = 'kg-popup kg-popup--error';
    // `chrome.runtime.getURL` always returns a `chrome-extension://` URL,
    // so `safeUrl` is a no-op pass-through here — kept for defense-in-depth
    // consistency with the sidepanel renderer.
    const rawOptionsUrl = extensionUrl('options/options.html');
    if (!rawOptionsUrl) {
      renderError(popup, CONTEXT_INVALIDATED_MSG);
      return;
    }
    const optionsUrl = safeUrl(rawOptionsUrl);
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

        if (runtimeLastError() || response == null) {
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

    readActiveNotebook((notebookId) => {
      sendMessageSafe(
        { type: 'addVocab', entries, notebookId },
        (response) => {
          if (runtimeLastError() || response == null) {
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
