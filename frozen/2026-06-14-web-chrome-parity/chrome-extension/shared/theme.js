/**
 * Theme management — reads/writes chrome.storage.local,
 * applies [data-theme] attribute, listens for live changes.
 *
 * NOTE: VALID_THEMES / DEFAULT_THEME / resolveTheme are declared as top-level
 * identifiers in shared/pure.js (loaded first in the same window scope).
 * Do NOT re-declare them here — duplicate top-level `const`/`function` in a
 * classic script context causes a SyntaxError that aborts this entire file.
 * Use globalThis.KGPure.resolveTheme() instead.
 */

const THEME_KEY = 'kg_theme';

function applyTheme(root, theme) {
  root.setAttribute('data-theme', theme);
}

async function initTheme(root) {
  const result = await chrome.storage.local.get(THEME_KEY);
  const theme = globalThis.KGPure.resolveTheme(result[THEME_KEY]);
  applyTheme(root, theme);

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes[THEME_KEY]) {
      applyTheme(root, globalThis.KGPure.resolveTheme(changes[THEME_KEY].newValue));
    }
  });

  return theme;
}

async function setTheme(name) {
  const theme = globalThis.KGPure.resolveTheme(name);
  await chrome.storage.local.set({ [THEME_KEY]: theme });
}

async function getTheme() {
  const result = await chrome.storage.local.get(THEME_KEY);
  return globalThis.KGPure.resolveTheme(result[THEME_KEY]);
}

if (typeof globalThis !== 'undefined') {
  globalThis.KGTheme = { initTheme, setTheme, getTheme };
}
