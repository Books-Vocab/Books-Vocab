// Pure transformers: vocabulary seed → API-response shapes (cards, graph links,
// the synthetic review-event log). The card-metadata defaults that the legacy
// mock hard-coded in its `card()` helper live HERE, applied uniformly to every
// seeded card so the derived CardResponse rows stay byte-equivalent.

import type {
  CardResponse,
  GraphLinkResponse,
  ReviewEventEntry,
  ReviewEventsResponse,
} from '../../api/types'
import type {
  GraphLinkSeed,
  ReviewEventLogSeed,
  VocabCardSeed,
} from '../seeds/vocabulary.seed'

const MS_PER_HOUR = 3_600_000

/** SEED_NOW-style ISO (seconds precision, trailing Z) — matches SEED_NOW_ISO. */
function isoSeconds(ms: number): string {
  // toISOString() yields `...:00.000Z`; strip the millis for byte-parity with
  // the SEED_NOW_ISO literal (`2026-06-11T00:00:00Z`).
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z')
}

/**
 * SRS metadata derived from the SoT per-card review state. The runtime stores
 * classify a card by (reviewCount, nextReviewAt vs wall-clock now):
 *   reviewCount === 0                       → 未學習 (unlearned)
 *   reviewCount ≥ 1 && nextReviewAt ≤ now   → 待複習 (due)
 *   reviewCount ≥ 1 && nextReviewAt > now   → 已複習 (reviewed)
 * so we anchor every timestamp at `nowIso` (= SEED_NOW_ISO) deterministically:
 *   'new'      → never reviewed; nextReviewAt = SEED_NOW (unlearned).
 *   'due'      → reviewed `interval`h ago; nextReviewAt = SEED_NOW (already
 *                overdue: SEED_NOW < wall-clock now ⇒ stays due).
 *   'reviewed' → just reviewed at SEED_NOW; nextReviewAt = SEED_NOW + interval
 *                (future relative to SEED_NOW; classified reviewed).
 */
function deriveReviewMeta(seed: VocabCardSeed, nowIso: string): {
  nextReviewAt: string
  lastReviewedAt: string | null
  reviewCount: number
  reviewStreak: number
  lastReviewFeedback: number
} {
  const nowMs = new Date(nowIso).getTime()
  const intervalMs = seed.reviewIntervalHours * MS_PER_HOUR
  switch (seed.reviewState) {
    case 'due':
      return {
        nextReviewAt: nowIso,
        lastReviewedAt: isoSeconds(nowMs - intervalMs),
        reviewCount: 1,
        reviewStreak: 1,
        lastReviewFeedback: 1,
      }
    case 'reviewed':
      return {
        nextReviewAt: isoSeconds(nowMs + intervalMs),
        lastReviewedAt: nowIso,
        reviewCount: 1,
        reviewStreak: 1,
        lastReviewFeedback: 1,
      }
    case 'new':
    default:
      return {
        nextReviewAt: nowIso,
        lastReviewedAt: null,
        reviewCount: 0,
        reviewStreak: 0,
        lastReviewFeedback: -1,
      }
  }
}

/**
 * Map a seeded card → CardResponse. Domain fields come from the seed; the
 * remaining card-metadata defaults reproduce the legacy `card()` helper (empty
 * link/collocation/example/inflection sets, recognition mode). The SRS metadata
 * (reviewIntervalHours / nextReviewAt / lastReviewedAt / reviewCount /
 * reviewStreak / lastReviewFeedback) is DERIVED from the SoT per-card
 * reviewState so the demo faithfully renders 未學習/待複習/已複習 instead of a
 * flat never-reviewed list. `nowIso` (= SEED_NOW_ISO) anchors updatedAt and the
 * SRS timestamps.
 */
export function toCardResponse(seed: VocabCardSeed, nowIso: string): CardResponse {
  const review = deriveReviewMeta(seed, nowIso)
  return {
    id: seed.id,
    content: seed.word,
    meaning: seed.meaning,
    pos: seed.pos,
    difficulty: null,
    difficultyTier: null,
    note: null,
    collocations: [],
    examples: [],
    mode: 'recognition',
    isDeleted: false,
    isArchived: false,
    inflections: [],
    linksByKind: {},
    notebookId: seed.notebookId,
    source: null,
    updatedAt: nowIso,
    reviewIntervalHours: seed.reviewIntervalHours,
    nextReviewAt: review.nextReviewAt,
    lastReviewedAt: review.lastReviewedAt,
    reviewCount: review.reviewCount,
    lapseCount: 0,
    reviewStreak: review.reviewStreak,
    lastReviewFeedback: review.lastReviewFeedback,
  }
}

export function toCardResponses(seeds: VocabCardSeed[], nowIso: string): CardResponse[] {
  return seeds.map((s) => toCardResponse(s, nowIso))
}

/** A graph link with the mock-internal hidden/notebook bookkeeping retained. */
export interface MockGraphLink extends GraphLinkResponse {
  hidden: boolean
  notebookId: string
}

export function toMockGraphLink(seed: GraphLinkSeed): MockGraphLink {
  return {
    id: seed.id,
    fromId: seed.fromId,
    toId: seed.toId,
    kind: seed.kind,
    confidence: seed.confidence,
    reason: seed.reason,
    hidden: seed.hidden,
    notebookId: seed.notebookId,
  }
}

export function toMockGraphLinks(seeds: GraphLinkSeed[]): MockGraphLink[] {
  return seeds.map(toMockGraphLink)
}

/**
 * Reproduce the legacy synthetic-event generator deterministically from the
 * seed params: over `windowDays`, skip every 4th day (offset % 4 === 0); each
 * kept day gets `((offset*3) % 11) + 1` events at 09:00 + i*7min, feedback 0 on
 * every 3rd event else 1, cycling the seed word list. All events are synthetic.
 */
export function toReviewEventEntries(seed: ReviewEventLogSeed): ReviewEventEntry[] {
  const anchor = new Date(seed.anchorIso)
  const entries: ReviewEventEntry[] = []
  for (let offset = 0; offset < seed.windowDays; offset++) {
    if (offset % 4 === 0) continue
    const day = new Date(anchor)
    day.setUTCDate(day.getUTCDate() - offset)
    const count = ((offset * 3) % 11) + 1
    for (let i = 0; i < count; i++) {
      const at = new Date(day)
      at.setUTCHours(9, i * 7, 0, 0)
      const iso = at.toISOString()
      entries.push({
        event_id: `mock-evt-${offset}-${i}`,
        card_id: null,
        word_snapshot: seed.words[i % seed.words.length]!,
        notebook_id: seed.notebookId,
        feedback: i % 3 === 0 ? 0 : 1,
        reviewed_at: iso,
        created_at: iso,
        is_synthetic: true,
      })
    }
  }
  return entries
}

export function toReviewEventsResponse(seed: ReviewEventLogSeed): ReviewEventsResponse {
  return { entries: toReviewEventEntries(seed), cursor: null }
}
