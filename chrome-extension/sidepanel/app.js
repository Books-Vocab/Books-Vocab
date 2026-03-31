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
const retryBtn     = $('#retryBtn');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

/** @type {Array<object>} full vocab list from API */
let vocabData = [];
/** @type {string|null} currently expanded card word */
let expandedWord = null;

const THEME_ICONS = { light: '🌗', dark: '☀️', sepia: '📜' };
const THEME_CYCLE = ['light', 'dark', 'sepia'];

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
  const theme = await initTheme(document.documentElement);
  updateThemeBtn(theme);

  // Listen for theme changes from other contexts
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes[THEME_KEY]) {
      updateThemeBtn(resolveTheme(changes[THEME_KEY].newValue));
    }
  });

  themeBtn.addEventListener('click', cycleTheme);
  retryBtn.addEventListener('click', loadVocabList);
  searchInput.addEventListener('input', debounce(onSearch, 300));

  loadVocabList();
});

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------

function updateThemeBtn(theme) {
  themeBtn.textContent = THEME_ICONS[theme] || THEME_ICONS.light;
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

    if (response && response.error) {
      throw new Error(response.message || '載入失敗');
    }

    // Response is the vocab array (or object with items)
    const items = Array.isArray(response) ? response : (response?.items ?? response?.data ?? []);

    vocabData = items;

    if (items.length === 0) {
      setState('empty');
    } else {
      setState('content');
      renderList(items);
    }
  } catch (err) {
    console.error('[KG] loadVocabList failed:', err);
    setState('error');
  }
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
    const word = (item.word || '').toLowerCase();
    const meaning = (item.meaning || item.translation || '').toLowerCase();
    return word.includes(query) || meaning.includes(query);
  });

  searchCount.textContent = `${filtered.length}`;
  renderList(filtered);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

/**
 * Render the vocab list.
 * @param {Array<object>} items
 */
function renderList(items) {
  stateContent.innerHTML = '';
  expandedWord = null;

  items.forEach((item) => {
    const card = createCard(item);
    stateContent.appendChild(card);
  });

  if (items.length > 0) {
    setState('content');
  }
}

/**
 * Create a vocab card element.
 * @param {object} item
 * @returns {HTMLElement}
 */
function createCard(item) {
  const card = document.createElement('div');
  card.className = 'kg-list-card';
  card.dataset.word = item.word || '';

  const meaning = item.meaning || item.translation || '';
  const pos = item.pos || '';
  const isWeb = !!(item.source_url || item.source_title);
  const sourceIcon = isWeb ? '🌐' : '📖';

  // Top row: word + pos + source
  const row = document.createElement('div');
  row.className = 'kg-list-card__row';

  const wordEl = document.createElement('span');
  wordEl.className = 'kg-list-card__word';
  wordEl.textContent = item.word || '';
  row.appendChild(wordEl);

  if (pos) {
    const posEl = document.createElement('span');
    posEl.className = 'kg-list-card__pos';
    posEl.textContent = pos;
    row.appendChild(posEl);
  }

  const srcEl = document.createElement('span');
  srcEl.className = 'kg-list-card__source';
  srcEl.textContent = sourceIcon;
  row.appendChild(srcEl);

  card.appendChild(row);

  // Meaning row
  if (meaning) {
    const meaningEl = document.createElement('div');
    meaningEl.className = 'kg-list-card__meaning';
    meaningEl.textContent = meaning;
    card.appendChild(meaningEl);
  }

  // Click handler
  card.addEventListener('click', () => toggleDetail(card, item));

  return card;
}

/**
 * Toggle detail view for a card.
 * @param {HTMLElement} card
 * @param {object} item
 */
function toggleDetail(card, item) {
  const existing = card.querySelector('.kg-detail');

  if (existing) {
    existing.remove();
    expandedWord = null;
    return;
  }

  // Collapse any other expanded card
  const prev = stateContent.querySelector('.kg-detail');
  if (prev) prev.remove();

  expandedWord = item.word;

  const detail = document.createElement('div');
  detail.className = 'kg-detail';

  const meaning = item.meaning || item.translation || '';
  const pos = item.pos || '';
  const examples = item.examples || [];
  const collocations = item.collocations || [];
  const note = item.note || '';
  const context = item.context_sentence || item.context || '';
  const sourceUrl = item.source_url || '';
  const sourceTitle = item.source_title || '';
  const isWeb = !!(sourceUrl || sourceTitle);

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
    const chips = collocations.map((c) => `<span class="kg-detail__chip">${esc(typeof c === 'string' ? c : c.word || '')}</span>`).join('');
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
    detail.appendChild(makeSection('來源', `<a class="kg-detail__link" href="${esc(sourceUrl)}" target="_blank" rel="noopener">${esc(sourceTitle || sourceUrl)}</a>`));
  } else {
    detail.appendChild(makeSection('來源', `<span class="kg-detail__source-text">iOS app</span>`));
  }

  card.appendChild(detail);
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
 * Escape HTML to prevent XSS.
 * @param {string} str
 * @returns {string}
 */
function esc(str) {
  const el = document.createElement('span');
  el.textContent = str;
  return el.innerHTML;
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
