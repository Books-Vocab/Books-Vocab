from __future__ import annotations

import json


def render_html(manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG UI Asset Gallery</title>
  <style>
    :root {{
      --bg: #f3efe7;
      --panel: rgba(255, 251, 245, 0.86);
      --line: #d8cfc0;
      --line-strong: #c8baa5;
      --ink: #1e1c19;
      --muted: #6d655d;
      --accent: #9a4b1f;
      --accent-soft: #f5dfcf;
      --accent-wash: #fff4eb;
      --good: #1f6b3a;
      --bad: #8f2d2d;
      --warn: #8a5a0a;
      --shadow: 0 18px 40px rgba(31, 22, 13, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino", "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, #fff7e9 0, transparent 34%),
        linear-gradient(180deg, #f6f0e6 0%, #efe7db 100%);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 320px 1fr;
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      align-self: start;
      height: 100vh;
      overflow: auto;
      padding: 24px 20px;
      border-right: 1px solid var(--line);
      background: rgba(255, 249, 241, 0.92);
      backdrop-filter: blur(10px);
    }}
    .sidebar h1 {{
      margin: 0 0 8px;
      font-size: 30px;
      line-height: 0.95;
    }}
    .sidebar p {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }}
    .side-block {{
      margin-bottom: 20px;
      padding-bottom: 18px;
      border-bottom: 1px solid rgba(216, 207, 192, 0.85);
    }}
    .stats {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}
    .stat {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      background: white;
      border-radius: 16px;
    }}
    .stat strong {{
      display: block;
      font-size: 22px;
      line-height: 1;
    }}
    .stat span {{
      color: var(--muted);
      font-size: 12px;
    }}
    label {{
      display: block;
      margin-bottom: 6px;
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .filters {{
      display: grid;
      gap: 12px;
    }}
    input, select {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      font: inherit;
    }}
    button {{
      cursor: pointer;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 12px;
      font: inherit;
    }}
    button.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .button-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .nav-list {{
      display: grid;
      gap: 8px;
    }}
    .nav-link {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: white;
      color: var(--ink);
      text-decoration: none;
      font-size: 14px;
    }}
    .nav-link small {{
      color: var(--muted);
      font-size: 12px;
    }}
    .main {{
      padding: 28px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.7fr) minmax(280px, 1fr);
      gap: 18px;
      margin-bottom: 26px;
    }}
    .hero-card {{
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 22px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }}
    .hero-card h2 {{
      margin: 0 0 10px;
      font-size: 30px;
      line-height: 1;
    }}
    .hero-card p {{
      margin: 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.6;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .summary-card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: white;
    }}
    .summary-card strong {{
      display: block;
      font-size: 24px;
      line-height: 1;
      margin-bottom: 6px;
    }}
    .summary-card span {{
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }}
    .section {{
      margin-bottom: 34px;
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 16px;
      border-bottom: 1px solid var(--line-strong);
      padding-bottom: 10px;
      margin-bottom: 14px;
    }}
    .section-header h2 {{
      margin: 0;
      font-size: 26px;
      line-height: 1.05;
    }}
    .section-header span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .surface-stack {{
      display: grid;
      gap: 16px;
    }}
    .surface {{
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 16px;
      background: rgba(255, 255, 255, 0.75);
      box-shadow: 0 12px 28px rgba(31, 22, 13, 0.05);
    }}
    .surface-header {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }}
    .surface-header h3 {{
      margin: 0;
      font-size: 19px;
      line-height: 1.15;
    }}
    .surface-header p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .surface-meta {{
      color: var(--muted);
      font-size: 12px;
      text-align: right;
      white-space: nowrap;
    }}
    .variant-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 12px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      background: white;
      box-shadow: 0 10px 24px rgba(31, 22, 13, 0.05);
    }}
    .card.focused {{
      outline: 3px solid var(--accent);
      outline-offset: 3px;
    }}
    .card img {{
      display: block;
      width: 100%;
      aspect-ratio: 1179 / 2556;
      object-fit: cover;
      background: #ddd7cf;
    }}
    .meta {{
      padding: 12px;
      display: grid;
      gap: 8px;
    }}
    .meta h4 {{
      margin: 0;
      font-size: 15px;
      line-height: 1.25;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .chip {{
      padding: 4px 8px;
      border-radius: 999px;
      background: #f4ede4;
      color: var(--muted);
      font-size: 11px;
      border: 1px solid #eadfce;
    }}
    .chip.mono {{
      font-family: "SF Mono", "Menlo", "Monaco", monospace;
      font-size: 10px;
    }}
    .actions {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }}
    .actions button {{
      padding: 8px 0;
      border-radius: 10px;
      font-size: 13px;
    }}
    .actions button[data-state="shortlist"].selected {{ background: #e3f3e8; color: var(--good); border-color: #b8d8c3; }}
    .actions button[data-state="review"].selected {{ background: #fff0cf; color: var(--warn); border-color: #e8ca82; }}
    .actions button[data-state="reject"].selected {{ background: #f7dddd; color: var(--bad); border-color: #e6b6b6; }}
    .utility-actions {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .utility-actions button {{
      padding: 8px 0;
      border-radius: 10px;
      font-size: 12px;
    }}
    .empty {{
      border: 1px dashed var(--line-strong);
      border-radius: 18px;
      padding: 18px;
      color: var(--muted);
      background: rgba(255,255,255,0.55);
    }}
    @media (max-width: 1024px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      .main {{ padding: 18px; }}
      .hero {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>KG UI Asset Gallery</h1>
      <p>這不是 996 張平鋪圖牆。這是離線 UI 資產系統：先看 feature 與 surface，再看 state，最後才看單張截圖。</p>
      <div class="side-block">
        <div class="stats">
          <div class="stat"><strong id="total-count">0</strong><span>總資產</span></div>
          <div class="stat"><strong id="visible-count">0</strong><span>目前可見</span></div>
          <div class="stat"><strong id="feature-count">0</strong><span>Feature</span></div>
          <div class="stat"><strong id="surface-count">0</strong><span>Surface</span></div>
        </div>
      </div>
      <div class="filters side-block">
        <div>
          <label for="search">搜尋</label>
          <input id="search" type="search" placeholder="feature / surface / state / asset id">
        </div>
        <div>
          <label for="feature">Feature</label>
          <select id="feature"><option value="">全部</option></select>
        </div>
        <div>
          <label for="promise">Promise</label>
          <select id="promise"><option value="">全部</option></select>
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
          <label for="kind">Kind</label>
          <select id="kind">
            <option value="">全部</option>
            <option value="screen">Screen</option>
            <option value="scene">Scene</option>
            <option value="overlay">Overlay</option>
            <option value="component">Component</option>
          </select>
        </div>
        <div>
          <label for="device">裝置</label>
          <select id="device"><option value="">全部</option></select>
        </div>
        <div>
          <label for="appearance">外觀</label>
          <select id="appearance">
            <option value="">全部</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
        <div>
          <label>視角</label>
          <div class="button-row" id="mode-buttons"></div>
        </div>
        <div>
          <label>審稿狀態</label>
          <div class="button-row" id="status-buttons"></div>
        </div>
      </div>
      <div class="side-block">
        <label>導航</label>
        <div class="nav-list" id="group-nav"></div>
      </div>
    </aside>
    <main class="main" id="app"></main>
  </div>
  <script>
    const manifest = {payload};
    const storageKey = "kg-catalog-review-states";
    const reviewStates = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
    const promiseOrder = ["Read", "Connect", "Retain", "Continue", "Weak"];
    const modeOptions = [
      {{ id: "feature", label: "Feature" }},
      {{ id: "surface", label: "Surface" }},
      {{ id: "promise", label: "Promise" }}
    ];
    const statusOptions = [
      {{ id: "", label: "全部" }},
      {{ id: "shortlist", label: "Shortlist" }},
      {{ id: "review", label: "Needs Review" }},
      {{ id: "reject", label: "Reject" }}
    ];
    const state = {{
      search: "",
      feature: "",
      promise: "",
      eligibility: "",
      kind: "",
      device: "",
      appearance: "",
      status: "",
      mode: "feature"
    }};

    const app = document.getElementById("app");
    const totalCount = document.getElementById("total-count");
    const visibleCount = document.getElementById("visible-count");
    const featureCount = document.getElementById("feature-count");
    const surfaceCount = document.getElementById("surface-count");
    totalCount.textContent = String(manifest.totalImages);
    featureCount.textContent = String(Object.keys(manifest.featureCounts || {{}}).length);
    surfaceCount.textContent = String(Object.keys(manifest.surfaceCounts || {{}}).length);

    function slug(text) {{
      return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    }}

    function currentStatus(item) {{
      return reviewStates[item.assetID] || item.reviewStatus || "";
    }}

    function setStatus(item, next) {{
      if (next) {{
        reviewStates[item.assetID] = next;
      }} else {{
        delete reviewStates[item.assetID];
      }}
      localStorage.setItem(storageKey, JSON.stringify(reviewStates));
      render();
    }}

    function mountControls() {{
      const featureSelect = document.getElementById("feature");
      for (const feature of Object.keys(manifest.featureCounts || {{}}).sort()) {{
        const option = document.createElement("option");
        option.value = feature;
        option.textContent = feature;
        featureSelect.appendChild(option);
      }}
      featureSelect.addEventListener("change", (e) => {{
        state.feature = e.target.value;
        render();
      }});

      const promiseSelect = document.getElementById("promise");
      for (const promise of promiseOrder.filter((name) => manifest.promiseCounts[name])) {{
        const option = document.createElement("option");
        option.value = promise;
        option.textContent = promise;
        promiseSelect.appendChild(option);
      }}
      promiseSelect.addEventListener("change", (e) => {{
        state.promise = e.target.value;
        render();
      }});

      const deviceSelect = document.getElementById("device");
      for (const device of [...new Set(manifest.items.map((item) => item.device))].sort()) {{
        const option = document.createElement("option");
        option.value = device;
        option.textContent = device;
        deviceSelect.appendChild(option);
      }}
      deviceSelect.addEventListener("change", (e) => {{
        state.device = e.target.value;
        render();
      }});

      document.getElementById("eligibility").addEventListener("change", (e) => {{
        state.eligibility = e.target.value;
        render();
      }});
      document.getElementById("kind").addEventListener("change", (e) => {{
        state.kind = e.target.value;
        render();
      }});
      document.getElementById("appearance").addEventListener("change", (e) => {{
        state.appearance = e.target.value;
        render();
      }});
      document.getElementById("search").addEventListener("input", (e) => {{
        state.search = e.target.value.trim().toLowerCase();
        render();
      }});

      const modeButtons = document.getElementById("mode-buttons");
      for (const mode of modeOptions) {{
        const btn = document.createElement("button");
        btn.textContent = mode.label;
        btn.dataset.value = mode.id;
        btn.onclick = () => {{
          state.mode = mode.id;
          render();
        }};
        modeButtons.appendChild(btn);
      }}

      const statusButtons = document.getElementById("status-buttons");
      for (const option of statusOptions) {{
        const btn = document.createElement("button");
        btn.textContent = option.label;
        btn.dataset.value = option.id;
        btn.onclick = () => {{
          state.status = option.id;
          render();
        }};
        statusButtons.appendChild(btn);
      }}
    }}

    function matches(item) {{
      if (state.search) {{
        const hay = `${{item.feature}} ${{item.surface}} ${{item.surfaceVariant}} ${{item.title}} ${{item.category}} ${{item.assetID}}`.toLowerCase();
        if (!hay.includes(state.search)) return false;
      }}
      if (state.feature && item.feature !== state.feature) return false;
      if (state.promise && item.promise !== state.promise) return false;
      if (state.eligibility && item.eligibility !== state.eligibility) return false;
      if (state.kind && item.assetKind !== state.kind) return false;
      if (state.device && item.device !== state.device) return false;
      if (state.appearance && item.appearance !== state.appearance) return false;
      if (state.status && currentStatus(item) !== state.status) return false;
      return true;
    }}

    function countByStatus(items, target) {{
      return items.filter((item) => currentStatus(item) === target).length;
    }}

    function renderHero(filtered) {{
      const wrap = document.createElement("section");
      wrap.className = "hero";
      const left = document.createElement("div");
      left.className = "hero-card";
      left.innerHTML = `
        <h2>UI 不是圖庫，是資產系統。</h2>
        <p>這裡先按 feature 與 surface 管理畫面，再看 state 與變體。promise 仍保留，但退到輔助視角；它不再主宰資訊架構。你現在可以在不開 app 的前提下，直接瀏覽哪個功能有多少 surface、每個 surface 有哪些 state，以及哪些只是 engineering coverage。</p>
      `;
      const right = document.createElement("div");
      right.className = "summary-grid";
      const cards = [
        {{ label: "目前可見", value: filtered.length }},
        {{ label: "Feature", value: new Set(filtered.map((item) => item.feature)).size }},
        {{ label: "Surface", value: new Set(filtered.map((item) => item.surfaceKey)).size }},
        {{ label: "Shortlist", value: countByStatus(filtered, "shortlist") }},
      ];
      for (const card of cards) {{
        const box = document.createElement("div");
        box.className = "summary-card";
        box.innerHTML = `<strong>${{card.value}}</strong><span>${{card.label}}</span>`;
        right.appendChild(box);
      }}
      wrap.appendChild(left);
      wrap.appendChild(right);
      return wrap;
    }}

    function card(item) {{
      const status = currentStatus(item);
      const wrapper = document.createElement("article");
      wrapper.className = "card";
      wrapper.id = `asset-${{item.assetID}}`;
      wrapper.innerHTML = `
        <a href="${{item.relPath}}" target="_blank" rel="noreferrer">
          <img loading="lazy" src="${{item.relPath}}" alt="${{item.category}} / ${{item.title}}">
        </a>
        <div class="meta">
          <h4>${{item.stateLabel}}</h4>
          <div class="chips">
            <span class="chip">${{item.feature}}</span>
            <span class="chip">${{item.surfaceRole}}</span>
            <span class="chip">${{item.device}}</span>
            <span class="chip">${{item.appearance}}</span>
            <span class="chip mono">${{item.assetID}}</span>
          </div>
          <div class="actions">
            <button data-state="shortlist" class="${{status === "shortlist" ? "selected" : ""}}">留</button>
            <button data-state="review" class="${{status === "review" ? "selected" : ""}}">再看</button>
            <button data-state="reject" class="${{status === "reject" ? "selected" : ""}}">砍</button>
          </div>
          <div class="utility-actions">
            <button data-action="copy-id">Copy ID</button>
            <button data-action="permalink">Permalink</button>
          </div>
        </div>
      `;
      wrapper.querySelectorAll(".actions button").forEach((button) => {{
        button.onclick = () => setStatus(item, button.dataset.state === status ? "" : button.dataset.state);
      }});
      wrapper.querySelector('[data-action="copy-id"]').onclick = async () => {{
        await navigator.clipboard.writeText(item.assetID);
      }};
      wrapper.querySelector('[data-action="permalink"]').onclick = async () => {{
        const url = `${{window.location.origin}}${{window.location.pathname}}#asset-${{item.assetID}}`;
        await navigator.clipboard.writeText(url);
        window.location.hash = `asset-${{item.assetID}}`;
      }};
      return wrapper;
    }}

    function groupBy(items, keyFn) {{
      const map = new Map();
      for (const item of items) {{
        const key = keyFn(item);
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(item);
      }}
      return map;
    }}

    function renderSurface(surfaceItems) {{
      const first = surfaceItems[0];
      const wrap = document.createElement("article");
      wrap.className = "surface";
      wrap.id = `section-${{first.surfaceKey}}`;
      const states = [...new Set(surfaceItems.map((item) => item.stateGroup))].filter(Boolean);
      const marketing = surfaceItems.filter((item) => item.eligibility === "marketing").length;
      wrap.innerHTML = `
        <div class="surface-header">
          <div>
            <h3>${{first.surface}}</h3>
            <p>${{first.feature}} · ${{first.promise}} · ${{first.assetKind}} · ${{first.surfaceRole}}</p>
          </div>
          <div class="surface-meta">${{surfaceItems.length}} 張 · ${{states.length}} 個 state 群 · marketing ${{marketing}}</div>
        </div>
      `;
      const grid = document.createElement("div");
      grid.className = "variant-grid";
      for (const item of surfaceItems.sort((a, b) => a.stateLabel.localeCompare(b.stateLabel) || a.device.localeCompare(b.device) || a.appearance.localeCompare(b.appearance))) {{
        grid.appendChild(card(item));
      }}
      wrap.appendChild(grid);
      return wrap;
    }}

    function buildSections(items) {{
      if (state.mode === "surface") {{
        return [...groupBy(items, (item) => item.surfaceKey).entries()]
          .sort((a, b) => a[1][0].surface.localeCompare(b[1][0].surface))
          .map(([key, grouped]) => ({{
            id: key,
            title: grouped[0].surface,
            meta: `${{grouped[0].feature}} · ${{grouped.length}} 張`,
            surfaces: [grouped]
          }}));
      }}
      if (state.mode === "promise") {{
        return promiseOrder
          .filter((promise) => items.some((item) => item.promise === promise))
          .map((promise) => {{
            const promiseItems = items.filter((item) => item.promise === promise);
            const surfaces = [...groupBy(promiseItems, (item) => item.surfaceKey).values()]
              .sort((a, b) => a[0].surface.localeCompare(b[0].surface));
            return {{
              id: slug(promise),
              title: promise,
              meta: `${{promiseItems.length}} 張 · ${{surfaces.length}} 個 surface`,
              surfaces
            }};
          }});
      }}
      return [...groupBy(items, (item) => item.feature).entries()]
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([feature, featureItems]) => {{
          const surfaces = [...groupBy(featureItems, (item) => item.surfaceKey).values()]
            .sort((a, b) => a[0].surface.localeCompare(b[0].surface));
          return {{
            id: slug(feature),
            title: feature,
            meta: `${{featureItems.length}} 張 · ${{surfaces.length}} 個 surface`,
            surfaces
          }};
        }});
    }}

    function mountNav(sections) {{
      const nav = document.getElementById("group-nav");
      nav.innerHTML = "";
      for (const section of sections) {{
        const link = document.createElement("a");
        link.className = "nav-link";
        link.href = `#section-${{section.id}}`;
        link.innerHTML = `<span>${{section.title}}</span><small>${{section.meta}}</small>`;
        nav.appendChild(link);
      }}
    }}

    function renderSections(filtered) {{
      const sections = buildSections(filtered);
      mountNav(sections);
      if (!sections.length) {{
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "目前沒有符合條件的資產。";
        return empty;
      }}
      const wrap = document.createElement("div");
      for (const section of sections) {{
        const sectionEl = document.createElement("section");
        sectionEl.className = "section";
        sectionEl.id = `section-${{section.id}}`;
        sectionEl.innerHTML = `
          <div class="section-header">
            <h2>${{section.title}}</h2>
            <span>${{section.meta}}</span>
          </div>
        `;
        const stack = document.createElement("div");
        stack.className = "surface-stack";
        for (const surfaceItems of section.surfaces) {{
          stack.appendChild(renderSurface(surfaceItems));
        }}
        sectionEl.appendChild(stack);
        wrap.appendChild(sectionEl);
      }}
      return wrap;
    }}

    function syncButtons() {{
      document.querySelectorAll("#mode-buttons button").forEach((button) => {{
        button.classList.toggle("active", button.dataset.value === state.mode);
      }});
      document.querySelectorAll("#status-buttons button").forEach((button) => {{
        button.classList.toggle("active", button.dataset.value === state.status);
      }});
    }}

    function render() {{
      syncButtons();
      const filtered = manifest.items.filter(matches);
      visibleCount.textContent = String(filtered.length);
      app.innerHTML = "";
      app.appendChild(renderHero(filtered));
      app.appendChild(renderSections(filtered));
      requestAnimationFrame(() => {{
        if (window.location.hash.startsWith("#asset-")) {{
          const target = document.querySelector(window.location.hash);
          if (target) target.classList.add("focused");
        }}
      }});
    }}

    mountControls();
    render();
  </script>
</body>
</html>"""
