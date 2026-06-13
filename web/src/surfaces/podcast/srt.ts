// SRT subtitle parsing + playhead→cue sync. Pure functions, no DOM.
//
// In the iOS app, episode subtitles arrive as `subtitle.srt` bytes from
// GET /api/podcasts/{sid}/{ep}/subtitle (or inline `subtitleContent`) and the
// player highlights the cue under the current audio time. The web mock backend
// does NOT expose a subtitle byte route (PodcastClient covers the JSON editorial
// + progress face only), so the shell-gated functional player parses an inline
// SRT payload and syncs it to the <audio> currentTime exactly the way the iOS
// `SubtitleRenderState` (current sentence index) drives the transcript.
//
// Mirrors the SRT shape `ops/podcast_upload.sh` embeds: blocks separated by a
// blank line, each block = index line, `HH:MM:SS,mmm --> HH:MM:SS,mmm` timing,
// then one-or-more text lines.

/** One parsed subtitle cue: half-open [start, end) seconds + text. */
export interface SubtitleCue {
  index: number
  start: number
  end: number
  text: string
}

/** Parse an `HH:MM:SS,mmm` (or `HH:MM:SS.mmm`) timestamp to seconds. */
export function parseTimestamp(raw: string): number {
  const m = raw.trim().match(/^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})$/)
  if (!m) return NaN
  const [, hh, mm, ss, ms] = m
  return (
    Number(hh) * 3600 +
    Number(mm) * 60 +
    Number(ss) +
    Number(ms.padEnd(3, '0')) / 1000
  )
}

/**
 * Parse SRT text into ordered cues. Tolerant of CRLF, BOM, blank-line runs and
 * a missing trailing newline; blocks without a valid timing line are skipped
 * (never throws — a malformed subtitle must degrade to "no highlight", not crash
 * the player).
 */
export function parseSrt(raw: string): SubtitleCue[] {
  const normalized = raw.replace(/^﻿/, '').replace(/\r\n?/g, '\n')
  const blocks = normalized.split(/\n{2,}/)
  const cues: SubtitleCue[] = []
  for (const block of blocks) {
    const lines = block.split('\n').filter((l) => l.trim().length > 0)
    if (lines.length === 0) continue
    // Optional leading numeric index line.
    let cursor = 0
    let index = cues.length + 1
    if (/^\d+$/.test(lines[0].trim())) {
      index = Number(lines[0].trim())
      cursor = 1
    }
    const timing = lines[cursor]
    if (!timing) continue
    const arrow = timing.split('-->')
    if (arrow.length !== 2) continue
    const start = parseTimestamp(arrow[0])
    const end = parseTimestamp(arrow[1])
    if (Number.isNaN(start) || Number.isNaN(end)) continue
    const text = lines.slice(cursor + 1).join(' ').trim()
    if (!text) continue
    cues.push({ index, start, end, text })
  }
  return cues
}

/**
 * Index of the cue active at time `t` (seconds), or -1 if none. Cues are
 * half-open [start, end); when they overlap the earliest match wins (mirrors the
 * iOS forward scan in `SubtitleRenderState`). Before the first cue / in a gap /
 * after the last cue → -1.
 */
export function activeCueIndex(cues: SubtitleCue[], t: number): number {
  for (let i = 0; i < cues.length; i++) {
    if (t >= cues[i].start && t < cues[i].end) return i
  }
  return -1
}
