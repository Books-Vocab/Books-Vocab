from __future__ import annotations

import hashlib
import html


def esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def status_kind(status: str | None) -> str:
    normalized = str(status or "unknown").lower()
    if normalized in {"ok", "pass", "passed", "success"}:
        return "passed"
    if normalized in {"fail", "failed", "error", "blocked"}:
        return "failed"
    if normalized == "never-run":
        return "pending"
    return "idle"


def status_badge(status: str | None) -> str:
    kind = status_kind(status)
    return f'<span class="badge {kind}">{esc(status or "unknown")}</span>'


def artifact_link(href: str | None, label: str, *, missing_label: str | None = None) -> str:
    if not href:
        return f'<span class="artifact missing">{esc(missing_label or label + " missing")}</span>'
    return f'<a class="artifact" href="{esc(href)}">{esc(label)}</a>'


def dom_id(prefix: str, value: str | None) -> str:
    digest = hashlib.sha1(str(value or "unknown").encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def shell_css() -> str:
    return """
    :root {
      --bg: #f5f6f8;
      --surface: #ffffff;
      --surface-2: #eef2f5;
      --ink: #17212b;
      --ink-soft: #44505c;
      --muted: #6b7580;
      --line: #d8dee6;
      --line-soft: #e8edf2;
      --focus: #1f6feb;
      --passed: #227348;
      --passed-bg: #e7f5ed;
      --failed: #b42318;
      --failed-bg: #fde8e5;
      --pending: #9a6700;
      --pending-bg: #fff4d6;
      --idle: #59636e;
      --idle-bg: #edf1f5;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", system-ui, sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.55;
    }
    a { color: var(--ink); text-decoration-thickness: 1px; text-underline-offset: 2px; }
    code {
      font-family: var(--mono);
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 56px;
      padding: 10px 18px;
      background: rgba(255, 255, 255, .96);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }
    .brand {
      display: flex;
      align-items: baseline;
      gap: 10px;
      min-width: 0;
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .brand span {
      color: var(--muted);
      font-weight: 500;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .btn, .tab {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--ink-soft);
      font-family: var(--mono);
      font-size: 11px;
      text-transform: uppercase;
      text-decoration: none;
      white-space: nowrap;
      cursor: pointer;
    }
    .btn { padding: 0 10px; }
    .tab { padding: 0 12px; }
    .btn:hover, .tab:hover { border-color: var(--ink-soft); color: var(--ink); }
    .tab.active { background: var(--ink); border-color: var(--ink); color: #fff; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 9px;
      font-family: var(--mono);
      font-size: 11px;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .badge.passed { color: var(--passed); background: var(--passed-bg); border-color: #9bd4b3; }
    .badge.failed { color: var(--failed); background: var(--failed-bg); border-color: #f0a8a0; }
    .badge.pending { color: var(--pending); background: var(--pending-bg); border-color: #e7c46a; }
    .badge.idle { color: var(--idle); background: var(--idle-bg); border-color: #cdd5de; }
    .muted, .path, .meta, .empty, .artifact.missing { color: var(--muted); }
    .page {
      max-width: 1440px;
      margin: 0 auto;
      padding: 18px;
    }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(320px, .9fr);
      gap: 14px;
      align-items: stretch;
      margin-bottom: 14px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      min-width: 0;
    }
    .panel.pad { padding: 14px; }
    .eyebrow {
      font-family: var(--mono);
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      margin-bottom: 6px;
    }
    h1, h2, h3, p { margin: 0; }
    h1 {
      font-size: 28px;
      line-height: 1.18;
      font-weight: 700;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }
    h2 {
      font-size: 14px;
      font-family: var(--mono);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    h3 {
      font-size: 15px;
      line-height: 1.3;
      overflow-wrap: anywhere;
    }
    .headline-row {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
    }
    .hero-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
      font-family: var(--mono);
      font-size: 12px;
      color: var(--ink-soft);
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }
    .metric {
      border: 1px solid var(--line-soft);
      border-radius: 7px;
      background: var(--surface-2);
      padding: 9px 10px;
      min-width: 0;
    }
    .metric .value {
      font-family: var(--mono);
      font-size: 24px;
      line-height: 1.1;
      color: var(--ink);
    }
    .metric .label {
      margin-top: 2px;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 10px;
      text-transform: uppercase;
    }
    .tabs, .toolbar {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
      margin: 12px 0;
    }
    .search {
      flex: 1;
      min-width: 260px;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--ink);
      padding: 0 11px;
      font: inherit;
      outline: none;
    }
    .search:focus { border-color: var(--focus); box-shadow: 0 0 0 3px rgba(31, 111, 235, .12); }
    .section {
      margin-top: 16px;
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: baseline;
      margin-bottom: 8px;
    }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }
    table {
      width: 100%;
      min-width: 1040px;
      border-collapse: collapse;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line-soft);
      text-align: left;
      vertical-align: top;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f7f9fb;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 10px;
      text-transform: uppercase;
    }
    tr:last-child td { border-bottom: 0; }
    .card-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      gap: 10px;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      min-width: 0;
    }
    .card.status-failed { border-color: #efb1aa; box-shadow: inset 3px 0 0 var(--failed); }
    .card.status-pending { border-style: dashed; box-shadow: inset 3px 0 0 var(--pending); }
    .card.status-passed { box-shadow: inset 3px 0 0 var(--passed); }
    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 8px;
    }
    .links, .artifact-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 10px;
      font-family: var(--mono);
      font-size: 11px;
    }
    .artifact {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 2px 8px;
      background: var(--surface);
      text-decoration: none;
    }
    .artifact:hover { border-color: var(--ink-soft); }
    .artifact.missing { background: var(--surface-2); }
    .command {
      display: block;
      margin-top: 10px;
      padding: 8px;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      background: #f7f9fb;
      font-family: var(--mono);
      font-size: 11px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .method-list {
      display: grid;
      gap: 3px;
      margin-top: 9px;
      color: var(--ink-soft);
      font-size: 12px;
    }
    .media-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
    }
    figure {
      margin: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
    }
    img, video {
      display: block;
      width: 100%;
      max-height: 620px;
      object-fit: contain;
      background: #111820;
    }
    .shot-button {
      display: block;
      width: 100%;
      padding: 0;
      border: 0;
      background: transparent;
      cursor: zoom-in;
    }
    figcaption {
      display: grid;
      gap: 3px;
      padding: 9px 10px;
      border-top: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 12px;
    }
    .empty {
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 22px;
    }
    .hidden { display: none !important; }
    .modal {
      position: fixed;
      inset: 0;
      z-index: 50;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 22px;
      background: rgba(9, 15, 22, .86);
    }
    .modal.open { display: flex; }
    .modal-inner {
      width: min(1280px, 100%);
      max-height: 94vh;
      border: 1px solid #384656;
      border-radius: 8px;
      background: #101820;
      overflow: hidden;
    }
    .modal-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 10px 12px;
      color: #eef2f5;
      font-family: var(--mono);
      font-size: 12px;
    }
    .modal img {
      max-height: calc(94vh - 48px);
      background: #05070a;
    }
    @media (max-width: 820px) {
      .topbar { align-items: flex-start; flex-direction: column; }
      .top-actions { justify-content: flex-start; }
      .page { padding: 12px; }
      .hero { grid-template-columns: 1fr; }
      .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      h1 { font-size: 22px; }
      .search { min-width: 0; width: 100%; }
      .card-grid, .media-grid { grid-template-columns: 1fr; }
    }
    """


def filter_script(*, total_runs: int, pending_flows: int) -> str:
    return f"""
    const search = document.getElementById('search');
    const tabs = Array.from(document.querySelectorAll('.tab'));
    const rows = Array.from(document.querySelectorAll('.flow-row'));
    const sections = Array.from(document.querySelectorAll('.flow-section'));
    const empty = document.getElementById('empty');
    const visibleCount = document.getElementById('visible-count');
    let activeFilter = 'all';

    function matchesFilter(node) {{
      if (activeFilter === 'all') return true;
      if (activeFilter === 'ran') return node.dataset.ran === 'true';
      return node.dataset.status === activeFilter;
    }}

    function applyFilters() {{
      const q = search.value.trim().toLowerCase();
      let shown = 0;
      rows.forEach((row) => {{
        const ok = matchesFilter(row) && (!q || row.dataset.text.toLowerCase().includes(q));
        row.classList.toggle('hidden', !ok);
        if (ok) shown += 1;
      }});
      sections.forEach((section) => {{
        const ok = matchesFilter(section) && (!q || section.dataset.text.toLowerCase().includes(q));
        section.classList.toggle('hidden', !ok);
      }});
      empty.classList.toggle('hidden', shown !== 0);
      visibleCount.textContent = `${{shown}} flow · {esc(total_runs)} run · {esc(pending_flows)} pending`;
    }}

    tabs.forEach((tab) => {{
      tab.addEventListener('click', () => {{
        activeFilter = tab.dataset.filter;
        tabs.forEach((item) => item.classList.toggle('active', item === tab));
        applyFilters();
      }});
    }});
    search.addEventListener('input', applyFilters);
    applyFilters();
    """


def image_modal_script() -> str:
    return """
    const modal = document.getElementById('image-modal');
    const modalImage = document.getElementById('modal-image');
    const modalTitle = document.getElementById('modal-title');
    const closeModal = () => {
      modal.classList.remove('open');
      modalImage.removeAttribute('src');
      modalImage.removeAttribute('alt');
    };
    document.querySelectorAll('[data-modal-src]').forEach((button) => {
      button.addEventListener('click', () => {
        modalImage.src = button.dataset.modalSrc;
        modalImage.alt = button.dataset.modalTitle || '';
        modalTitle.textContent = button.dataset.modalTitle || button.dataset.modalSrc;
        modal.classList.add('open');
      });
    });
    modal.addEventListener('click', (event) => {
      if (event.target === modal || event.target.dataset.closeModal === 'true') closeModal();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeModal();
    });
    """
