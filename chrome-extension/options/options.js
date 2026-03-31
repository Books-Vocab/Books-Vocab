/**
 * Options page — login flow, theme switching, about info.
 */

const AUTH_KEYS = ['auth_token', 'user_id'];
const authStatus = document.getElementById('auth-status');
const themeSelector = document.getElementById('theme-selector');

// ── Helpers ──

function truncateId(id) {
  if (!id) return '—';
  const s = String(id);
  return s.length > 12 ? s.slice(0, 6) + '…' + s.slice(-4) : s;
}

// ── Auth UI ──

function renderLoggedIn(userId) {
  authStatus.innerHTML = '';

  const info = document.createElement('div');
  info.className = 'kg-auth-info';
  info.textContent = '已登入：' + truncateId(userId);

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

async function refreshAuthUI() {
  const data = await chrome.storage.local.get(AUTH_KEYS);
  if (data.auth_token) {
    renderLoggedIn(data.user_id);
  } else {
    renderLoggedOut();
  }
}

// ── Auth Actions ──

function handleLogin() {
  chrome.tabs.create({ url: 'https://wordnexus.lol/login' });
}

async function handleLogout() {
  await chrome.storage.local.remove(AUTH_KEYS);
  renderLoggedOut();
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
  // Theme
  const currentTheme = await initTheme(document.documentElement);
  activateThemeOption(currentTheme);
  themeSelector.addEventListener('click', handleThemeChange);

  // Auth
  await refreshAuthUI();

  // Live storage changes (e.g. OAuth completing in another tab)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && (changes.auth_token || changes.user_id)) {
      refreshAuthUI();
    }
  });
})();
