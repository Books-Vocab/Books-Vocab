(function () {
  "use strict";

  const HOUR_MS = 60 * 60 * 1000;
  const DAY_MS = 24 * HOUR_MS;
  const TICK_INTERVALS = [
    15 * 60 * 1000,
    30 * 60 * 1000,
    HOUR_MS,
    2 * HOUR_MS,
    4 * HOUR_MS,
    6 * HOUR_MS,
    12 * HOUR_MS,
    DAY_MS,
    2 * DAY_MS,
    7 * DAY_MS,
  ];

  const elements = {
    details: document.getElementById("details"),
    notice: document.getElementById("notice"),
    refresh: document.getElementById("refresh"),
    summary: document.getElementById("summary"),
    timeline: document.getElementById("timeline"),
    updated: document.getElementById("updated"),
    zoom: document.getElementById("zoom"),
  };

  const state = {
    records: [],
    selectedNumber: null,
    zoom: Number(elements.zoom.value),
  };

  function dateValue(value) {
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

  function tickInterval(durationMs) {
    const minimumSpacing = 76;
    return TICK_INTERVALS.find((interval) => (interval / HOUR_MS) * state.zoom >= minimumSpacing) || TICK_INTERVALS[TICK_INTERVALS.length - 1];
  }

  function createTick(time, start, duration, interval) {
    const tick = document.createElement("div");
    tick.className = "tick";
    tick.style.left = `${((time - start) / duration) * 100}%`;

    const label = document.createElement("span");
    label.className = "tick-label";
    label.textContent = interval >= DAY_MS
      ? localDate(time, { month: "short", day: "numeric" })
      : localDate(time, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    tick.appendChild(label);
    return tick;
  }

  function selectRecord(record) {
    state.selectedNumber = record.number;
    document.querySelectorAll(".pr-marker").forEach((marker) => {
      marker.classList.toggle("is-selected", Number(marker.dataset.number) === state.selectedNumber);
    });

    elements.details.replaceChildren();
    const summary = document.createElement("div");
    summary.className = "pr-summary";
    const title = document.createElement("p");
    title.className = "pr-title";
    title.textContent = `#${record.number} ${record.title || "Untitled PR"}`;
    summary.appendChild(title);

    const url = safePullUrl(record);
    if (url) {
      const link = document.createElement("a");
      link.className = "pr-link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = "GitHub ↗";
      summary.appendChild(link);
    }
    elements.details.appendChild(summary);

    const row = document.createElement("div");
    row.className = "detail-row muted";
    const merged = document.createElement("span");
    merged.textContent = `Merged ${longTime(record.merged_at)}`;
    const author = document.createElement("span");
    author.textContent = `by ${record.author || "unknown"}`;
    row.append(merged, author);
    elements.details.appendChild(row);
  }

  function renderTimeline() {
    const records = state.records;
    elements.timeline.replaceChildren();
    if (records.length === 0) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No merged PRs";
      elements.timeline.appendChild(empty);
      elements.details.replaceChildren();
      const emptyDetails = document.createElement("p");
      emptyDetails.className = "muted";
      emptyDetails.textContent = "Select a PR";
      elements.details.appendChild(emptyDetails);
      return;
    }

    const times = records.map((record) => dateValue(record.merged_at));
    const first = Math.min(...times);
    const last = Math.max(...times);
    const interval = tickInterval(last - first);
    const paddingMs = Math.max(HOUR_MS, interval);
    const start = Math.floor((first - paddingMs) / interval) * interval;
    const end = Math.ceil((last + paddingMs) / interval) * interval;
    const duration = Math.max(end - start, HOUR_MS);
    const width = Math.max(760, ((duration / HOUR_MS) * state.zoom) + 36);
    elements.timeline.style.width = `${Math.ceil(width)}px`;

    for (let time = start; time <= end; time += interval) {
      elements.timeline.appendChild(createTick(time, start, duration, interval));
    }

    const laneLastX = [-Infinity, -Infinity];
    records.forEach((record) => {
      const x = ((dateValue(record.merged_at) - start) / duration) * width;
      let lane = laneLastX[0] + 70 <= x ? 0 : 1;
      if (laneLastX[lane] + 70 > x && laneLastX[1 - lane] + 70 <= x) lane = 1 - lane;
      laneLastX[lane] = x;

      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = "pr-marker";
      marker.dataset.number = String(record.number);
      marker.style.left = `${x}px`;
      marker.style.top = `${108 + lane * 86}px`;
      marker.setAttribute("aria-label", `PR ${record.number}, merged ${longTime(record.merged_at)}`);

      const dot = document.createElement("span");
      dot.className = "marker-dot";
      const label = document.createElement("span");
      label.className = "marker-label";
      label.textContent = `#${record.number}`;
      const time = document.createElement("span");
      time.className = "marker-time";
      time.textContent = shortTime(record.merged_at);
      marker.append(dot, label, time);
      marker.addEventListener("click", () => selectRecord(record));
      elements.timeline.appendChild(marker);
    });

    const selected = records.find((record) => record.number === state.selectedNumber) || records[records.length - 1];
    selectRecord(selected);
  }

  function render(payload) {
    state.records = validRecords(Array.isArray(payload.prs) ? payload.prs : []);
    elements.summary.textContent = `${state.records.length} PR${state.records.length === 1 ? "" : "s"}`;
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
    renderTimeline();
  });
  window.setInterval(refresh, 60 * 1000);
  refresh();
}());
