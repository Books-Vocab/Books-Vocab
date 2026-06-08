from __future__ import annotations

import json


def render_html(manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False)
    # The payload is embedded inside a <script> tag, so neutralise sequences that
    # could break out of it or out of the JS string parser (</script>, U+2028/9).
    # These chars only ever appear inside JSON string values, so the \uXXXX
    # escapes round-trip to identical data when parsed.
    payload = (
        payload.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return _TEMPLATE.replace("__MANIFEST__", payload)


# The view is intentionally a single self-contained template with one data hole
# (``__MANIFEST__``). Token replacement (not an f-string) keeps the JS/CSS braces
# literal so the surface/state-first logic stays readable.
_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG UI Asset Gallery</title>
  <style>
    :root {
      --bg: #f3efe7;
      --panel: rgba(255, 251, 245, 0.86);
      --line: #d8cfc0;
      --line-strong: #c8baa5;
      --ink: #1e1c19;
      --muted: #6d655d;
      --accent: #9a4b1f;
      --accent-soft: #f5dfcf;
      --good: #1f6b3a;
      --bad: #8f2d2d;
      --warn: #8a5a0a;
      --shadow: 0 18px 40px rgba(31, 22, 13, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino", "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fff7e9 0, transparent 34%),
        linear-gradient(180deg, #f6f0e6 0%, #efe7db 100%);
    }
    .layout { display: grid; grid-template-columns: 320px 1fr; min-height: 100vh; }
    .sidebar {
      position: sticky; top: 0; align-self: start; height: 100vh; overflow: auto;
      padding: 22px 18px; border-right: 1px solid var(--line);
      background: rgba(255, 249, 241, 0.92); backdrop-filter: blur(10px);
    }
    .sidebar h1 { margin: 0 0 6px; font-size: 27px; line-height: 0.98; }
    .sidebar .lede { margin: 0 0 16px; color: var(--muted); font-size: 13px; line-height: 1.5; }
    .side-block { margin-bottom: 18px; padding-bottom: 16px; border-bottom: 1px solid rgba(216, 207, 192, 0.85); }
    .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .stat { padding: 9px 11px; border: 1px solid var(--line); background: white; border-radius: 14px; }
    .stat strong { display: block; font-size: 20px; line-height: 1; }
    .stat span { color: var(--muted); font-size: 11px; }
    label { display: block; margin-bottom: 5px; font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted); }
    .filters { display: grid; gap: 11px; }
    input, select {
      width: 100%; padding: 9px 11px; border-radius: 11px; border: 1px solid var(--line);
      background: white; color: var(--ink); font: inherit; font-size: 14px;
    }
    button { cursor: pointer; border: 1px solid var(--line); background: white; color: var(--ink); border-radius: 999px; padding: 7px 11px; font: inherit; font-size: 13px; }
    button.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
    .lane-rail { display: grid; gap: 7px; }
    .lane-btn { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; text-align: left; border-radius: 11px; padding: 9px 12px; }
    .lane-btn small { color: var(--muted); font-size: 12px; }
    .lane-btn.active small { color: var(--accent); }
    .nav-list { display: grid; gap: 6px; }
    .nav-link { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; padding: 8px 11px; border-radius: 11px; border: 1px solid var(--line); background: white; color: var(--ink); text-decoration: none; font-size: 13px; }
    .nav-link small { color: var(--muted); font-size: 11px; }
    .main { padding: 26px 28px 60px; }
    .topbar { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
    .topbar h2 { margin: 0; font-size: 26px; line-height: 1.05; }
    .topbar .sub { color: var(--muted); font-size: 13px; }
    .appearance-toggle { display: flex; gap: 6px; }
    .feature-section { margin-bottom: 30px; }
    .feature-header { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; border-bottom: 1px solid var(--line-strong); padding-bottom: 8px; margin-bottom: 14px; }
    .feature-header h3 { margin: 0; font-size: 22px; }
    .feature-header span { color: var(--muted); font-size: 12px; }
    .surface-stack { display: grid; gap: 14px; }
    .group-subhead { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 6px 2px -4px; padding-bottom: 4px; }
    .group-subhead span { font-size: 14px; font-weight: 700; letter-spacing: 0.02em; color: var(--accent); }
    .group-subhead small { color: var(--muted); font-size: 11px; }
    .surface {
      border: 1px solid var(--line); border-radius: 20px; padding: 15px 16px;
      background: rgba(255, 255, 255, 0.78); box-shadow: 0 12px 26px rgba(31, 22, 13, 0.05);
    }
    .surface.focused { outline: 2px solid var(--accent); outline-offset: 3px; }
    .surface-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 10px; }
    .surface-title { display: flex; flex-direction: column; gap: 4px; }
    .crumb { color: var(--muted); font-size: 11px; letter-spacing: 0.03em; }
    .surface-title h4 { margin: 0; font-size: 18px; line-height: 1.15; }
    .badges { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 4px; }
    .badge { padding: 3px 8px; border-radius: 999px; font-size: 10px; border: 1px solid #eadfce; background: #f4ede4; color: var(--muted); letter-spacing: 0.02em; }
    .badge.lane-feature-surface { background: #e7f0ff; border-color: #c3d8f2; color: #2b4f7e; }
    .badge.lane-building-block { background: #eef3e8; border-color: #cfe0c0; color: #3c5a2c; }
    .badge.lane-overlay { background: #f3eaff; border-color: #ddccf2; color: #5a3c7e; }
    .badge.lane-engineering-only { background: #efeae3; border-color: #d8cdbc; color: #6d5a3c; }
    .badge.elig-marketing { background: #fbe8d6; border-color: #ecc59a; color: var(--accent); }
    .badge.hero { background: #fff0cf; border-color: #e8ca82; color: var(--warn); }
    .badge.weak { background: #f0e6e6; border-color: #d8bdbd; color: var(--bad); }
    .surface-meta { color: var(--muted); font-size: 11px; text-align: right; white-space: nowrap; }
    .surface-meta .focus-btn { margin-top: 6px; padding: 5px 11px; font-size: 12px; }
    .facet-rail { display: flex; flex-wrap: wrap; gap: 5px; margin: 0 0 11px; }
    .facet-pip { padding: 3px 8px; border-radius: 999px; font-size: 10px; border: 1px dashed var(--line-strong); color: var(--muted); }
    .facet-pip.present { border-style: solid; background: #fff; color: var(--ink); }
    .facet-pip.present strong { font-weight: 700; }
    .facet-pip.missing { opacity: 0.5; }
    .matrix { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 10px; }
    .surface.focused .matrix { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
    .scene { border: 1px solid var(--line); border-radius: 13px; overflow: hidden; background: white; cursor: pointer; transition: transform 0.08s ease, box-shadow 0.08s ease; }
    .scene:hover { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(31, 22, 13, 0.12); }
    .scene.rejected { opacity: 0.42; }
    .scene.shortlisted { outline: 2px solid var(--good); outline-offset: -2px; }
    /* Theme-neutral transparency checkerboard: clear / letterboxed areas read as
       "no content" in both light and dark mode (never mistaken for the asset). */
    .checker {
      background-color: #a39d94;
      background-image:
        linear-gradient(45deg, rgba(0, 0, 0, 0.17) 25%, transparent 25%, transparent 75%, rgba(0, 0, 0, 0.17) 75%),
        linear-gradient(45deg, rgba(0, 0, 0, 0.17) 25%, transparent 25%, transparent 75%, rgba(0, 0, 0, 0.17) 75%);
      background-size: 14px 14px;
      background-position: 0 0, 7px 7px;
    }
    .scene-shots { display: flex; align-items: flex-start; }
    /* Each shot renders at its real pixel aspect ratio (set inline per image), so
       tickers stay thin and badges stay square instead of being cropped to a phone. */
    .scene-shots img { display: block; width: 100%; height: auto; }
    .scene-shots.both img { width: 50%; }
    .scene-cap { padding: 7px 9px; display: grid; gap: 5px; }
    .scene-cap h5 { margin: 0; font-size: 12px; line-height: 1.25; font-weight: 600; }
    .scene-cap .facet-tag { font-size: 10px; color: var(--muted); }
    .facet-tag.f-empty, .facet-tag.f-loading { color: var(--warn); }
    .facet-tag.f-error { color: var(--bad); }
    .facet-tag.f-a11y, .facet-tag.f-overflow { color: #2b4f7e; }
    .empty { border: 1px dashed var(--line-strong); border-radius: 16px; padding: 20px; color: var(--muted); background: rgba(255,255,255,0.55); }
    /* Coverage matrix */
    .cov-legend { color: var(--muted); font-size: 13px; margin: 0 2px 16px; }
    .cov-table { width: 100%; border-collapse: collapse; margin-bottom: 8px; font-size: 12px; background: rgba(255,255,255,0.6); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
    .cov-table th, .cov-table td { border-bottom: 1px solid var(--line); border-right: 1px solid var(--line); padding: 7px 6px; text-align: center; }
    .cov-table th { background: rgba(255,249,241,0.95); font-weight: 600; color: var(--muted); letter-spacing: 0.02em; position: sticky; top: 0; }
    .cov-fhead { font-size: 11px; }
    .cov-rowhead { text-align: left; min-width: 190px; max-width: 240px; line-height: 1.25; }
    td.cov-rowhead { font-size: 13px; }
    .cov-crumb { color: var(--muted); font-size: 10px; }
    .cov-link { cursor: pointer; }
    .cov-link:hover { color: var(--accent); }
    .cov-cell { width: 56px; }
    .cov-has { background: var(--accent-soft); color: var(--accent); font-weight: 700; cursor: pointer; }
    .cov-has:hover { background: var(--accent); color: white; }
    .cov-gap { color: #cdc4b6; }
    .cov-gapcount { background: rgba(255,255,255,0.4); color: var(--muted); font-weight: 600; }
    .cov-gaphot { background: #f7dddd; color: var(--bad); }
    .cov-eng td.cov-rowhead { color: #8a7e6a; }
    .cov-eng { opacity: 0.82; }
    /* Leaf detail overlay */
    .overlay-back { position: fixed; inset: 0; background: rgba(28, 22, 13, 0.55); display: none; align-items: center; justify-content: center; padding: 24px; z-index: 50; }
    .overlay-back.open { display: flex; }
    .leaf { background: var(--panel); border: 1px solid var(--line-strong); border-radius: 20px; max-width: 1100px; width: 100%; max-height: 92vh; overflow: auto; padding: 20px 22px; box-shadow: var(--shadow); }
    .leaf-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin-bottom: 12px; }
    .leaf-head h3 { margin: 0 0 4px; font-size: 22px; }
    .leaf-head .crumb { font-size: 12px; }
    .leaf-close { border-radius: 999px; padding: 6px 14px; }
    .leaf-shots { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
    .leaf-shot { border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
    .leaf-shot figcaption { padding: 6px 10px; font-size: 12px; color: var(--muted); display: flex; justify-content: space-between; background: var(--panel); }
    .leaf-shot .shot-frame { display: flex; justify-content: center; align-items: center; padding: 8px; }
    .leaf-shot img { display: block; max-width: 100%; max-height: 72vh; height: auto; }
    .leaf-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .leaf-actions .group { display: flex; gap: 6px; }
    .leaf-actions button[data-act="shortlist"].sel { background: #e3f3e8; color: var(--good); border-color: #b8d8c3; }
    .leaf-actions button[data-act="review"].sel { background: #fff0cf; color: var(--warn); border-color: #e8ca82; }
    .leaf-actions button[data-act="reject"].sel { background: #f7dddd; color: var(--bad); border-color: #e6b6b6; }
    .leaf-id { font-family: "SF Mono", "Menlo", monospace; font-size: 11px; color: var(--muted); margin-left: auto; }
    @media (max-width: 1024px) {
      .layout { grid-template-columns: 1fr; }
      .sidebar { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
      .main { padding: 16px; }
      .leaf-shots { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>KG UI Asset Gallery</h1>
      <p class="lede">不是 996 張圖牆。一級物件是 <strong>surface</strong>，比較單位是 <strong>state</strong>，PNG 只是 leaf。先選 lane、看某 surface 的所有 state，再點開單張。</p>
      <div class="side-block">
        <div class="stats">
          <div class="stat"><strong id="stat-surfaces">0</strong><span>Surface</span></div>
          <div class="stat"><strong id="stat-scenes">0</strong><span>State / scene</span></div>
          <div class="stat"><strong id="stat-visible">0</strong><span>目前可見 surface</span></div>
          <div class="stat"><strong id="stat-shots">0</strong><span>Shot (light+dark)</span></div>
        </div>
      </div>
      <div class="side-block">
        <label>Lane（資產分層）</label>
        <div class="lane-rail" id="lane-rail"></div>
      </div>
      <div class="filters side-block">
        <div>
          <label for="search">搜尋</label>
          <input id="search" type="search" placeholder="surface / state / asset id">
        </div>
        <div>
          <label for="feature">Feature</label>
          <select id="feature"><option value="">全部</option></select>
        </div>
        <div>
          <label for="facet">State facet</label>
          <select id="facet"><option value="">全部 state</option></select>
        </div>
        <div>
          <label for="eligibility">Eligibility</label>
          <select id="eligibility">
            <option value="">全部</option>
            <option value="marketing">Marketing</option>
            <option value="review">Review</option>
            <option value="engineering">Engineering</option>
          </select>
        </div>
        <div>
          <label for="quality">Quality tier</label>
          <select id="quality">
            <option value="">全部</option>
            <option value="hero">Hero</option>
            <option value="marketing">Marketing</option>
            <option value="keep">Keep</option>
            <option value="weak">Weak</option>
          </select>
        </div>
      </div>
      <div class="side-block">
        <label>導航（Feature）</label>
        <div class="nav-list" id="feature-nav"></div>
      </div>
    </aside>
    <main class="main" id="main"></main>
  </div>
  <div class="overlay-back" id="overlay"><div class="leaf" id="leaf"></div></div>
  <script>
    const MANIFEST = __MANIFEST__;
    const surfacesIndex = MANIFEST.surfaces || [];
    const shots = MANIFEST.items || [];
    const storageKey = "kg-catalog-review-states";
    const reviewStates = JSON.parse(localStorage.getItem(storageKey) || "{}");

    // Escape free-text (state labels / surface names) before it lands in innerHTML
    // so a title containing < or & renders as text instead of breaking markup.
    function esc(s) {
      return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    }

    const FACET_ORDER = ["default","populated","selected","empty","loading","disabled","bounds","overflow","error","a11y"];
    const LANES = [
      { id: "", label: "All lanes" },
      { id: "feature-surface", label: "Feature surface" },
      { id: "building-block", label: "Building block" },
      { id: "overlay", label: "Overlay" },
      { id: "engineering-only", label: "Engineering-only" },
      { id: "weak", label: "Weak · cull" },
    ];

    const state = { view: "gallery", search: "", lane: "", feature: "", facet: "", eligibility: "", quality: "", appearance: "light", focus: "" };

    // shots grouped by surface, then into scenes (clusterID) pairing light+dark.
    const shotsBySurface = new Map();
    for (const s of shots) {
      if (!shotsBySurface.has(s.surfaceKey)) shotsBySurface.set(s.surfaceKey, []);
      shotsBySurface.get(s.surfaceKey).push(s);
    }
    const surfaceByKey = new Map(surfacesIndex.map((s) => [s.surfaceKey, s]));

    function scenesOf(surfaceKey) {
      const group = shotsBySurface.get(surfaceKey) || [];
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
          stateFacet: rep.stateFacet,
          stateFacetRank: rep.stateFacetRank,
          qualityTier: rep.qualityTier,
          eligibility: rep.eligibility,
          light: sceneShots.find((x) => x.appearance === "light") || rep,
          dark: sceneShots.find((x) => x.appearance === "dark") || rep,
          shots: sceneShots,
        });
      }
      scenes.sort((a, b) => a.stateFacetRank - b.stateFacetRank || a.stateLabel.localeCompare(b.stateLabel));
      return scenes;
    }

    function sceneStatus(scene) {
      const states = scene.shots.map((s) => reviewStates[s.assetID] || s.reviewStatus || "");
      if (states.includes("reject")) return "reject";
      if (states.includes("shortlist")) return "shortlist";
      if (states.includes("review")) return "review";
      return "";
    }

    function setSceneStatus(scene, next) {
      for (const s of scene.shots) {
        if (next) reviewStates[s.assetID] = next; else delete reviewStates[s.assetID];
      }
      localStorage.setItem(storageKey, JSON.stringify(reviewStates));
      render();
      if (overlay.classList.contains("open")) openLeaf(scene);
    }

    function laneOf(surface) {
      return surface.lane;
    }

    // A surface passes lane filter; its scenes are filtered by facet/quality/search.
    function visibleScenes(surface) {
      let scenes = scenesOf(surface.surfaceKey);
      if (state.facet) scenes = scenes.filter((sc) => sc.stateFacet === state.facet);
      if (state.eligibility) scenes = scenes.filter((sc) => sc.eligibility === state.eligibility);
      if (state.quality === "weak") {
        scenes = scenes.filter((sc) => sc.qualityTier === "weak" || sceneStatus(sc) === "reject");
      } else if (state.quality) {
        scenes = scenes.filter((sc) => sc.qualityTier === state.quality);
      }
      if (state.search) {
        const q = state.search;
        scenes = scenes.filter((sc) =>
          (surface.surface + " " + surface.feature + " " + sc.stateLabel + " " + sc.light.assetID).toLowerCase().includes(q)
        );
      }
      return scenes;
    }

    function surfaceMatchesLane(surface) {
      if (!state.lane) return true;
      if (state.lane === "weak") return true; // weak handled at scene level
      return surface.lane === state.lane;
    }

    function visibleSurfaces() {
      const out = [];
      for (const surface of surfacesIndex) {
        if (state.focus && surface.surfaceKey !== state.focus) continue;
        if (!surfaceMatchesLane(surface)) continue;
        if (state.feature && surface.feature !== state.feature) continue;
        const scenes = visibleScenes(surface);
        if (!scenes.length) continue;
        out.push({ surface, scenes });
      }
      return out;
    }

    function badge(text, cls) { return `<span class="badge ${cls || ""}">${esc(text)}</span>`; }

    // Render a shot at its true pixel aspect ratio (falls back to no lock if unknown).
    function shotImg(shot) {
      const ar = shot.width && shot.height ? ` style="aspect-ratio:${shot.width}/${shot.height}"` : "";
      return `<img loading="lazy" src="${shot.relPath}" alt=""${ar}>`;
    }

    function facetRail(surface, scenes) {
      const present = new Set(scenes.map((s) => s.stateFacet));
      const counts = {};
      for (const s of scenes) counts[s.stateFacet] = (counts[s.stateFacet] || 0) + 1;
      return FACET_ORDER.map((f) => {
        const has = present.has(f);
        const n = counts[f] || 0;
        return `<span class="facet-pip ${has ? "present" : "missing"}">${has ? `<strong>${f}</strong> ${n}` : f}</span>`;
      }).join("");
    }

    function sceneTile(surface, scene) {
      const status = sceneStatus(scene);
      const tile = document.createElement("article");
      tile.className = "scene" + (status === "reject" ? " rejected" : "") + (status === "shortlist" ? " shortlisted" : "");
      const both = state.appearance === "both";
      const imgs = both
        ? shotImg(scene.light) + shotImg(scene.dark)
        : shotImg(state.appearance === "dark" ? scene.dark : scene.light);
      tile.innerHTML = `
        <div class="scene-shots checker ${both ? "both" : ""}">${imgs}</div>
        <div class="scene-cap">
          <h5>${esc(scene.stateLabel)}</h5>
          <span class="facet-tag f-${scene.stateFacet}">${scene.stateFacet}</span>
        </div>`;
      tile.onclick = () => openLeaf(scene, surface);
      return tile;
    }

    function renderSurface(surface, scenes) {
      const allScenes = scenesOf(surface.surfaceKey);
      const card = document.createElement("section");
      card.className = "surface" + (state.focus === surface.surfaceKey ? " focused" : "");
      card.id = `surface-${surface.surfaceKey}`;
      const badges = [
        badge(surface.lane, "lane-" + surface.lane),
        surface.eligibility === "marketing" ? badge("marketing", "elig-marketing") : "",
        surface.heroCandidate ? badge("hero", "hero") : "",
        surface.newScenes ? badge(`+${surface.newScenes} new`, "") : "",
      ].filter(Boolean).join("");
      const head = document.createElement("div");
      head.className = "surface-head";
      head.innerHTML = `
        <div class="surface-title">
          <span class="crumb">${esc(surface.feature)} › ${esc(surface.surfaceGroup)}</span>
          <h4>${esc(surface.surface)}</h4>
          <div class="badges">${badges}</div>
        </div>
        <div class="surface-meta">
          ${scenes.length}/${allScenes.length} state · ${surface.shotCount} shot
          <br><button class="focus-btn">${state.focus === surface.surfaceKey ? "退出 focus" : "Focus 比較"}</button>
        </div>`;
      head.querySelector(".focus-btn").onclick = (e) => {
        e.stopPropagation();
        state.focus = state.focus === surface.surfaceKey ? "" : surface.surfaceKey;
        if (state.focus) state.appearance = "both";
        render();
      };
      card.appendChild(head);
      const rail = document.createElement("div");
      rail.className = "facet-rail";
      rail.innerHTML = facetRail(surface, allScenes);
      card.appendChild(rail);
      const matrix = document.createElement("div");
      matrix.className = "matrix";
      for (const scene of scenes) matrix.appendChild(sceneTile(surface, scene));
      card.appendChild(matrix);
      return card;
    }

    function openLeaf(scene, surface) {
      surface = surface || surfaceByKey.get(scene.light.surfaceKey);
      const status = sceneStatus(scene);
      const leaf = document.getElementById("leaf");
      leaf.innerHTML = `
        <div class="leaf-head">
          <div>
            <span class="crumb">${esc(surface.feature)} › ${esc(surface.surfaceGroup)} › ${esc(surface.surface)}</span>
            <h3>${esc(scene.stateLabel)}</h3>
            <div class="badges">${badge(scene.stateFacet)}${badge(scene.qualityTier, scene.qualityTier === "weak" ? "weak" : scene.qualityTier === "hero" ? "hero" : "")}${badge(surface.lane, "lane-" + surface.lane)}</div>
          </div>
          <button class="leaf-close">關閉 ✕</button>
        </div>
        <div class="leaf-shots">
          <figure class="leaf-shot"><a class="shot-frame checker" href="${scene.light.relPath}" target="_blank" rel="noreferrer"><img src="${scene.light.relPath}" alt=""></a><figcaption><span>Light</span><span>${scene.light.width}×${scene.light.height}</span></figcaption></figure>
          <figure class="leaf-shot"><a class="shot-frame checker" href="${scene.dark.relPath}" target="_blank" rel="noreferrer"><img src="${scene.dark.relPath}" alt=""></a><figcaption><span>Dark</span><span>${scene.dark.width}×${scene.dark.height}</span></figcaption></figure>
        </div>
        <div class="leaf-actions">
          <div class="group">
            <button data-act="shortlist" class="${status === "shortlist" ? "sel" : ""}">留</button>
            <button data-act="review" class="${status === "review" ? "sel" : ""}">再看</button>
            <button data-act="reject" class="${status === "reject" ? "sel" : ""}">砍</button>
          </div>
          <button data-act="copy">Copy ID</button>
          <button data-act="permalink">Permalink</button>
          <span class="leaf-id">${scene.light.assetID}</span>
        </div>`;
      leaf.querySelectorAll('.leaf-actions [data-act]').forEach((btn) => {
        const act = btn.dataset.act;
        btn.onclick = async () => {
          if (act === "copy") { await navigator.clipboard.writeText(scene.light.assetID); btn.textContent = "已複製"; return; }
          if (act === "permalink") {
            const url = `${location.origin}${location.pathname}#surface-${scene.light.surfaceKey}`;
            await navigator.clipboard.writeText(url); location.hash = `surface-${scene.light.surfaceKey}`; btn.textContent = "已複製"; return;
          }
          setSceneStatus(scene, status === act ? "" : act);
        };
      });
      leaf.querySelector(".leaf-close").onclick = closeLeaf;
      overlay.classList.add("open");
    }
    function closeLeaf() { overlay.classList.remove("open"); }
    const overlay = document.getElementById("overlay");
    overlay.onclick = (e) => { if (e.target === overlay) closeLeaf(); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLeaf(); });

    function mountControls() {
      const featureSel = document.getElementById("feature");
      for (const f of Object.keys(MANIFEST.featureCounts || {}).sort()) {
        const o = document.createElement("option"); o.value = f; o.textContent = f; featureSel.appendChild(o);
      }
      featureSel.onchange = (e) => { state.feature = e.target.value; render(); };

      const facetSel = document.getElementById("facet");
      for (const f of FACET_ORDER.filter((x) => (MANIFEST.stateFacetCounts || {})[x])) {
        const o = document.createElement("option"); o.value = f; o.textContent = `${f} (${MANIFEST.stateFacetCounts[f]})`; facetSel.appendChild(o);
      }
      facetSel.onchange = (e) => { state.facet = e.target.value; render(); };
      document.getElementById("eligibility").onchange = (e) => { state.eligibility = e.target.value; render(); };
      document.getElementById("quality").onchange = (e) => { state.quality = e.target.value; render(); };
      document.getElementById("search").oninput = (e) => { state.search = e.target.value.trim().toLowerCase(); render(); };

      const rail = document.getElementById("lane-rail");
      const laneCounts = MANIFEST.laneCounts || {};
      const weakScenes = MANIFEST.qualityTierCounts ? (MANIFEST.qualityTierCounts.weak || 0) : 0;
      for (const lane of LANES) {
        const btn = document.createElement("button");
        btn.className = "lane-btn";
        const count = lane.id === "" ? surfacesIndex.length + " surface" : lane.id === "weak" ? weakScenes + " shot" : (laneCounts[lane.id] || 0) + " shot";
        btn.innerHTML = `<span>${lane.label}</span><small>${count}</small>`;
        btn.dataset.value = lane.id;
        btn.onclick = () => {
          state.lane = lane.id;
          state.focus = "";
          if (lane.id === "weak") state.quality = "weak";
          else if (state.quality === "weak") state.quality = "";
          document.getElementById("quality").value = state.quality;
          render();
        };
        rail.appendChild(btn);
      }

      document.getElementById("stat-surfaces").textContent = String(surfacesIndex.length);
      document.getElementById("stat-scenes").textContent = String(MANIFEST.sceneCount || 0);
      document.getElementById("stat-shots").textContent = String(MANIFEST.totalImages || 0);
    }

    function appearanceToggle() {
      const wrap = document.createElement("div");
      wrap.className = "appearance-toggle";
      for (const ap of [["light", "Light"], ["dark", "Dark"], ["both", "Both"]]) {
        const b = document.createElement("button");
        b.textContent = ap[1];
        b.className = state.appearance === ap[0] ? "active" : "";
        b.onclick = () => { state.appearance = ap[0]; render(); };
        wrap.appendChild(b);
      }
      return wrap;
    }

    function viewToggle() {
      const wrap = document.createElement("div");
      wrap.className = "appearance-toggle";
      for (const v of [["gallery", "Gallery"], ["coverage", "Coverage"]]) {
        const b = document.createElement("button");
        b.textContent = v[1];
        b.className = state.view === v[0] ? "active" : "";
        b.onclick = () => { state.view = v[0]; state.focus = ""; render(); };
        wrap.appendChild(b);
      }
      return wrap;
    }

    // Surfaces in scope for the coverage matrix: lane / feature / search only
    // (facet & quality filters are intentionally ignored — the matrix IS the
    // facet view). Built straight off the surface index's facetSceneCounts.
    function coverageSurfaces() {
      const q = state.search;
      return surfacesIndex.filter((s) => {
        if (state.lane && state.lane !== "weak" && s.lane !== state.lane) return false;
        if (state.feature && s.feature !== state.feature) return false;
        if (q && !(s.surface + " " + s.feature + " " + s.surfaceGroup).toLowerCase().includes(q)) return false;
        return true;
      });
    }

    function renderCoverage(main) {
      const surfaces = coverageSurfaces();
      const facets = FACET_ORDER;
      const byFeature = new Map();
      for (const s of surfaces) {
        if (!byFeature.has(s.feature)) byFeature.set(s.feature, []);
        byFeature.get(s.feature).push(s);
      }
      if (!surfaces.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "目前沒有符合條件的 surface。";
        main.appendChild(empty);
        return;
      }
      const legend = document.createElement("div");
      legend.className = "cov-legend";
      legend.innerHTML = `每格 = 該 surface 在該 state facet 的 scene 數;空格 = <strong>缺口</strong>。點 surface 名或格子跳到該 surface。`;
      main.appendChild(legend);
      for (const feature of [...byFeature.keys()].sort()) {
        const rows = byFeature.get(feature).sort((a, b) =>
          (b.facetsPresent.length - a.facetsPresent.length) || a.surface.localeCompare(b.surface));
        const section = document.createElement("section");
        section.className = "feature-section";
        const header = document.createElement("div");
        header.className = "feature-header";
        header.innerHTML = `<h3>${esc(feature)}</h3><span>${rows.length} surface</span>`;
        section.appendChild(header);
        const table = document.createElement("table");
        table.className = "cov-table";
        const head = ["<th class=\"cov-rowhead\">surface</th>"]
          .concat(facets.map((f) => `<th class="cov-fhead">${f}</th>`))
          .concat(["<th class=\"cov-fhead\">缺</th>"]);
        const thead = document.createElement("thead");
        thead.innerHTML = `<tr>${head.join("")}</tr>`;
        table.appendChild(thead);
        const tbody = document.createElement("tbody");
        for (const s of rows) {
          const missing = facets.filter((f) => f !== "default" && !(s.facetSceneCounts || {})[f]).length;
          const tr = document.createElement("tr");
          if (s.lane === "engineering-only") tr.className = "cov-eng";
          const rowhead = document.createElement("td");
          rowhead.className = "cov-rowhead cov-link";
          rowhead.innerHTML = `<span class="cov-crumb">${esc(s.surfaceGroup)}</span><br>${esc(s.surface)}`;
          rowhead.onclick = () => jumpToSurface(s.surfaceKey);
          tr.appendChild(rowhead);
          for (const f of facets) {
            const n = (s.facetSceneCounts || {})[f] || 0;
            const td = document.createElement("td");
            td.className = "cov-cell" + (n ? " cov-has" : " cov-gap");
            td.textContent = n ? String(n) : "·";
            if (n) td.onclick = () => jumpToSurface(s.surfaceKey, f);
            tr.appendChild(td);
          }
          const gap = document.createElement("td");
          gap.className = "cov-cell cov-gapcount" + (missing >= 6 ? " cov-gaphot" : "");
          gap.textContent = String(missing);
          tr.appendChild(gap);
          tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        section.appendChild(table);
        main.appendChild(section);
      }
    }

    function jumpToSurface(surfaceKey, facet) {
      state.view = "gallery";
      state.focus = surfaceKey;
      state.facet = facet || "";
      document.getElementById("facet").value = state.facet;
      if (facet) state.appearance = "both";
      render();
    }

    function syncLaneButtons() {
      document.querySelectorAll("#lane-rail .lane-btn").forEach((b) => b.classList.toggle("active", b.dataset.value === state.lane));
    }

    function render() {
      syncLaneButtons();
      const main = document.getElementById("main");
      main.innerHTML = "";

      if (state.view === "coverage") {
        const covSurfaces = coverageSurfaces();
        document.getElementById("stat-visible").textContent = String(covSurfaces.length);
        const laneLabel = (LANES.find((l) => l.id === state.lane) || LANES[0]).label;
        const top = document.createElement("div");
        top.className = "topbar";
        top.innerHTML = `<div><h2>Coverage · ${laneLabel}</h2><div class="sub">${covSurfaces.length} surface × ${FACET_ORDER.length} facet · 找缺口</div></div>`;
        top.appendChild(viewToggle());
        main.appendChild(top);
        renderCoverage(main);
        mountFeatureNav([]);
        return;
      }

      const groups = visibleSurfaces();
      document.getElementById("stat-visible").textContent = String(groups.length);

      const top = document.createElement("div");
      top.className = "topbar";
      const laneLabel = (LANES.find((l) => l.id === state.lane) || LANES[0]).label;
      const sceneTotal = groups.reduce((n, g) => n + g.scenes.length, 0);
      top.innerHTML = `<div><h2>${state.focus ? "Focus compare" : laneLabel}</h2><div class="sub">${groups.length} surface · ${sceneTotal} state${state.focus ? " · 單一 surface 並排 light/dark" : ""}</div></div>`;
      const toggles = document.createElement("div");
      toggles.style.cssText = "display:flex;gap:10px;align-items:center";
      toggles.appendChild(viewToggle());
      toggles.appendChild(appearanceToggle());
      top.appendChild(toggles);
      main.appendChild(top);

      if (!groups.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "目前沒有符合條件的 surface。調整 lane 或清掉 filter。";
        main.appendChild(empty);
        mountFeatureNav([]);
        return;
      }

      // group surfaces by feature
      const byFeature = new Map();
      for (const g of groups) {
        if (!byFeature.has(g.surface.feature)) byFeature.set(g.surface.feature, []);
        byFeature.get(g.surface.feature).push(g);
      }
      const featureOrder = [...byFeature.keys()].sort();
      for (const feature of featureOrder) {
        const section = document.createElement("section");
        section.className = "feature-section";
        section.id = `feature-${feature.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
        const fGroups = byFeature.get(feature);
        const fScenes = fGroups.reduce((n, g) => n + g.scenes.length, 0);
        const fHero = fGroups.filter((g) => g.surface.heroCandidate).length;
        const fWeak = fGroups.filter((g) => g.surface.lane === "engineering-only").length;
        const header = document.createElement("div");
        header.className = "feature-header";
        header.innerHTML = `<h3>${esc(feature)}</h3><span>${fGroups.length} surface · ${fScenes} state · ${fHero} hero · ${fWeak} eng-only</span>`;
        section.appendChild(header);
        const stack = document.createElement("div");
        stack.className = "surface-stack";
        // Sub-group surfaces by surfaceGroup so a group's variants cluster together
        // (e.g. all "Card Document" surfaces). Single-surface groups stay flat.
        const byGroup = new Map();
        for (const g of fGroups) {
          if (!byGroup.has(g.surface.surfaceGroup)) byGroup.set(g.surface.surfaceGroup, []);
          byGroup.get(g.surface.surfaceGroup).push(g);
        }
        const groupOrder = [...byGroup.keys()].sort();
        for (const groupName of groupOrder) {
          const gSurfaces = byGroup.get(groupName);
          gSurfaces.sort((a, b) => a.surface.lane.localeCompare(b.surface.lane) || a.surface.surface.localeCompare(b.surface.surface));
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
      mountFeatureNav(featureOrder.map((f) => ({ feature: f, count: byFeature.get(f).length })));

      requestAnimationFrame(() => {
        if (location.hash.startsWith("#surface-")) {
          const el = document.querySelector(location.hash);
          if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    }

    function mountFeatureNav(features) {
      const nav = document.getElementById("feature-nav");
      nav.innerHTML = "";
      for (const f of features) {
        const a = document.createElement("a");
        a.className = "nav-link";
        a.href = `#feature-${f.feature.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
        a.innerHTML = `<span>${esc(f.feature)}</span><small>${f.count} surface</small>`;
        nav.appendChild(a);
      }
    }

    mountControls();
    render();
  </script>
</body>
</html>"""
