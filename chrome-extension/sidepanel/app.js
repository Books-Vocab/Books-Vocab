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
const emptyIcon    = $('#emptyIcon');
const emptyTitle   = $('#emptyTitle');
const emptySubtitle = $('#emptySubtitle');
const themeBtn     = $('#themeBtn');
const settingsBtn  = $('#settingsBtn');
const retryBtn     = $('#retryBtn');
const errorIcon    = $('#errorIcon');
const errorTitle   = $('#errorTitle');
const errorSubtitle = $('#errorSubtitle');
const filterChips  = $('#filterChips');
const filterActions = $('#filterActions');
const notebookSwitcher = $('#notebookSwitcher');
const notebookSelect = $('#notebookSelect');
const notebookAddBtn = $('#notebookAddBtn');
const notebookEditBtn = $('#notebookEditBtn');
const notebookDeleteBtn = $('#notebookDeleteBtn');
const notebookSheet = $('#notebookSheet');
const notebookSheetScrim = $('#notebookSheetScrim');
const notebookForm = $('#notebookForm');
const notebookSheetTitle = $('#notebookSheetTitle');
const notebookSheetClose = $('#notebookSheetClose');
const notebookNameInput = $('#notebookNameInput');
const notebookCoverPreview = $('#notebookCoverPreview');
const notebookCoverPreviewName = $('#notebookCoverPreviewName');
const notebookColorSwatches = $('#notebookColorSwatches');
const notebookPatternChoices = $('#notebookPatternChoices');
const notebookSheetError = $('#notebookSheetError');
const notebookSheetDelete = $('#notebookSheetDelete');
const notebookSheetSubmit = $('#notebookSheetSubmit');
const stateDetail  = $('#stateDetail');
const detailBack   = $('#detailBack');
const detailShare  = $('#detailShare');
const detailBarWord = $('#detailBarWord');
const detailBody   = $('#detailBody');

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
 * Optimistic rows for words enqueued in the add-outbox but not yet on the server
 * list (pending / failed sync). Rendered ABOVE the server corpus so a freshly
 * added word is visible immediately and a sync failure is surfaced. Kept OUT of
 * `vocabData` (filter-chip counts / sort mirror the server corpus only).
 * @type {Array<object>}
 */
let pendingSyncItems = [];

/** @type {Array<object>} notebook list from API */
let notebooks = [];

/** Active notebook scope for list/add parity with iOS. */
let activeNotebookId = 'default';

/** @type {'create'|'rename'|null} */
let notebookSheetMode = null;
let notebookDraftColor = KGPure.NOTEBOOK_DEFAULT_COLOR;
let notebookDraftPattern = null;

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
  if (notebookSelect) {
    notebookSelect.addEventListener('change', onNotebookChanged);
  }
  if (notebookAddBtn) {
    KGIcons.setIcon(notebookAddBtn, 'plus');
    notebookAddBtn.addEventListener('click', () => openNotebookSheet('create'));
  }
  if (notebookEditBtn) {
    KGIcons.setIcon(notebookEditBtn, 'pencil');
    notebookEditBtn.addEventListener('click', () => openNotebookSheet('rename'));
  }
  if (notebookDeleteBtn) {
    KGIcons.setIcon(notebookDeleteBtn, 'trash');
    notebookDeleteBtn.addEventListener('click', () => openNotebookSheet('rename', { focusDelete: true }));
  }
  if (notebookSheetClose) {
    KGIcons.setIcon(notebookSheetClose, 'xmark');
    notebookSheetClose.addEventListener('click', closeNotebookSheet);
  }
  if (notebookSheetScrim) notebookSheetScrim.addEventListener('click', closeNotebookSheet);
  if (notebookForm) notebookForm.addEventListener('submit', submitNotebookForm);
  if (notebookNameInput) notebookNameInput.addEventListener('input', renderNotebookCoverPreview);
  if (notebookColorSwatches) notebookColorSwatches.addEventListener('click', onNotebookColorClick);
  if (notebookPatternChoices) notebookPatternChoices.addEventListener('click', onNotebookPatternClick);
  if (notebookSheetDelete) notebookSheetDelete.addEventListener('click', deleteActiveNotebook);

  // Word detail panel — back navigation + delegated speaker / link-nav actions.
  KGIcons.setIcon(detailBack, 'chevron-left');
  detailBack.addEventListener('click', popDetail);
  KGIcons.setIcon(detailShare, 'square.and.arrow.up');
  detailShare.addEventListener('click', shareDetailTop);
  detailBody.addEventListener('click', onDetailAction);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !stateDetail.hidden) popDetail();
    else if (e.key === 'Escape' && notebookSheet && !notebookSheet.hidden) closeNotebookSheet();
  });

  // React to cross-context storage changes.
  //  - auth_token   → a full (re)load (login/logout in another tab).
  //  - VOCAB_DIRTY_KEY → a silent refresh: a word was added from the in-page
  //    popup, so refetch WITHOUT clobbering the user's search / filter / open
  //    detail. (auth wins — a logout makes the list moot.)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes.auth_token) {
      loadVocabList();
      return;
    }
    if (changes[KGPure.VOCAB_DIRTY_KEY]) {
      refreshVocabSilently();
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
  if (state === 'empty') renderStandaloneEmptyState();
  stateLoading.hidden = state !== 'loading';
  stateEmpty.hidden   = state !== 'empty';
  stateError.hidden   = state !== 'error';
  stateContent.hidden = state !== 'content';
}

function currentEmptyState(hasNoEntries) {
  return KGPure.vocabEmptyState({
    hasNoEntries,
    searchText: searchInput.value,
    filters: selectedStates,
  });
}

function createEmptyStateElement(model, compact = false) {
  const wrap = document.createElement('div');
  wrap.className = 'kg-empty' + (compact ? ' kg-empty--inline' : '');
  wrap.dataset.emptyKind = model.kind;

  const icon = document.createElement('span');
  icon.className = 'kg-empty__icon';
  icon.setAttribute('aria-hidden', 'true');
  KGIcons.setIcon(icon, model.systemImage);

  const title = document.createElement('p');
  title.className = 'kg-empty__title';
  title.textContent = t(model.titleKey);

  const subtitle = document.createElement('p');
  subtitle.className = 'kg-empty__subtitle';
  subtitle.textContent = t(model.descriptionKey);

  wrap.append(icon, title, subtitle);
  return wrap;
}

function renderStandaloneEmptyState() {
  const model = currentEmptyState(true);
  if (emptyIcon) KGIcons.setIcon(emptyIcon, model.systemImage);
  if (emptyTitle) emptyTitle.textContent = t(model.titleKey);
  if (emptySubtitle) emptySubtitle.textContent = t(model.descriptionKey);
}

// ---------------------------------------------------------------------------
// Load vocab
// ---------------------------------------------------------------------------

async function loadVocabList() {
  setState('loading');
  closeDetail(); // a reload invalidates the open detail stack (stale items)
  searchInput.value = '';
  syncClearButton();

  try {
    await loadNotebookScope();
    const response = await chrome.runtime.sendMessage({ type: 'listVocab', notebookId: activeNotebookId });

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
    await loadPendingSyncItems(items);

    if (items.length === 0 && pendingSyncItems.length === 0) {
      setState('empty');
    } else {
      setState('content');
      applyView(); // pending rows + state filter → search → sort → render
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
 * Silently re-fetch the vocab list after a cross-context mutation — a word
 * added from the in-page popup bumps VOCAB_DIRTY_KEY (see background.js).
 *
 * Unlike loadVocabList this is non-destructive: it keeps the current search
 * term, filter chips, sort, scroll position and any open detail panel intact,
 * so the freshly-added row just appears under the live view instead of yanking
 * the user back to a cleared, scrolled-to-top list. A fetch failure is swallowed
 * — the user didn't explicitly act, so a momentarily stale list beats an error
 * banner clobbering what they're reading.
 */
async function refreshVocabSilently() {
  // An explicit flow already owns the screen: a logout/login reload is in
  // flight (loading), or the user is reading an error we shouldn't yank away.
  if (!stateLoading.hidden || !stateError.hidden) return;

  try {
    await loadNotebookScope({ silent: true });
    const response = await chrome.runtime.sendMessage({ type: 'listVocab', notebookId: activeNotebookId });
    if (response == null || response.error) return; // keep the current view

    const items = KGPure.normalizeVocabList(response)
      .map(KGPure.normalizeVocabItem)
      .map(enrichWithReviewData);
    vocabData = items;
    await loadPendingSyncItems(items);

    if (items.length === 0 && pendingSyncItems.length === 0) {
      closeDetail();
      setState('empty');
      return;
    }

    // Preserve scroll across the full re-render (renderList resets innerHTML).
    // The side panel scrolls on the page (body), so capture the page scroller.
    const scroller = document.scrollingElement || document.documentElement;
    const savedTop = scroller ? scroller.scrollTop : 0;
    setState('content');
    applyView(); // re-applies filter → search → sort, then renders
    if (scroller) scroller.scrollTop = savedTop;
  } catch (err) {
    console.error('[KG] refreshVocabSilently failed:', err);
  }
}

// Pull the backend `vocab_ui` cursor via the background worker. Returns null when
// unauthenticated / offline / never-set so the caller keeps the local cursor.
async function fetchRemoteActiveNotebook() {
  try {
    const config = await chrome.runtime.sendMessage({ type: 'getUserConfig' });
    if (config == null || config.error) return null;
    const vu = config.vocab_ui;
    if (!vu || typeof vu.active_notebook_id !== 'string') return null;
    return {
      id: vu.active_notebook_id,
      updatedAt: typeof vu.updated_at === 'number' ? vu.updated_at : null,
    };
  } catch (_err) {
    return null;
  }
}

// Persist the active-notebook cursor locally (id + LWW timestamp) and push it to
// the backend `vocab_ui` group so iOS / web / content script converge. Best-effort
// push: a failure is logged, never rolled back — chrome.storage.local is the local
// source of truth; the backend is the cross-platform bridge.
async function persistActiveNotebook(id) {
  const updatedAt = Date.now() / 1000;
  await chrome.storage.local.set({
    [KGPure.ACTIVE_NOTEBOOK_KEY]: id,
    [KGPure.ACTIVE_NOTEBOOK_UPDATED_KEY]: updatedAt,
  });
  try {
    await chrome.runtime.sendMessage({
      type: 'updateUserConfig',
      config: KGPure.buildVocabUiConfigPatch(id, updatedAt),
    });
  } catch (err) {
    console.error('[KG] push active notebook failed:', err);
  }
}

async function loadNotebookScope(options = {}) {
  const silent = !!options.silent;
  try {
    // Two-layer LWW cold-start: reconcile the local cursor (chrome.storage.local)
    // with the backend `vocab_ui` group so a notebook selected on iOS / web shows
    // here, and vice-versa. Best-effort — a failed / unauthenticated pull keeps
    // the local cursor.
    const stored = await chrome.storage.local.get([
      KGPure.ACTIVE_NOTEBOOK_KEY,
      KGPure.ACTIVE_NOTEBOOK_UPDATED_KEY,
    ]);
    let cursor = {
      id: stored[KGPure.ACTIVE_NOTEBOOK_KEY] || 'default',
      updatedAt: typeof stored[KGPure.ACTIVE_NOTEBOOK_UPDATED_KEY] === 'number'
        ? stored[KGPure.ACTIVE_NOTEBOOK_UPDATED_KEY]
        : null,
    };
    const remote = await fetchRemoteActiveNotebook();
    if (remote) {
      const resolved = KGPure.resolveActiveNotebook(cursor, remote);
      if (resolved.id !== cursor.id || resolved.updatedAt !== cursor.updatedAt) {
        await chrome.storage.local.set({
          [KGPure.ACTIVE_NOTEBOOK_KEY]: resolved.id,
          [KGPure.ACTIVE_NOTEBOOK_UPDATED_KEY]: resolved.updatedAt,
        });
      }
      cursor = resolved;
    }
    const storedId = cursor.id;
    const response = await chrome.runtime.sendMessage({ type: 'listNotebooks' });
    if (response == null || response.error) {
      if (!silent) renderNotebookSwitcher([]);
      activeNotebookId = storedId || 'default';
      return;
    }
    notebooks = KGPure.normalizeNotebookList(response).filter((nb) => !nb.isDeleted);
    const hasStored = notebooks.some((nb) => nb.id === storedId);
    activeNotebookId = hasStored ? storedId : 'default';
    if (storedId !== activeNotebookId) {
      // Local cursor points at a notebook deleted elsewhere — fall back to default
      // and push it so the backend (and other platforms) drop the dead id too.
      await persistActiveNotebook(activeNotebookId);
    }
    renderNotebookSwitcher(notebooks);
  } catch (err) {
    console.error('[KG] loadNotebookScope failed:', err);
    activeNotebookId = 'default';
    if (!silent) renderNotebookSwitcher([]);
  }
}

function renderNotebookSwitcher(items) {
  if (!notebookSwitcher || !notebookSelect) return;
  notebookSelect.innerHTML = '';
  const list = Array.isArray(items) && items.length
    ? items
    : [{ id: 'default', name: t('notebookDefaultName'), color: null, isDefault: true }];
  for (const nb of list) {
    const opt = document.createElement('option');
    opt.value = nb.id;
    opt.textContent = nb.name || nb.id;
    opt.selected = nb.id === activeNotebookId;
    notebookSelect.appendChild(opt);
  }
  syncNotebookActionButtons();
  notebookSwitcher.hidden = false;
}

function syncNotebookActionButtons() {
  const nb = currentNotebook();
  const canDelete = KGPure.canDeleteNotebook(nb);
  if (notebookEditBtn) notebookEditBtn.disabled = !nb;
  if (notebookDeleteBtn) notebookDeleteBtn.disabled = !canDelete;
}

function currentNotebook() {
  return notebooks.find((nb) => nb.id === activeNotebookId) || null;
}

async function onNotebookChanged() {
  const next = notebookSelect && notebookSelect.value ? notebookSelect.value : 'default';
  if (next === activeNotebookId) return;
  activeNotebookId = next;
  await persistActiveNotebook(activeNotebookId);
  loadVocabList();
}

function openNotebookSheet(mode, options = {}) {
  const nb = currentNotebook();
  notebookSheetMode = mode;
  if (!notebookSheet || !notebookNameInput || !notebookSheetTitle || !notebookSheetSubmit) return;
  clearNotebookSheetError();
  notebookSheetTitle.textContent = mode === 'create'
    ? t('notebookAdd')
    : (options.focusDelete ? t('notebookManage') : t('notebookRename'));
  notebookNameInput.value = mode === 'create' ? '' : ((nb && nb.name) || '');
  notebookDraftColor = KGPure.normalizeNotebookColor(mode === 'create' ? KGPure.NOTEBOOK_DEFAULT_COLOR : nb && nb.color)
    || KGPure.NOTEBOOK_DEFAULT_COLOR;
  notebookDraftPattern = KGPure.normalizeNotebookCoverPattern(mode === 'create' ? null : nb && nb.coverPattern) || null;
  notebookNameInput.placeholder = t('notebookNamePlaceholder');
  notebookSheetSubmit.textContent = mode === 'create' ? t('notebookCreateSubmit') : t('notebookRenameSubmit');
  renderNotebookAppearanceControls();
  const canDelete = mode === 'rename' && KGPure.canDeleteNotebook(nb);
  if (notebookSheetDelete) {
    notebookSheetDelete.hidden = !canDelete;
    notebookSheetDelete.textContent = t('notebookDelete');
  }
  notebookSheet.hidden = false;
  setTimeout(() => {
    if (options.focusDelete && canDelete && notebookSheetDelete) notebookSheetDelete.focus();
    else notebookNameInput.focus();
  }, 0);
}

function closeNotebookSheet() {
  if (notebookSheet) notebookSheet.hidden = true;
  notebookSheetMode = null;
  clearNotebookSheetError();
}

function clearNotebookSheetError() {
  if (!notebookSheetError) return;
  notebookSheetError.textContent = '';
  notebookSheetError.hidden = true;
}

function showNotebookSheetError(message) {
  if (!notebookSheetError) return;
  notebookSheetError.textContent = message;
  notebookSheetError.hidden = false;
}

function renderNotebookAppearanceControls() {
  if (notebookColorSwatches) {
    notebookColorSwatches.innerHTML = KGPure.NOTEBOOK_PALETTE.map((item) => {
      const selected = item.hex === notebookDraftColor;
      return `<button class="kg-notebook-swatch${selected ? ' is-selected' : ''}" type="button" data-color="${esc(item.hex)}" title="${esc(item.name)}" aria-label="${esc(item.name)}" aria-pressed="${selected ? 'true' : 'false'}" style="--swatch:${esc(item.hex)}"></button>`;
    }).join('');
  }
  if (notebookPatternChoices) {
    const options = [{ id: '', label: t('notebookPatternNone') }, ...KGPure.NOTEBOOK_COVER_PATTERNS];
    notebookPatternChoices.innerHTML = options.map((item) => {
      const selected = (item.id || null) === notebookDraftPattern;
      const patternClass = item.id ? ` kg-notebook-pattern--${esc(item.id)}` : '';
      return `<button class="kg-notebook-pattern${patternClass}${selected ? ' is-selected' : ''}" type="button" data-pattern="${esc(item.id)}" aria-pressed="${selected ? 'true' : 'false'}" style="--cover-color:${esc(notebookDraftColor)}"><span class="kg-notebook-pattern__sample"></span><span>${esc(item.label)}</span></button>`;
    }).join('');
  }
  renderNotebookCoverPreview();
}

function renderNotebookCoverPreview() {
  if (!notebookCoverPreview || !notebookCoverPreviewName) return;
  const name = (notebookNameInput && notebookNameInput.value.trim()) || t('notebookPreviewName');
  notebookCoverPreview.style.setProperty('--cover-color', notebookDraftColor || KGPure.NOTEBOOK_DEFAULT_COLOR);
  notebookCoverPreview.dataset.pattern = notebookDraftPattern || '';
  notebookCoverPreviewName.textContent = name;
}

function onNotebookColorClick(event) {
  const btn = event.target.closest('[data-color]');
  if (!btn) return;
  const color = KGPure.normalizeNotebookColor(btn.dataset.color);
  if (!color) return;
  notebookDraftColor = color;
  renderNotebookAppearanceControls();
}

function onNotebookPatternClick(event) {
  const btn = event.target.closest('[data-pattern]');
  if (!btn) return;
  const pattern = KGPure.normalizeNotebookCoverPattern(btn.dataset.pattern || null);
  if (pattern === undefined) return;
  notebookDraftPattern = pattern;
  renderNotebookAppearanceControls();
}

async function submitNotebookForm(event) {
  event.preventDefault();
  if (!notebookSheetMode || !notebookNameInput || !notebookSheetSubmit) return;
  clearNotebookSheetError();
  const payload = notebookSheetMode === 'create'
    ? KGPure.buildNotebookCreatePayload(notebookNameInput.value, notebookDraftColor, notebookDraftPattern)
    : KGPure.buildNotebookUpdatePayload(notebookNameInput.value, notebookDraftColor, notebookDraftPattern);
  if (!payload) {
    showNotebookSheetError(t('notebookNameInvalid'));
    return;
  }
  notebookSheetSubmit.disabled = true;
  try {
    const msg = notebookSheetMode === 'create'
      ? { type: 'createNotebook', notebook: payload }
      : { type: 'updateNotebook', notebookId: activeNotebookId, patch: payload };
    const response = await chrome.runtime.sendMessage(msg);
    if (response == null || response.error) {
      showNotebookSheetError((response && response.message) || t('notebookSaveError'));
      return;
    }
    const nb = KGPure.normalizeNotebookItem(response);
    activeNotebookId = nb.id || activeNotebookId;
    await persistActiveNotebook(activeNotebookId);
    closeNotebookSheet();
    await loadVocabList();
  } catch (err) {
    console.error('[KG] submitNotebookForm failed:', err);
    showNotebookSheetError(t('notebookSaveError'));
  } finally {
    notebookSheetSubmit.disabled = false;
  }
}

async function deleteActiveNotebook() {
  const nb = currentNotebook();
  if (!KGPure.canDeleteNotebook(nb) || !notebookSheetDelete) return;
  clearNotebookSheetError();
  notebookSheetDelete.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: 'deleteNotebook', notebookId: nb.id });
    if (response == null || response.error) {
      showNotebookSheetError((response && response.message) || t('notebookDeleteError'));
      return;
    }
    activeNotebookId = 'default';
    await persistActiveNotebook(activeNotebookId);
    closeNotebookSheet();
    await loadVocabList();
  } catch (err) {
    console.error('[KG] deleteActiveNotebook failed:', err);
    showNotebookSheetError(t('notebookDeleteError'));
  } finally {
    notebookSheetDelete.disabled = false;
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
  // Optimistic pending/failed rows always sit on top of the server corpus.
  renderList([...pendingSyncItems, ...visible]);
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
 * Read the add-outbox and project its unresolved entries (pending/failed) not
 * yet on the server list into optimistic rows (`pendingSyncItems`) for applyView
 * to prepend. Best-effort: a storage read failure just yields no optimistic rows.
 * @param {Array<object>} serverItems — the normalized server list (for dedup)
 */
async function loadPendingSyncItems(serverItems) {
  try {
    const stored = await chrome.storage.local.get(KGOutbox.OUTBOX_KEY);
    const queue = Array.isArray(stored[KGOutbox.OUTBOX_KEY]) ? stored[KGOutbox.OUTBOX_KEY] : [];
    const serverWords = new Set(serverItems.map((i) => i.word));
    pendingSyncItems = KGPure.pendingItemsForNotebook(KGOutbox.pendingOutboxItems(queue, serverWords), activeNotebookId)
      .map(decoratePendingItem);
  } catch (err) {
    console.error('[KG] loadPendingSyncItems failed:', err);
    pendingSyncItems = [];
  }
}

/**
 * Shape an outbox projection into a renderable row: a full normalized item (so
 * createRow never hits undefined fields) plus `syncState` and an i18n trailing
 * label. Deliberately does NOT run enrichWithReviewData — a pending word has no
 * CardResponse review fields and reviewProgress would misclassify it.
 * @param {{word: string, meaning: string, source: object|null, syncState: string}} it
 */
function decoratePendingItem(it) {
  const base = KGPure.normalizeVocabItem({ word: it.word, meaning: it.meaning, source: it.source });
  return {
    ...base,
    syncState: it.syncState,
    dueInfo: it.syncState === 'failed' ? t('syncFailed') : t('syncPending'),
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

  // No match for the active search/filter (corpus is non-empty) — mirror iOS
  // KGVocabEmptyState while keeping list chrome mounted.
  if (items.length === 0) {
    stateContent.appendChild(createEmptyStateElement(currentEmptyState(false), true));
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

  // iOS KGVocabPresenter renders the list with showsReviewState:false, so the
  // review-status word (待複習 / 下次 X / 未學習) is deliberately suppressed in the
  // row top line — it lives only in the detail panel. The right-side progress bar
  // + dueLabel still convey timing, matching the iOS list exactly. (item.dueInfo
  // stays computed for any future showsReviewState:true context.)
  //
  // Optimistic outbox rows are the one exception: their trailing pill is *sync*
  // status (pending / failed), not review status, so it stays. Gate on syncState
  // (truthy only for outbox rows) so plain rows render no trailing label.
  if (item.syncState && item.dueInfo) {
    const trailingEl = document.createElement('span');
    trailingEl.className = 'kg-vocab-row__trailing';
    if (item.syncState === 'failed') trailingEl.classList.add('kg-vocab-row__trailing--sync-failed');
    else if (item.syncState === 'pending') trailingEl.classList.add('kg-vocab-row__trailing--syncing');
    trailingEl.textContent = item.dueInfo;
    topRow.appendChild(trailingEl);

    if (item.syncState === 'failed') {
      const retryBtn = document.createElement('button');
      retryBtn.type = 'button';
      retryBtn.className = 'kg-vocab-row__sync-retry';
      retryBtn.textContent = t('syncRetry');
      retryBtn.addEventListener('click', retryOutboxNow);
      topRow.appendChild(retryBtn);
    }
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

  // Optimistic pending-sync rows aren't real cards yet — no detail to open;
  // mark them (CSS dims) and skip the click handler.
  if (item.syncState) {
    row.classList.add('kg-vocab-row--pending-sync');
  } else {
    // Click handler — open the full-cover detail panel (iOS push navigation).
    row.addEventListener('click', () => openDetail(item));
  }

  return row;
}

async function retryOutboxNow(event) {
  event.preventDefault();
  event.stopPropagation();
  const btn = event.currentTarget;
  if (btn) btn.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: 'retryOutbox' });
    if (!response || response.error) {
      throw new Error((response && response.message) || 'retryOutbox failed');
    }
    await loadVocabList();
  } catch (err) {
    console.error('[KG] retryOutboxNow failed:', err);
    if (btn) btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Word detail panel (full-cover push view; mirrors iOS WordDetailSheet)
// ---------------------------------------------------------------------------

/** Knowledge-link kind order + i18n fallback labels (payload `label` wins). */
const LINK_KIND_ORDER = ['contrasts_with', 'shares_usage'];
const LINK_KIND_LABEL = { contrasts_with: 'linkLabelContrast', shares_usage: 'linkLabelRelated' };

/** Navigation stack of vocab items (knowledge-link drill-down); top = visible. */
const detailStack = [];

/** Lazy zh-Hant short-date formatter for the metadata footer. */
let _detailDateFmt = null;
function formatDetailDate(value) {
  const ms = Date.parse(String(value || ''));
  if (Number.isNaN(ms)) return '';
  if (!_detailDateFmt && typeof Intl !== 'undefined' && Intl.DateTimeFormat) {
    _detailDateFmt = new Intl.DateTimeFormat('zh-Hant', { year: 'numeric', month: 'short', day: 'numeric' });
  }
  return _detailDateFmt ? _detailDateFmt.format(new Date(ms)) : '';
}

/** Open the detail panel for `item`, resetting the navigation stack. */
function openDetail(item) {
  if (!item) return;
  detailStack.length = 0;
  detailStack.push(item);
  renderDetailTop();
  stateDetail.hidden = false;
}

/** Push a linked card onto the stack (knowledge-link navigation). */
function pushDetail(item) {
  if (!item) return;
  detailStack.push(item);
  renderDetailTop();
}

/** Back: pop one level, closing the panel when the stack empties. */
function popDetail() {
  detailStack.pop();
  if (detailStack.length === 0) {
    closeDetail();
  } else {
    renderDetailTop();
  }
}

/** Hide the panel + clear the stack (also called on reload / auth change). */
function closeDetail() {
  detailStack.length = 0;
  stateDetail.hidden = true;
  if (typeof window.speechSynthesis !== 'undefined') window.speechSynthesis.cancel();
}

/** Render the top-of-stack item into the panel. */
function renderDetailTop() {
  const item = detailStack[detailStack.length - 1];
  if (!item) return;
  detailBarWord.textContent = item.word;
  if (detailShare) {
    detailShare.dataset.state = 'idle';
    detailShare.setAttribute('aria-label', t('detailShareAria'));
    detailShare.setAttribute('title', t('detailShareAria'));
    KGIcons.setIcon(detailShare, 'square.and.arrow.up');
  }
  detailBody.innerHTML = buildDetailHTML(item);
  detailBody.scrollTop = 0;
}

async function shareDetailTop() {
  const top = detailStack[detailStack.length - 1];
  if (!top) return;
  const text = KGPure.vocabPlainTextExport(top);
  if (!text) return;

  try {
    if (navigator.share) {
      await navigator.share({ title: top.word, text });
      markDetailShareCopied();
      return;
    }
  } catch (err) {
    if (err && err.name === 'AbortError') return;
  }

  try {
    await navigator.clipboard.writeText(text);
    markDetailShareCopied();
  } catch (err) {
    console.error('[KG] detail copy failed:', err);
    markDetailShareFailed();
  }
}

function markDetailShareCopied() {
  if (!detailShare) return;
  detailShare.dataset.state = 'copied';
  detailShare.setAttribute('aria-label', t('detailCopied'));
  detailShare.setAttribute('title', t('detailCopied'));
  KGIcons.setIcon(detailShare, 'doc.on.doc');
  setTimeout(() => {
    if (!detailShare || detailShare.dataset.state !== 'copied') return;
    detailShare.dataset.state = 'idle';
    detailShare.setAttribute('aria-label', t('detailShareAria'));
    detailShare.setAttribute('title', t('detailShareAria'));
    KGIcons.setIcon(detailShare, 'square.and.arrow.up');
  }, 1600);
}

function markDetailShareFailed() {
  if (!detailShare) return;
  detailShare.dataset.state = 'failed';
  detailShare.setAttribute('aria-label', t('detailCopyFailed'));
  detailShare.setAttribute('title', t('detailCopyFailed'));
  KGIcons.setIcon(detailShare, 'square.and.arrow.up');
  setTimeout(() => {
    if (!detailShare || detailShare.dataset.state !== 'failed') return;
    detailShare.dataset.state = 'idle';
    detailShare.setAttribute('aria-label', t('detailShareAria'));
    detailShare.setAttribute('title', t('detailShareAria'));
    KGIcons.setIcon(detailShare, 'square.and.arrow.up');
  }, 1600);
}

/** Delegated click handler for the detail body (speaker + link navigation). */
function onDetailAction(e) {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  if (action === 'speak') {
    const top = detailStack[detailStack.length - 1];
    if (top) speakWord(top.word);
  } else if (action === 'navlink') {
    const target = vocabData.find((v) => v.cardId && v.cardId === btn.dataset.cardId);
    if (target) pushDetail(target);
  }
}

/** Pronounce `word` via the device Web Speech API (no backend; silent on failure). */
function speakWord(word) {
  if (!word || typeof window.speechSynthesis === 'undefined') return;
  try {
    const synth = window.speechSynthesis;
    synth.cancel();
    const u = new SpeechSynthesisUtterance(String(word));
    u.lang = 'en-US';
    // Pick the most natural voice instead of letting the OS hand back a robotic
    // compact default. getVoices() populates asynchronously, so on the very
    // first call it can be empty — wait once for `voiceschanged`, then speak.
    const speak = () => {
      const picker = globalThis.KGPure && globalThis.KGPure.pickPreferredVoice;
      const v = picker ? picker(synth.getVoices(), 'en-US') : null;
      if (v) {
        u.voice = v;
        u.lang = v.lang;
      }
      synth.speak(u);
    };
    if (synth.getVoices().length) speak();
    else synth.addEventListener('voiceschanged', speak, { once: true });
  } catch (_err) {
    /* TTS unavailable — no-op */
  }
}

/** Section label with a leading SF-Symbols-style icon (mirrors iOS CardSectionLabel,
 *  which always renders a Label{Text}icon:{Image(systemName:)}). */
function detailLabel(iconName, text) {
  return `<div class="kg-detail__label">${KGIcons.svg(iconName)}<span>${esc(text)}</span></div>`;
}

/** Render an example with the target word highlighted (each segment escaped). */
function renderExampleHTML(example, word) {
  const marked = KGPure.markWordInExample(example, word);
  return KGPure.parseInlineMarks(marked)
    .map((seg) => (seg.type === 'mark' ? `<mark class="kg-mark">${esc(seg.value)}</mark>` : esc(seg.value)))
    .join('');
}

/**
 * Build the detail document HTML for `item`, mirroring iOS CardDocumentView flow:
 * hero → example → meaning → 搭配 → 變化形 → 知識連結 → 複習進度 → footer → 來源.
 * Every interpolation is escaped; `KGIcons.svg` returns module-internal markup.
 * @param {object} item — an enriched vocab item
 * @returns {string}
 */
function buildDetailHTML(item) {
  const corpusIds = new Set(vocabData.map((v) => v.cardId).filter(Boolean));
  const parts = [];

  // hero — word + pos + tier (left), speaker (right)
  let hero = '<div class="kg-detail-hero"><div class="kg-detail-hero__head">';
  hero += `<span class="kg-detail-hero__word">${esc(item.word)}</span>`;
  if (item.pos) hero += `<span class="kg-detail-hero__pos">${esc(item.pos)}</span>`;
  if (item.difficultyTier) {
    hero += `<span class="kg-detail-hero__tier" data-tier="${esc(item.difficultyTier)}">${esc(item.difficultyTier)}</span>`;
  }
  hero += '</div>';
  hero += `<button class="kg-detail-hero__speak" type="button" data-action="speak" aria-label="${esc(t('detailSpeak'))}">${KGIcons.svg('speaker')}</button>`;
  hero += '</div>';
  parts.push(hero);

  // example (first, highlighted)
  const ex0 = Array.isArray(item.examples) && item.examples.length ? item.examples[0] : null;
  const example = typeof ex0 === 'string' ? ex0 : (ex0 && (ex0.sentence || ex0.text)) || '';
  if (example) {
    parts.push(`<p class="kg-detail__example">${renderExampleHTML(example, item.word)}</p>`);
  }

  // meaning (翻譯 title) + definition body (note)
  if (item.meaning || item.note) {
    let m = '<div class="kg-detail-meaning">';
    if (item.meaning) m += `<h3 class="kg-detail-meaning__title">${esc(item.meaning)}</h3>`;
    if (item.note) {
      const paras = String(item.note).split(/\n+/).map((s) => s.trim()).filter(Boolean);
      m += `<div class="kg-detail-meaning__body">${paras.map((p) => `<p>${esc(p)}</p>`).join('')}</div>`;
    }
    m += '</div>';
    parts.push(m);
  }

  // collocations (搭配)
  if (Array.isArray(item.collocations) && item.collocations.length) {
    const chips = item.collocations
      .map((c) => `<span class="kg-chip kg-chip--tint">${esc(typeof c === 'string' ? c : (c && c.word) || '')}</span>`)
      .join('');
    parts.push(`<div class="kg-detail-block">${detailLabel('detail-collocation', t('detailCollocation'))}<div class="kg-detail__chips">${chips}</div></div>`);
  }

  // inflections (變化形)
  if (Array.isArray(item.inflections) && item.inflections.length) {
    const forms = item.inflections.map((f) => `<span class="kg-detail-form">${esc(f)}</span>`).join('');
    parts.push(`<div class="kg-detail-block">${detailLabel('detail-forms', t('detailForms'))}<div class="kg-detail-forms">${forms}</div></div>`);
  }

  // knowledge links (對比 / 相關)
  const linksHTML = buildLinksHTML(item, corpusIds);
  if (linksHTML) parts.push(linksHTML);

  // review progress
  const reviewHTML = buildReviewHTML(item);
  if (reviewHTML) parts.push(reviewHTML);

  // metadata footer
  const footerHTML = buildFooterHTML(item);
  if (footerHTML) parts.push(footerHTML);

  // source
  const sourceHTML = buildSourceHTML(item);
  if (sourceHTML) parts.push(sourceHTML);

  return `<div class="kg-detail-doc">${parts.join('')}</div>`;
}

/**
 * Build the knowledge-links section (grouped 對比/相關; hidden links omitted).
 * A link is navigable when its target cardId exists in the loaded corpus.
 */
function buildLinksHTML(item, corpusIds) {
  const lbk = item.linksByKind && typeof item.linksByKind === 'object' ? item.linksByKind : {};
  const orderedKinds = LINK_KIND_ORDER.filter((k) => Array.isArray(lbk[k]) && lbk[k].length);
  const extraKinds = Object.keys(lbk).filter(
    (k) => !LINK_KIND_ORDER.includes(k) && Array.isArray(lbk[k]) && lbk[k].length,
  );
  const groups = [];

  [...orderedKinds, ...extraKinds].forEach((kind) => {
    const links = lbk[kind].filter((l) => l && !l.hidden);
    if (!links.length) return;
    const label = (links[0] && links[0].label) || t(LINK_KIND_LABEL[kind] || '') || kind;
    const rows = links
      .map((l) => {
        const navigable = Boolean(l.cardId && corpusIds.has(l.cardId));
        const tag = navigable ? 'button' : 'div';
        const navAttr = navigable ? ` type="button" data-action="navlink" data-card-id="${esc(l.cardId)}"` : '';
        const cls = 'kg-detail__related-item' + (navigable ? ' kg-detail__related-item--nav' : '');
        const arrow = navigable
          ? `<span class="kg-detail__related-arrow" aria-hidden="true">${KGIcons.svg('arrow-up-right')}</span>`
          : '';
        return `<${tag} class="${cls}"${navAttr}>` +
          `<span class="kg-detail__related-word">${esc(l.word || '')}</span>` +
          `<span class="kg-detail__related-desc">${esc(l.reason || '')}</span>` +
          arrow +
          `</${tag}>`;
      })
      .join('');
    groups.push(`<div class="kg-detail-links__group"><div class="kg-detail-links__group-label">${esc(label)}</div>${rows}</div>`);
  });

  if (!groups.length) return '';
  return `<div class="kg-detail-links">${detailLabel('link', t('detailKnowledgeLinks'))}${groups.join('')}</div>`;
}

/** Build the review-progress section (reuses the row progress-bar markup). */
function buildReviewHTML(item) {
  if (!item.reviewState) return '';
  const status = STATE_LABELS[item.reviewState] || '';
  let bar = '';
  if (item.dueLabel) bar += `<span class="kg-vocab-row__progress-label">${esc(item.dueLabel)}</span>`;
  if (item.reviewRatio != null && item.reviewRatio >= 0) {
    const ratio = Math.min(item.reviewRatio, 1.0);
    const grad = (typeof KGReviewGradient !== 'undefined')
      ? KGReviewGradient.reviewGradientColor(item.reviewRatio)
      : '#4D7396';
    bar += `<div class="kg-vocab-row__progress-track"><div class="kg-vocab-row__progress-fill" style="width:${ratio * 100}%;background-color:${esc(grad)}"></div></div>`;
  }
  return `<div class="kg-detail-review"><span class="kg-detail-review__status">${esc(status)}</span><div class="kg-detail-review__progress">${bar}</div></div>`;
}

/** Build the metadata footer (calendar date + link-count chips). */
function buildFooterHTML(item) {
  const chips = [];
  const dateStr = formatDetailDate(item.updatedAt);
  if (dateStr) {
    chips.push(`<span class="kg-detail__footer-chip">${KGIcons.svg('calendar')}<span>${esc(dateStr)}</span></span>`);
  }
  const lbk = item.linksByKind && typeof item.linksByKind === 'object' ? item.linksByKind : {};
  const linkCount = Object.values(lbk).reduce(
    (n, arr) => n + (Array.isArray(arr) ? arr.filter((l) => l && !l.hidden).length : 0),
    0,
  );
  if (linkCount > 0) {
    chips.push(`<span class="kg-detail__footer-chip">${KGIcons.svg('link')}<span>${esc(t('detailLinkCount', [String(linkCount)]))}</span></span>`);
  }
  if (!chips.length) return '';
  return `<div class="kg-detail__footer"><div class="kg-detail__footer-meta">${chips.join('')}</div></div>`;
}

/** Build the source block (web → safe link; otherwise app / book text). */
function buildSourceHTML(item) {
  const source = item.source;
  if (!source) return '';
  const url = source.url || '';
  const title = source.title || source.book || '';
  let inner;
  if (source.type === 'web' && url) {
    const safe = KGPure.safeUrl(url);
    inner = `<a class="kg-link kg-detail__link" href="${esc(safe)}" target="_blank" rel="noopener">${esc(title || url)}</a>`;
  } else if (title) {
    inner = `<span class="kg-detail__source-text">${esc(title)}</span>`;
  } else {
    inner = `<span class="kg-detail__source-text">${esc(t('detailSourceApp'))}</span>`;
  }
  return `<div class="kg-detail-block">${detailLabel('source-local', t('detailSource'))}${inner}</div>`;
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
