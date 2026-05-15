/**
 * Options page — login flow, theme switching, about info.
 */

const AUTH_KEYS = ['auth_token'];
const authStatus = document.getElementById('auth-status');
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
}

function renderLoggedOut() {
  authStatus.innerHTML = '';

  const btn = document.createElement('button');
  btn.className = 'kg-btn';
  btn.textContent = '登入';
  btn.addEventListener('click', handleLogin);

  authStatus.appendChild(btn);
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
  btn.className = 'kg-btn';
  btn.textContent = '重試';
  btn.addEventListener('click', onRetry);

  authStatus.appendChild(msg);
  authStatus.appendChild(btn);
}

async function refreshAuthUI() {
  try {
    const data = await chrome.storage.local.get(AUTH_KEYS);
    if (data.auth_token) {
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
    chrome.tabs.create({ url: 'https://wordnexus.lol/login' });
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

  // Live storage changes (e.g. OAuth completing in another tab)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.auth_token) {
      refreshAuthUI();
    }
  });
})();
