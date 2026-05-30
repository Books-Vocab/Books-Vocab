// Podcast Pipeline Monitor — live dashboard
// Streams pipeline_log.jsonl + events.jsonl via SSE; pulls cost summary from
// /api/workspace/<n>/cost (claude CLI's costUSD + Vertex TTS calc).

const STAGES = [
  "prep", "analyst", "architect", "plan-review",
  "enricher-gap", "enricher", "scriptwrite",
  "series-polish", "script-review",
  "tts-prep", "synthesize", "audio-qa", "subtitle",
];

const OPUS_CTX_MAX = 1_000_000;
const COST_REFRESH_MS = 4000;
const JOBS_REFRESH_MS = 3000;

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
  recentJobs: [],
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
async function loadWorkspaces() {
  const r = await fetch("/api/workspaces");
  const list = await r.json();
  const sel = $("#ws-select");
  sel.innerHTML = "";
  for (const name of list) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  }
  const wsFromUrl = new URLSearchParams(location.search).get("ws");
  if (wsFromUrl && list.includes(wsFromUrl)) sel.value = wsFromUrl;
  sel.onchange = () => switchWorkspace(sel.value);
  if (list.length) switchWorkspace(sel.value);
}

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
}

async function switchWorkspace(ws) {
  resetState();
  state.ws = ws;
  const url = new URL(location.href);
  url.searchParams.set("ws", ws);
  history.replaceState(null, "", url);

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

// ─── Action handlers ───
async function actionUpload() {
  if (!state.ws) return toast("no workspace selected", "warn");
  // No confirm dialog — upload is idempotent + non-destructive (rsync into
  // a series-namespaced remote dir, atomic index rebuild).
  try {
    const r = await fetch(`/api/workspace/${state.ws}/upload`, { method: "POST" });
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    toast(`upload started · job ${body.job_id}`, "info");
    refreshJobs();
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
  try {
    const r = await fetch("/api/jobs?limit=8");
    if (!r.ok) return;
    state.recentJobs = await r.json();
    renderJobs();
  } catch { /* network blip */ }
}

function renderJobs() {
  const table = $("#jobs-table");
  const meta = $("#jobs-meta");
  if (!table) return;
  if (!state.recentJobs.length) {
    table.innerHTML = `<div class="empty">no jobs yet — click ↑ UPLOAD or use a stage ↻</div>`;
    meta.textContent = "none";
    return;
  }
  const running = state.recentJobs.filter(j => j.status === "running").length;
  meta.textContent = running ? `${running} running · ${state.recentJobs.length} recent` : `${state.recentJobs.length} recent`;
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

function renderStages() {
  const grid = $("#stage-grid");
  grid.innerHTML = "";
  for (const stage of STAGES) {
    const s = state.stages[stage] || { status: "pending" };
    const card = document.createElement("div");
    const isParallel = stage === "scriptwrite" || stage === "script-review" || stage === "synthesize";
    card.className = `stage ${s.status || "pending"}${isParallel ? " stage-wide" : ""}`;

    let epLine = "";
    if (isParallel) {
      const eps = state.parallelEps[stage] || {};
      const epNums = Object.keys(eps).map(Number).sort((a, b) => a - b);
      if (epNums.length) {
        const tiles = epNums.map(n => {
          const st = eps[n] || "pending";
          return `<span class="ep-tile ${st}" title="EP${n} · ${st}">${n}</span>`;
        }).join("");
        epLine = `<div class="ep-tiles">${tiles}</div>`;
      }
    }

    const elapsed = s.elapsed_s ? `${s.elapsed_s}s`
      : s.started_ts ? `started ${fmtTime(s.started_ts)}`
      : "";

    card.innerHTML = `
      <div class="stage-head">
        <span class="stage-name">${stage}</span>
        <span class="stage-pill ${s.status}">${s.status}</span>
      </div>
      ${epLine}
      ${elapsed ? `<div class="stage-meta">${elapsed}</div>` : ""}
      <button class="stage-rerun" data-rerun-stage="${stage}" title="Re-run ${stage}">↻</button>
    `;
    grid.appendChild(card);
  }
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
  $("#ws-refresh").addEventListener("click", loadWorkspaces);
  $("#act-upload").addEventListener("click", actionUpload);
  $("#act-delete").addEventListener("click", actionDelete);
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
  loadWorkspaces();
});
