/**
 * Theme management — reads/writes chrome.storage.local,
 * applies [data-theme] attribute, listens for live changes.
 */

const THEME_KEY = 'kg_theme';
const VALID_THEMES = ['light', 'dark', 'sepia'];
const DEFAULT_THEME = 'light';

/**
 * Resolve a stored value to a valid theme name.
 * @param {string|undefined} raw
 * @returns {string}
 */
function resolveTheme(raw) {
  return VALID_THEMES.includes(raw) ? raw : DEFAULT_THEME;
}

/**
 * Apply the theme to the given root element.
 * @param {HTMLElement} root — typically document.documentElement
 * @param {string} theme
 */
function applyTheme(root, theme) {
  root.setAttribute('data-theme', theme);
}

/**
 * Initialise theme on a root element.
 * Reads persisted preference from chrome.storage.local,
 * applies it, and listens for live changes.
 *
 * @param {HTMLElement} root — typically document.documentElement
 * @returns {Promise<string>} the resolved theme name
 */
async function initTheme(root) {
  const result = await chrome.storage.local.get(THEME_KEY);
  const theme = resolveTheme(result[THEME_KEY]);
  applyTheme(root, theme);

  // Live‑switch when another context (options page, background) changes the theme
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes[THEME_KEY]) {
      applyTheme(root, resolveTheme(changes[THEME_KEY].newValue));
    }
  });

  return theme;
}

/**
 * Persist and broadcast a theme change.
 * @param {string} name — 'light' | 'dark' | 'sepia'
 */
async function setTheme(name) {
  const theme = resolveTheme(name);
  await chrome.storage.local.set({ [THEME_KEY]: theme });
  // Storage onChanged listener will apply it to any open roots.
}

/**
 * Read the current persisted theme without side effects.
 * @returns {Promise<string>}
 */
async function getTheme() {
  const result = await chrome.storage.local.get(THEME_KEY);
  return resolveTheme(result[THEME_KEY]);
}

// Export for ES module consumers (side panel, options page)
// background.js uses importScripts — these will land on globalThis.
if (typeof globalThis !== 'undefined') {
  globalThis.KGTheme = { initTheme, setTheme, getTheme };
}
