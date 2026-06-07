from __future__ import annotations

import json


def render_html(manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KG Catalog Review Desk</title>
  <style>
    :root {{
      --bg: #f3efe7;
      --panel: #fffaf2;
      --line: #d8cfc0;
      --ink: #1e1c19;
      --muted: #6d655d;
      --accent: #b54d2e;
      --accent-soft: #f7d8cc;
      --good: #1f6b3a;
      --bad: #8f2d2d;
      --warn: #8a5a0a;
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
      grid-template-columns: 300px 1fr;
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
      background: rgba(255, 250, 242, 0.9);
      backdrop-filter: blur(8px);
    }}
    .sidebar h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1;
    }}
    .sidebar p {{
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.5;
    }}
    .side-block {{
      margin-bottom: 18px;
      padding-bottom: 18px;
      border-bottom: 1px solid rgba(216, 207, 192, 0.8);
    }}
    .stats {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}
    .stat {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 14px;
    }}
    .stat strong {{ display: block; font-size: 22px; }}
    .stat span {{ color: var(--muted); font-size: 12px; }}
    .filters {{
      display: grid;
      gap: 12px;
    }}
    label {{
      display: block;
      margin-bottom: 6px;
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
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
    .promise-buttons, .status-buttons {{
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
    .main {{
      padding: 28px;
    }}
    .lead {{
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr);
      gap: 18px;
      margin-bottom: 28px;
    }}
    .lead-card {{
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 20px;
      background: rgba(255,255,255,0.78);
      box-shadow: 0 10px 25px rgba(31, 22, 13, 0.05);
    }}
    .lead-card h2 {{
      margin: 0 0 10px;
      font-size: 28px;
      line-height: 1.05;
    }}
    .lead-card p {{
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
    .section {{
      margin-bottom: 38px;
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }}
    .section-header h2 {{
      margin: 0;
      font-size: 24px;
    }}
    .section-header span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .cluster-list {{
      display: grid;
      gap: 18px;
    }}
    .cluster {{
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 16px;
      background: rgba(255,255,255,0.68);
    }}
    .cluster-header {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }}
    .cluster-header h3 {{
      margin: 0;
      font-size: 18px;
      line-height: 1.2;
    }}
    .cluster-header p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .cluster-meta {{
      color: var(--muted);
      font-size: 12px;
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
      background: rgba(255,255,255,0.82);
      box-shadow: 0 10px 25px rgba(31, 22, 13, 0.05);
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
      border: 1px dashed var(--line);
      border-radius: 16px;
      padding: 18px;
      color: var(--muted);
      background: rgba(255,255,255,0.5);
    }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .sidebar {{
        position: static;
        height: auto;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      .main {{ padding: 18px; }}
      .lead {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>Catalog Review Desk</h1>
      <p>這不是作品集。這是審稿台。先砍垃圾圖，再挑 promise 候選。</p>
      <div class="side-block">
        <div class="stats">
          <div class="stat"><strong id="total-count">0</strong><span>總圖數</span></div>
          <div class="stat"><strong id="visible-count">0</strong><span>目前可見</span></div>
          <div class="stat"><strong id="shortlist-count">0</strong><span>Shortlist</span></div>
          <div class="stat"><strong id="reject-count">0</strong><span>Reject</span></div>
        </div>
      </div>
      <div class="filters side-block">
        <div>
          <label for="search">搜尋</label>
          <input id="search" type="search" placeholder="scenario / category">
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
          <label>Promise</label>
          <div class="promise-buttons" id="promise-buttons"></div>
        </div>
        <div>
          <label>審稿狀態</label>
          <div class="status-buttons" id="status-buttons"></div>
        </div>
      </div>
      <div class="side-block">
        <label>Promise 導航</label>
        <div class="nav-list" id="promise-nav"></div>
      </div>
    </aside>
    <main class="main" id="app"></main>
  </div>
  <script>
    const manifest = {payload};
    const storageKey = "kg-catalog-review-states";
    const reviewStates = JSON.parse(localStorage.getItem(storageKey) || "{{}}");
    const promiseOrder = ["Read", "Connect", "Retain", "Continue", "Weak"];
    const statusOptions = [
      {{ id: "", label: "全部" }},
      {{ id: "shortlist", label: "Shortlist" }},
      {{ id: "review", label: "Needs Review" }},
      {{ id: "reject", label: "Reject" }}
    ];

    const state = {{
      search: "",
      device: "",
      appearance: "",
      promise: "",
      status: ""
    }};

    const app = document.getElementById("app");
    const totalCount = document.getElementById("total-count");
    const visibleCount = document.getElementById("visible-count");
    const shortlistCount = document.getElementById("shortlist-count");
    const rejectCount = document.getElementById("reject-count");
    totalCount.textContent = String(manifest.totalImages);

    function mountFilterButtons() {{
      const promiseButtons = document.getElementById("promise-buttons");
      const promises = ["", ...promiseOrder.filter((p) => manifest.promiseCounts[p])];
      for (const promise of promises) {{
        const btn = document.createElement("button");
        btn.textContent = promise || "全部";
        btn.dataset.value = promise;
        btn.onclick = () => {{
          state.promise = promise;
          render();
        }};
        promiseButtons.appendChild(btn);
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

      const devices = [...new Set(manifest.items.map((item) => item.device))].sort();
      const deviceSelect = document.getElementById("device");
      for (const device of devices) {{
        const option = document.createElement("option");
        option.value = device;
        option.textContent = device;
        deviceSelect.appendChild(option);
      }}

      document.getElementById("search").addEventListener("input", (e) => {{
        state.search = e.target.value.trim().toLowerCase();
        render();
      }});
      deviceSelect.addEventListener("change", (e) => {{
        state.device = e.target.value;
        render();
      }});
      document.getElementById("appearance").addEventListener("change", (e) => {{
        state.appearance = e.target.value;
        render();
      }});
    }}

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

    function matches(item) {{
      if (state.search) {{
        const hay = `${{item.category}} ${{item.title}} ${{item.assetID}}`.toLowerCase();
        if (!hay.includes(state.search)) return false;
      }}
      if (state.device && item.device !== state.device) return false;
      if (state.appearance && item.appearance !== state.appearance) return false;
      if (state.promise && item.promise !== state.promise) return false;
      if (state.status && currentStatus(item) !== state.status) return false;
      return true;
    }}

    function renderLead(filtered) {{
      const wrap = document.createElement("section");
      wrap.className = "lead";
      const left = document.createElement("div");
      left.className = "lead-card";
      left.innerHTML = `
        <h2>先看承諾，不先看頁面。</h2>
        <p>這裡的工作不是欣賞畫面，而是快速回答三件事：哪一張在賣核心價值、哪一張只是 feature 截圖、哪一張該立刻淘汰。現在的版面把同 promise 的 category 綁在一起，讓你先做決策，再看細節。</p>
      `;
      const right = document.createElement("div");
      right.className = "summary-grid";
      for (const promise of promiseOrder) {{
        const items = filtered.filter((item) => item.promise === promise);
        if (!items.length) continue;
        const box = document.createElement("div");
        box.className = "lead-card";
        box.innerHTML = `<h2>${{items.length}}</h2><p><strong>${{promise}}</strong><br>分類 ${{new Set(items.map((item) => item.category)).size}} 組</p>`;
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
          <h4>${{item.title}}</h4>
          <div class="chips">
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
            <button data-action="copy-link">Permalink</button>
          </div>
        </div>
      `;
      for (const button of wrapper.querySelectorAll(".actions button")) {{
        button.addEventListener("click", () => {{
          const next = button.dataset.state === status ? "" : button.dataset.state;
          setStatus(item, next);
        }});
      }}
      for (const button of wrapper.querySelectorAll(".utility-actions button")) {{
        button.addEventListener("click", async () => {{
          const action = button.dataset.action;
          const permalink = `${{window.location.pathname}}#asset-${{item.assetID}}`;
          const text = action === "copy-link" ? permalink : item.assetID;
          if (navigator.clipboard?.writeText) {{
            await navigator.clipboard.writeText(text);
          }}
        }});
      }}
      return wrapper;
    }}

    function applyHashTarget() {{
      const hash = window.location.hash || "";
      document.querySelectorAll(".card.focused").forEach((card) => card.classList.remove("focused"));
      if (!hash.startsWith("#asset-")) return;
      const assetId = decodeURIComponent(hash.slice("#asset-".length));
      const card = document.getElementById(`asset-${{assetId}}`);
      if (!card) return;
      card.classList.add("focused");
      card.scrollIntoView({{ block: "center", behavior: "smooth" }});
    }}

    function render() {{
      document.querySelectorAll("#promise-buttons button").forEach((btn) => {{
        btn.classList.toggle("active", btn.dataset.value === state.promise);
      }});
      document.querySelectorAll("#status-buttons button").forEach((btn) => {{
        btn.classList.toggle("active", btn.dataset.value === state.status);
      }});

      const filtered = manifest.items.filter(matches);
      visibleCount.textContent = String(filtered.length);
      shortlistCount.textContent = String(manifest.items.filter((item) => currentStatus(item) === "shortlist").length);
      rejectCount.textContent = String(manifest.items.filter((item) => currentStatus(item) === "reject").length);
      app.innerHTML = "";
      document.getElementById("promise-nav").innerHTML = "";

      if (!filtered.length) {{
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = "目前沒有符合條件的圖。";
        app.appendChild(empty);
        return;
      }}

      app.appendChild(renderLead(filtered));

      const grouped = new Map();
      for (const promise of promiseOrder) grouped.set(promise, []);
      for (const item of filtered) grouped.get(item.promise).push(item);

      for (const promise of promiseOrder) {{
        const items = grouped.get(promise);
        if (!items.length) continue;
        const categoryMap = new Map();
        for (const item of items) {{
          if (!categoryMap.has(item.category)) categoryMap.set(item.category, []);
          categoryMap.get(item.category).push(item);
        }}
        const categories = [...categoryMap.entries()].sort((a, b) => {{
          if (b[1].length !== a[1].length) return b[1].length - a[1].length;
          return a[0].localeCompare(b[0]);
        }});

        const section = document.createElement("section");
        section.className = "section";
        section.id = `promise-${{slug(promise)}}`;
        const header = document.createElement("div");
        header.className = "section-header";
        header.innerHTML = `<h2>${{promise}}</h2><span>${{items.length}} 張 / ${{categories.length}} 組</span>`;
        const clusterList = document.createElement("div");
        clusterList.className = "cluster-list";
        for (const [category, bucket] of categories) {{
          bucket.sort((a, b) => `${{a.title}}/${{a.appearance}}/${{a.device}}`.localeCompare(`${{b.title}}/${{b.appearance}}/${{b.device}}`));
          const cluster = document.createElement("article");
          cluster.className = "cluster";
          const clusterHeader = document.createElement("div");
          clusterHeader.className = "cluster-header";
          clusterHeader.innerHTML = `
            <div>
              <h3>${{category}}</h3>
              <p>${{bucket[0].promise}} promise 下的同組變體，請一起看，不要拆散判斷。</p>
            </div>
            <div class="cluster-meta">${{bucket.length}} 張</div>
          `;
          const variantGrid = document.createElement("div");
          variantGrid.className = "variant-grid";
          bucket.forEach((item) => variantGrid.appendChild(card(item)));
          cluster.appendChild(clusterHeader);
          cluster.appendChild(variantGrid);
          clusterList.appendChild(cluster);
        }}
        section.appendChild(header);
        section.appendChild(clusterList);
        app.appendChild(section);

        const nav = document.createElement("a");
        nav.className = "nav-link";
        nav.href = `#promise-${{slug(promise)}}`;
        nav.innerHTML = `<span>${{promise}}</span><small>${{items.length}} 張 / ${{categories.length}} 組</small>`;
        document.getElementById("promise-nav").appendChild(nav);
      }}
      applyHashTarget();
    }}

    window.addEventListener("hashchange", render);
    mountFilterButtons();
    render();
  </script>
</body>
</html>
"""
