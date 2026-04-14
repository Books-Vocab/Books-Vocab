// Podcast Pipeline Monitor — live dashboard

const STAGES = [
  "prep", "analyst", "architect", "plan-review",
  "enricher-gap", "enricher", "scriptwrite",
  "series-polish", "script-review",
  "tts-prep", "synthesize", "audio-qa", "subtitle",
];

const OPUS_CTX_MAX = 1_000_000; // 1M context

const state = {
  ws: null,
  stages: {},          // stage -> { status, elapsed_s, started_ts }
  parallelEps: {       // per-stage per-episode runner status
    scriptwrite: {},   // { 1: "running"|"done"|"failed", ... }
    "script-review": {},
  },
  tokensTotal: { out: 0, cacheRead: 0, cacheCreate: 0, fresh: 0 },
  lastCtx: 0,          // real context size from last assistant msg
  peakCtx: 0,          // max context ever observed
  currentStage: null,  // label from last stage_start
  pipelineStartTs: null,
  pipelineEndTs: null,
  feed: [],            // most-recent-first
  maxFeed: 200,
  eventSource: null,
};

// Map an agent stage_label from events.jsonl to its pipeline stage + episode (if parallel).
function parseLabel(label) {
  if (!label) return { stage: null, ep: null };
  let m = label.match(/^Scriptwriter EP(\d+)$/i);
  if (m) return { stage: "scriptwrite", ep: Number(m[1]) };
  m = label.match(/^Script Review EP(\d+)$/i);
  if (m) return { stage: "script-review", ep: Number(m[1]) };
  return { stage: null, ep: null };
}

const $ = (sel) => document.querySelector(sel);

function fmtNum(n) {
  return new Intl.NumberFormat().format(Math.round(n));
}

function fmtDuration(ms) {
  if (!ms || ms < 0) return "—";
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
  state.tokensTotal = { in: 0, out: 0, cache: 0 };
  state.lastCtx = 0;
  state.currentStage = null;
  state.pipelineStartTs = null;
  state.pipelineEndTs = null;
  state.feed = [];
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
}

async function switchWorkspace(ws) {
  resetState();
  state.ws = ws;
  renderStages();
  renderMetrics();
  renderFeed();

  const r = await fetch(`/api/workspace/${ws}/snapshot`);
  const snap = await r.json();
  for (const e of (snap.events || [])) {
    if (e.kind === "pipeline") handlePipelineEvent(e.data);
    else handleStreamEvent(e.data);
  }
  renderAll();

  // Connect SSE for live updates
  const es = new EventSource(`/api/workspace/${ws}/stream`);
  state.eventSource = es;
  es.addEventListener("pipeline", (ev) => {
    const obj = JSON.parse(ev.data);
    handlePipelineEvent(obj);
    renderAll();
  });
  es.addEventListener("stream", (ev) => {
    const obj = JSON.parse(ev.data);
    handleStreamEvent(obj);
    renderAll();
  });
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
  } else if (ev === "info") {
    if (obj.msg === "claude invocation") {
      pushFeed(ts, stage || (state.currentStage || ""), {
        kind: "info", msg: `claude invoked · timeout ${obj.timeout_s}s`,
      });
    } else if (obj.msg) {
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
      // Mark parallel-ep as running on first event
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
    // Usage tokens
    const usage = msg.usage || {};
    if (usage.input_tokens !== undefined) {
      // Real context size = fresh input + cache_read + cache_creation
      // (Anthropic's `input_tokens` is only the fresh/new portion)
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
        const first = (part.text || "").trim().split("\n")[0].slice(0, 300);
        if (first) {
          pushFeed(ts, stageLabel, { kind: "text", msg: first });
        }
      }
    }
    return;
  }

  if (type === "result") {
    const dur = (ev.duration_ms || 0) / 1000;
    const turns = ev.num_turns;
    const isErr = !!ev.is_error;
    if (pStage && ep != null) {
      state.parallelEps[pStage] ||= {};
      state.parallelEps[pStage][ep] = isErr ? "failed" : "done";
    }
    pushFeed(ts, stageLabel, {
      kind: isErr ? "stage_fail" : "result",
      msg: `${isErr ? "FAILED" : "done"} · ${dur.toFixed(0)}s · ${turns} turns`,
    });
    return;
  }
}

function pushFeed(ts, stage, entry) {
  state.feed.unshift({ ts, stage, ...entry });
  if (state.feed.length > state.maxFeed) state.feed.length = state.maxFeed;
}

// ─── Renderers ───
function renderAll() {
  renderStages();
  renderMetrics();
  renderFeed();
  renderNavStatus();
}

function renderStages() {
  const grid = $("#stage-grid");
  grid.innerHTML = "";
  for (const stage of STAGES) {
    const s = state.stages[stage] || { status: "pending" };
    const card = document.createElement("div");
    const isParallel = stage === "scriptwrite" || stage === "script-review";
    card.className = `stage-card ${s.status || "pending"}${isParallel ? " stage-parallel" : ""}`;

    let subGrid = "";
    if (isParallel) {
      const eps = state.parallelEps[stage] || {};
      const epNums = Object.keys(eps).map(Number).sort((a, b) => a - b);
      if (epNums.length) {
        const running = epNums.filter(n => eps[n] === "running").length;
        const done = epNums.filter(n => eps[n] === "done").length;
        const failed = epNums.filter(n => eps[n] === "failed").length;
        const tiles = epNums.map(n => {
          const st = eps[n] || "pending";
          return `<span class="ep-tile ${st}" title="EP${n} · ${st}">EP${n}</span>`;
        }).join("");
        subGrid = `
          <div class="ep-summary">
            <span>✓ ${done}</span>
            <span>⦿ ${running}</span>
            ${failed ? `<span class="fail">✗ ${failed}</span>` : ""}
          </div>
          <div class="ep-tiles">${tiles}</div>
        `;
      }
    }

    card.innerHTML = `
      <div class="stage-title">${stage}</div>
      <div class="stage-status-chip ${s.status}">${s.status}</div>
      ${subGrid}
      <div class="stage-meta">
        ${s.elapsed_s ? `<span class="k">elapsed</span> <span class="v tabular">${s.elapsed_s}s</span>` :
          s.started_ts ? `<span class="k">started</span> <span class="v tabular">${fmtTime(s.started_ts)}</span>` : ""}
      </div>
    `;
    grid.appendChild(card);
  }
}

function renderMetrics() {
  // Elapsed
  let elapsed = "—";
  if (state.pipelineStartTs) {
    const end = state.currentStage ? new Date() : (state.pipelineEndTs ? new Date(state.pipelineEndTs) : new Date());
    const ms = end - new Date(state.pipelineStartTs);
    elapsed = fmtDuration(ms);
  }
  $("#m-elapsed").textContent = elapsed;
  $("#m-stage").textContent = state.currentStage || "—";

  // Context (real size = fresh + cache_read + cache_creation)
  const ctx = state.lastCtx || 0;
  const pct = (ctx / OPUS_CTX_MAX) * 100;
  $("#m-ctx").textContent = fmtNum(ctx);
  $("#m-ctx-pct").textContent = pct < 0.01 && pct > 0 ? "<0.01%" : pct.toFixed(2) + "%";
  $("#m-ctx-bar").style.width = Math.min(100, pct) + "%";
  const peakEl = document.querySelector("#m-ctx-peak");
  if (peakEl) peakEl.textContent = fmtNum(state.peakCtx);

  // Tokens: OUT is the only truly cumulative meaningful number (cost of generation).
  // IN breakdown shows fresh vs cache split for research into caching effectiveness.
  $("#m-tok-total").textContent = fmtNum(state.tokensTotal.out);
  $("#m-tok-in").textContent = fmtNum(state.tokensTotal.fresh);
  $("#m-tok-out").textContent = fmtNum(state.tokensTotal.cacheRead);
  $("#m-tok-cache").textContent = fmtNum(state.tokensTotal.cacheCreate);
}

function renderFeed() {
  const feed = $("#activity-feed");
  $("#activity-stage").textContent = state.currentStage ? `running · ${state.currentStage}` : "idle";

  const frag = document.createDocumentFragment();
  for (const e of state.feed) {
    const row = document.createElement("div");
    row.className = "feed-line";
    const time = document.createElement("span");
    time.className = "feed-time";
    time.textContent = fmtTime(e.ts);
    const stage = document.createElement("span");
    stage.className = "feed-stage";
    stage.textContent = e.stage;
    const body = document.createElement("span");
    body.className = "feed-body";
    body.innerHTML = renderEntry(e);
    row.append(time, stage, body);
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
    case "text":
      return `<span class="feed-text">💬 ${escapeHtml(e.msg)}</span>`;
    case "stage_start":
      return `<span class="feed-text" style="color:var(--contra);font-weight:500">▸ ${escapeHtml(e.msg)}</span>`;
    case "stage_done":
      return `<span class="feed-text" style="color:var(--ink);font-weight:500">✓ ${escapeHtml(e.msg)}</span>`;
    case "stage_fail":
      return `<span class="feed-error">✗ ${escapeHtml(e.msg)}</span>`;
    case "error":
      return `<span class="feed-error">✗ ${escapeHtml(e.msg)}</span>`;
    case "sys":
      return `<span class="feed-text" style="color:var(--sub)">· ${escapeHtml(e.msg)}</span>`;
    case "result":
      return `<span class="feed-usage">· ${escapeHtml(e.msg)}</span>`;
    case "info":
    default:
      return `<span class="feed-text" style="color:var(--inkLight)">${escapeHtml(e.msg || "")}</span>`;
  }
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) =>
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

// Elapsed ticks forward while running
setInterval(() => {
  if (state.currentStage) renderMetrics();
}, 1000);

loadWorkspaces();
