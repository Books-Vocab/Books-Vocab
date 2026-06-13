/**
 * Options page — login flow, theme switching, about info.
 */

// Mirrors KGApi.TOKEN_KEY in shared/api.js — options.js is a classic script and
// cannot import the module, so the literal is defined once here and reused.
const TOKEN_KEY = 'auth_token';
const AUTH_KEYS = [TOKEN_KEY];
const authStatus = document.getElementById('auth-status');
const logoutArea = document.getElementById('logout-area');
const tokenPasteArea = document.getElementById('token-paste-area');
const tokenInput = document.getElementById('tokenInput');
const tokenSubmit = document.getElementById('tokenSubmit');
const themeSelector = document.getElementById('theme-selector');

// Master on/off switch. Mirrors ENABLED_KEY in content/content.js — default ON,
// only an explicit stored `false` disables the selection-to-translate popup.
const ENABLED_KEY = 'kg_enabled';
const enabledToggle = document.getElementById('enabled-toggle');

// Short i18n accessor (static HTML is localized by shared/i18n.js; this covers
// strings built in JS, e.g. auth status / error messages).
const t = (key, subs) => chrome.i18n.getMessage(key, subs);

// Translation-language + Pro elements.
const proStatus = document.getElementById('pro-status');
const sourceLangSelect = document.getElementById('sourceLangSelect');
const targetLangSelect = document.getElementById('targetLangSelect');
const langHint = document.getElementById('langHint');

// Translation languages — value = code the backend validates (mirror of
// kg/languages.py SUPPORTED_SOURCE_LANGS / SUPPORTED_TARGET_LANGS), label =
// endonym (a language picker shows each name in its own script regardless of
// UI locale, so these are locale-stable data, not chrome.i18n strings).
const SOURCE_LANGS = [
  ['en', 'English'], ['ja', '日本語'], ['ko', '한국어'],
  ['fr', 'Français'], ['de', 'Deutsch'], ['es', 'Español'],
];
const TARGET_LANGS = [
  ['zh-Hant', '繁體中文'], ['zh-Hans', '简体中文'], ['en', 'English'],
  ['ja', '日本語'], ['ko', '한국어'],
];
const DEFAULT_TRANSLATION = KGPure.DEFAULT_TRANSLATION_CONFIG;
// Last value accepted by the server — the revert target if a PUT fails.
let currentTranslation = { ...DEFAULT_TRANSLATION };

// ── Auth UI ──

function renderLoggedIn() {
  authStatus.innerHTML = '';

  const info = document.createElement('div');
  info.className = 'kg-auth-info';
  info.textContent = t('authLoggedIn');

  const btn = document.createElement('button');
  btn.className = 'kg-auth-logout';
  btn.textContent = t('authLogout');
  btn.addEventListener('click', handleLogout);

  authStatus.appendChild(info);
  // Logout sits at the foot of the account group (below Pro) — iOS grouped-list
  // convention puts the destructive row last. It lives in #logout-area (rendered
  // after #pro-status), not inline after 已登入.
  if (logoutArea) { logoutArea.innerHTML = ''; logoutArea.appendChild(btn); }

  if (tokenPasteArea) tokenPasteArea.hidden = true;
}

function renderLoggedOut() {
  authStatus.innerHTML = '';
  if (logoutArea) logoutArea.innerHTML = '';

  const btn = document.createElement('button');
  btn.className = 'kg-btn kg-btn--primary';
  btn.textContent = t('authLogin');
  btn.addEventListener('click', handleLogin);

  authStatus.appendChild(btn);

  if (tokenPasteArea) tokenPasteArea.hidden = false;
}

/**
 * Render an inline error with a retry button under the auth section.
 * @param {string} message
 * @param {Function} onRetry
 */
function renderAuthError(message, onRetry) {
  authStatus.innerHTML = '';
  if (logoutArea) logoutArea.innerHTML = '';

  const msg = document.createElement('div');
  msg.className = 'kg-auth-info';
  msg.textContent = message;

  const btn = document.createElement('button');
  btn.className = 'kg-btn kg-btn--primary';
  btn.textContent = t('commonRetry');
  btn.addEventListener('click', onRetry);

  authStatus.appendChild(msg);
  authStatus.appendChild(btn);
}

async function refreshAuthUI() {
  try {
    const data = await chrome.storage.local.get(AUTH_KEYS);
    if (data[TOKEN_KEY]) {
      renderLoggedIn();
      // Per-user surfaces — async, non-blocking. Re-run whenever auth changes
      // (this fn is the storage.onChanged target for auth_token).
      loadProStatus();
      loadTranslationConfig();
    } else {
      renderLoggedOut();
      if (proStatus) proStatus.hidden = true;
      renderLangLoggedOut();
    }
  } catch (err) {
    // chrome.storage can reject when the extension context is invalidated.
    console.error('[KG] refreshAuthUI failed:', err);
    renderAuthError(t('authErrorRead'), refreshAuthUI);
  }
}

// ── Auth Actions ──

function handleLogin() {
  try {
    chrome.tabs.create({
      url: `${KGPure.PUBLIC_WEB_ORIGIN}${KGPure.LOGIN_PATH}`,
    }).catch((err) => console.error('[KG] handleLogin tabs.create failed', err));
  } catch (err) {
    console.error('[KG] handleLogin failed:', err);
    renderAuthError(t('authErrorOpen'), handleLogin);
  }
}

async function handleLogout() {
  try {
    await chrome.storage.local.remove(AUTH_KEYS);
    renderLoggedOut();
  } catch (err) {
    console.error('[KG] handleLogout failed:', err);
    renderAuthError(t('authErrorLogout'), handleLogout);
  }
}

async function handleTokenSubmit() {
  const raw = tokenInput.value.trim();
  if (!raw) return;

  // Minimal JWT shape validation — three dot-separated base64url segments.
  const jwtPattern = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
  if (!jwtPattern.test(raw)) {
    renderAuthError(t('authErrorTokenFormat'), () => {
      renderLoggedOut();
      tokenInput.value = raw;
      tokenInput.focus();
    });
    return;
  }

  try {
    await chrome.storage.local.set({ [TOKEN_KEY]: raw });
    tokenInput.value = '';
    renderLoggedIn();
  } catch (err) {
    console.error('[KG] handleTokenSubmit failed:', err);
    renderAuthError(t('authErrorTokenSave'), () => {
      renderLoggedOut();
      tokenInput.value = raw;
      tokenInput.focus();
    });
  }
}

// ── Theme UI ──

function activateThemeOption(theme) {
  const options = themeSelector.querySelectorAll('.kg-theme-option');
  options.forEach((opt) => {
    const value = opt.dataset.themeValue;
    const radio = opt.querySelector('input[type="radio"]');
    radio.checked = value === theme;
    opt.classList.toggle('kg-theme-option--active', value === theme);
  });
}

function handleThemeChange(e) {
  const radio = e.target.closest('.kg-theme-option')?.querySelector('input[type="radio"]');
  if (!radio) return;
  const value = radio.value;
  radio.checked = true;
  activateThemeOption(value);
  setTheme(value);
}

// ── Master switch ──

async function initEnabledToggle() {
  if (!enabledToggle) return;
  // Default ON: missing key or read failure leaves the popup enabled.
  try {
    const data = await chrome.storage.local.get(ENABLED_KEY);
    enabledToggle.checked = data[ENABLED_KEY] !== false;
  } catch (err) {
    console.error('[KG] enabled toggle init failed:', err);
    enabledToggle.checked = true;
  }
  enabledToggle.addEventListener('change', async () => {
    const next = enabledToggle.checked;
    try {
      await chrome.storage.local.set({ [ENABLED_KEY]: next });
    } catch (err) {
      console.error('[KG] enabled toggle save failed:', err);
      enabledToggle.checked = !next; // revert UI to the persisted state
    }
  });
}

// ── Translation language + Pro status ──

/**
 * Send a message to the background worker and normalize its reply. Resolves with
 * the payload, or throws an Error carrying { code, status } for error envelopes
 * / a missing worker (mirrors the side panel's error shape).
 */
async function bgRequest(msg) {
  const res = await chrome.runtime.sendMessage(msg);
  if (res == null) throw Object.assign(new Error('no_response'), { code: 'no_response' });
  if (res.error) {
    throw Object.assign(new Error(res.message || 'request failed'), { code: res.code, status: res.status });
  }
  return res;
}

/** Fill a <select> from [value, label] pairs, selecting `selected`. */
function populateSelect(selectEl, pairs, selected) {
  if (!selectEl) return;
  selectEl.innerHTML = '';
  for (const [value, label] of pairs) {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    if (value === selected) opt.selected = true;
    selectEl.appendChild(opt);
  }
}

function setLangControlsEnabled(on) {
  if (sourceLangSelect) sourceLangSelect.disabled = !on;
  if (targetLangSelect) targetLangSelect.disabled = !on;
}

function showLangHint(message) {
  if (!langHint) return;
  langHint.textContent = message;
  langHint.hidden = false;
}

function hideLangHint() {
  if (langHint) langHint.hidden = true;
}

function renderTranslationPresentation(presentation) {
  currentTranslation = { ...presentation.translation };
  populateSelect(sourceLangSelect, SOURCE_LANGS, currentTranslation.source_lang);
  populateSelect(targetLangSelect, TARGET_LANGS, currentTranslation.target_lang);
  setLangControlsEnabled(!presentation.disabled);
  if (presentation.hintKey) {
    showLangHint(t(presentation.hintKey));
  } else {
    hideLangHint();
  }
}

/** Logged-out state: show defaults, disabled, with a "log in first" hint. */
function renderLangLoggedOut() {
  renderTranslationPresentation(KGPure.optionsTranslationPresentation({
    isLoggedIn: false,
    fallbackTranslation: DEFAULT_TRANSLATION,
  }));
}

/** Logged-in: fetch the user's translation config and populate the selects. */
async function loadTranslationConfig() {
  if (!sourceLangSelect || !targetLangSelect) return;
  setLangControlsEnabled(false);
  try {
    const cfg = await bgRequest({ type: 'getUserConfig' });
    const tr = (cfg && cfg.translation) || {};
    renderTranslationPresentation(KGPure.optionsTranslationPresentation({
      isLoggedIn: true,
      translation: tr,
      fallbackTranslation: currentTranslation,
    }));
  } catch (err) {
    console.error('[KG] loadTranslationConfig failed:', err);
    renderTranslationPresentation(KGPure.optionsTranslationPresentation({
      isLoggedIn: true,
      fallbackTranslation: currentTranslation,
      errorStatus: err.status || 0,
    }));
  }
}

/** Persist the selected source/target pair; revert the UI on failure. */
async function onLangChange() {
  const next = { source_lang: sourceLangSelect.value, target_lang: targetLangSelect.value };
  setLangControlsEnabled(false);
  try {
    const updated = await bgRequest({ type: 'updateUserConfig', config: { translation: next } });
    const tr = (updated && updated.translation) || next;
    currentTranslation = { source_lang: tr.source_lang, target_lang: tr.target_lang };
    // Reflect the server's canonical values (in case it normalized them).
    if (sourceLangSelect.value !== currentTranslation.source_lang) sourceLangSelect.value = currentTranslation.source_lang;
    if (targetLangSelect.value !== currentTranslation.target_lang) targetLangSelect.value = currentTranslation.target_lang;
    hideLangHint();
  } catch (err) {
    console.error('[KG] updateUserConfig failed:', err);
    sourceLangSelect.value = currentTranslation.source_lang;
    targetLangSelect.value = currentTranslation.target_lang;
    showLangHint(err.status === 401 ? t('translateLangLoginHint') : t('translateLangSaveError'));
  } finally {
    setLangControlsEnabled(true);
  }
}

/** Logged-in: fetch entitlements and render the Pro badge / free-plan label. */
async function loadProStatus() {
  if (!proStatus) return;
  try {
    const ent = await bgRequest({ type: 'getEntitlements' });
    renderProStatus((ent && ent.pro) || {});
  } catch (err) {
    // Can't determine entitlement (offline / 401) — show nothing rather than guess.
    console.error('[KG] loadProStatus failed:', err);
    proStatus.hidden = true;
  }
}

function renderProStatus(pro) {
  const presentation = KGPure.optionsProPresentation(pro);
  proStatus.innerHTML = '';
  if (presentation.hidden) {
    proStatus.hidden = true;
    return;
  }
  if (presentation.badge) {
    const badge = document.createElement('span');
    badge.className = 'kg-pro-badge';
    badge.textContent = presentation.badge; // brand tier label — locale-stable, not translated
    const label = document.createElement('span');
    label.className = 'kg-pro-status__label';
    label.textContent = presentation.planName
      ? `${t(presentation.labelKey)}・${presentation.planName}`
      : t(presentation.labelKey);
    proStatus.appendChild(badge);
    proStatus.appendChild(label);
  } else {
    const label = document.createElement('span');
    label.className = `kg-pro-status__label${presentation.isFree ? ' kg-pro-status__label--free' : ''}`;
    label.textContent = t(presentation.labelKey);
    proStatus.appendChild(label);
  }
  proStatus.hidden = false;
}

// ── Init ──

(async function init() {
  // Grouped-list section-header leading icons (mirror iOS Settings).
  document.querySelectorAll('[data-hdr-icon]').forEach((el) => KGIcons.setIcon(el, el.dataset.hdrIcon));

  // Theme — fall back to the default if storage is unavailable.
  try {
    const currentTheme = await initTheme(document.documentElement);
    activateThemeOption(currentTheme);
  } catch (err) {
    console.error('[KG] theme init failed:', err);
    activateThemeOption('light');
  }
  themeSelector.addEventListener('click', handleThemeChange);

  // Master switch
  await initEnabledToggle();

  // Translation language — persist on change. Selects are disabled while logged
  // out (gated by refreshAuthUI), so a change event only fires for an authed user.
  if (sourceLangSelect) sourceLangSelect.addEventListener('change', onLangChange);
  if (targetLangSelect) targetLangSelect.addEventListener('change', onLangChange);

  // Auth (also kicks off Pro + translation-config loading when logged in)
  await refreshAuthUI();

  // Token paste (manual fallback when auto-send fails)
  if (tokenSubmit) {
    tokenSubmit.addEventListener('click', handleTokenSubmit);
  }
  if (tokenInput) {
    tokenInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleTokenSubmit();
    });
  }

  // Live storage changes (e.g. OAuth completing in another tab)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes[TOKEN_KEY]) {
      refreshAuthUI();
    }
    if (changes[ENABLED_KEY] && enabledToggle) {
      enabledToggle.checked = changes[ENABLED_KEY].newValue !== false;
    }
  });
})();
