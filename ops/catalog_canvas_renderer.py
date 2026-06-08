from __future__ import annotations

import json


def render_canvas_html(manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG UI Atlas</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Noto+Sans+TC:wght@300;400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #f8f7f4;
      --surface: #fcfbfa;
      --border: #dbd6cd;
      --border-l: #e8e4db;
      --ink: #2a2520;
      --sub: #7a756c;
      --ink-light: #5a5550;
      --accent: #c0392b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ height: 100%; overflow: hidden; }}
    body {{
      font-family: 'Noto Sans TC', sans-serif;
      background: var(--bg);
      color: var(--ink);
      font-size: 13px;
    }}
    .topbar {{
      position: fixed; top: 0; left: 0; right: 0; height: 44px; z-index: 10;
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 16px; background: var(--surface); border-bottom: 1px solid var(--border);
    }}
    .brand {{
      font-family: 'JetBrains Mono', monospace; font-size: 11px;
      letter-spacing: .14em; text-transform: uppercase;
    }}
    .meta {{
      font-family: 'JetBrains Mono', monospace; font-size: 10px;
      color: var(--sub); letter-spacing: .08em; text-transform: uppercase;
    }}
    .ops {{ display: flex; gap: 6px; }}
    .ops button {{
      height: 28px; padding: 0 10px; border: 1px solid var(--border);
      background: transparent; color: var(--ink-light);
      font-family: 'JetBrains Mono', monospace; font-size: 10px;
      letter-spacing: .10em; text-transform: uppercase;
      border-radius: 2px; cursor: pointer;
    }}
    .ops button:hover {{ border-color: var(--ink); color: var(--ink); }}
    #canvas {{
      position: fixed; top: 44px; left: 0; right: 0; bottom: 0;
      cursor: grab;
    }}
    #canvas.dragging {{ cursor: grabbing; }}
    .nodepath {{
      position: fixed; bottom: 12px; left: 16px;
      font-family: 'JetBrains Mono', monospace; font-size: 10px;
      color: var(--sub); letter-spacing: .04em;
      background: var(--surface); border: 1px solid var(--border);
      padding: 4px 8px; border-radius: 2px; max-width: 60vw;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .hint {{
      position: fixed; bottom: 12px; right: 16px;
      font-family: 'JetBrains Mono', monospace; font-size: 9px;
      color: var(--sub); letter-spacing: .08em; text-transform: uppercase;
    }}
    /* SVG node styling */
    .edge {{ stroke: var(--border); stroke-width: 1; fill: none; }}
    .node-shell {{ fill: var(--surface); stroke: var(--border); stroke-width: 1; }}
    .node-shell.expanded {{ stroke: var(--ink); }}
    .node-shell.focused {{ stroke: var(--accent); stroke-width: 2; }}
    .node-label {{
      font-family: 'Noto Sans TC', sans-serif; font-size: 12px;
      fill: var(--ink); pointer-events: none;
    }}
    .node-sub {{
      font-family: 'JetBrains Mono', monospace; font-size: 9px;
      fill: var(--sub); letter-spacing: .08em; text-transform: uppercase;
      pointer-events: none;
    }}
    .node-asset {{ cursor: zoom-in; }}
    .node-branch {{ cursor: pointer; }}
    .node-branch:hover .node-shell {{ stroke: var(--ink); }}
    .node-asset:hover .node-shell {{ stroke: var(--accent); }}
    image {{ image-rendering: -webkit-optimize-contrast; }}
  </style>
</head>
<body>
  <div class="topbar">
    <div>
      <span class="brand">KG · UI ATLAS</span>
      <span class="meta" id="counts"></span>
    </div>
    <div class="ops">
      <button id="op-collapse">Collapse</button>
      <button id="op-expand">Expand L1</button>
      <button id="op-fit">Fit</button>
    </div>
  </div>
  <svg id="canvas" xmlns="http://www.w3.org/2000/svg">
    <g id="viewport">
      <g id="edges"></g>
      <g id="nodes"></g>
    </g>
  </svg>
  <div class="nodepath" id="path-readout">/</div>
  <div class="hint">drag · wheel zoom · click branch · dbl-click asset</div>
  <script>
    const manifest = {payload};
    const tree = manifest.tree;
    const counts = document.getElementById("counts");
    counts.textContent = `${{manifest.totalImages}} assets · ${{(tree.children || []).length}} features`;

    const COLS = {{ root: 0, feature: 1, surface: 2, state: 3, asset: 4 }};
    const COL_X = 280;
    const ROW_Y = 44;
    const ASSET_W = 80;
    const ASSET_H = 168;
    const BRANCH_W = 220;
    const BRANCH_H = 36;

    const expanded = new Set([""]);
    let focused = "";
    const nodeIndex = new Map();
    function index(node) {{
      nodeIndex.set(node.nodePath, node);
      for (const child of node.children || []) index(child);
    }}
    index(tree);

    function isExpanded(path) {{ return expanded.has(path); }}
    function toggle(path) {{
      if (expanded.has(path)) expanded.delete(path);
      else expanded.add(path);
    }}
    function expandAncestors(path) {{
      if (!path) return;
      const parts = path.split("/");
      let acc = "";
      expanded.add("");
      for (let i = 0; i < parts.length - 1; i++) {{
        acc = acc ? `${{acc}}/${{parts[i]}}` : parts[i];
        expanded.add(acc);
      }}
    }}

    // Layout: vertical stacking. Each node owns a "span" = total rows it occupies when expanded.
    function spanOf(node) {{
      if (node.kind === "asset") return 1;
      if (!isExpanded(node.nodePath) || !(node.children || []).length) return 1;
      let s = 0;
      for (const child of node.children) s += spanOf(child);
      return Math.max(s, 1);
    }}

    function layout() {{
      const positions = new Map();
      let cursor = 0;
      function place(node, depth) {{
        const span = spanOf(node);
        const yCenter = (cursor + span / 2) * ROW_Y;
        positions.set(node.nodePath, {{ x: depth * COL_X, y: yCenter, span, depth, node }});
        if (isExpanded(node.nodePath)) {{
          for (const child of node.children || []) place(child, depth + 1);
        }} else {{
          cursor += span;
          return;
        }}
        if (!(node.children || []).length) cursor += span;
      }}
      place(tree, 0);
      // place() advances cursor on leaves and collapsed nodes only; ensure root advanced too
      return positions;
    }}

    const svg = document.getElementById("canvas");
    const viewport = document.getElementById("viewport");
    const edgesG = document.getElementById("edges");
    const nodesG = document.getElementById("nodes");

    function render() {{
      const positions = layout();
      edgesG.replaceChildren();
      nodesG.replaceChildren();

      for (const {{ x, y, depth, node }} of positions.values()) {{
        if (!node.nodePath) continue;
        const parentPath = node.nodePath.includes("/")
          ? node.nodePath.slice(0, node.nodePath.lastIndexOf("/"))
          : "";
        const parent = positions.get(parentPath);
        if (parent) {{
          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          const px = parent.x + (parent.node.kind === "asset" ? ASSET_W : BRANCH_W);
          const mx = (px + x) / 2;
          path.setAttribute("d", `M${{px}},${{parent.y}} C${{mx}},${{parent.y}} ${{mx}},${{y}} ${{x}},${{y}}`);
          path.setAttribute("class", "edge");
          edgesG.appendChild(path);
        }}
      }}

      for (const {{ x, y, node }} of positions.values()) {{
        if (node.kind === "asset") nodesG.appendChild(assetNode(node, x, y));
        else nodesG.appendChild(branchNode(node, x, y));
      }}
    }}

    function branchNode(node, x, y) {{
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "node-branch");
      g.setAttribute("transform", `translate(${{x}},${{y - BRANCH_H / 2}})`);
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("width", BRANCH_W);
      rect.setAttribute("height", BRANCH_H);
      rect.setAttribute("rx", 2);
      let cls = "node-shell";
      if (isExpanded(node.nodePath)) cls += " expanded";
      if (focused === node.nodePath) cls += " focused";
      rect.setAttribute("class", cls);
      g.appendChild(rect);

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("class", "node-label");
      label.setAttribute("x", 12);
      label.setAttribute("y", 16);
      label.textContent = node.label || "KG";
      g.appendChild(label);

      const sub = document.createElementNS("http://www.w3.org/2000/svg", "text");
      sub.setAttribute("class", "node-sub");
      sub.setAttribute("x", 12);
      sub.setAttribute("y", 30);
      const kind = node.kind.toUpperCase();
      const extra = node.kind === "surface" && node.promise ? ` · ${{node.promise}}` : "";
      sub.textContent = `${{kind}} · ${{node.count}}${{extra}}`;
      g.appendChild(sub);

      const chevron = document.createElementNS("http://www.w3.org/2000/svg", "text");
      chevron.setAttribute("class", "node-sub");
      chevron.setAttribute("x", BRANCH_W - 16);
      chevron.setAttribute("y", 24);
      chevron.setAttribute("text-anchor", "end");
      chevron.textContent = (node.children || []).length ? (isExpanded(node.nodePath) ? "−" : "+") : "·";
      g.appendChild(chevron);

      g.addEventListener("click", (e) => {{
        e.stopPropagation();
        toggle(node.nodePath);
        focused = node.nodePath;
        updatePath();
        render();
      }});
      return g;
    }}

    function assetNode(node, x, y) {{
      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("class", "node-asset");
      g.setAttribute("transform", `translate(${{x}},${{y - ASSET_H / 2}})`);
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("width", ASSET_W);
      rect.setAttribute("height", ASSET_H);
      rect.setAttribute("rx", 2);
      let cls = "node-shell";
      if (focused === node.nodePath) cls += " focused";
      rect.setAttribute("class", cls);
      g.appendChild(rect);

      const img = document.createElementNS("http://www.w3.org/2000/svg", "image");
      img.setAttribute("x", 2);
      img.setAttribute("y", 2);
      img.setAttribute("width", ASSET_W - 4);
      img.setAttribute("height", ASSET_H - 28);
      img.setAttribute("preserveAspectRatio", "xMidYMid slice");
      img.setAttributeNS("http://www.w3.org/1999/xlink", "href", node.relPath);
      img.setAttribute("href", node.relPath);
      g.appendChild(img);

      const sub = document.createElementNS("http://www.w3.org/2000/svg", "text");
      sub.setAttribute("class", "node-sub");
      sub.setAttribute("x", 4);
      sub.setAttribute("y", ASSET_H - 8);
      sub.textContent = `${{node.appearance}}`;
      g.appendChild(sub);

      g.addEventListener("click", (e) => {{
        e.stopPropagation();
        focused = node.nodePath;
        updatePath();
        render();
      }});
      g.addEventListener("dblclick", (e) => {{
        e.stopPropagation();
        window.open(node.relPath, "_blank", "noreferrer");
      }});
      return g;
    }}

    // Pan / zoom
    let tx = 80, ty = 60, scale = 1;
    function applyTransform() {{
      viewport.setAttribute("transform", `translate(${{tx}},${{ty}}) scale(${{scale}})`);
    }}
    applyTransform();

    let dragging = false, lastX = 0, lastY = 0;
    svg.addEventListener("mousedown", (e) => {{
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      svg.classList.add("dragging");
    }});
    window.addEventListener("mousemove", (e) => {{
      if (!dragging) return;
      tx += e.clientX - lastX;
      ty += e.clientY - lastY;
      lastX = e.clientX; lastY = e.clientY;
      applyTransform();
    }});
    window.addEventListener("mouseup", () => {{
      dragging = false; svg.classList.remove("dragging");
    }});
    svg.addEventListener("wheel", (e) => {{
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const next = Math.max(0.15, Math.min(3.0, scale * (e.deltaY > 0 ? 0.9 : 1.1)));
      tx = mx - ((mx - tx) * (next / scale));
      ty = my - ((my - ty) * (next / scale));
      scale = next;
      applyTransform();
    }}, {{ passive: false }});

    document.getElementById("op-collapse").onclick = () => {{
      expanded.clear(); expanded.add(""); render();
    }};
    document.getElementById("op-expand").onclick = () => {{
      expanded.clear(); expanded.add("");
      for (const child of (tree.children || [])) expanded.add(child.nodePath);
      render();
    }};
    document.getElementById("op-fit").onclick = () => {{
      tx = 80; ty = 60; scale = 1; applyTransform();
    }};

    function updatePath() {{
      const node = nodeIndex.get(focused);
      const readout = document.getElementById("path-readout");
      readout.textContent = focused ? `/${{focused}}` : "/";
      if (node && node.kind === "asset") readout.textContent += `  →  ${{node.relPath}}`;
      if (focused) window.history.replaceState(null, "", `#node=${{encodeURIComponent(focused)}}`);
    }}

    function initFromHash() {{
      const match = window.location.hash.match(/^#node=(.+)$/);
      if (!match) return;
      const path = decodeURIComponent(match[1]);
      if (!nodeIndex.has(path)) return;
      expandAncestors(path);
      const node = nodeIndex.get(path);
      if (node && node.children && node.children.length) expanded.add(path);
      focused = path;
    }}

    initFromHash();
    render();
    updatePath();
  </script>
</body>
</html>"""
