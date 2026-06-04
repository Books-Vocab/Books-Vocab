/**
 * Options page — login flow, theme switching, about info.
 */

// Mirrors KGApi.TOKEN_KEY in shared/api.js — options.js is a classic script and
// cannot import the module, so the literal is defined once here and reused.
const TOKEN_KEY = 'auth_token';
const AUTH_KEYS = [TOKEN_KEY];
const authStatus = document.getElementById('auth-status');
const tokenPasteArea = document.getElementById('token-paste-area');
const tokenInput = document.getElementById('tokenInput');
const tokenSubmit = document.getElementById('tokenSubmit');
const themeSelector = document.getElementById('theme-selector');

// ── Auth UI ──

function renderLoggedIn() {
  authStatus.innerHTML = '';

  const info = document.createElement('div');
  info.className = 'kg-auth-info';
  info.textContent = '已登入';

  const btn = document.createElement('button');
  btn.className = 'kg-btn kg-btn--destructive';
  btn.textContent = '登出';
  btn.addEventListener('click', handleLogout);

  authStatus.appendChild(info);
  authStatus.appendChild(btn);

  if (tokenPasteArea) tokenPasteArea.hidden = true;
}

function renderLoggedOut() {
  authStatus.innerHTML = '';

  const btn = document.createElement('button');
  btn.className = 'kg-btn kg-btn--primary';
  btn.textContent = '登入';
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

  const msg = document.createElement('div');
  msg.className = 'kg-auth-info';
  msg.textContent = message;

  const btn = document.createElement('button');
  btn.className = 'kg-btn kg-btn--primary';
  btn.textContent = '重試';
  btn.addEventListener('click', onRetry);

  authStatus.appendChild(msg);
  authStatus.appendChild(btn);
}

async function refreshAuthUI() {
  try {
    const data = await chrome.storage.local.get(AUTH_KEYS);
    if (data[TOKEN_KEY]) {
      renderLoggedIn();
    } else {
      renderLoggedOut();
    }
  } catch (err) {
    // chrome.storage can reject when the extension context is invalidated.
    console.error('[KG] refreshAuthUI failed:', err);
    renderAuthError('無法讀取登入狀態', refreshAuthUI);
  }
}

// ── Auth Actions ──

function handleLogin() {
  try {
    chrome.tabs.create({ url: 'https://wordnexus.lol/login' }).catch((err) => console.error('[KG] handleLogin tabs.create failed', err));
  } catch (err) {
    console.error('[KG] handleLogin failed:', err);
    renderAuthError('無法開啟登入頁面', handleLogin);
  }
}

async function handleLogout() {
  try {
    await chrome.storage.local.remove(AUTH_KEYS);
    renderLoggedOut();
  } catch (err) {
    console.error('[KG] handleLogout failed:', err);
    renderAuthError('登出失敗，請重試', handleLogout);
  }
}

async function handleTokenSubmit() {
  const raw = tokenInput.value.trim();
  if (!raw) return;

  // Minimal JWT shape validation — three dot-separated base64url segments.
  const jwtPattern = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
  if (!jwtPattern.test(raw)) {
    renderAuthError('Token 格式不正確，請確認為完整 JWT 字串', () => {
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
    renderAuthError('儲存 Token 失敗，請重試', () => {
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

// ── Init ──

(async function init() {
  // Theme — fall back to the default if storage is unavailable.
  try {
    const currentTheme = await initTheme(document.documentElement);
    activateThemeOption(currentTheme);
  } catch (err) {
    console.error('[KG] theme init failed:', err);
    activateThemeOption('light');
  }
  themeSelector.addEventListener('click', handleThemeChange);

  // Auth
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
    if (area === 'local' && changes[TOKEN_KEY]) {
      refreshAuthUI();
    }
  });
})();
