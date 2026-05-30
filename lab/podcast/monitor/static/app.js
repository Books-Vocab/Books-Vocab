// Podcast Pipeline Monitor — live dashboard
// Streams pipeline_log.jsonl + events.jsonl via SSE; pulls cost summary from
// /api/workspace/<n>/cost (claude CLI's costUSD + Vertex TTS calc).

// Build stamp — visible in the nav so we can tell at-a-glance whether the
// browser is serving fresh JS or a stale cache. Bumped per noteworthy change.
const APP_VERSION = "2026-05-31b";

// Sidebar UI state (filter / sort / drawer). Persisted to localStorage so a
// reload remembers what the user was looking at.
const SIDEBAR_LS_KEY = "podcast-monitor:sidebar";
const SIDEBAR_STATUS_VALUES = new Set(["all", "running", "failed", "idle", "done", "fresh"]);
const SIDEBAR_SORT_VALUES = new Set(["recent", "name"]);
const sidebarUI = (() => {
  // Defaults are the authoritative shape; any stored value not matching the
  // current enum (e.g. after a release renames "warning" → "failed") gets
  // dropped silently rather than wedging the filter to show zero cards.
  const defaults = { query: "", status: "all", sort: "recent", collapsed: [] };
  try {
    const stored = JSON.parse(localStorage.getItem(SIDEBAR_LS_KEY) || "{}");
    return {
      query: typeof stored.query === "string" ? stored.query : defaults.query,
      status: SIDEBAR_STATUS_VALUES.has(stored.status) ? stored.status : defaults.status,
      sort: SIDEBAR_SORT_VALUES.has(stored.sort) ? stored.sort : defaults.sort,
      // Collapsed date-group keys (YYYY-MM-DD strings). Filtered to strings so
      // a corrupted store can't inject objects into the collapse Set.
      collapsed: Array.isArray(stored.collapsed)
        ? stored.collapsed.filter(k => typeof k === "string")
        : defaults.collapsed,
    };
  } catch { return { ...defaults }; }
})();
function persistSidebarUI() {
  try { localStorage.setItem(SIDEBAR_LS_KEY, JSON.stringify(sidebarUI)); }
  catch { /* private mode etc. — silently skip */ }
}
console.info(`[monitor] app.js loaded · version ${APP_VERSION}`);

// Surface any uncaught JS error to the toast stack so the user sees it
// instead of having to open DevTools to discover the dashboard is broken.
window.addEventListener("error", (e) => {
  console.error("[monitor] uncaught:", e.error || e.message);
  try { document.querySelector("#toasts") &&
        document.dispatchEvent(new CustomEvent("monitor-error", { detail: String(e.message) })); }
  catch {}
});

const STAGES = [
  "prep", "analyst", "architect", "plan-review",
  "enricher-gap", "enricher", "scriptwrite",
  "series-polish", "script-review",
  "tts-prep", "synthesize", "audio-qa", "subtitle",
];

const OPUS_CTX_MAX = 1_000_000;
const COST_REFRESH_MS = 4000;
const JOBS_REFRESH_MS = 3000;
const REMOTE_REFRESH_MS = 30000;  // SSH each tick — gentle cadence
const REMOTE_LOW_FREE_BYTES = 500 * 1024 * 1024;  // warn at <500MB free

const state = {
  ws: null,
  stages: {},          // stage -> { status, elapsed_s, started_ts }
  parallelEps: {       // per-stage per-episode runner status
    scriptwrite: {},
    "script-review": {},
    synthesize: {},
  },
  tokensTotal: { fresh: 0, out: 0, cacheRead: 0, cacheCreate: 0 },
  lastCtx: 0,
  peakCtx: 0,
  currentStage: null,
  pipelineStartTs: null,
  pipelineEndTs: null,
  feed: [],
  maxFeed: 200,
  eventSource: null,
  costTimer: null,
  jobsTimer: null,
  jobsInflight: false,
  recentJobs: [],
  remoteTimer: null,
  remoteInflight: false,
  remote: { series: [], disk: null },
};

// Map an agent stage_label from events.jsonl to its pipeline stage + episode.
function parseLabel(label) {
  if (!label) return { stage: null, ep: null };
  let m = label.match(/^Scriptwriter EP(\d+)$/i);
  if (m) return { stage: "scriptwrite", ep: Number(m[1]) };
  m = label.match(/^Script Review EP(\d+)$/i);
  if (m) return { stage: "script-review", ep: Number(m[1]) };
  m = label.match(/^Synthesize EP(\d+)$/i);
  if (m) return { stage: "synthesize", ep: Number(m[1]) };
  return { stage: null, ep: null };
}

const $ = (sel) => document.querySelector(sel);

function fmtNum(n) {
  if (n == null || Number.isNaN(n)) return "0";
  return new Intl.NumberFormat().format(Math.round(n));
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(n)) return "$0.00";
  if (n < 0.01) return "<$0.01";
  return "$" + n.toFixed(2);
}

function fmtDuration(ms) {
  if (!ms || ms < 0 || Number.isNaN(ms)) return "—";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toTimeString().slice(0, 8);
  } catch { return iso.slice(11, 19); }
}

function fmtAudioSecs(s) {
  if (!s) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  if (m) return `${m}m${sec.toString().padStart(2, "0")}s`;
  return `${Math.round(s)}s`;
}

// ─── Workspace list ───
//
// Two callers: explicit (initial load + manual ↻ click) and a quiet 8s poll.
// The poll path MUST preserve the user's current selection — clobbering it
// every 8s would force a re-subscribe to SSE and re-fetch cost / episodes,
// which both breaks the inline player and looks like the dashboard "resets".
const WORKSPACES_POLL_MS = 8000;

async function loadWorkspaces({ quiet = false } = {}) {
  // P1 endpoint returns rich summaries; bare fallback would return strings.
  // Always request full=1; if the server is somehow stale, normalize below.
  let summaries;
  try {
    const r = await fetch("/api/workspaces?full=1");
    if (!r.ok) return;
    summaries = await r.json();
  } catch { return; }

  // Defensive: tolerate legacy string-list shape (server pre-P1).
  if (summaries.length && typeof summaries[0] === "string") {
    summaries = summaries.map(name => ({
      name, status: "idle", n_stages_done: 0, n_stages_total: 13,
      episode_count: 0, last_updated: 0,
      total_usd: 0, claude_usd: 0, tts_usd: 0,
      has_cost_data: false, active_job: null,
    }));
  }

  const list = summaries.map(s => s.name);
  state.workspaceSummaries = summaries;
  const prevList = state.workspaceList || [];

  // Decide which workspace to select: priority order is
  //   1. whatever's already active (state.ws set by a prior switch)
  //   2. ?ws= URL param (deep link / page reload)
  //   3. first workspace in the (newly sorted) list
  // Resolved here so renderSidebar can highlight + switchWorkspace can fire.
  let selection = state.ws;
  if (!selection || !list.includes(selection)) {
    const wsFromUrl = new URLSearchParams(location.search).get("ws");
    selection = (wsFromUrl && list.includes(wsFromUrl)) ? wsFromUrl : list[0];
  }

  // Detect newly-appeared workspaces. Skip toasting on the very first load
  // (prevList is empty) — that's just "what was already there".
  const fresh = list.filter(n => !prevList.includes(n));
  state.workspaceList = list;

  // Render sidebar with the decided active selection so the highlight matches.
  renderSidebar(summaries, selection);

  if (!quiet || prevList.length === 0) {
    // Explicit load: switch to the (preserved or first) selection so the
    // dashboard fills with data.
    if (list.length && !state.ws) switchWorkspace(selection);
  } else {
    // Quiet poll: workspace appeared while user wasn't watching. Toast it.
    // If user has nothing selected yet, auto-switch to the newest.
    for (const n of fresh) toast(`new workspace: ${n}`, "info", 6000);
    if (fresh.length && !state.ws) {
      switchWorkspace(fresh[fresh.length - 1]);
    }
  }
}

// ─── Sidebar render ──────────────────────────────────────────────────────────
//
// Sorts by last_updated desc (most recently active floats to top), with status
// priority as the tiebreak so a running workspace beats an older idle one.
// Re-render is cheap (innerHTML rebuild) — sidebar's typical N is < 20.
// Bucket a `created` epoch into a date group. Returns {key, label} where key
// is a stable YYYY-MM-DD (used for collapse persistence + bucket ordering) and
// label is the human header — relative for recent days (Today / Yesterday /
// N days ago), absolute thereafter. Workspaces with no created date fall into
// a trailing "No date" bucket.
function dateBucket(epoch) {
  if (!epoch) return { key: "0000-unknown", label: "No date" };
  const d = new Date(epoch * 1000);
  const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const startOfDay = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000);
  let label;
  if (diffDays <= 0) label = "Today";
  else if (diffDays === 1) label = "Yesterday";
  else if (diffDays < 7) label = `${diffDays} days ago`;
  else label = d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  return { key, label };
}

// Group the (already within-group sorted) summaries by added-date into
// collapsible sections, newest bucket first. The "No date" bucket sorts last.
function groupedSidebarHtml(sorted, activeName) {
  const buckets = new Map();
  for (const s of sorted) {
    const b = dateBucket(s.created);
    if (!buckets.has(b.key)) buckets.set(b.key, { label: b.label, items: [] });
    buckets.get(b.key).items.push(s);
  }
  const orderedKeys = [...buckets.keys()].sort((a, b) => (a < b ? 1 : a > b ? -1 : 0)); // desc; "0000-unknown" trails
  const collapsed = new Set(sidebarUI.collapsed);
  return orderedKeys.map(key => {
    const { label, items } = buckets.get(key);
    const isCollapsed = collapsed.has(key);
    const cards = items.map(s => sidebarCardHtml(s, s.name === activeName)).join("");
    return `
<div class="ws-group${isCollapsed ? " is-collapsed" : ""}">
  <button type="button" class="ws-group-head" data-bucket="${escapeAttr(key)}" aria-expanded="${isCollapsed ? "false" : "true"}">
    <span class="ws-group-chevron" aria-hidden="true"></span>
    <span class="ws-group-label">${escapeHtml(label)}</span>
    <span class="ws-group-count">${items.length}</span>
  </button>
  <div class="ws-group-body"${isCollapsed ? " hidden" : ""}>${cards}</div>
</div>`;
  }).join("");
}

function renderSidebar(summaries, activeName) {
  const list = $("#sidebar-list");
  const countEl = $("#sidebar-count");
  if (!list) return;

  // Apply filter (search + status). Counts shown reflect the TOTAL workspace
  // count, not the filtered visible count, so users can tell when filter hides
  // things ("2 of 6" semantics handled below by chip badges).
  const q = sidebarUI.query.trim().toLowerCase();
  const filtered = summaries.filter(s => {
    if (sidebarUI.status !== "all" && s.status !== sidebarUI.status) return false;
    if (q && !s.name.toLowerCase().includes(q)) return false;
    return true;
  });

  // Update count badge — "filtered/total" if a filter narrows the list.
  countEl.textContent = (filtered.length === summaries.length)
    ? summaries.length.toString()
    : `${filtered.length}/${summaries.length}`;

  // Update chip status counts so the user sees "RUN 1 · FAIL 0" at a glance.
  // Cheap: one pass over summaries (typically < 20).
  const counts = { all: summaries.length, running: 0, failed: 0, idle: 0, done: 0, fresh: 0 };
  for (const s of summaries) {
    counts[s.status] = (counts[s.status] ?? 0) + 1;
  }
  for (const chip of document.querySelectorAll(".sidebar-chip")) {
    const k = chip.dataset.status;
    const n = counts[k] ?? 0;
    // Label authored in HTML (data-label) so it survives an initial render
    // before any user interaction.  Count gets its own span so CSS can dim
    // it without dimming the label.
    const label = chip.dataset.label || chip.textContent.trim();
    chip.innerHTML = `${escapeHtml(label)}<span class="sidebar-chip-count">${n}</span>`;
    chip.classList.toggle("is-active", k === sidebarUI.status);
    chip.setAttribute("aria-pressed", k === sidebarUI.status ? "true" : "false");
  }

  if (!filtered.length) {
    list.innerHTML = summaries.length === 0
      ? `<div class="sidebar-empty">no workspaces yet — pick "+ NEW PODCAST"</div>`
      : `<div class="sidebar-empty">no match — clear filter to see all ${summaries.length}</div>`;
    return;
  }

  const statusOrder = { running: 0, failed: 1, idle: 2, done: 3, fresh: 4 };
  const sorted = filtered.slice().sort((a, b) => {
    if (sidebarUI.sort === "name") {
      return a.name.localeCompare(b.name);
    }
    // recent (default): newest first; status priority breaks ties so a
    // running ws beats an older idle one with the same epoch.
    if (b.last_updated !== a.last_updated) return b.last_updated - a.last_updated;
    return (statusOrder[a.status] ?? 99) - (statusOrder[b.status] ?? 99);
  });

  // Preserve scroll position across re-render (poll every 8s would otherwise
  // snap a scrolled user to top mid-skim).
  const prevScroll = list.scrollTop;
  list.innerHTML = groupedSidebarHtml(sorted, activeName);
  list.scrollTop = prevScroll;

  // Reflect sort mode on the sort button (icon class + aria + title).
  // The button's text node is empty in HTML; ::before paints the active
  // glyph (clock for recent, "A→Z" for name) so we never see both at once.
  const sortBtn = $("#sidebar-sort");
  if (sortBtn) {
    sortBtn.classList.toggle("by-recent", sidebarUI.sort === "recent");
    sortBtn.classList.toggle("by-name", sidebarUI.sort === "name");
    sortBtn.setAttribute("aria-pressed", sidebarUI.sort === "name" ? "true" : "false");
    sortBtn.title = sidebarUI.sort === "recent"
      ? "Sort: recent activity (click for A→Z)"
      : "Sort: A→Z (click for recent)";
  }

  // Single delegated click handler — replaced every render, no leak.
  list.onclick = (ev) => {
    // Group header → toggle collapse. Mutate the DOM in place (don't
    // re-render) so scroll + other groups stay put; persist the key set.
    const head = ev.target.closest(".ws-group-head");
    if (head) {
      const key = head.dataset.bucket;
      const set = new Set(sidebarUI.collapsed);
      const nowCollapsed = !set.has(key);
      if (nowCollapsed) set.add(key); else set.delete(key);
      sidebarUI.collapsed = [...set];
      persistSidebarUI();
      head.setAttribute("aria-expanded", nowCollapsed ? "false" : "true");
      head.parentElement.classList.toggle("is-collapsed", nowCollapsed);
      const body = head.nextElementSibling;
      if (body) body.hidden = nowCollapsed;
      return;
    }
    const card = ev.target.closest(".ws-card");
    if (!card) return;
    const name = card.dataset.ws;
    if (!name || name === state.ws) return;
    switchWorkspace(name);
    for (const el of list.querySelectorAll(".ws-card")) {
      el.classList.toggle("is-active", el.dataset.ws === name);
    }
    // On narrow viewports the sidebar is a drawer — close it after picking.
    if (document.body.classList.contains("sidebar-open")) {
      closeSidebarDrawer();
    }
  };
}

// ─── Drawer (mobile) toggle ──────────────────────────────────────────────────
function openSidebarDrawer() {
  document.body.classList.add("sidebar-open");
  const btn = $("#sidebar-toggle");
  if (btn) btn.setAttribute("aria-expanded", "true");
}
function closeSidebarDrawer() {
  document.body.classList.remove("sidebar-open");
  const btn = $("#sidebar-toggle");
  if (btn) btn.setAttribute("aria-expanded", "false");
}
function toggleSidebarDrawer() {
  if (document.body.classList.contains("sidebar-open")) closeSidebarDrawer();
  else openSidebarDrawer();
}

// The four production gates, in pipeline order, with the short labels shown
// in the sidebar. Whitelisting the keys here (rather than trusting whatever
// the server sends) keeps the segment CSS class injection-safe.
const MILESTONE_SHORT = { plan: "PLAN", script: "SCRIPT", audio: "AUDIO", subtitle: "SUB" };

// Build the four-segment depth-shaded progress bar from server-derived
// milestones. Each gate owns a fixed 1/4 slot; the inner fill width is the
// gate's completion ratio, coloured by depth (plan darkest → subtitle
// lightest). The label names the *frontier* — the first gate that isn't yet
// full — so the producer sees at a glance which stage a workspace is stuck on
// ("AUDIO 0/10"), or "READY" when all four gates are complete.
function milestoneBar(s) {
  const ms = Array.isArray(s.milestones) ? s.milestones : null;
  if (!ms || !ms.length) {
    // Back-compat: a cached/placeholder summary without milestones falls
    // back to the legacy single-bar marker ratio.
    const pct = s.n_stages_total ? Math.round((s.n_stages_done / s.n_stages_total) * 100) : 0;
    return {
      segs: `<div class="ws-mseg ws-mseg-legacy"><i style="width:${pct}%"></i></div>`,
      label: `${s.n_stages_done || 0}/${s.n_stages_total || 13}`,
    };
  }
  // Four visually-separated bars, one per gate, each filled by its OWN ratio.
  // The gates sit in fixed pipeline order (PLAN→SCRIPT→AUDIO→SUBTITLE), so
  // position + the label identify the stage; colour is a single blue (no
  // depth ramp). Showing each gate's real ratio is the most informative —
  // the_let_them reads "audio 5/8 AND subtitle 3/8" at a glance, instead of
  // a cumulative fill that would hide the subtitle progress. Because the bars
  // are clearly separated (gap + own rounding), a partial-then-partial
  // sequence reads as two independent bars, not a broken-looking gap.
  const segs = ms.map(m => {
    const key = MILESTONE_SHORT[m.key] ? m.key : "legacy"; // whitelist for class safety
    const w = Math.max(0, Math.min(100, Math.round((m.ratio || 0) * 100)));
    return `<div class="ws-mseg ws-mseg-${key}"><i style="width:${w}%"></i></div>`;
  }).join("");
  const frontier = ms.find(m => (m.ratio || 0) < 1);
  const label = frontier
    ? `${MILESTONE_SHORT[frontier.key] || frontier.key.toUpperCase()} ${frontier.done}/${frontier.total}`
    : "READY";
  return { segs, label };
}

function sidebarCardHtml(s, isActive) {
  const cost = s.total_usd >= 0.01 ? `$${s.total_usd.toFixed(2)}` : "<$0.01";
  const costClass = s.total_usd >= 0.01 ? "ws-cost" : "ws-cost zero";
  const ep = s.episode_count ? `${s.episode_count} ep` : "—";
  const time = relativeTime(s.last_updated);
  const { segs, label } = milestoneBar(s);
  // Status text override for clarity (active job kind tells you more than "running")
  const statusText = s.status === "running" && s.active_job
    ? (s.active_job.kind || "running")
    : s.status;

  // The <button> element carries its own implicit "button" role; we DON'T
  // double-up with role="listitem" because that would override the more
  // useful "button" announcement screen readers give by default.
  const absTime = s.last_updated > 0
    ? escapeAttr(new Date(s.last_updated * 1000).toLocaleString())
    : "never updated";
  return `
<button class="ws-card ws-card-${s.status}${isActive ? " is-active" : ""}"
        data-ws="${escapeAttr(s.name)}"
        title="${escapeAttr(s.name)}">
  <div class="ws-card-head">
    <span class="ws-status-dot ws-status-${s.status}"></span>
    <span class="ws-name">${escapeHtml(s.name)}</span>
    <span class="ws-time" title="${absTime}">${time}</span>
  </div>
  <div class="ws-card-bar">
    <div class="ws-mstrip">${segs}</div>
    <span class="ws-card-progress">${escapeHtml(label)}</span>
  </div>
  <div class="ws-card-meta">
    <span class="${costClass}">${cost}</span>
    <span class="ws-sep">·</span>
    <span class="ws-eps">${ep}</span>
    <span class="ws-sep">·</span>
    <span class="ws-status-text">${escapeHtml(statusText)}</span>
  </div>
</button>`;
}

function relativeTime(epochSeconds) {
  if (!epochSeconds) return "—";
  const diff = Date.now() / 1000 - epochSeconds;
  if (diff < 0) return "now";
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)}d`;
  return `${Math.floor(diff / (86400 * 30))}mo`;
}

// escapeHtml lives further down (line ~1201). Use the same one for sidebar
// markup — function hoisting makes it available here. escapeAttr is a thin
// alias used in attribute contexts; same escapes serve both.
function escapeAttr(s) { return escapeHtml(s); }

function resetState() {
  state.stages = {};
  state.parallelEps = { scriptwrite: {}, "script-review": {}, synthesize: {} };
  state.tokensTotal = { fresh: 0, out: 0, cacheRead: 0, cacheCreate: 0 };
  state.lastCtx = 0;
  state.peakCtx = 0;
  state.currentStage = null;
  state.pipelineStartTs = null;
  state.pipelineEndTs = null;
  state.feed = [];
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
  if (state.costTimer) { clearInterval(state.costTimer); state.costTimer = null; }
  if (state.jobsTimer) { clearInterval(state.jobsTimer); state.jobsTimer = null; }
  // remoteTimer is NOT cleared here — it's workspace-independent (shows
  // server-wide state), started once at DOMContentLoaded.
}

async function switchWorkspace(ws) {
  resetState();
  state.ws = ws;
  const url = new URL(location.href);
  url.searchParams.set("ws", ws);
  history.replaceState(null, "", url);

  // Update the nav "CURRENT" display (replaced the old <select> in P4).
  const cur = $("#nav-current-ws");
  if (cur) {
    cur.textContent = ws || "—";
    cur.title = ws || "—";
    cur.classList.toggle("empty", !ws);
  }

  // Mirror into the THIS PODCAST scope-band so the workspace zone is self-labelling.
  const band = $("#scope-ws-name");
  if (band) {
    band.textContent = ws || "—";
    band.title = ws || "—";
    band.classList.toggle("empty", !ws);
  }

  // Re-render sidebar so any path (URL ?ws=, direct click, programmatic
  // call) ends with the correct card highlighted — without waiting for the
  // 8s poll.
  if (state.workspaceSummaries) renderSidebar(state.workspaceSummaries, ws);

  renderAll();
  renderCost({ total_usd: 0, by_stage: {}, by_model: {}, warnings: [] });
  if (state.player) state.player.load(ws);

  const r = await fetch(`/api/workspace/${ws}/snapshot`);
  const snap = await r.json();
  for (const e of (snap.events || [])) {
    if (e.kind === "pipeline") handlePipelineEvent(e.data);
    else handleStreamEvent(e.data);
  }
  renderAll();
  await refreshCost();

  // Live updates
  const es = new EventSource(`/api/workspace/${ws}/stream`);
  state.eventSource = es;
  es.addEventListener("pipeline", (ev) => {
    handlePipelineEvent(JSON.parse(ev.data));
    renderAll();
  });
  es.addEventListener("stream", (ev) => {
    handleStreamEvent(JSON.parse(ev.data));
    renderAll();
  });

  // Cost polled (events.jsonl is tailed but we recompute server-side for accuracy)
  state.costTimer = setInterval(refreshCost, COST_REFRESH_MS);
  // Jobs panel polls separately — independent cadence so a slow cost call
  // doesn't make recent-jobs status look stale.
  state.jobsTimer = setInterval(refreshJobs, JOBS_REFRESH_MS);
  refreshJobs();
}

async function refreshCost() {
  if (!state.ws) return;
  try {
    const r = await fetch(`/api/workspace/${state.ws}/cost`);
    if (!r.ok) return;
    renderCost(await r.json());
  } catch { /* network blip; next tick */ }
}

// ─── pipeline_log.jsonl events ───
function handlePipelineEvent(obj) {
  const ev = obj.event;
  const ts = obj.ts;
  const stage = obj.stage || "";

  if (ev === "stage_start") {
    state.stages[stage] = { status: "running", started_ts: ts };
    state.currentStage = stage;
    if (!state.pipelineStartTs) state.pipelineStartTs = ts;
    pushFeed(ts, stage, { kind: "stage_start", msg: `stage started` });
  } else if (ev === "stage_end") {
    const s = state.stages[stage] || {};
    s.status = obj.success ? "done" : "failed";
    s.elapsed_s = obj.elapsed_s;
    state.stages[stage] = s;
    if (state.currentStage === stage) state.currentStage = null;
    state.pipelineEndTs = ts;
    pushFeed(ts, stage, {
      kind: obj.success ? "stage_done" : "stage_fail",
      msg: `stage ${obj.success ? "OK" : "FAILED"} in ${obj.elapsed_s}s`,
    });
  } else if (ev === "error") {
    pushFeed(ts, stage || (state.currentStage || ""), { kind: "error", msg: obj.msg });
  } else if (ev === "info" && obj.msg) {
    if (obj.msg === "claude invocation") {
      pushFeed(ts, stage || (state.currentStage || ""), {
        kind: "info", msg: `claude invoked · timeout ${obj.timeout_s}s`,
      });
    } else {
      pushFeed(ts, stage || (state.currentStage || ""), { kind: "info", msg: obj.msg });
    }
  }
}

// ─── events.jsonl (stream-json) events ───
function handleStreamEvent(obj) {
  const ts = obj.ts;
  const stageLabel = obj.stage_label || "";
  const ev = obj.event || {};
  const type = ev.type;
  const { stage: pStage, ep } = parseLabel(stageLabel);

  if (type === "system") {
    if (ev.subtype === "init") {
      if (pStage && ep != null) {
        state.parallelEps[pStage] ||= {};
        state.parallelEps[pStage][ep] = "running";
      }
      pushFeed(ts, stageLabel, { kind: "sys", msg: `agent started (cwd=${ev.cwd || "?"})` });
    }
    return;
  }

  if (type === "assistant") {
    const msg = ev.message || {};
    const content = msg.content || [];
    const usage = msg.usage || {};
    if (usage.input_tokens !== undefined) {
      const freshIn = usage.input_tokens || 0;
      const cacheRead = usage.cache_read_input_tokens || 0;
      const cacheCreate = usage.cache_creation_input_tokens || 0;
      const ctx = freshIn + cacheRead + cacheCreate;
      state.lastCtx = ctx;
      if (ctx > state.peakCtx) state.peakCtx = ctx;
      state.tokensTotal.fresh += freshIn;
      state.tokensTotal.cacheRead += cacheRead;
      state.tokensTotal.cacheCreate += cacheCreate;
      state.tokensTotal.out += usage.output_tokens || 0;
    }
    for (const part of content) {
      if (part.type === "tool_use") {
        pushFeed(ts, stageLabel, {
          kind: "tool",
          tool: part.name,
          input: part.input || {},
        });
      } else if (part.type === "text" && part.text) {
        const first = (part.text || "").trim().split("\n")[0].slice(0, 280);
        if (first) {
          pushFeed(ts, stageLabel, { kind: "text", msg: first });
        }
      }
    }
    return;
  }

  if (type === "tts_usage") {
    // Synthesize batch finished — mark parallel EP tile.
    if (pStage && ep != null) {
      state.parallelEps[pStage] ||= {};
      // Don't downgrade from "done"; record progress via running until pipeline_log says stage_end.
      if (state.parallelEps[pStage][ep] !== "done") {
        state.parallelEps[pStage][ep] = "running";
      }
    }
    pushFeed(ts, stageLabel, {
      kind: "tts",
      msg: `batch ${ev.batch_index}/${ev.batch_total} · ${ev.words}w → ${ev.audio_seconds}s audio · ${ev.elapsed_s}s${ev.usage_source === "estimated" ? " (est)" : ""}`,
    });
    return;
  }

  if (type === "result") {
    const dur = (ev.duration_ms || 0) / 1000;
    const turns = ev.num_turns;
    const isErr = !!ev.is_error;
    const cost = ev.total_cost_usd;
    if (pStage && ep != null) {
      state.parallelEps[pStage] ||= {};
      state.parallelEps[pStage][ep] = isErr ? "failed" : "done";
    }
    pushFeed(ts, stageLabel, {
      kind: isErr ? "stage_fail" : "result",
      msg: `${isErr ? "FAILED" : "done"} · ${dur.toFixed(0)}s · ${turns} turns${cost ? " · " + fmtUsd(cost) : ""}`,
    });
    return;
  }
}

function pushFeed(ts, stage, entry) {
  state.feed.unshift({ ts, stage, ...entry });
  if (state.feed.length > state.maxFeed) state.feed.length = state.maxFeed;
}

// ─── Toast (transient notifications) ───
function toast(msg, kind = "info", ttlMs = 4500) {
  const stack = $("#toasts");
  if (!stack) return;
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.textContent = msg;
  stack.appendChild(el);
  // Fade-out animation handled by CSS; remove from DOM after.
  setTimeout(() => el.classList.add("toast-leaving"), Math.max(ttlMs - 400, 0));
  setTimeout(() => el.remove(), ttlMs);
}

// ─── Remote (Lightsail) series panel (Phase 5) ───
function fmtBytes(n) {
  if (!n || !Number.isFinite(n)) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  // Server returns full ISO with offset; show YYYY-MM-DD in local zone.
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch { return iso.slice(0, 10); }
}

async function refreshRemote() {
  // Two parallel SSH probes: df+du for the disk gauge, ls + index.json for
  // the series list. Both share the same SSH key + host, but separate HTTP
  // calls give us partial-failure tolerance — if disk fails we still show
  // series and vice versa.
  if (state.remoteInflight) return;
  state.remoteInflight = true;
  try {
    const [diskR, seriesR] = await Promise.allSettled([
      fetch("/api/remote/disk"),
      fetch("/api/remote/series"),
    ]);
    if (diskR.status === "fulfilled" && diskR.value.ok) {
      state.remote.disk = await diskR.value.json();
    } else {
      state.remote.disk = null;
    }
    if (seriesR.status === "fulfilled" && seriesR.value.ok) {
      state.remote.series = await seriesR.value.json();
    } else {
      state.remote.series = [];
    }
    renderRemote();
  } catch { /* network blip */ }
  finally { state.remoteInflight = false; }
}

function renderRemote() {
  const diskEl = $("#remote-disk");
  const barEl = $("#disk-bar-fill");
  const listEl = $("#remote-series");
  if (!listEl) return;

  // ─── Disk gauge ───
  if (state.remote.disk) {
    const d = state.remote.disk;
    const pct = d.total_bytes ? (d.used_bytes / d.total_bytes) * 100 : 0;
    const lowFree = d.avail_bytes < REMOTE_LOW_FREE_BYTES;
    diskEl.innerHTML = `
      ${fmtBytes(d.used_bytes)} used · ${fmtBytes(d.avail_bytes)} free
      <span class="disk-podcasts">· podcasts ${fmtBytes(d.podcast_bytes)}</span>
      ${lowFree ? `<span class="disk-warn">⚠ LOW FREE</span>` : ""}
    `;
    barEl.style.width = Math.min(100, pct).toFixed(1) + "%";
    barEl.classList.toggle("warn", lowFree || pct > 85);
  } else {
    diskEl.textContent = "ssh probe failed";
    barEl.style.width = "0%";
  }

  // ─── Series rows ───
  if (!state.remote.series.length) {
    listEl.innerHTML = `<div class="empty">nothing published</div>`;
    return;
  }
  listEl.innerHTML = state.remote.series.map(s => {
    const id = s.id || "(unknown)";
    const title = s.title || id;
    const meta = s.orphan
      ? `<span class="orphan-flag">ORPHAN · not in index</span>`
      : `${s.episodeCount ?? "?"} ep · created ${fmtDate(s.createdAt)}`;
    return `
      <div class="series-row">
        <div class="series-main">
          <span class="series-title">${escapeHtml(title)}</span>
          <span class="series-id tabular">${escapeHtml(id)}</span>
          <span class="series-meta">${meta} · ${fmtBytes(s.sizeBytes)}</span>
        </div>
        <button class="job-action danger" data-action="unpublish" data-series="${escapeHtml(id)}">UNPUBLISH</button>
      </div>
    `;
  }).join("");
}

async function actionUnpublish(seriesId) {
  const typed = window.prompt(
    `UNPUBLISH series '${seriesId}' from production?\n` +
    `This rm -rf's the remote dir and rebuilds the index.\n\n` +
    `Type the series ID to confirm:`
  );
  if (typed !== seriesId) {
    if (typed != null) toast("name mismatch — unpublish cancelled", "warn");
    return;
  }
  try {
    const r = await fetch(
      `/api/remote/series/${encodeURIComponent(seriesId)}?confirm=${encodeURIComponent(seriesId)}`,
      { method: "DELETE" }
    );
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    // Server returns {deleted, fully_deleted, remaining, rm_errors, ...}.
    // Surface partial-delete situations honestly — the remote can legitimately
    // refuse to remove a file (EBUSY, perm) and silent success would lie.
    if (body.fully_deleted) {
      toast(`✓ unpublished ${body.deleted} (${body.remaining} series left)`, "info");
    } else {
      toast(
        `⚠ partial delete: ${body.rm_errors?.length || "?"} files survived. ` +
        `Check ssh manually.`, "error", 9000
      );
    }
    refreshRemote();
  } catch (e) {
    toast(`unpublish failed: ${e.message}`, "error", 7000);
  }
}

// Delegate remote-panel unpublish clicks (same pattern as job actions).
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action='unpublish']");
  if (btn) actionUnpublish(btn.dataset.series);
});

// ─── New-podcast modal (Phase 4) ───
const modalState = {
  file: null,       // selected File
  submitting: false,
};

function openNewPodcastModal() {
  $("#modal-backdrop").hidden = false;
  // Reset state so re-opening starts fresh.
  modalState.file = null;
  modalState.submitting = false;
  $("#epub-input").value = "";
  // Belt-and-suspenders on the parallel default — HTML carries value="3" but
  // browser autofill / stale cached HTML can leave it blank. Set both the
  // attribute and the live value so neither path can drop it.
  const pi = $("#parallel-input");
  pi.value = "3";
  pi.setAttribute("value", "3");
  // Make the disabled button SAY what's blocking it — "↑ START PIPELINE"
  // greyed out with no explanation is the screenshot bug user hit.
  const submit = $("#modal-submit");
  submit.disabled = true;
  submit.textContent = "↑ PICK AN EPUB ABOVE";
  refreshDropzonePrompt();
  // Add a one-shot pulse to the dropzone so the click target is obvious.
  const dz = $("#dropzone");
  dz.classList.add("dropzone-pulse");
  setTimeout(() => dz.classList.remove("dropzone-pulse"), 2200);
}

function closeNewPodcastModal() {
  // Always allow close. The submit job runs server-side and is tracked by
  // /api/jobs — dismissing the modal doesn't cancel it. The previous
  // `if (modalState.submitting) return` guard was over-cautious: if a
  // submit threw before the error handler reset the flag, ✕ and CANCEL
  // would silently no-op and trap the user inside.
  $("#modal-backdrop").hidden = true;
  modalState.submitting = false;
}

function refreshDropzonePrompt() {
  const promptEl = $("#dropzone-prompt");
  if (!promptEl) return;
  if (modalState.file) {
    const mb = (modalState.file.size / (1 << 20)).toFixed(1);
    promptEl.innerHTML = `
      <span class="dropzone-icon">✓</span>
      <span class="dropzone-text">${escapeHtml(modalState.file.name)}</span>
      <span class="dropzone-hint">${mb} MB · click to pick a different file</span>
    `;
  } else {
    promptEl.innerHTML = `
      <span class="dropzone-icon">📚</span>
      <span class="dropzone-text">drag an EPUB here, or click to pick</span>
      <span class="dropzone-hint">max 200MB · pipeline runs all 13 stages</span>
    `;
  }
}

function setModalFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith(".epub")) {
    toast(`not an EPUB: ${file.name}`, "warn");
    return;
  }
  if (file.size > 200 * (1 << 20)) {
    toast(`file too large (>200 MB)`, "error");
    return;
  }
  modalState.file = file;
  const submit = $("#modal-submit");
  submit.disabled = false;
  submit.textContent = "↑ START PIPELINE";
  refreshDropzonePrompt();
}

async function submitNewPodcast(e) {
  e.preventDefault();
  if (!modalState.file || modalState.submitting) return;
  modalState.submitting = true;
  const submitBtn = $("#modal-submit");
  submitBtn.disabled = true;
  submitBtn.textContent = "STARTING…";

  const fd = new FormData();
  fd.append("epub", modalState.file);
  fd.append("parallel", $("#parallel-input").value || "3");

  let job;
  try {
    const r = await fetch("/api/pipeline/start", { method: "POST", body: fd });
    job = await r.json();
    if (!r.ok) throw new Error(job.detail || `HTTP ${r.status}`);
  } catch (err) {
    toast(`start failed: ${err.message}`, "error", 8000);
    modalState.submitting = false;
    submitBtn.disabled = false;
    submitBtn.textContent = "↑ START PIPELINE";
    return;
  }

  toast(`pipeline started · ${job.label} · job ${job.job_id}`, "info");
  closeNewPodcastModal();
  modalState.submitting = false;
  submitBtn.disabled = false;
  submitBtn.textContent = "↑ START PIPELINE";

  // The workspace name isn't known until pipeline.py:setup_workspace runs
  // (slug derived from book title + content hash). Poll workspaces list
  // for ~90s; switch to the first new entry that appears.
  watchForNewWorkspace(job.job_id);
}

async function watchForNewWorkspace(jobId) {
  // Snapshot the workspace list at start so we can spot the new one.
  let before;
  try {
    before = new Set(await (await fetch("/api/workspaces")).json());
  } catch { return; }

  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 2500));
    // Job might have crashed fast — stop watching if it failed. Also handle
    // the (rare) case where the entire pipeline ran to completion within the
    // poll window: do one final list-diff to attribute the new workspace.
    let jobTerminal = false;
    try {
      const jr = await fetch(`/api/jobs/${jobId}?log_bytes=0`);
      if (jr.ok) {
        const j = await jr.json();
        if (j.status === "failed" || j.status === "killed") {
          toast(`pipeline ${j.status} before workspace created — check job log`, "error", 8000);
          return;
        }
        if (j.status === "succeeded") jobTerminal = true;
      }
    } catch { /* keep watching */ }

    try {
      const list = await (await fetch("/api/workspaces")).json();
      const fresh = list.find(name => !before.has(name));
      if (fresh) {
        toast(`workspace created: ${fresh}`, "info");
        // Refresh the sidebar list, then switch — switchWorkspace will
        // re-render the sidebar so the new card is highlighted.
        await loadWorkspaces();
        switchWorkspace(fresh);
        return;
      }
      // Job succeeded but no new workspace appeared in the diff — odd, but
      // bail rather than poll for 60 more seconds.
      if (jobTerminal) return;
    } catch { /* keep watching */ }
  }
  toast("workspace didn't appear in 90s — pipeline may be slow on prep", "warn", 6000);
}

// ─── Action handlers ───
async function actionUpload() {
  if (!state.ws) return toast("no workspace selected", "warn");

  // Pre-flight: warn (don't block) if remote disk is getting tight. Prevents
  // the rsync from filling the volume mid-transfer and ending up half-applied.
  // state.remote.disk is refreshed every 30s; if missing we don't gate the upload.
  if (state.remote.disk && state.remote.disk.avail_bytes < REMOTE_LOW_FREE_BYTES) {
    const free = fmtBytes(state.remote.disk.avail_bytes);
    if (!confirm(`Server has only ${free} free.\nUpload anyway?`)) return;
  }

  try {
    const r = await fetch(`/api/workspace/${state.ws}/upload`, { method: "POST" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    toast(`upload started · job ${body.job_id}`, "info");
    refreshJobs();
    // Re-probe remote shortly after upload completes (~20s for typical
    // workspace ~200MB rsync) so the gauge + series list reflect the new state.
    setTimeout(refreshRemote, 25000);
  } catch (e) {
    toast(`upload failed: ${e.message}`, "error", 7000);
  }
}

async function actionDelete() {
  if (!state.ws) return toast("no workspace selected", "warn");
  // Destructive — require user to type the workspace name to confirm.
  // window.prompt is OK here; this is localhost-only ops tooling.
  const typed = window.prompt(
    `DELETE local workspace '${state.ws}'?\n` +
    `(does NOT touch the remote server)\n\n` +
    `Type the workspace name to confirm:`
  );
  if (typed !== state.ws) {
    if (typed != null) toast("name mismatch — delete cancelled", "warn");
    return;
  }
  try {
    const r = await fetch(
      `/api/workspace/${state.ws}?confirm=${encodeURIComponent(state.ws)}`,
      { method: "DELETE" }
    );
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    toast(`deleted ${body.deleted}`, "info");
    loadWorkspaces();
  } catch (e) {
    toast(`delete failed: ${e.message}`, "error", 7000);
  }
}

async function actionRerunStage(stage, episode = null) {
  if (!state.ws) return toast("no workspace selected", "warn");
  const epLabel = episode != null ? ` ep${episode}` : "";
  if (!confirm(`Re-run ${stage}${epLabel} on ${state.ws}?\n\nDrops the .stage_${stage}_done marker so the stage actually executes.`)) {
    return;
  }
  const params = new URLSearchParams({ stage });
  if (episode != null) params.set("episode", String(episode));
  try {
    const r = await fetch(`/api/workspace/${state.ws}/rerun?${params}`, { method: "POST" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    toast(`rerun started · job ${body.job_id}`, "info");
    refreshJobs();
  } catch (e) {
    toast(`rerun failed: ${e.message}`, "error", 7000);
  }
}

// ─── Recent jobs panel ───
async function refreshJobs() {
  // Debounce: if the previous request hasn't returned yet, don't pile on.
  // Action handlers may call this immediately after a slow tick fires; we
  // want one in-flight at a time, not stacked GETs.
  if (state.jobsInflight) return;
  state.jobsInflight = true;
  try {
    const r = await fetch("/api/jobs?limit=8");
    if (!r.ok) return;
    const prev = state.recentJobs;
    const next = await r.json();
    state.recentJobs = next;
    // Detect status transitions running → failed/killed so the user gets a
    // toast even if they weren't watching the panel.
    const prevById = new Map(prev.map(j => [j.id, j.status]));
    for (const j of next) {
      const was = prevById.get(j.id);
      if (was === "running" && (j.status === "failed" || j.status === "killed")) {
        toast(`job ${j.status}: ${j.label}`, "error", 8000);
      } else if (was === "running" && j.status === "succeeded") {
        toast(`✓ ${j.label}`, "info");
      }
    }
    renderJobs();
  } catch { /* network blip */ }
  finally { state.jobsInflight = false; }
}

function renderJobs() {
  const table = $("#jobs-table");
  const meta = $("#jobs-meta");
  if (!table) return;
  if (!state.recentJobs.length) {
    table.innerHTML = `<div class="empty">no jobs yet — click ↑ UPLOAD or use a stage ↻</div>`;
    if (meta) meta.textContent = "none";
    return;
  }
  const running = state.recentJobs.filter(j => j.status === "running").length;
  if (meta) meta.textContent = running ? `${running} running · ${state.recentJobs.length} recent` : `${state.recentJobs.length} recent`;
  table.innerHTML = state.recentJobs.map(j => {
    const dur = j.duration_s != null ? `${j.duration_s.toFixed(1)}s` : "—";
    const statusCls = `job-status job-${j.status}`;
    return `
      <div class="job-row" data-job="${j.id}">
        <span class="${statusCls}">${j.status}</span>
        <span class="job-label">${escapeHtml(j.label)}</span>
        <span class="job-dur tabular">${dur}</span>
        <button class="job-action" data-action="log" data-job="${j.id}">log</button>
        ${j.status === "running" ? `<button class="job-action danger" data-action="kill" data-job="${j.id}">kill</button>` : ""}
      </div>
    `;
  }).join("");
}

// Delegate job-row actions.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".job-action");
  if (!btn) return;
  const id = btn.dataset.job;
  const action = btn.dataset.action;
  if (action === "log") {
    try {
      const r = await fetch(`/api/jobs/${id}?log_bytes=16384`);
      const j = await r.json();
      // Cheap in-browser log viewer — alert is ugly but localhost dev.
      // Replace with a modal in a later phase if it gets used heavily.
      window.alert(`# ${j.label}\nstatus=${j.status} exit=${j.exit_code} dur=${j.duration_s}s\n\n${j.log_tail || "(empty)"}`);
    } catch (err) { toast(`log fetch failed: ${err.message}`, "error"); }
  } else if (action === "kill") {
    if (!confirm("Kill this running job?")) return;
    try {
      const r = await fetch(`/api/jobs/${id}/kill`, { method: "POST" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      toast("kill signal sent", "info");
      refreshJobs();
    } catch (err) { toast(`kill failed: ${err.message}`, "error"); }
  }
});

// ─── Renderers ───
function renderAll() {
  renderStages();
  renderKpis();
  renderFeed();
  renderNavStatus();
}

// Vertical timeline: one row per stage, top→bottom = pipeline order. State reads
// from the spine dot + connector colour + name tint; the redundant per-stage
// "DONE" pill is dropped (it was 11 identical noisy chips) — only the states the
// producer acts on (running / failed) get an explicit pill.
const PARALLEL_STAGES = new Set(["scriptwrite", "script-review", "synthesize"]);

function renderStages() {
  const grid = $("#stage-grid");
  const rows = STAGES.map(stage => {
    const s = state.stages[stage] || { status: "pending" };
    const status = s.status || "pending";

    let eps = "";
    if (PARALLEL_STAGES.has(stage)) {
      const e = state.parallelEps[stage] || {};
      const nums = Object.keys(e).map(Number).sort((a, b) => a - b);
      eps = nums.map(n => {
        const st = e[n] || "pending";
        return `<span class="ep-tile ${st}" title="EP${n} · ${st}">${n}</span>`;
      }).join("");
    }

    const time = s.elapsed_s != null ? `${s.elapsed_s}s`
      : s.started_ts ? fmtTime(s.started_ts)
      : "—";
    const label = stage.toUpperCase();
    const pill = (status === "running" || status === "failed")
      ? `<span class="tl-pill tl-pill-${status}">${status}</span>` : "";

    return `
      <div class="tl-row tl-${status}">
        <span class="tl-spine"><span class="tl-dot"></span></span>
        <span class="tl-name" title="${label}">${label}</span>
        <span class="tl-eps">${eps}</span>
        <span class="tl-meta">
          ${pill}
          <span class="tl-time tabular">${time}</span>
          <button class="tl-rerun" data-rerun-stage="${stage}" title="Re-run ${label}" aria-label="Re-run ${label}">↻</button>
        </span>
      </div>`;
  }).join("");
  grid.innerHTML = `<div class="timeline">${rows}</div>`;
}

function renderKpis() {
  // Elapsed
  let elapsed = "—";
  if (state.pipelineStartTs) {
    const end = state.currentStage ? new Date() : (state.pipelineEndTs ? new Date(state.pipelineEndTs) : new Date());
    const ms = end - new Date(state.pipelineStartTs);
    elapsed = fmtDuration(ms);
  }
  $("#k-elapsed").textContent = elapsed;
  $("#k-current").textContent = state.currentStage ? `running · ${state.currentStage}` : "idle";

  // Context
  const ctx = state.lastCtx || 0;
  const pct = (ctx / OPUS_CTX_MAX) * 100;
  $("#k-ctx").textContent = fmtNum(ctx);
  $("#k-ctx-pct").textContent = pct < 0.01 && pct > 0 ? "<0.01%" : pct.toFixed(2) + "%";
  $("#k-ctx-bar").style.width = Math.min(100, pct) + "%";
  $("#k-ctx-peak").textContent = fmtNum(state.peakCtx);

  // Tokens
  $("#k-tok-out").textContent = fmtNum(state.tokensTotal.out);
  $("#k-tok-fresh").textContent = fmtNum(state.tokensTotal.fresh);
  $("#k-tok-cr").textContent = fmtNum(state.tokensTotal.cacheRead);
  $("#k-tok-cc").textContent = fmtNum(state.tokensTotal.cacheCreate);
}

function renderCost(c) {
  const total = c.total_usd || 0;
  $("#k-cost").textContent = fmtUsd(total);
  $("#cost-total").textContent = fmtUsd(total);

  // Claude vs TTS split for the primary KPI sub-line.
  let claudeUsd = 0, ttsUsd = 0;
  for (const [model, m] of Object.entries(c.by_model || {})) {
    if (/claude/i.test(model)) claudeUsd += m.usd || 0;
    else ttsUsd += m.usd || 0;
  }
  $("#k-cost-claude").textContent = fmtUsd(claudeUsd);
  $("#k-cost-tts").textContent = fmtUsd(ttsUsd);

  // Pricing source footnote
  const meta = c.pricing || {};
  $("#cost-pricing-src").textContent = meta.verified_against
    ? `verified ${meta.verified_against} · vertex + claude CLI rates`
    : "";

  // Table — order rows by canonical STAGES sequence, hide empty rows.
  const tbody = $("#cost-tbody");
  tbody.innerHTML = "";
  const byStage = c.by_stage || {};
  for (const stage of STAGES) {
    const b = byStage[stage];
    if (!b || b.calls === 0) continue;
    const tr = document.createElement("tr");
    const cacheRW = (b.cache_read_tokens || b.cache_create_tokens)
      ? `${fmtNum(b.cache_read_tokens)} / ${fmtNum(b.cache_create_tokens)}`
      : "—";
    tr.innerHTML = `
      <td class="stage-cell">${stage}</td>
      <td class="model-cell">${escapeHtml(b.model || "—")}</td>
      <td class="r tabular">${b.calls}</td>
      <td class="r tabular">${fmtNum(b.input_tokens)}</td>
      <td class="r tabular">${fmtNum(b.output_tokens)}</td>
      <td class="r tabular">${cacheRW}</td>
      <td class="r tabular">${fmtAudioSecs(b.audio_seconds)}</td>
      <td class="r tabular usd"><strong>${fmtUsd(b.usd)}</strong></td>
    `;
    tbody.appendChild(tr);
  }
  if (!tbody.children.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">No cost data yet — set <code>PODCAST_VERBOSE=1</code> before running pipeline.</td></tr>`;
  }

  // Warnings
  const wEl = $("#cost-warnings");
  wEl.innerHTML = "";
  for (const w of (c.warnings || [])) {
    const div = document.createElement("div");
    div.className = "warn";
    div.textContent = "⚠ " + w;
    wEl.appendChild(div);
  }
}

function renderFeed() {
  const feed = $("#activity-feed");
  $("#activity-stage").textContent = state.currentStage ? `running · ${state.currentStage}` : "idle";

  const frag = document.createDocumentFragment();
  for (const e of state.feed) {
    const row = document.createElement("div");
    row.className = "feed-line";
    row.innerHTML = `
      <span class="feed-time">${fmtTime(e.ts)}</span>
      <span class="feed-stage">${escapeHtml(e.stage || "")}</span>
      <span class="feed-body">${renderEntry(e)}</span>
    `;
    frag.appendChild(row);
  }
  feed.innerHTML = "";
  feed.appendChild(frag);
}

function renderEntry(e) {
  switch (e.kind) {
    case "tool": {
      const i = e.input || {};
      let detail = "";
      switch (e.tool) {
        case "Read": case "Write": case "Edit":
          detail = i.file_path || "";
          break;
        case "Bash":
          detail = (i.command || "").slice(0, 160);
          break;
        case "Grep":
          detail = `'${i.pattern || ""}' in ${i.path || "."}`;
          break;
        case "Glob":
          detail = i.pattern || "";
          break;
        case "WebFetch": case "WebSearch":
          detail = (i.url || i.query || "").slice(0, 160);
          break;
        default:
          detail = JSON.stringify(i).slice(0, 120);
      }
      return `<span class="feed-tool">→ ${escapeHtml(e.tool)}</span><span class="feed-text">${escapeHtml(detail)}</span>`;
    }
    case "text":      return `<span class="feed-text">💬 ${escapeHtml(e.msg)}</span>`;
    case "stage_start": return `<span class="feed-text strong contra">▸ ${escapeHtml(e.msg)}</span>`;
    case "stage_done":  return `<span class="feed-text strong">✓ ${escapeHtml(e.msg)}</span>`;
    case "stage_fail":  return `<span class="feed-error">✗ ${escapeHtml(e.msg)}</span>`;
    case "error":       return `<span class="feed-error">✗ ${escapeHtml(e.msg)}</span>`;
    case "sys":         return `<span class="feed-text muted">· ${escapeHtml(e.msg)}</span>`;
    case "result":      return `<span class="feed-usage">· ${escapeHtml(e.msg)}</span>`;
    case "tts":         return `<span class="feed-tts">♪ ${escapeHtml(e.msg)}</span>`;
    case "info":
    default:            return `<span class="feed-text muted">${escapeHtml(e.msg || "")}</span>`;
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c])
  );
}

function renderNavStatus() {
  const dot = $("#status-dot");
  const text = $("#status-text");
  if (state.currentStage) {
    dot.className = "status-dot running";
    text.textContent = `RUNNING · ${state.currentStage}`;
  } else if (Object.values(state.stages).some(s => s.status === "failed")) {
    dot.className = "status-dot failed";
    text.textContent = "FAILED";
  } else if (Object.values(state.stages).some(s => s.status === "done")) {
    dot.className = "status-dot done";
    text.textContent = "DONE";
  } else {
    dot.className = "status-dot";
    text.textContent = "IDLE";
  }
}

setInterval(() => {
  if (state.currentStage) renderKpis();
}, 1000);

document.addEventListener("DOMContentLoaded", () => {
  // Stamp the loaded version in the nav so user can confirm at a glance
  // whether the browser is serving fresh JS or a stale cache.
  const v = document.querySelector("#nav-version");
  if (v) v.textContent = `v${APP_VERSION}`;

  $("#ws-refresh")?.addEventListener("click", loadWorkspaces);
  $("#act-new").addEventListener("click", openNewPodcastModal);
  $("#act-upload").addEventListener("click", actionUpload);
  $("#act-delete").addEventListener("click", actionDelete);

  // ─── Sidebar interactive controls (P3) ──────────────────────────────────
  // All re-renders consume state.workspaceSummaries (no extra fetch) so the
  // user gets sub-frame latency on every keystroke / chip click.
  const reRenderFromCache = () =>
    renderSidebar(state.workspaceSummaries || [], state.ws);

  // Search: input fires on every keystroke (incl. the X clear button on type=search).
  const searchEl = $("#sidebar-search");
  if (searchEl) {
    searchEl.addEventListener("input", (e) => {
      sidebarUI.query = e.target.value;
      persistSidebarUI();
      reRenderFromCache();
    });
    // Restore persisted search on load.
    searchEl.value = sidebarUI.query;
  }

  // Status filter chips (delegated to the chip row).
  $("#sidebar-chips")?.addEventListener("click", (e) => {
    const chip = e.target.closest(".sidebar-chip");
    if (!chip) return;
    const next = chip.dataset.status;
    // Guard against a malformed chip — only allow known enum values to land
    // in persistent state (same defense as the localStorage load path).
    if (!SIDEBAR_STATUS_VALUES.has(next)) return;
    sidebarUI.status = next;
    persistSidebarUI();
    reRenderFromCache();
  });

  // Sort toggle (recent ⇄ name).
  $("#sidebar-sort")?.addEventListener("click", () => {
    sidebarUI.sort = sidebarUI.sort === "recent" ? "name" : "recent";
    persistSidebarUI();
    reRenderFromCache();
  });

  // Drawer toggle (mobile hamburger + backdrop click + Esc).
  $("#sidebar-toggle").addEventListener("click", toggleSidebarDrawer);
  $("#sidebar-backdrop").addEventListener("click", closeSidebarDrawer);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("sidebar-open")) {
      closeSidebarDrawer();
    }
  });

  // Modal: close (esc / backdrop click / cancel / X)
  //
  // Delegated on document so a JS error earlier in DOMContentLoaded can't
  // silently leave the close buttons inert. Whichever code path got the user
  // INTO the modal also gets them OUT. Even if openNewPodcastModal somehow
  // ran but this DOMContentLoaded block didn't, the delegated listener on
  // document still catches the click.
  document.addEventListener("click", (e) => {
    if (e.target.closest("#modal-close, #modal-cancel")) {
      console.debug("[monitor] modal close via button");
      closeNewPodcastModal();
      return;
    }
    // Backdrop click (outside the modal box) — only when the click landed
    // ON the backdrop itself, not on a child inside.
    if (e.target.id === "modal-backdrop") {
      console.debug("[monitor] modal close via backdrop");
      closeNewPodcastModal();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#modal-backdrop")?.hidden) closeNewPodcastModal();
  });

  // Modal: file picker + drag/drop. The <label class="dropzone"> wrapping
  // the hidden file input already triggers the OS picker on click via HTML —
  // no JS click handler needed (and adding one would double-fire the picker).
  $("#epub-input").addEventListener("change", (e) => setModalFile(e.target.files[0]));
  const dz = $("#dropzone");
  dz.addEventListener("dragenter", (e) => { e.preventDefault(); dz.classList.add("drag-over"); });
  dz.addEventListener("dragover",  (e) => { e.preventDefault(); dz.classList.add("drag-over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("drag-over"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("drag-over");
    setModalFile(e.dataTransfer.files[0]);
  });
  $("#new-podcast-form").addEventListener("submit", submitNewPodcast);
  // Stage rerun button — delegated since renderStages re-creates the DOM.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-rerun-stage]");
    if (btn) actionRerunStage(btn.dataset.rerunStage);
  });

  // Attach the inline player (Phase 2). Player loads its workspace via
  // switchWorkspace() once the workspace list resolves.
  const playerRoot = $("#player-panel");
  if (playerRoot && window.PodcastPlayer) {
    state.player = window.PodcastPlayer.attach(playerRoot);
  }

  // Remote panel (Phase 5) — workspace-independent; runs forever.
  $("#remote-refresh").addEventListener("click", refreshRemote);
  refreshRemote();
  state.remoteTimer = setInterval(refreshRemote, REMOTE_REFRESH_MS);

  loadWorkspaces();
  // Quiet poll for new workspaces — fills the gap when pipeline runs from
  // an external terminal (./start.sh standalone, not via the modal).
  setInterval(() => loadWorkspaces({ quiet: true }), WORKSPACES_POLL_MS);
});
