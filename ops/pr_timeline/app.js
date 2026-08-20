(function () {
  "use strict";

  const HOUR_MS = 60 * 60 * 1000;
  const DAY_MS = 24 * HOUR_MS;
  const LINE_INSET = 24;
  const LINE_Y = 76;
  const TIMELINE_HEIGHT = 156;
  const TICK_INTERVALS = [
    HOUR_MS,
    3 * HOUR_MS,
    6 * HOUR_MS,
    12 * HOUR_MS,
    DAY_MS,
    2 * DAY_MS,
    7 * DAY_MS,
    14 * DAY_MS,
    30 * DAY_MS,
    90 * DAY_MS,
    180 * DAY_MS,
    365 * DAY_MS,
  ];

  const elements = {
    details: document.getElementById("details"),
    notice: document.getElementById("notice"),
    range: document.getElementById("range"),
    refresh: document.getElementById("refresh"),
    summary: document.getElementById("summary"),
    timeline: document.getElementById("timeline"),
    rule: document.getElementById("timeline-rule"),
    timelineViewport: document.getElementById("timeline-viewport"),
    tooltip: document.getElementById("timeline-tooltip"),
    updated: document.getElementById("updated"),
    zoom: document.getElementById("zoom"),
    zoomValue: document.getElementById("zoom-value"),
  };

  const state = {
    hasInitialScroll: false,
    records: [],
    selectedNumber: null,
    zoom: Number(elements.zoom.value),
  };

  function dateValue(value) {
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : null;
    }
    const parsed = Date.parse(value || "");
    return Number.isFinite(parsed) ? parsed : null;
  }

  function localDate(value, options) {
    const parsed = dateValue(value);
    if (parsed === null) return "—";
    return new Intl.DateTimeFormat(undefined, options).format(parsed);
  }

  function shortTime(value) {
    return localDate(value, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function longTime(value) {
    return localDate(value, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  function rangeDate(value) {
    return localDate(value, { year: "numeric", month: "short", day: "numeric" });
  }

  function setNotice(message) {
    elements.notice.textContent = message || "";
    elements.notice.hidden = !message;
  }

  function validRecords(records) {
    return records
      .filter((record) => record && Number.isInteger(Number(record.number)) && dateValue(record.merged_at) !== null)
      .map((record) => ({ ...record, number: Number(record.number) }))
      .sort((left, right) => dateValue(left.merged_at) - dateValue(right.merged_at));
  }

  function safePullUrl(record) {
    try {
      const url = new URL(record.url);
      if (url.protocol !== "https:" || url.hostname !== "github.com") return null;
      if (!/^\/Books-Vocab\/Books-Vocab\/pull\/\d+$/.test(url.pathname)) return null;
      return url.href;
    } catch (_error) {
      return null;
    }
  }

  function tickInterval() {
    const minimumSpacing = 104;
    return TICK_INTERVALS.find((interval) => (interval / HOUR_MS) * state.zoom >= minimumSpacing)
      || TICK_INTERVALS[TICK_INTERVALS.length - 1];
  }

  function tickLabel(time, interval) {
    return interval >= DAY_MS
      ? localDate(time, { month: "short", day: "numeric" })
      : localDate(time, { month: "short", day: "numeric", hour: "2-digit" });
  }

  function createTick(time, start, duration, width, interval) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = `${LINE_INSET + ((time - start) / duration) * (width - LINE_INSET * 2)}px`;

    const label = document.createElement("span");
    label.className = "tick-label";
    label.textContent = tickLabel(time, interval);
    tick.appendChild(label);
    return tick;
  }

  function showTooltip(record, marker) {
    const x = Number.parseFloat(marker.style.left);
    const timelineWidth = elements.timeline.clientWidth;
    const tooltipX = Math.min(Math.max(x, 100), Math.max(100, timelineWidth - 100));
    elements.tooltip.textContent = `#${record.number} · ${shortTime(record.merged_at)}`;
    elements.tooltip.style.left = `${tooltipX}px`;
    elements.tooltip.style.top = `${Math.max(18, LINE_Y - 12)}px`;
    elements.tooltip.hidden = false;
  }

  function hideTooltip() {
    elements.tooltip.hidden = true;
  }

  function selectRecord(record) {
    state.selectedNumber = record.number;
    document.querySelectorAll(".pr-marker").forEach((marker) => {
      marker.classList.toggle("is-selected", Number(marker.dataset.number) === state.selectedNumber);
    });

    elements.details.replaceChildren();
    elements.details.hidden = false;

    const line = document.createElement("div");
    line.className = "details-line";
    const primary = document.createElement("span");
    primary.className = "detail-primary";
    primary.textContent = `#${record.number} ${record.title || "Untitled PR"}`;
    line.appendChild(primary);

    const secondary = document.createElement("span");
    secondary.className = "detail-secondary";
    secondary.textContent = `${longTime(record.merged_at)} · ${record.author || "unknown"}`;
    line.appendChild(secondary);

    const url = safePullUrl(record);
    if (url) {
      const link = document.createElement("a");
      link.className = "pr-link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = "↗";
      link.setAttribute("aria-label", `Open PR ${record.number} on GitHub`);
      line.appendChild(link);
    }
    elements.details.appendChild(line);
  }

  function renderTimeline() {
    const records = state.records;
    const wasAtLatest = elements.timelineViewport.scrollLeft + elements.timelineViewport.clientWidth
      >= elements.timelineViewport.scrollWidth - 24;
    elements.timeline.replaceChildren(elements.rule, elements.tooltip);
    hideTooltip();

    if (records.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No merged PRs";
      elements.timeline.appendChild(empty);
      elements.details.replaceChildren();
      elements.details.hidden = true;
      elements.timeline.style.width = "100%";
      elements.timeline.style.height = `${TIMELINE_HEIGHT}px`;
      elements.timeline.style.setProperty("--line-y", `${LINE_Y}px`);
      return;
    }

    const times = records.map((record) => dateValue(record.merged_at));
    const first = Math.min(...times);
    const last = Math.max(...times);
    const interval = tickInterval();
    const paddingMs = Math.max(DAY_MS, interval);
    const start = Math.floor((first - paddingMs) / interval) * interval;
    const end = Math.ceil((last + paddingMs) / interval) * interval;
    const duration = Math.max(end - start, HOUR_MS);
    const availableWidth = Math.max(elements.timelineViewport.clientWidth, 640);
    const width = Math.max(availableWidth, Math.ceil((duration / HOUR_MS) * state.zoom) + LINE_INSET * 2);
    const lineY = LINE_Y;

    elements.timeline.style.width = `${width}px`;
    elements.timeline.style.height = `${TIMELINE_HEIGHT}px`;
    elements.timeline.style.setProperty("--line-y", `${lineY}px`);
    elements.timeline.style.setProperty("--line-inset", `${LINE_INSET}px`);

    for (let time = start; time <= end; time += interval) {
      elements.timeline.appendChild(createTick(time, start, duration, width, interval));
    }

    records.forEach((record, index) => {
      const marker = document.createElement("button");
      const x = LINE_INSET + ((dateValue(record.merged_at) - start) / duration) * (width - LINE_INSET * 2);
      marker.type = "button";
      marker.className = "pr-marker";
      marker.dataset.number = String(record.number);
      marker.style.left = `${x}px`;
      marker.style.top = `${lineY}px`;
      marker.style.zIndex = String(index + 2);
      marker.title = `#${record.number} · ${longTime(record.merged_at)}`;
      marker.setAttribute("aria-label", `PR ${record.number}, merged ${longTime(record.merged_at)}`);

      const dot = document.createElement("span");
      dot.className = "marker-dot";
      marker.append(dot);
      marker.addEventListener("click", () => selectRecord(record));
      marker.addEventListener("mouseenter", () => showTooltip(record, marker));
      marker.addEventListener("mouseleave", hideTooltip);
      marker.addEventListener("focus", () => showTooltip(record, marker));
      marker.addEventListener("blur", hideTooltip);
      elements.timeline.appendChild(marker);
    });

    const selected = records.find((record) => record.number === state.selectedNumber) || records[records.length - 1];
    selectRecord(selected);

    if (!state.hasInitialScroll || wasAtLatest) {
      state.hasInitialScroll = true;
      elements.timelineViewport.scrollLeft = elements.timelineViewport.scrollWidth;
    }
  }

  function updateZoomValue() {
    const zoom = Number.isInteger(state.zoom) ? state.zoom : state.zoom.toFixed(2).replace(/0+$/, "");
    elements.zoomValue.textContent = `${zoom}×`;
  }

  function render(payload) {
    state.records = validRecords(Array.isArray(payload.prs) ? payload.prs : []);
    elements.summary.textContent = `${state.records.length} PR${state.records.length === 1 ? "" : "s"}`;
    elements.range.textContent = state.records.length > 0
      ? `${rangeDate(state.records[0].merged_at)} — ${rangeDate(state.records[state.records.length - 1].merged_at)}`
      : "—";
    elements.updated.textContent = payload.last_success_at
      ? `Updated ${longTime(payload.last_success_at)}`
      : "Waiting for first sync";
    if (payload.error) {
      setNotice(payload.stale ? `Showing cached data · ${payload.error}` : payload.error);
    } else {
      setNotice("");
    }
    renderTimeline();
  }

  async function refresh() {
    elements.refresh.disabled = true;
    try {
      const response = await fetch("/api/prs", { cache: "no-store" });
      if (!response.ok) throw new Error(`API ${response.status}`);
      render(await response.json());
    } catch (error) {
      setNotice(`Unable to load timeline · ${error.message}`);
    } finally {
      elements.refresh.disabled = false;
    }
  }

  elements.refresh.addEventListener("click", refresh);
  elements.zoom.addEventListener("input", () => {
    state.zoom = Number(elements.zoom.value);
    updateZoomValue();
    renderTimeline();
  });
  window.addEventListener("resize", () => renderTimeline());
  updateZoomValue();
  window.setInterval(refresh, 60 * 1000);
  refresh();
}());
