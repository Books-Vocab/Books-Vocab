// Podcast Player — inline audio + word-synced subtitles.
// Single class operates on a fixed DOM root (#player-panel). Exposes:
//   PodcastPlayer.attach(rootEl) → returns instance
//   instance.load(workspaceName) → fetch episodes, render UI
//   instance.clear() → tear down audio + DOM
//
// Subtitle sync: SRT cues map start/end times to lines. The audio element's
// `timeupdate` event fires at ~250ms cadence; we look up the active cue by
// binary searching the cue array (O(log n), no per-tick scan) and apply a
// CSS class. Click on a cue → seek there.

(function () {
  "use strict";

  // ─── SRT parser ────────────────────────────────────────────────────────
  // Cues: [{ start: seconds, end: seconds, text: "…" }, …]
  // The pipeline emits per-word SRT (one word per cue), so 8-min episodes
  // → ~1500 cues. Binary search keeps the hot loop cheap.
  // Speaker prefix pattern: per-word SRT lines look like "[Dev] Welcome",
  // "[Maren] Today:". We strip the prefix at parse time so the rendered word
  // span is clean ("Welcome", not "[Dev] Welcome"), and remember the speaker
  // on the cue itself for chat-bubble grouping below.
  const SPEAKER_RE = /^\[([^\]]+)\]\s*/;

  function parseSrt(text) {
    const out = [];
    const blocks = text.replace(/\r\n/g, "\n").split(/\n\n+/);
    for (const block of blocks) {
      const lines = block.split("\n").filter(Boolean);
      if (lines.length < 2) continue;
      // Format: index / "HH:MM:SS,mmm --> HH:MM:SS,mmm" / text lines…
      const timeLineIdx = lines.findIndex(l => l.includes("-->"));
      if (timeLineIdx < 0) continue;
      const m = lines[timeLineIdx].match(
        /(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)/
      );
      if (!m) continue;
      const start =
        Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Number(m[4]) / 1000;
      const end =
        Number(m[5]) * 3600 + Number(m[6]) * 60 + Number(m[7]) + Number(m[8]) / 1000;
      let txt = lines.slice(timeLineIdx + 1).join(" ").trim();
      if (!txt) continue;
      let speaker = "";
      const sm = txt.match(SPEAKER_RE);
      if (sm) { speaker = sm[1].trim(); txt = txt.slice(sm[0].length); }
      out.push({ start, end, text: txt, speaker });
    }
    return out;
  }

  // Slugify speaker name for stable CSS class. "Dev" → "dev",
  // "Maren K." → "maren-k". Used so two distinct speakers reliably get the
  // two pre-styled accent colors regardless of casing/punctuation.
  function speakerSlug(name) {
    return (name || "unknown").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
  }

  // Find the cue active at `t`. Returns the cue index, or -1 before first cue.
  //
  // Algorithm: largest i where cues[i].start <= t. This is a clean predicate
  // for binary search and gives the correct answer for three cases at once —
  // inside a cue (start <= t < end), in a gap (previous cue stays highlighted),
  // and past the last cue (last index stays "sticky" until reset). Before the
  // first cue's start time we return -1 so nothing highlights.
  //
  // Previous version tried to special-case the gap by inspecting cues[mid+1]
  // mid-loop and was incorrect for sparse SRT — the recursive search direction
  // could skip past the true answer. The simpler invariant is robust.
  function findCueIdx(cues, t) {
    if (!cues.length || t < cues[0].start) return -1;
    let lo = 0, hi = cues.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (cues[mid].start <= t) { ans = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    return ans;
  }

  function fmtTime(sec) {
    if (!Number.isFinite(sec)) return "0:00";
    const s = Math.floor(sec);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${r.toString().padStart(2, "0")}`;
  }

  // ─── Player class ──────────────────────────────────────────────────────
  class PodcastPlayer {
    static attach(rootEl) {
      return new PodcastPlayer(rootEl);
    }

    constructor(rootEl) {
      this.root = rootEl;
      this.workspace = null;
      this.episodes = [];
      this.currentEp = null;
      this.cues = [];
      this.lastCueIdx = -1;
      this.audio = null;
      this._build();
    }

    _build() {
      this.root.innerHTML = `
        <div class="panel-head">
          <span class="micro-label">EPISODES</span>
          <span class="panel-sub" id="player-status">no workspace selected</span>
        </div>
        <div class="ep-chips" id="ep-chips"></div>
        <div class="player-body" id="player-body" hidden>
          <div class="player-controls">
            <audio id="audio" preload="metadata" controls></audio>
            <div class="player-meta" id="player-meta"></div>
          </div>
          <div class="cue-list" id="cue-list"></div>
        </div>
      `;
      this.elChips = this.root.querySelector("#ep-chips");
      this.elBody = this.root.querySelector("#player-body");
      this.elAudio = this.root.querySelector("#audio");
      this.elMeta = this.root.querySelector("#player-meta");
      this.elCues = this.root.querySelector("#cue-list");
      this.elStatus = this.root.querySelector("#player-status");

      this.elAudio.addEventListener("timeupdate", () => this._onTime());
      this.elAudio.addEventListener("loadedmetadata", () => this._updateMeta());
      // Click outside a cue link still scrolls — rebind via delegation.
      this.elCues.addEventListener("click", (e) => {
        const target = e.target.closest("[data-cue]");
        if (target) {
          const t = Number(target.dataset.start);
          if (Number.isFinite(t)) {
            this.elAudio.currentTime = t;
            if (this.elAudio.paused) this.elAudio.play().catch(() => {});
          }
        }
      });
    }

    async load(workspaceName) {
      // Stop any currently playing audio before swapping workspaces —
      // otherwise the previous episode keeps streaming until selectEpisode
      // sets a new src, causing brief cross-workspace audio leak.
      this.elAudio.pause();
      this.elAudio.removeAttribute("src");
      this.elAudio.load();

      this.workspace = workspaceName;
      this.episodes = [];
      this.currentEp = null;
      this.cues = [];
      this.cueEls = [];
      this.lastCueIdx = -1;
      this.elBody.hidden = true;
      this.elChips.innerHTML = "";
      this.elStatus.textContent = "loading…";

      if (!workspaceName) { this.elStatus.textContent = "no workspace selected"; return; }

      let list;
      try {
        const r = await fetch(`/api/workspace/${workspaceName}/episodes`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        list = await r.json();
      } catch (e) {
        this.elStatus.textContent = `failed to load episodes: ${e.message}`;
        return;
      }

      this.episodes = list;
      if (!list.length) {
        this.elStatus.textContent = "no audio yet — run synthesize stage";
        return;
      }
      this.elStatus.textContent = `${list.length} episode${list.length > 1 ? "s" : ""} ready`;
      this._renderChips();
      // Auto-select first ep for instant play; user can click another chip.
      this.selectEpisode(list[0].episode);
    }

    _renderChips() {
      this.elChips.innerHTML = "";
      for (const ep of this.episodes) {
        const chip = document.createElement("button");
        chip.className = "ep-chip";
        chip.dataset.ep = ep.episode;
        const sizeMb = (ep.audio_bytes / (1 << 20)).toFixed(1);
        chip.innerHTML = `
          <span class="ep-chip-num">EP${ep.episode}</span>
          <span class="ep-chip-meta">${ep.variant} · ${sizeMb}MB${ep.has_subtitle ? "" : " · no SRT"}</span>
        `;
        chip.addEventListener("click", () => this.selectEpisode(ep.episode));
        this.elChips.appendChild(chip);
      }
    }

    async selectEpisode(epNum) {
      this.currentEp = epNum;
      this.cues = [];
      this.lastCueIdx = -1;
      // Highlight selected chip
      for (const c of this.elChips.children) {
        c.classList.toggle("active", Number(c.dataset.ep) === epNum);
      }

      const ep = this.episodes.find(e => e.episode === epNum);
      if (!ep) return;
      this.elBody.hidden = false;
      this.elAudio.src = `/api/workspace/${this.workspace}/episode/${epNum}/audio`;
      this.elMeta.textContent = `EP${epNum} · ${ep.variant}`;
      this.elCues.innerHTML = ep.has_subtitle
        ? `<div class="cue-loading">loading subtitle…</div>`
        : `<div class="cue-loading muted">no subtitle for this episode</div>`;

      if (!ep.has_subtitle) return;
      try {
        const r = await fetch(`/api/workspace/${this.workspace}/episode/${epNum}/subtitle`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const text = await r.text();
        this.cues = parseSrt(text);
        this._renderCues();
      } catch (e) {
        this.elCues.innerHTML = `<div class="cue-loading warn">subtitle load failed: ${e.message}</div>`;
      }
    }

    _renderCues() {
      // Chat-style rendering: group consecutive same-speaker cues into one
      // bubble with the speaker name above. Each word inside the bubble is
      // still its own <span class="cue"> so timeupdate's binary-search
      // highlight + click-to-seek behavior stays intact — the bubble is
      // purely a presentational wrapper.
      //
      // Speaker-side alternation: the first two distinct speakers we see
      // claim the "left" and "right" sides respectively (think iMessage).
      // A third speaker (rare; usually means the script broke convention)
      // falls back to the left side, sharing the first speaker's color.
      // Cues with no speaker prefix (legacy SRTs, narration) get a
      // speaker-less bubble on the left.
      if (!this.cues.length) {
        this.elCues.innerHTML = `<div class="cue-loading muted">subtitle empty</div>`;
        this.cueEls = [];
        return;
      }
      const sideOf = new Map();
      const slotOf = new Map(); // speaker slug → "a" | "b" (color slot)
      const parts = [];
      let i = 0;
      while (i < this.cues.length) {
        const speaker = this.cues[i].speaker || "";
        const slug = speakerSlug(speaker);
        if (!sideOf.has(slug)) {
          const claimed = sideOf.size;
          sideOf.set(slug, claimed === 1 ? "right" : "left");
          slotOf.set(slug, claimed === 1 ? "b" : "a");
        }
        const side = sideOf.get(slug);
        const slot = slotOf.get(slug);
        // Collect this speaker's run.
        const words = [];
        const runStart = i;
        while (i < this.cues.length && (this.cues[i].speaker || "") === speaker) {
          const c = this.cues[i];
          const t = c.text.replace(/[<>&]/g, ch => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[ch]));
          words.push(`<span class="cue" data-cue="${i}" data-start="${c.start}">${t}</span>`);
          i++;
        }
        const speakerLabel = speaker
          ? `<div class="chat-speaker">${speaker.replace(/[<>&]/g, ch => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[ch]))}</div>`
          : "";
        parts.push(
          `<div class="chat-turn chat-turn-${side} chat-slot-${slot}" data-run-start="${runStart}">` +
          speakerLabel +
          `<div class="chat-bubble">${words.join(" ")}</div>` +
          `</div>`
        );
      }
      this.elCues.innerHTML = parts.join("");
      // Cache the word elements in cue-index order so timeupdate's hot path
      // can toggle the highlight class via O(1) array lookup instead of
      // querySelector on every tick. Matters for 30-min episodes (6000+ cues).
      this.cueEls = Array.from(this.elCues.querySelectorAll(".cue"));
    }

    _onTime() {
      if (!this.cues.length || !this.cueEls?.length) return;
      const t = this.elAudio.currentTime;
      const idx = findCueIdx(this.cues, t);
      if (idx === this.lastCueIdx) return;
      // O(1) class toggles via cached element refs — see _renderCues comment.
      if (this.lastCueIdx >= 0) {
        const prev = this.cueEls[this.lastCueIdx];
        if (prev) prev.classList.remove("cue-active");
      }
      if (idx >= 0) {
        const cur = this.cueEls[idx];
        if (cur) {
          cur.classList.add("cue-active");
          // Scroll into view only when the active cue moves out of the viewport
          // — frequent scrollIntoView during fast playback is jarring.
          const r = cur.getBoundingClientRect();
          const cr = this.elCues.getBoundingClientRect();
          if (r.top < cr.top + 20 || r.bottom > cr.bottom - 20) {
            cur.scrollIntoView({ block: "center", behavior: "smooth" });
          }
        }
      }
      this.lastCueIdx = idx;
    }

    _updateMeta() {
      if (!this.elAudio.duration || !Number.isFinite(this.elAudio.duration)) return;
      const dur = fmtTime(this.elAudio.duration);
      const ep = this.episodes.find(e => e.episode === this.currentEp);
      if (ep) {
        this.elMeta.textContent = `EP${this.currentEp} · ${ep.variant} · ${dur}`;
      }
    }

    clear() {
      this.elAudio.pause();
      this.elAudio.removeAttribute("src");
      this.elAudio.load();
      this.workspace = null;
      this.episodes = [];
      this.currentEp = null;
      this.cues = [];
      this.lastCueIdx = -1;
      this.elBody.hidden = true;
      this.elChips.innerHTML = "";
      this.elStatus.textContent = "no workspace selected";
    }
  }

  window.PodcastPlayer = PodcastPlayer;
})();
