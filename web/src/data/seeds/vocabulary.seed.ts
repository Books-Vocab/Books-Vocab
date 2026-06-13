// Vocabulary domain seed — cards + graph links + review-event log.
//
// CANONICAL note: today the legacy mock lifts MOCK_VOCAB_CARDS from the
// vocabulary SURFACE fixture (surfaces/vocabulary/fixtures.ts::populated.rows),
// mapping word→content / translation→meaning / partOfSpeech(no trailing dot)→pos.
// This seed is the NEW independent SoT: the four card words/translations/pos are
// lifted from that fixture's populated set VERBATIM so transformer output stays
// byte-equivalent. (Phase B — owned by another workflow — will invert the
// dependency so the surface fixture derives from THIS seed; do not touch
// surfaces here.)

import { SEED_NOW_ISO } from './account.seed'

/** Default per-card review interval (hours) for freshly-added unlearned cards. */
export const CARD_DEFAULT_INTERVAL_HOURS = 12.0

export interface VocabCardSeed {
  /** Stable card id (card-1, card-2, …). */
  id: string
  /** Headword (CardResponse.content). */
  word: string
  /** Translation (CardResponse.meaning). */
  meaning: string
  /** Part of speech WITHOUT trailing dot, or null (CardResponse.pos). */
  pos: string | null
  /** Owning notebook (all seeded cards live in the default notebook). */
  notebookId: string
}

/**
 * The four synced unlearned cards. Words / translations / pos mirror the
 * vocabulary surface fixture's populated rows verbatim:
 *   serendipity / ephemeral / petrichor / ineffable.
 * `pos` is the fixture's partOfSpeech with the trailing dot stripped (n. → n).
 */
export const VOCAB_CARD_SEEDS: VocabCardSeed[] = [
  { id: 'card-1', word: 'serendipity', meaning: '機緣巧合', pos: 'n', notebookId: 'default' },
  { id: 'card-2', word: 'ephemeral', meaning: '短暫的', pos: 'adj', notebookId: 'default' },
  { id: 'card-3', word: 'petrichor', meaning: '雨後泥土香', pos: 'n', notebookId: 'default' },
  { id: 'card-4', word: 'ineffable', meaning: '難以言喻的', pos: 'adj', notebookId: 'default' },
]

export interface GraphLinkSeed {
  id: string
  fromId: string
  toId: string
  kind: string
  confidence: number
  reason: string
  hidden: boolean
  notebookId: string
}

/** Edges between the seeded cards (mirrors legacy MOCK_GRAPH_LINKS). */
export const GRAPH_LINK_SEEDS: GraphLinkSeed[] = [
  { id: 'link-1', fromId: 'card-1', toId: 'card-2', kind: 'synonym', confidence: 0.82, reason: '兩字在語意上高度重疊', hidden: false, notebookId: 'default' },
  { id: 'link-2', fromId: 'card-2', toId: 'card-3', kind: 'related', confidence: 0.64, reason: '常於同一語境共現', hidden: false, notebookId: 'default' },
]

export interface ReviewEventLogSeed {
  /** UTC day anchor for the synthetic event window (= SEED_NOW_ISO). */
  anchorIso: string
  /** Words cycled through the synthetic events. */
  words: string[]
  /** Notebook all synthetic events belong to. */
  notebookId: string
  /** Number of trailing days the window spans. */
  windowDays: number
}

/**
 * Parameters for the synthetic review-event log. The legacy mock generated a
 * deterministic 42-day window (skip every 4th day, ramping counts) anchored to
 * NOW_ISO; the transformer reproduces that generation from these params.
 */
export const REVIEW_EVENT_LOG_SEED: ReviewEventLogSeed = {
  anchorIso: SEED_NOW_ISO,
  words: ['serendipity', 'ephemeral', 'quintessential', 'ubiquitous', 'eloquent'],
  notebookId: 'default',
  windowDays: 42,
}
