import type { ScenarioId } from '../../harness/scenarios'

/**
 * Podcast player surface fixtures — mirrors iOS Catalog "Podcast Player View"
 * (PodcastPlayerViewScenarios.swift seed + sampleSRT).
 *
 * Two surface states map 1:1 onto the iOS scenarios:
 * - `preview-player` → the deterministic `.ready` chrome the catalog seam
 *   renders: transcript bubbles + preview banner + scrubber + transport.
 *   Seeded `durationSec: 1832`, `currentSec: 6.09` (mid third sentence,
 *   word "quietly") → elapsed 00:06 / 30:32, active = 3rd sentence.
 * - `locked-gate` → guest hits `PodcastPlayerLockedGateView` (lock + sign-in CTA).
 *
 * Subtitle copy is the FIRST-viewport slice of sampleSRT collapsed to sentences
 * (the snapshot sits at scroll offset 0 — auto-scroll-to-current doesn't run in a
 * static capture). All sentences share one speaker (empty attribution → slot 0,
 * accent tint, left-aligned, no speaker label). `activeWordIndex` lights the
 * playback underline under one word of the active sentence.
 */

export interface PodcastSentence {
  /** Collapsed sentence text (joined word cues). */
  text: string
  /** true for the mid-episode active sentence (stronger tint + playback underline). */
  isActive: boolean
  /** word index (0-based) carrying the playback underline; -1 = none. */
  activeWordIndex: number
}

export interface PodcastPlayerFixture {
  kind: 'preview-player'
  sentences: PodcastSentence[]
  /** elapsed clock (mm:ss). */
  elapsed: string
  /** total duration clock (mm:ss). */
  total: string
  /** 0–1 scrubber progress (currentSec / durationSec). */
  progress: number
  /** speed pill label. */
  rate: string
}

export interface PodcastLockedFixture {
  kind: 'locked-gate'
}

export type PodcastFixture = PodcastPlayerFixture | PodcastLockedFixture

const PREVIEW_PLAYER: PodcastPlayerFixture = {
  kind: 'preview-player',
  sentences: [
    { text: 'Welcome back to Deep Work, Decoded.', isActive: false, activeWordIndex: -1 },
    { text: 'Today we trace the comfort crisis.', isActive: false, activeWordIndex: -1 },
    // currentSec 6.09 lands on "quietly" (cue 15) — 3rd sentence, 3rd word.
    { text: 'Easy distraction quietly erodes our focus.', isActive: true, activeWordIndex: 2 },
    { text: 'The thesis is simple and a little uncomfortable.', isActive: false, activeWordIndex: -1 },
    { text: 'Discomfort chosen on purpose builds durable attention.', isActive: false, activeWordIndex: -1 },
  ],
  elapsed: '00:06',
  total: '30:32', // durationSec 1832 → %02d:%02d
  progress: 6.09 / 1832,
  rate: '×1',
}

const LOCKED_GATE: PodcastLockedFixture = { kind: 'locked-gate' }

export const PODCAST_FIXTURES: Record<ScenarioId<'podcast'>, PodcastFixture> = {
  'preview-player': PREVIEW_PLAYER,
  'locked-gate': LOCKED_GATE,
}
