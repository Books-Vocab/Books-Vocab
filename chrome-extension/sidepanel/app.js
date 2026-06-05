/**
 * KG Side Panel — vocab list, search, detail view.
 */

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);
const stateLoading = $('#stateLoading');
const stateEmpty   = $('#stateEmpty');
const stateError   = $('#stateError');
const stateContent = $('#stateContent');
const searchInput  = $('#searchInput');
const searchCount  = $('#searchCount');
const themeBtn     = $('#themeBtn');
const settingsBtn  = $('#settingsBtn');
const retryBtn     = $('#retryBtn');
const errorIcon    = $('#errorIcon');
const errorTitle   = $('#errorTitle');
const errorSubtitle = $('#errorSubtitle');
const filterChips  = $('#filterChips');
const filterActions = $('#filterActions');

/**
 * Current retry action — varies by error kind.
 * - 'reload'   : re-call loadVocabList
 * - 'login'    : open options page (login entry)
 * - 'settings' : open options page (quota / account info)
 * @type {'reload'|'login'|'settings'}
 */
let retryAction = 'reload';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {Array<object>} full vocab list from API */
let vocabData = [];

// Theme glyphs come from KGIcons (shared/icons.js) — SVG, not emoji — so the
// button matches the iOS SF-Symbols look. Icon name = `theme-${theme}`.
const THEME_CYCLE = ['light', 'dark', 'sepia'];

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
  const theme = await initTheme(document.documentElement);
  updateThemeBtn(theme);
  KGIcons.setIcon(settingsBtn, 'settings');

  themeBtn.addEventListener('click', cycleTheme);
  settingsBtn.addEventListener('click', openSettings);
  retryBtn.addEventListener('click', onRetry);
  searchInput.addEventListener('input', debounce(onSearch, 300));

  // Auto-reload when auth token changes (e.g. login completed in another tab).
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.auth_token) {
      loadVocabList();
    }
  });

  loadVocabList();
});

/** Open the extension options page in a new tab. */
function openSettings() {
  if (chrome.runtime.openOptionsPage) {
    chrome.runtime.openOptionsPage().catch((err) => console.error('[KG] openOptionsPage failed', err));
  } else {
    chrome.tabs.create({ url: chrome.runtime.getURL('options/options.html') }).catch((err) => console.error('[KG] openSettings tabs.create failed', err));
  }
}

/** Retry button dispatcher — login / settings flow vs. plain reload. */
function onRetry() {
  if (retryAction === 'login' || retryAction === 'settings') {
    openSettings();
  } else {
    loadVocabList();
  }
}

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

function updateThemeBtn(theme) {
  const icon = document.getElementById('themeIcon');
  if (icon) {
    KGIcons.setIcon(icon, THEME_CYCLE.includes(theme) ? `theme-${theme}` : 'theme-light');
  }
}

async function cycleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const idx = THEME_CYCLE.indexOf(current);
  const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
  await setTheme(next);
  updateThemeBtn(next);
}

// ---------------------------------------------------------------------------
// State management
// ---------------------------------------------------------------------------

/**
 * Show one state container, hide the rest.
 * @param {'loading'|'empty'|'error'|'content'} state
 */
function setState(state) {
  stateLoading.hidden = state !== 'loading';
  stateEmpty.hidden   = state !== 'empty';
  stateError.hidden   = state !== 'error';
  stateContent.hidden = state !== 'content';
}

// ---------------------------------------------------------------------------
// Load vocab
// ---------------------------------------------------------------------------

async function loadVocabList() {
  setState('loading');
  searchInput.value = '';
  searchCount.textContent = '';

  try {
    const response = await chrome.runtime.sendMessage({ type: 'listVocab' });

    // A missing/torn-down service worker resolves sendMessage with `undefined`
    // (no error thrown). Treat that as a connection failure rather than an
    // empty vocab list, otherwise the user sees a false "empty" state.
    if (response === undefined || response === null) {
      showErrorFromResponse({
        error: true,
        code: 'network_error',
        message: '擴充功能背景服務未回應，請重新整理',
      });
      return;
    }

    if (response.error) {
      showErrorFromResponse(response);
      return;
    }

    // Response is the vocab array (or an { items } / { data } envelope).
    // Normalize each raw payload to one canonical shape here, at the single
    // ingress point, so every downstream read (search / card / detail) uses
    // canonical field names instead of papering over snake_case/legacy aliases.
    const items = KGPure.normalizeVocabList(response)
      .map(KGPure.normalizeVocabItem)
      .map(enrichWithMockReviewData);

    vocabData = items;

    if (items.length === 0) {
      setState('empty');
    } else {
      setState('content');
      renderList(items);
    }
  } catch (err) {
    // chrome.runtime.sendMessage rejects when there is no receiver, or the
    // extension context was invalidated (e.g. after an update/reload).
    console.error('[KG] loadVocabList failed:', err);
    showErrorFromResponse({
      error: true,
      code: 'network_error',
      message: '無法連線至背景服務，請重試',
    });
  }
}

/**
 * Render the error state with messaging keyed off the API error code/status.
 * Updates icon, title, subtitle, retry button label, and the retry action.
 * For login errors, applies the editorial login treatment (no emoji, brand-hero CTA).
 * @param {{error: true, code?: string, status?: number, message?: string}} response
 */
function showErrorFromResponse(response) {
  const { icon, title, subtitle, btnLabel, action } =
    KGPure.classifyError(response || {});

  const container = document.getElementById('errorContainer');
  const isLogin = action === 'login';

  if (container) {
    container.classList.toggle('kg-error--login', isLogin);
  }

  if (isLogin) {
    // Editorial login state: no icon, clean typography, brand-hero CTA.
    KGIcons.setIcon(errorIcon, '');
    retryBtn.className = 'kg-btn kg-error__retry';
  } else {
    // icon is a KGIcons name (error-*) from classifyError → render as SVG.
    KGIcons.setIcon(errorIcon, icon);
    retryBtn.className = 'kg-btn kg-btn--accent kg-error__retry';
  }

  errorTitle.textContent = title;
  if (subtitle) {
    errorSubtitle.textContent = subtitle;
    errorSubtitle.hidden = false;
  } else {
    errorSubtitle.textContent = '';
    errorSubtitle.hidden = true;
  }
  retryBtn.textContent = btnLabel;
  retryAction = action;
  setState('error');
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

function onSearch() {
  const query = searchInput.value.trim().toLowerCase();

  if (!query) {
    searchCount.textContent = '';
    renderList(vocabData);
    return;
  }

  const filtered = vocabData.filter((item) => {
    const word = item.word.toLowerCase();
    const meaning = item.meaning.toLowerCase();
    return word.includes(query) || meaning.includes(query);
  });

  searchCount.textContent = `${filtered.length}`;
  renderList(filtered);
}

// ---------------------------------------------------------------------------
// Filter + Sort Bar
// ---------------------------------------------------------------------------

/**
 * Deterministically generate mock review-progress data from the word itself.
 * This gives every row a progress bar + due label so the sidepanel visually
 * matches the iOS vocab list. When the backend API gains real review metadata,
 * replace this with actual data — the UI structure (progress bar, trailing label)
 * is already wired and ready.
 * @param {object} item
 * @returns {object}
 */
function enrichWithMockReviewData(item) {
  // djb2 hash over the word for deterministic, stable mock values
  let hash = 5381;
  for (let i = 0; i < item.word.length; i++) {
    hash = ((hash << 5) + hash) + item.word.charCodeAt(i);
  }
  const positive = Math.abs(hash);

  // ratio 0..3 (fresh → deep overdue)
  const ratio = (positive % 350) / 100;

  // "55d / 2d" style label
  const daysSince = positive % 80;
  const daysUntil = Math.max(1, 20 - (positive % 25));
  const dueLabel = `${daysSince}d / ${daysUntil}d`;

  return {
    ...item,
    reviewRatio: ratio,
    dueLabel,
    dueInfo: dueLabel,
  };
}

/**
 * Render filter chips (mirrors iOS VocabFilterChipBar).
 * Since the sidepanel API lacks review-state counts, we show a simplified
 * "All" chip with the total count, reserving the structure for future data.
 * @param {Array<object>} items
 */
function renderFilterBar(items) {
  if (!filterChips) return;
  filterChips.innerHTML = '';

  // Deterministic mock counts from total vocab size for visual parity with iOS
  const total = items.length;
  const dueCount = Math.floor(total * 0.45);
  const unlearnedCount = Math.floor(total * 0.25);
  const reviewedCount = total - dueCount - unlearnedCount;

  const states = [
    { label: '全部', count: total, active: true },
    { label: '未學習', count: unlearnedCount },
    { label: '待複習', count: dueCount },
    { label: '已複習', count: reviewedCount },
  ];
  states.forEach((s) => {
    const chip = document.createElement('span');
    chip.className = 'kg-filter-bar__chip' + (s.active ? ' kg-filter-bar__chip--active' : '');
    chip.innerHTML = `${esc(s.label)} <span class="kg-filter-bar__count">${s.count}</span>`;
    filterChips.appendChild(chip);
  });
}

/**
 * Render sort pill + review CTA (mirrors iOS VocabSortPill + VocabReviewCTAPill).
 */
function renderSortPill(items) {
  if (!filterActions) return;
  filterActions.innerHTML = '';

  // Sort pill
  const sortPill = document.createElement('span');
  sortPill.className = 'kg-sort-pill';
  sortPill.textContent = '複習優先';
  filterActions.appendChild(sortPill);

  // Review CTA pill — brandHero fill (mirrors iOS ReviewCTAPill)
  // When API gains dueCount, replace mock with real data.
  const dueCount = Math.floor(items.length * 0.45); // Mock: 45% of total as due
  if (dueCount > 0) {
    const cta = document.createElement('span');
    cta.className = 'kg-review-cta';
    cta.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> <span class="kg-review-cta__count">${dueCount}</span>`;
    filterActions.appendChild(cta);
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * Render the vocab list.
 * Mirrors iOS KGVocabPresenter: single ListSectionCard with divider-separated rows.
 * @param {Array<object>} items
 */
function renderList(items) {
  stateContent.innerHTML = '';

  // Update filter bar + sort pill (mirrors iOS KGVocabPresenter chrome)
  renderFilterBar(items);
  renderSortPill(items);

  // Single card container (mirrors iOS ListSectionCard / VocabListCard)
  const card = document.createElement('div');
  card.className = 'kg-list-section';

  items.forEach((item, index) => {
    const row = createRow(item);
    card.appendChild(row);

    if (index < items.length - 1) {
      const divider = document.createElement('div');
      divider.className = 'kg-vocab-row__divider';
      card.appendChild(divider);
    }
  });

  stateContent.appendChild(card);

  if (items.length > 0) {
    setState('content');
  }
}

/**
 * Create a vocab row element (mirrors iOS KGVocabRow + WordRow).
 * @param {object} item
 * @returns {HTMLElement}
 */
function createRow(item) {
  const row = document.createElement('div');
  row.className = 'kg-vocab-row';
  row.dataset.word = item.word;

  // ── Left content column ────────────────────────────────────────────────
  const content = document.createElement('div');
  content.className = 'kg-vocab-row__content';

  // Top row: word + pos + trailing label
  const topRow = document.createElement('div');
  topRow.className = 'kg-vocab-row__top';

  const wordEl = document.createElement('span');
  wordEl.className = 'kg-vocab-row__word';
  wordEl.textContent = item.word;
  topRow.appendChild(wordEl);

  if (item.pos) {
    const posEl = document.createElement('span');
    posEl.className = 'kg-vocab-row__pos';
    posEl.textContent = item.pos;
    topRow.appendChild(posEl);
  }

  // Trailing label (e.g., "55d / 2d") — show if API provides it
  if (item.dueInfo) {
    const trailingEl = document.createElement('span');
    trailingEl.className = 'kg-vocab-row__trailing';
    trailingEl.textContent = item.dueInfo;
    topRow.appendChild(trailingEl);
  }

  content.appendChild(topRow);

  // Meaning / translation
  if (item.meaning) {
    const meaningEl = document.createElement('div');
    meaningEl.className = 'kg-vocab-row__meaning';
    meaningEl.textContent = item.meaning;
    content.appendChild(meaningEl);
  }

  // Source metadata (book / chapter)
  if (item.source && (item.source.title || item.source.book)) {
    const meta = document.createElement('div');
    meta.className = 'kg-vocab-row__meta';
    const sourceName = item.source.title || item.source.book || '';
    const chapter = item.source.chapter || '';
    meta.textContent = chapter ? `${sourceName} · ${chapter}` : sourceName;
    content.appendChild(meta);
  }

  row.appendChild(content);

  // ── Right side: progress bar ───────────────────────────────────────────
  if (item.reviewRatio != null && item.reviewRatio >= 0) {
    const progress = document.createElement('div');
    progress.className = 'kg-vocab-row__progress';

    if (item.dueLabel) {
      const labelEl = document.createElement('span');
      labelEl.className = 'kg-vocab-row__progress-label';
      labelEl.textContent = item.dueLabel;
      progress.appendChild(labelEl);
    }

    const track = document.createElement('div');
    track.className = 'kg-vocab-row__progress-track';

    const fill = document.createElement('div');
    fill.className = 'kg-vocab-row__progress-fill';
    const ratio = Math.min(item.reviewRatio, 1.0);
    fill.style.width = `${ratio * 100}%`;
    // Use shared KGReviewGradient if available, else fallback
    const gradColor = (typeof KGReviewGradient !== 'undefined')
      ? KGReviewGradient.reviewGradientColor(item.reviewRatio)
      : '#4D7396';
    fill.style.backgroundColor = gradColor;

    track.appendChild(fill);
    progress.appendChild(track);
    row.appendChild(progress);
  }

  // Click handler
  row.addEventListener('click', () => toggleDetail(row, item));

  return row;
}

/**
 * Toggle detail view for a row.
 * @param {HTMLElement} row
 * @param {object} item
 */
function toggleDetail(row, item) {
  const existing = row.querySelector('.kg-detail');

  if (existing) {
    existing.remove();
    return;
  }

  // Collapse any other expanded row
  const prev = stateContent.querySelector('.kg-detail');
  if (prev) prev.remove();

  const detail = document.createElement('div');
  detail.className = 'kg-detail';

  const meaning = item.meaning;
  const pos = item.pos;
  const examples = item.examples;
  const collocations = item.collocations;
  const note = item.note;
  const context = item.context;
  const source = item.source;
  const sourceUrl = source ? (source.url || '') : '';
  const sourceTitle = source ? (source.title || '') : '';
  const isWeb = source && source.type === 'web';

  // Full meaning
  if (meaning) {
    detail.appendChild(makeSection('意思', `<div class="kg-detail__meaning">${esc(meaning)}</div>`));
  }

  // POS
  if (pos) {
    detail.appendChild(makeSection('詞性', `<div class="kg-detail__meaning">${esc(pos)}</div>`));
  }

  // Examples
  if (examples.length > 0) {
    const lis = examples.map((ex) => `<li>${esc(typeof ex === 'string' ? ex : ex.sentence || ex.text || '')}</li>`).join('');
    detail.appendChild(makeSection('例句', `<ul class="kg-detail__examples">${lis}</ul>`));
  }

  // Collocations
  if (collocations.length > 0) {
    const chips = collocations.map((c) => `<span class="kg-chip kg-chip--tint">${esc(typeof c === 'string' ? c : c.word || '')}</span>`).join('');
    detail.appendChild(makeSection('搭配', `<div class="kg-detail__chips">${chips}</div>`));
  }

  // Note
  if (note) {
    detail.appendChild(makeSection('筆記', `<div class="kg-detail__note">${esc(note)}</div>`));
  }

  // Context
  if (context) {
    detail.appendChild(makeSection('上下文', `<div class="kg-detail__context">${esc(context)}</div>`));
  }

  // Source
  if (isWeb && sourceUrl) {
    const safeHref = KGPure.safeUrl(sourceUrl);
    detail.appendChild(makeSection('來源', `<a class="kg-link kg-detail__link" href="${esc(safeHref)}" target="_blank" rel="noopener">${esc(sourceTitle || sourceUrl)}</a>`));
  } else {
    detail.appendChild(makeSection('來源', `<span class="kg-detail__source-text">iOS app</span>`));
  }

  // Append detail to the content column so it sits below word/meaning,
  // not beside the progress bar (row is flex, content is flex-column).
  const content = row.querySelector('.kg-vocab-row__content');
  if (content) {
    content.appendChild(detail);
  } else {
    row.appendChild(detail);
  }
}

/**
 * Create a detail section.
 * @param {string} label
 * @param {string} contentHTML
 * @returns {HTMLElement}
 */
function makeSection(label, contentHTML) {
  const section = document.createElement('div');
  section.className = 'kg-detail__section';
  section.innerHTML = `<div class="kg-detail__label">${esc(label)}</div>${contentHTML}`;
  return section;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Escape HTML to prevent XSS. Thin alias for `KGPure.escapeHtml` — kept under
 * the local `esc` name because the template-literal call sites read better
 * short (`${esc(meaning)}` vs `${KGPure.escapeHtml(meaning)}`).
 * @param {string} str
 * @returns {string}
 */
function esc(str) {
  return KGPure.escapeHtml(str);
}

/**
 * Debounce a function.
 * @param {Function} fn
 * @param {number} ms
 * @returns {Function}
 */
function debounce(fn, ms) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}
