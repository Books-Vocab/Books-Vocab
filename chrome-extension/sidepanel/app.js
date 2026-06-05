/**
 * KG Side Panel — vocab list, search, detail view.
 */

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

// Short i18n accessor — sidepanel reads chrome.i18n directly.
const t = (key, subs) => chrome.i18n.getMessage(key, subs);

const $ = (sel) => document.querySelector(sel);
const stateLoading = $('#stateLoading');
const stateEmpty   = $('#stateEmpty');
const stateError   = $('#stateError');
const stateContent = $('#stateContent');
const searchInput  = $('#searchInput');
const searchIcon   = $('#searchIcon');
const searchClear  = $('#searchClear');
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

/**
 * Selected review-state filter (iOS multi-select chips). Empty = show all.
 * Members are 'unlearned' | 'due' | 'reviewed'.
 * @type {Set<string>}
 */
const selectedStates = new Set();

/** Active sort (iOS KGVocabSortOption). @type {string} */
let sortOption = 'default';

/** Sort labels — mirrors iOS KGVocabSortOption.label. i18n lives here, not pure.js. */
const SORT_LABELS = {
  default: t('sortDefault'),
  alphabetical: t('sortAlphabetical'),
  dateAdded: t('sortDateAdded'),
  difficulty: t('sortDifficulty'),
};

/** UI label for a review-state chip (iOS VocabularyReviewState.displayName). */
const STATE_LABELS = { unlearned: t('stateUnlearned'), due: t('stateDue'), reviewed: t('stateReviewed') };

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
  KGIcons.setIcon(searchIcon, 'search');
  KGIcons.setIcon(searchClear, 'clear');

  themeBtn.addEventListener('click', cycleTheme);
  settingsBtn.addEventListener('click', openSettings);
  retryBtn.addEventListener('click', onRetry);
  searchInput.addEventListener('input', debounce(onSearch, 300));
  searchInput.addEventListener('input', syncClearButton);
  searchClear.addEventListener('click', () => {
    searchInput.value = '';
    syncClearButton();
    onSearch();
    searchInput.focus();
  });

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
  syncClearButton();

  try {
    const response = await chrome.runtime.sendMessage({ type: 'listVocab' });

    // A missing/torn-down service worker resolves sendMessage with `undefined`
    // (no error thrown). Treat that as a connection failure rather than an
    // empty vocab list, otherwise the user sees a false "empty" state.
    if (response === undefined || response === null) {
      showErrorFromResponse({
        error: true,
        code: 'network_error',
        message: t('errorBackgroundNoResponse'),
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
      .map(enrichWithReviewData);

    vocabData = items;

    if (items.length === 0) {
      setState('empty');
    } else {
      setState('content');
      applyView(); // state filter → search → sort → render
    }
  } catch (err) {
    // chrome.runtime.sendMessage rejects when there is no receiver, or the
    // extension context was invalidated (e.g. after an update/reload).
    console.error('[KG] loadVocabList failed:', err);
    showErrorFromResponse({
      error: true,
      code: 'network_error',
      message: t('errorBackgroundUnreachable'),
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

/**
 * Recompute the visible list from the full corpus through the iOS pipeline:
 * state filter (chips) → search filter → sort, then render. Chrome (chips + sort
 * pill + CTA) always reflects the full corpus / current control state.
 */
function applyView() {
  const visible = KGPure.sortVocab(
    KGPure.filterVocab(vocabData, { query: searchInput.value, states: selectedStates }),
    sortOption
  );
  renderList(visible);
}

// Search input feeds the same pipeline as chips/sort.
function onSearch() {
  applyView();
}

/** Show the clear (✕) button only when the search field has text. */
function syncClearButton() {
  searchClear.hidden = searchInput.value.length === 0;
}

// ---------------------------------------------------------------------------
// Filter + Sort Bar
// ---------------------------------------------------------------------------

// Relative formatter for the "下次 X" trailing label — web-native equivalent of
// iOS LocaleAwareFormatter.relativeString(style:.full). Lazily built once.
let _relFmt = null;
function relativeReviewLabel(nextReviewAt, nowMs = Date.now()) {
  const ts = Date.parse(String(nextReviewAt || ''));
  if (Number.isNaN(ts)) return '';
  if (!_relFmt && typeof Intl !== 'undefined' && Intl.RelativeTimeFormat) {
    _relFmt = new Intl.RelativeTimeFormat('zh-Hant', { numeric: 'auto', style: 'long' });
  }
  if (!_relFmt) return '';
  const diffSec = (ts - nowMs) / 1000;
  const abs = Math.abs(diffSec);
  if (abs >= 86400) return _relFmt.format(Math.round(diffSec / 86400), 'day');
  if (abs >= 3600) return _relFmt.format(Math.round(diffSec / 3600), 'hour');
  return _relFmt.format(Math.round(diffSec / 60), 'minute');
}

/**
 * Attach real review-progress fields to a vocab item, mirroring iOS
 * WordRowPresentation (no mocks — driven by CardResponse review state preserved
 * through normalizeVocabItem):
 *   - reviewRatio: 0=fresh→3=deep overdue (null for unlearned → label-only, no bar)
 *   - dueLabel:    progress detailLabel ("首輪 Xh" | "elapsed / interval")
 *   - dueInfo:     trailing status (iOS rowStatus: 未複習 | 待複習 | 下次 X)
 * @param {object} item
 * @returns {object}
 */
function enrichWithReviewData(item) {
  const p = KGPure.reviewProgress(item);
  const isUnlearned = p.state === 'unlearned';

  const dueLabel = isUnlearned
    ? t('reviewFirstRound', [KGPure.compactReviewLabel(item.reviewIntervalHours * 3600)])
    : `${KGPure.compactReviewLabel(p.elapsedSec)} / ${KGPure.compactReviewLabel(p.intervalSec)}`;

  let dueInfo;
  if (p.state === 'due') dueInfo = t('stateDue');
  else if (isUnlearned) dueInfo = t('rowStatusUnreviewed');
  else dueInfo = t('rowStatusNext', [relativeReviewLabel(item.nextReviewAt)]).trim();

  return {
    ...item,
    reviewState: p.state,
    reviewRatio: isUnlearned ? null : p.ratio,
    dueLabel,
    dueInfo,
  };
}

/**
 * Render filter chips (mirrors iOS VocabFilterChipBar): multi-select, no '全部'
 * chip (empty selection = all). Counts are the real per-state tally over the full
 * corpus; clicking a chip toggles it in `selectedStates` and re-applies the view.
 * @param {Array<object>} corpus — the full vocab list (counts are corpus-wide)
 */
function renderFilterBar(corpus) {
  if (!filterChips) return;
  filterChips.innerHTML = '';

  const counts = KGPure.countReviewStates(corpus);

  // Order mirrors iOS chip bar: 未學習 / 待複習 / 已複習.
  ['unlearned', 'due', 'reviewed'].forEach((state) => {
    const active = selectedStates.has(state);
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'kg-filter-bar__chip' + (active ? ' kg-filter-bar__chip--active' : '');
    chip.setAttribute('aria-pressed', active ? 'true' : 'false');
    chip.innerHTML = `${esc(STATE_LABELS[state])} <span class="kg-filter-bar__count">${counts[state]}</span>`;
    chip.addEventListener('click', () => {
      if (selectedStates.has(state)) selectedStates.delete(state);
      else selectedStates.add(state);
      applyView();
    });
    filterChips.appendChild(chip);
  });
}

/**
 * Render sort pill + review CTA (mirrors iOS VocabSortPill Menu + ReviewCTAPill).
 * The pill shows the active sort label + chevron and opens a dropdown of the 4
 * KGVocabSortOption choices (checkmark on the active one).
 * @param {Array<object>} corpus — full vocab list (CTA due count is corpus-wide)
 */
function renderSortPill(corpus) {
  if (!filterActions) return;
  closeSortMenu();
  filterActions.innerHTML = '';

  // Sort pill — a Menu trigger (iOS VocabSortPill is a SwiftUI Menu).
  const sortPill = document.createElement('button');
  sortPill.type = 'button';
  sortPill.className = 'kg-sort-pill';
  sortPill.setAttribute('aria-haspopup', 'true');
  sortPill.innerHTML =
    `<span>${esc(SORT_LABELS[sortOption] || SORT_LABELS.default)}</span>` +
    '<svg class="kg-sort-pill__chevron" width="10" height="10" viewBox="0 0 24 24" fill="none"' +
    ' stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"' +
    ' aria-hidden="true"><polyline points="6 9 12 15 18 9"></polyline></svg>';
  sortPill.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleSortMenu(sortPill);
  });
  filterActions.appendChild(sortPill);

  // Review CTA pill — brandHero fill (mirrors iOS ReviewCTAPill). Real count of
  // due cards (reviewCount>0 && nextReviewAt<=now), same predicate as iOS.
  const dueCount = KGPure.countReviewStates(corpus).due;
  if (dueCount > 0) {
    const cta = document.createElement('span');
    cta.className = 'kg-review-cta';
    cta.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg> <span class="kg-review-cta__count">${dueCount}</span>`;
    filterActions.appendChild(cta);
  }
}

// --- Sort dropdown menu (mirrors iOS VocabSortPill Menu) ---------------------

/** The live menu element + its outside-click/Escape dismiss handler, if open. */
let sortMenuEl = null;
let sortMenuDismiss = null;

function closeSortMenu() {
  if (sortMenuDismiss) {
    document.removeEventListener('click', sortMenuDismiss);
    document.removeEventListener('keydown', sortMenuDismiss);
    sortMenuDismiss = null;
  }
  if (sortMenuEl) {
    sortMenuEl.remove();
    sortMenuEl = null;
  }
}

function toggleSortMenu(anchor) {
  if (sortMenuEl) { closeSortMenu(); return; }

  const menu = document.createElement('div');
  menu.className = 'kg-sort-menu';
  menu.setAttribute('role', 'menu');

  let activeItem = null;
  KGPure.VOCAB_SORT_OPTIONS.forEach((opt) => {
    const active = opt === sortOption;
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'kg-sort-menu__item' + (active ? ' kg-sort-menu__item--active' : '');
    item.setAttribute('role', 'menuitemradio');
    item.setAttribute('aria-checked', active ? 'true' : 'false');
    const check = document.createElement('span');
    check.className = 'kg-sort-menu__check';
    check.setAttribute('aria-hidden', 'true');
    if (active) KGIcons.setIcon(check, 'check'); // SVG, not a glyph (icon convention)
    const text = document.createElement('span');
    text.textContent = SORT_LABELS[opt];
    item.append(check, text);
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      sortOption = opt;
      closeSortMenu();
      applyView();
    });
    menu.appendChild(item);
    if (active) activeItem = item;
  });

  // Anchor the menu under the pill, right-aligned within the actions row.
  filterActions.style.position = 'relative';
  filterActions.appendChild(menu);
  sortMenuEl = menu;
  // Focus the active option so keyboard users land on the current selection.
  if (activeItem) activeItem.focus();

  // Dismiss on any outside click or Escape (the pill's own click is stopped).
  sortMenuDismiss = (e) => {
    if (e.type === 'keydown' && e.key !== 'Escape') return;
    if (e.type === 'click' && menu.contains(e.target)) return;
    closeSortMenu();
  };
  // Defer so the opening click doesn't immediately dismiss it.
  setTimeout(() => {
    if (!sortMenuEl) return;
    document.addEventListener('click', sortMenuDismiss);
    document.addEventListener('keydown', sortMenuDismiss);
  }, 0);
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

  // Filter chips + CTA reflect the FULL corpus (iOS chip counts are full-list
  // and stable while searching), not the search-filtered `items` shown as rows.
  const corpus = Array.isArray(vocabData) && vocabData.length ? vocabData : items;
  renderFilterBar(corpus);
  renderSortPill(corpus);

  // No match for the active search/filter (corpus is non-empty) — iOS shows a
  // "沒有符合的單字" empty state; mirror it inline so the chrome stays put.
  if (items.length === 0) {
    const hint = document.createElement('p');
    hint.className = 'kg-list-nomatch';
    hint.textContent = t('noMatch');
    stateContent.appendChild(hint);
    setState('content');
    return;
  }

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
  setState('content');
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

  // ── Right side: progress (mirrors iOS VocabReviewProgressBar) ──────────────
  // ratio present (due/reviewed) → label + gradient bar; ratio null (unlearned)
  // → label only ("首輪 Xh"), no bar — exactly as iOS renders it.
  const hasBar = item.reviewRatio != null && item.reviewRatio >= 0;
  if (hasBar || item.dueLabel) {
    const progress = document.createElement('div');
    progress.className = 'kg-vocab-row__progress';

    if (item.dueLabel) {
      const labelEl = document.createElement('span');
      labelEl.className = 'kg-vocab-row__progress-label';
      labelEl.textContent = item.dueLabel;
      progress.appendChild(labelEl);
    }

    if (hasBar) {
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
    }

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
    detail.appendChild(makeSection(t('detailMeaning'), `<div class="kg-detail__meaning">${esc(meaning)}</div>`));
  }

  // POS
  if (pos) {
    detail.appendChild(makeSection(t('detailPos'), `<div class="kg-detail__meaning">${esc(pos)}</div>`));
  }

  // Examples
  if (examples.length > 0) {
    const lis = examples.map((ex) => `<li>${esc(typeof ex === 'string' ? ex : ex.sentence || ex.text || '')}</li>`).join('');
    detail.appendChild(makeSection(t('detailExamples'), `<ul class="kg-detail__examples">${lis}</ul>`));
  }

  // Collocations
  if (collocations.length > 0) {
    const chips = collocations.map((c) => `<span class="kg-chip kg-chip--tint">${esc(typeof c === 'string' ? c : c.word || '')}</span>`).join('');
    detail.appendChild(makeSection(t('detailCollocation'), `<div class="kg-detail__chips">${chips}</div>`));
  }

  // Note
  if (note) {
    detail.appendChild(makeSection(t('detailNote'), `<div class="kg-detail__note">${esc(note)}</div>`));
  }

  // Context
  if (context) {
    detail.appendChild(makeSection(t('detailContext'), `<div class="kg-detail__context">${esc(context)}</div>`));
  }

  // Source
  if (isWeb && sourceUrl) {
    const safeHref = KGPure.safeUrl(sourceUrl);
    detail.appendChild(makeSection(t('detailSource'), `<a class="kg-link kg-detail__link" href="${esc(safeHref)}" target="_blank" rel="noopener">${esc(sourceTitle || sourceUrl)}</a>`));
  } else {
    detail.appendChild(makeSection(t('detailSource'), `<span class="kg-detail__source-text">iOS app</span>`));
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
