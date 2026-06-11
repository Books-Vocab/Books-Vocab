from __future__ import annotations

import json


def _embed_json(data) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    # The payload is embedded inside a <script> tag, so neutralise sequences that
    # could break out of it or out of the JS string parser (</script>, U+2028/9).
    # These chars only ever appear inside JSON string values, so the \uXXXX
    # escapes round-trip to identical data when parsed.
    return (
        payload.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def render_html(manifest: dict, ui_test_videos: list[dict] | None = None) -> str:
    html = _TEMPLATE.replace("__MANIFEST__", _embed_json(manifest))
    return html.replace(
        "__UITEST_VIDEOS__",
        _embed_json(ui_test_videos) if ui_test_videos else "null",
    )


# A single self-contained template with two data holes (``__MANIFEST__`` and
# ``__UITEST_VIDEOS__``). Token
# replacement (not an f-string) keeps the JS/CSS braces literal.
#
# This is a *UI-management* browser, not a marketing-asset curator: the only
# axes it surfaces are the source-declared ones — feature → surface → state →
# shot(light/dark) + the three-bucket lane (畫面/浮層/組件, with 工程 secondary).
# The heuristic curation layer (eligibility / qualityTier / hero / promise /
# coverage facets / review-state) is intentionally NOT consumed here even though
# the manifest still carries it for the separate CLI workflow.
#
# Visual language mirrors backend /admin (admin_dashboard.html): warm-paper
# palette, JetBrains Mono labels + Noto Sans TC body, sticky top-nav + tab bar +
# centred main, no left sidebar, single light theme. The Light/Dark/Both toggle
# switches which *screenshot* variant shows — it is content, not page theme.
_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG UI Gallery</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+TC:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #f8f7f4;
      --surface: #fcfbfa;
      --border: #dbd6cd;
      --border-l: #e8e4db;
      --ink: #2a2520;
      --sub: #7a756c;
      --ink-light: #5a5550;
      --dev: #c0392b;
      --thead: #f3f0ea;
      --mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
      --sans: 'Noto Sans TC', system-ui, -apple-system, sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: var(--sans); color: var(--ink); background: var(--bg); }
    /* top nav */
    .nav {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      height: 52px; padding: 0 20px; background: var(--surface);
      border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 20;
    }
    .brand { font-family: var(--mono); font-size: 13px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; display: flex; align-items: center; gap: 9px; }
    .brand .tag { font-weight: 500; font-size: 10px; letter-spacing: .1em; color: #fff; background: var(--ink); border-radius: 2px; padding: 2px 7px; }
    .nav-actions { display: flex; align-items: center; gap: 14px; }
    .counts { font-family: var(--mono); font-size: 11px; letter-spacing: .04em; color: var(--sub); }
    .seg { display: flex; gap: 6px; }
    .seg-btn {
      font-family: var(--mono); font-size: 10px; letter-spacing: .1em; text-transform: uppercase;
      height: 28px; padding: 0 10px; border: 1px solid var(--border); border-radius: 3px;
      background: transparent; color: var(--ink-light); cursor: pointer;
    }
    .seg-btn:hover { border-color: var(--ink); color: var(--ink); }
    .seg-btn.active { background: var(--ink); border-color: var(--ink); color: #fff; }
    /* tabs */
    .tabs { display: flex; gap: 8px; padding: 12px 20px; border-bottom: 1px solid var(--border); background: var(--surface); flex-wrap: wrap; }
    .tab {
      display: inline-flex; align-items: center; gap: 7px; height: 32px; padding: 0 14px;
      border: 1px solid var(--border); border-radius: 3px; background: transparent;
      font-family: var(--mono); font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
      color: var(--ink-light); cursor: pointer;
    }
    .tab:hover { border-color: var(--ink); color: var(--ink); }
    .tab.active { background: var(--ink); border-color: var(--ink); color: #fff; }
    .tab.eng { margin-left: auto; opacity: 0.78; }
    .tab .n { font-size: 10px; opacity: 0.7; }
    /* toolbar */
    .toolbar { display: flex; align-items: center; gap: 10px; padding: 12px 20px 4px; flex-wrap: wrap; }
    .filter-input {
      flex: 1; min-width: 220px; padding: 7px 11px; border: 1px solid var(--border); border-radius: 2px;
      font-family: var(--sans); font-size: 13px; color: var(--ink); background: var(--surface); outline: none;
    }
    .filter-input:focus { border-color: var(--ink); }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; }
    .chip {
      height: 28px; padding: 0 10px; border: 1px solid var(--border); border-radius: 2px; background: transparent;
      font-family: var(--mono); font-size: 10px; letter-spacing: .06em; text-transform: uppercase;
      color: var(--ink-light); cursor: pointer; display: inline-flex; align-items: center; gap: 5px;
    }
    .chip:hover { border-color: var(--ink); color: var(--ink); }
    .chip.active { background: var(--ink); border-color: var(--ink); color: #fff; }
    .chip .n { opacity: 0.65; }
    /* stat strip */
    .stats { display: flex; gap: 8px; padding: 8px 20px 0; flex-wrap: wrap; }
    .stat { border: 1px solid var(--border); border-radius: 3px; background: var(--surface); padding: 7px 13px; min-width: 96px; }
    .stat .v { font-family: var(--mono); font-size: 21px; line-height: 1.1; letter-spacing: .03em; color: var(--ink); }
    .stat .l { font-family: var(--mono); font-size: 9px; letter-spacing: .12em; text-transform: uppercase; color: var(--sub); margin-top: 2px; }
    /* main */
    .main { max-width: 1320px; margin: 0 auto; padding: 18px 20px 64px; }
    .feature-section { margin-bottom: 30px; }
    .feature-header { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; border-bottom: 1px solid var(--border); padding-bottom: 7px; margin-bottom: 14px; }
    .feature-header h3 { margin: 0; font-family: var(--mono); font-size: 13px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--ink); }
    .feature-header span { font-family: var(--mono); font-size: 10px; letter-spacing: .06em; color: var(--sub); }
    .surface-stack { display: grid; gap: 12px; }
    .group-subhead { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin: 6px 2px -2px; }
    .group-subhead span { font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-light); }
    .group-subhead small { font-family: var(--mono); font-size: 10px; color: var(--sub); }
    .surface { border: 1px solid var(--border); border-radius: 4px; padding: 14px 16px; background: var(--surface); }
    .surface.focused { outline: 2px solid var(--ink); outline-offset: 2px; }
    .surface-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 11px; }
    .surface-title { display: flex; flex-direction: column; gap: 4px; }
    .crumb { font-family: var(--mono); font-size: 10px; letter-spacing: .06em; text-transform: uppercase; color: var(--sub); }
    .surface-title h4 { margin: 0; font-size: 16px; font-weight: 500; line-height: 1.2; color: var(--ink); }
    .badges { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 3px; }
    .badge {
      border: 1px solid var(--border); border-radius: 2px; padding: 1px 7px;
      font-family: var(--mono); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-light);
    }
    .badge.lane-feature-surface { background: #eef2f7; border-color: #c8d6e6; color: #3a5170; }
    .badge.lane-overlay { background: #f1ecf6; border-color: #d6c9e4; color: #5a4470; }
    .badge.lane-building-block { background: #eef2ea; border-color: #cdddc2; color: #45603a; }
    .badge.lane-engineering-only { background: #efece6; border-color: #d8cdbc; color: #6d5f48; }
    .surface-meta { font-family: var(--mono); font-size: 10px; color: var(--sub); text-align: right; white-space: nowrap; }
    .btn {
      display: inline-flex; align-items: center; justify-content: center; height: 28px; padding: 0 11px; margin-top: 6px;
      border: 1px solid var(--border); border-radius: 3px; background: transparent; color: var(--ink-light);
      font-family: var(--mono); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; cursor: pointer;
    }
    .btn:hover { border-color: var(--ink); color: var(--ink); }
    .btn.on { background: var(--ink); border-color: var(--ink); color: #fff; }
    .graph-summary { margin: 0 0 11px; padding: 10px 11px; border: 1px solid var(--border-l); border-radius: 3px; background: #f7f4ee; }
    .graph-summary-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin-bottom: 7px; }
    .graph-summary-head strong { font-family: var(--mono); font-size: 10px; letter-spacing: .12em; text-transform: uppercase; color: var(--ink-light); }
    .graph-summary-head span { font-family: var(--mono); font-size: 10px; color: var(--sub); }
    .graph-facts { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
    .fact {
      display: inline-flex; align-items: center; gap: 5px; min-height: 24px; padding: 0 8px;
      border: 1px solid var(--border); border-radius: 2px; background: var(--surface);
      font-family: var(--mono); font-size: 10px; color: var(--ink-light);
    }
    .fact strong { font-weight: 700; color: var(--ink); }
    .fact.status-linked { background: #edf4ea; border-color: #cadabe; color: #395a38; }
    .fact.status-ambiguous, .fact.status-unresolved, .fact.status-graph-missing { background: #fbf1e7; border-color: #e6ccb1; color: #805221; }
    .fact.status-no-backing { background: #f2efea; border-color: #d8d0c2; color: #685f52; }
    .graph-lists { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .graph-block { min-width: 0; }
    .graph-block h5 { margin: 0 0 4px; font-family: var(--mono); font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--sub); }
    .graph-block p { margin: 0; font-size: 12px; line-height: 1.45; color: var(--ink-light); }
    .graph-block ul { margin: 0; padding-left: 16px; font-size: 12px; line-height: 1.45; color: var(--ink-light); }
    .graph-block li { margin: 0; }
    /* state tiles */
    .matrix { display: grid; grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: 10px; }
    .surface.focused .matrix { grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
    .scene { border: 1px solid var(--border); border-radius: 3px; overflow: hidden; background: #fff; cursor: pointer; transition: border-color .1s ease, box-shadow .1s ease; }
    .scene:hover { border-color: var(--ink); box-shadow: 0 4px 14px rgba(42,37,32,.1); }
    /* Theme-neutral transparency checkerboard: clear / letterboxed areas read as
       "no content" in both light and dark shots (never mistaken for the asset). */
    .checker {
      background-color: #a39d94;
      background-image:
        linear-gradient(45deg, rgba(0,0,0,.17) 25%, transparent 25%, transparent 75%, rgba(0,0,0,.17) 75%),
        linear-gradient(45deg, rgba(0,0,0,.17) 25%, transparent 25%, transparent 75%, rgba(0,0,0,.17) 75%);
      background-size: 14px 14px; background-position: 0 0, 7px 7px;
    }
    .scene-shots { display: flex; align-items: flex-start; }
    .scene-shots img { display: block; width: 100%; height: auto; }
    .scene-shots.both img { width: 50%; }
    .scene-cap { padding: 6px 9px; border-top: 1px solid var(--border-l); }
    .scene-cap h5 { margin: 0; font-size: 11px; font-weight: 400; line-height: 1.25; color: var(--ink-light); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .empty { border: 1px dashed var(--border); border-radius: 3px; padding: 20px; color: var(--sub); font-size: 13px; background: var(--surface); }
    .uitest-videos-wrap { max-width: 1320px; margin: 0 auto; padding: 12px 20px 0; }
    .uitest-videos-wrap summary { cursor: pointer; font-family: var(--mono); font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-light); padding: 8px 12px; border: 1px solid var(--border); border-radius: 3px; background: var(--surface); }
    .uitest-videos-wrap summary small { color: var(--sub); text-transform: none; letter-spacing: 0; margin-left: 8px; }
    .uitest-video-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; padding: 14px 0 4px; }
    .uitest-video-card { margin: 0; border: 1px solid var(--border); border-radius: 3px; background: var(--surface); overflow: hidden; }
    .uitest-video-card video { display: block; width: 100%; max-height: 540px; background: #000; }
    .uitest-video-card figcaption { padding: 6px 10px; font-family: var(--mono); font-size: 10px; letter-spacing: .04em; color: var(--sub); display: flex; justify-content: space-between; gap: 8px; border-top: 1px solid var(--border-l); }
    /* leaf modal */
    .modal-overlay { position: fixed; inset: 0; background: rgba(42,37,32,.5); display: none; align-items: center; justify-content: center; padding: 24px; z-index: 100; }
    .modal-overlay.open { display: flex; }
    .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; max-width: 1100px; width: 100%; max-height: 92vh; overflow: auto; padding: 20px 22px; }
    .modal-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 14px; }
    .modal-head h3 { margin: 2px 0 0; font-size: 18px; font-weight: 500; color: var(--ink); }
    .modal-graph { margin-bottom: 14px; }
    .modal-shots { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
    .modal-shot { border: 1px solid var(--border); border-radius: 3px; overflow: hidden; }
    .modal-shot .frame { display: flex; justify-content: center; align-items: center; padding: 8px; }
    .modal-shot img { display: block; max-width: 100%; max-height: 72vh; height: auto; }
    .modal-shot figcaption { padding: 6px 10px; font-family: var(--mono); font-size: 10px; letter-spacing: .06em; text-transform: uppercase; color: var(--sub); display: flex; justify-content: space-between; background: var(--surface); border-top: 1px solid var(--border-l); }
    .modal-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .modal-id { font-family: var(--mono); font-size: 11px; color: var(--sub); margin-left: auto; }
    @media (max-width: 900px) {
      .modal-shots, .graph-lists { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="nav">
    <div class="brand">KG UI Gallery <span class="tag" id="lane-tag"></span></div>
    <div class="nav-actions">
      <span class="counts" id="counts"></span>
      <div class="seg" id="device-seg"></div>
      <div class="seg" id="appearance"></div>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
  <div class="toolbar">
    <input id="search" class="filter-input" type="search" placeholder="搜尋 surface / state / asset id">
    <div class="chips" id="feature-chips"></div>
  </div>
  <div class="stats" id="stats"></div>
  <section id="uitest-videos"></section>
  <main class="main" id="main"></main>
  <div class="modal-overlay" id="overlay"><div class="modal" id="leaf"></div></div>
  <script>
    const MANIFEST = __MANIFEST__;
    const surfacesIndex = MANIFEST.surfaces || [];
    const shots = MANIFEST.items || [];
    // UITest run recordings archived by ios_test.sh (build/snapshots/uitest-
    // videos/, hard-linked into this root at sync time). Page data outside the
    // shot taxonomy — mounted once, never rebuilt by render().
    const UITEST_VIDEOS = __UITEST_VIDEOS__;

    function esc(s) {
      return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    }

    // Three source-declared buckets + secondary engineering lane. 工程 (dev
    // harness) is present but parked on the right and never the default view.
    const LANE_TABS = [
      { id: "feature-surface", label: "畫面" },
      { id: "overlay", label: "浮層" },
      { id: "building-block", label: "組件" },
      { id: "engineering-only", label: "工程", eng: true },
    ];
    const LANE_LABEL = Object.fromEntries(LANE_TABS.map((l) => [l.id, l.label]));

    // Ordered device list (manifest-provided; derived from shots for older
    // manifests). Scene pairing is scoped to ONE device at a time — without the
    // scope a second device's shots silently shadow the first device's
    // light/dark pair inside the same cluster.
    const DEVICES = (MANIFEST.devices && MANIFEST.devices.length)
      ? MANIFEST.devices
      : [...new Set(shots.map((s) => s.device))];

    const state = { lane: "feature-surface", search: "", feature: "", appearance: "light", focus: "", device: DEVICES[0] || "" };

    // shots grouped by surface, then into scenes (clusterID) pairing light+dark.
    const shotsBySurface = new Map();
    for (const s of shots) {
      if (!shotsBySurface.has(s.surfaceKey)) shotsBySurface.set(s.surfaceKey, []);
      shotsBySurface.get(s.surfaceKey).push(s);
    }
    const surfaceByKey = new Map(surfacesIndex.map((s) => [s.surfaceKey, s]));

    const DEFAULTISH = new Set(["", "default", "preview", "normal"]);
    function scenesOf(surfaceKey) {
      const group = (shotsBySurface.get(surfaceKey) || [])
        .filter((s) => !state.device || s.device === state.device);
      const byScene = new Map();
      for (const s of group) {
        if (!byScene.has(s.clusterID)) byScene.set(s.clusterID, []);
        byScene.get(s.clusterID).push(s);
      }
      const scenes = [];
      for (const [clusterID, sceneShots] of byScene.entries()) {
        const rep = sceneShots[0];
        scenes.push({
          clusterID,
          stateLabel: rep.stateLabel,
          light: sceneShots.find((x) => x.appearance === "light") || rep,
          dark: sceneShots.find((x) => x.appearance === "dark") || rep,
          shots: sceneShots,
        });
      }
      // The resting/default state first, then the rest alphabetically — a stable,
      // source-truth ordering with no heuristic facet bucketing.
      scenes.sort((a, b) => {
        const da = DEFAULTISH.has(a.stateLabel.toLowerCase());
        const db = DEFAULTISH.has(b.stateLabel.toLowerCase());
        if (da !== db) return da ? -1 : 1;
        return a.stateLabel.localeCompare(b.stateLabel);
      });
      return scenes;
    }

    function laneSurfaceCount(laneId) {
      return surfacesIndex.filter((s) => s.lane === laneId).length;
    }

    function visibleScenes(surface) {
      let scenes = scenesOf(surface.surfaceKey);
      if (state.search) {
        const q = state.search;
        scenes = scenes.filter((sc) =>
          (surface.surface + " " + surface.feature + " " + sc.stateLabel + " " + sc.light.assetID).toLowerCase().includes(q)
        );
      }
      return scenes;
    }

    function visibleSurfaces() {
      const out = [];
      for (const surface of surfacesIndex) {
        if (state.focus && surface.surfaceKey !== state.focus) continue;
        if (!state.focus && surface.lane !== state.lane) continue;
        if (state.feature && surface.feature !== state.feature) continue;
        const scenes = visibleScenes(surface);
        if (!scenes.length) continue;
        out.push({ surface, scenes });
      }
      return out;
    }

    function badge(text, cls) { return `<span class="badge ${cls || ""}">${esc(text)}</span>`; }
    function fact(text, cls) { return `<span class="fact ${cls || ""}">${text}</span>`; }

    function graphStatusLabel(status) {
      return {
        "linked": "linked",
        "ambiguous": "ambiguous",
        "unresolved": "unresolved",
        "no-backing": "no backing",
        "graph-missing": "graph missing",
      }[status] || status || "graph missing";
    }

    function graphInfo(surface) {
      return surface.graph || {
        status: surface.backing ? "graph-missing" : "no-backing",
        depCount: 0, userCount: 0, dependentSurfaceCount: 0, externalIn: 0,
        deps: [], directUsers: [], dependentSurfaces: [], health: []
      };
    }

    function graphSummary(surface) {
      const graph = graphInfo(surface);
      const health = (graph.health || []).map((h) => fact(esc(h), `status-${esc(h)}`)).join("");
      const healthRow = health ? `<div class="graph-facts">${health}</div>` : "";
      const deps = (graph.deps && graph.deps.length) ? `<ul>${graph.deps.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : "<p>—</p>";
      const impacts = (graph.dependentSurfaces && graph.dependentSurfaces.length) ? `<ul>${graph.dependentSurfaces.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>` : "<p>—</p>";
      return `
        <div class="graph-summary">
          <div class="graph-summary-head">
            <strong>結構</strong>
            <span>${esc(graphStatusLabel(graph.status))}</span>
          </div>
          <div class="graph-facts">
            ${fact(`backing <strong>${esc(surface.backing || "—")}</strong>`)}
            ${fact(`depends <strong>${graph.depCount || 0}</strong>`)}
            ${fact(`users <strong>${graph.userCount || 0}</strong>`)}
            ${fact(`impacts <strong>${graph.dependentSurfaceCount || 0}</strong>`)}
            ${fact(`external <strong>${graph.externalIn || 0}</strong>`)}
            ${fact(`status <strong>${esc(graphStatusLabel(graph.status))}</strong>`, `status-${esc(graph.status || "graph-missing")}`)}
          </div>
          ${healthRow}
          <div class="graph-lists">
            <div class="graph-block">
              <h5>Depends</h5>
              ${deps}
            </div>
            <div class="graph-block">
              <h5>Impacts</h5>
              ${impacts}
            </div>
          </div>
        </div>`;
    }

    function shotImg(shot) {
      const ar = shot.width && shot.height ? ` style="aspect-ratio:${shot.width}/${shot.height}"` : "";
      return `<img loading="lazy" src="${shot.relPath}" alt=""${ar}>`;
    }

    function sceneTile(surface, scene) {
      const tile = document.createElement("article");
      tile.className = "scene";
      const both = state.appearance === "both";
      const imgs = both
        ? shotImg(scene.light) + shotImg(scene.dark)
        : shotImg(state.appearance === "dark" ? scene.dark : scene.light);
      tile.innerHTML = `
        <div class="scene-shots checker ${both ? "both" : ""}">${imgs}</div>
        <div class="scene-cap"><h5 title="${esc(scene.stateLabel)}">${esc(scene.stateLabel)}</h5></div>`;
      tile.onclick = () => openLeaf(scene, surface);
      return tile;
    }

    function renderSurface(surface, scenes) {
      const allScenes = scenesOf(surface.surfaceKey);
      const card = document.createElement("section");
      card.className = "surface" + (state.focus === surface.surfaceKey ? " focused" : "");
      card.id = `surface-${surface.surfaceKey}`;
      const head = document.createElement("div");
      head.className = "surface-head";
      head.innerHTML = `
        <div class="surface-title">
          <span class="crumb">${esc(surface.feature)} › ${esc(surface.surfaceGroup)}</span>
          <h4>${esc(surface.surface)}</h4>
          <div class="badges">${badge(LANE_LABEL[surface.lane] || surface.lane, "lane-" + surface.lane)}</div>
        </div>
        <div class="surface-meta">
          ${scenes.length}/${allScenes.length} state · ${surface.shotCount} shot
          <br><button class="btn focus-btn">${state.focus === surface.surfaceKey ? "退出 focus" : "Focus 比較"}</button>
        </div>`;
      head.querySelector(".focus-btn").onclick = (e) => {
        e.stopPropagation();
        state.focus = state.focus === surface.surfaceKey ? "" : surface.surfaceKey;
        if (state.focus) state.appearance = "both";
        render();
      };
      card.appendChild(head);
      card.insertAdjacentHTML("beforeend", graphSummary(surface));
      const matrix = document.createElement("div");
      matrix.className = "matrix";
      for (const scene of scenes) matrix.appendChild(sceneTile(surface, scene));
      card.appendChild(matrix);
      return card;
    }

    function openLeaf(scene, surface) {
      surface = surface || surfaceByKey.get(scene.light.surfaceKey);
      const leaf = document.getElementById("leaf");
      leaf.innerHTML = `
        <div class="modal-head">
          <div>
            <span class="crumb">${esc(surface.feature)} › ${esc(surface.surfaceGroup)} › ${esc(surface.surface)}</span>
            <h3>${esc(scene.stateLabel)}</h3>
            <div class="badges">${badge(LANE_LABEL[surface.lane] || surface.lane, "lane-" + surface.lane)}</div>
          </div>
          <button class="btn" data-act="close">關閉 ✕</button>
        </div>
        <div class="modal-graph">${graphSummary(surface)}</div>
        <div class="modal-shots">
          <figure class="modal-shot"><a class="frame checker" href="${scene.light.relPath}" target="_blank" rel="noreferrer"><img src="${scene.light.relPath}" alt=""></a><figcaption><span>Light</span><span>${scene.light.width}×${scene.light.height}</span></figcaption></figure>
          <figure class="modal-shot"><a class="frame checker" href="${scene.dark.relPath}" target="_blank" rel="noreferrer"><img src="${scene.dark.relPath}" alt=""></a><figcaption><span>Dark</span><span>${scene.dark.width}×${scene.dark.height}</span></figcaption></figure>
        </div>
        <div class="modal-actions">
          <button class="btn" data-act="copy">Copy ID</button>
          <button class="btn" data-act="permalink">Permalink</button>
          <span class="modal-id">${esc(scene.light.assetID)}</span>
        </div>`;
      leaf.querySelectorAll('[data-act]').forEach((btn) => {
        const act = btn.dataset.act;
        btn.onclick = async () => {
          if (act === "close") return closeLeaf();
          if (act === "copy") { await navigator.clipboard.writeText(scene.light.assetID); btn.textContent = "已複製"; return; }
          if (act === "permalink") {
            const url = `${location.origin}${location.pathname}#surface-${scene.light.surfaceKey}`;
            await navigator.clipboard.writeText(url); location.hash = `surface-${scene.light.surfaceKey}`; btn.textContent = "已複製"; return;
          }
        };
      });
      overlay.classList.add("open");
    }
    function closeLeaf() { overlay.classList.remove("open"); }
    const overlay = document.getElementById("overlay");
    overlay.onclick = (e) => { if (e.target === overlay) closeLeaf(); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLeaf(); });

    function mountTabs() {
      const tabs = document.getElementById("tabs");
      tabs.innerHTML = "";
      for (const lane of LANE_TABS) {
        const btn = document.createElement("button");
        btn.className = "tab" + (lane.eng ? " eng" : "") + (state.lane === lane.id && !state.focus ? " active" : "");
        btn.innerHTML = `${esc(lane.label)} <span class="n">${laneSurfaceCount(lane.id)}</span>`;
        btn.onclick = () => { state.lane = lane.id; state.focus = ""; state.feature = ""; render(); };
        tabs.appendChild(btn);
      }
    }

    function mountDeviceSeg() {
      const wrap = document.getElementById("device-seg");
      wrap.innerHTML = "";
      if (DEVICES.length < 2) return; // single-device snapshot: keep chrome unchanged
      for (const dev of DEVICES) {
        const b = document.createElement("button");
        b.className = "seg-btn" + (state.device === dev ? " active" : "");
        b.textContent = dev;
        b.onclick = () => { state.device = dev; render(); };
        wrap.appendChild(b);
      }
    }

    function mountAppearance() {
      const wrap = document.getElementById("appearance");
      wrap.innerHTML = "";
      for (const ap of [["light", "Light"], ["dark", "Dark"], ["both", "Both"]]) {
        const b = document.createElement("button");
        b.className = "seg-btn" + (state.appearance === ap[0] ? " active" : "");
        b.textContent = ap[1];
        b.onclick = () => { state.appearance = ap[0]; render(); };
        wrap.appendChild(b);
      }
    }

    function mountFeatureChips() {
      const wrap = document.getElementById("feature-chips");
      wrap.innerHTML = "";
      // Features present in the current lane (drives narrowing within a bucket).
      const counts = new Map();
      for (const s of surfacesIndex) {
        if (s.lane !== state.lane) continue;
        counts.set(s.feature, (counts.get(s.feature) || 0) + 1);
      }
      const features = [...counts.keys()].sort();
      const mkChip = (id, label, n, active) => {
        const c = document.createElement("button");
        c.className = "chip" + (active ? " active" : "");
        c.innerHTML = `${esc(label)}${n != null ? ` <span class="n">${n}</span>` : ""}`;
        c.onclick = () => { state.feature = id; state.focus = ""; render(); };
        return c;
      };
      wrap.appendChild(mkChip("", "全部", null, !state.feature));
      for (const f of features) wrap.appendChild(mkChip(f, f, counts.get(f), state.feature === f));
    }

    function mountStats(groups) {
      const visSurfaces = groups.length;
      const visScenes = groups.reduce((n, g) => n + g.scenes.length, 0);
      const visShots = groups.reduce((n, g) => n + g.scenes.reduce((m, sc) => m + sc.shots.length, 0), 0);
      const linked = groups.filter((g) => graphInfo(g.surface).status === "linked").length;
      const risky = groups.filter((g) => graphInfo(g.surface).status !== "linked").length;
      const cells = [
        [visSurfaces, "Surface"],
        [visScenes, "State"],
        [visShots, "Shot"],
        [linked, "Graph Linked"],
        [risky, "Graph Risk"],
      ];
      const el = document.getElementById("stats");
      el.innerHTML = cells.map(([v, l]) => `<div class="stat"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
    }

    function render() {
      const laneLabel = state.focus ? "Focus compare" : (LANE_LABEL[state.lane] || state.lane);
      document.getElementById("lane-tag").textContent = laneLabel;
      mountTabs();
      mountDeviceSeg();
      mountAppearance();
      const main = document.getElementById("main");
      main.innerHTML = "";

      const groups = visibleSurfaces();
      if (!state.focus) mountFeatureChips(); else document.getElementById("feature-chips").innerHTML = "";
      mountStats(groups);
      document.getElementById("counts").textContent =
        `${surfacesIndex.length} surface · ${MANIFEST.sceneCount || 0} state · ${MANIFEST.totalImages || 0} shot`;

      if (!groups.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "目前沒有符合條件的 surface。換一個 tab 或清掉搜尋。";
        main.appendChild(empty);
        return;
      }

      // group surfaces by feature, then by surfaceGroup (variants cluster).
      const byFeature = new Map();
      for (const g of groups) {
        if (!byFeature.has(g.surface.feature)) byFeature.set(g.surface.feature, []);
        byFeature.get(g.surface.feature).push(g);
      }
      for (const feature of [...byFeature.keys()].sort()) {
        const section = document.createElement("section");
        section.className = "feature-section";
        section.id = `feature-${feature.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
        const fGroups = byFeature.get(feature);
        const fScenes = fGroups.reduce((n, g) => n + g.scenes.length, 0);
        const header = document.createElement("div");
        header.className = "feature-header";
        header.innerHTML = `<h3>${esc(feature)}</h3><span>${fGroups.length} surface · ${fScenes} state</span>`;
        section.appendChild(header);
        const stack = document.createElement("div");
        stack.className = "surface-stack";
        const byGroup = new Map();
        for (const g of fGroups) {
          if (!byGroup.has(g.surface.surfaceGroup)) byGroup.set(g.surface.surfaceGroup, []);
          byGroup.get(g.surface.surfaceGroup).push(g);
        }
        for (const groupName of [...byGroup.keys()].sort()) {
          const gSurfaces = byGroup.get(groupName);
          gSurfaces.sort((a, b) => a.surface.surface.localeCompare(b.surface.surface));
          if (gSurfaces.length > 1) {
            const gScenes = gSurfaces.reduce((n, g) => n + g.scenes.length, 0);
            const sub = document.createElement("div");
            sub.className = "group-subhead";
            sub.innerHTML = `<span>${esc(groupName)}</span><small>${gSurfaces.length} surface · ${gScenes} state</small>`;
            stack.appendChild(sub);
          }
          for (const g of gSurfaces) stack.appendChild(renderSurface(g.surface, g.scenes));
        }
        section.appendChild(stack);
        main.appendChild(section);
      }

      requestAnimationFrame(() => {
        if (location.hash.startsWith("#surface-")) {
          const el = document.querySelector(location.hash);
          if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    }

    // Wire the search input ONCE: it lives in the static chrome (not rebuilt by
    // render(), which only touches #main / chrome counts), so a single listener
    // keeps input focus while typing and re-filters on every keystroke.
    document.getElementById("search").addEventListener("input", (e) => {
      state.search = e.target.value.trim().toLowerCase();
      render();
    });

    function mountUITestVideos() {
      const host = document.getElementById("uitest-videos");
      if (!UITEST_VIDEOS || !UITEST_VIDEOS.length) { host.remove(); return; }
      const cards = UITEST_VIDEOS.map((v) => `
        <figure class="uitest-video-card">
          <video controls preload="metadata" src="${esc(v.src)}"></video>
          <figcaption>
            <span>${esc(v.recordedAtUtc || "?")} · ${esc(v.scope || "?")}</span>
            <span>${esc(v.caller || "?")} · ${v.sizeBytes ? (v.sizeBytes / 1048576).toFixed(1) : "?"} MB</span>
          </figcaption>
        </figure>`).join("");
      host.innerHTML = `
        <details class="uitest-videos-wrap">
          <summary>UITest 錄影 <small>${UITEST_VIDEOS.length} 段 · 最新在前 · 每段=一次 --ui 全程錄影</small></summary>
          <div class="uitest-video-grid">${cards}</div>
        </details>`;
    }

    mountUITestVideos();
    render();
  </script>
</body>
</html>"""
