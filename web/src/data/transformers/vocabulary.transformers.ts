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
import { CARD_DEFAULT_INTERVAL_HOURS } from '../seeds/vocabulary.seed'
import type {
  GraphLinkSeed,
  ReviewEventLogSeed,
  VocabCardSeed,
} from '../seeds/vocabulary.seed'

/**
 * Map a seeded card → CardResponse. The non-domain fields reproduce the legacy
 * `card()` helper's defaults verbatim (freshly-added unlearned card: empty
 * link/collocation/example/inflection sets, recognition mode, first-round 12h
 * interval, never reviewed). `nowIso` anchors updatedAt / nextReviewAt.
 */
export function toCardResponse(seed: VocabCardSeed, nowIso: string): CardResponse {
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
    reviewIntervalHours: CARD_DEFAULT_INTERVAL_HOURS,
    nextReviewAt: nowIso,
    lastReviewedAt: null,
    reviewCount: 0,
    lapseCount: 0,
    reviewStreak: 0,
    lastReviewFeedback: -1,
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
