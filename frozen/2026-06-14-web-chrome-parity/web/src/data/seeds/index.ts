// Unified data Source-of-Truth for the web app.
//
// All demo/mock data originates HERE — one canonical value per domain. The mock
// backend (api/mock/data.ts) DERIVES its responses from this seed via the pure
// transformers in ../transformers, so there are zero hand-duplicated literals
// downstream. A drift-guard test (../validation/driftGuard.test.ts) fails if the
// derived mock output ever diverges from transformer(SEED).
//
// Phase B (owned by another workflow) will additionally make the surface
// fixtures derive from this same SEED — do NOT edit surfaces from this stream.

import { ACCOUNT_SEED, NOTEBOOK_SEEDS, SEED_NOW_ISO } from './account.seed'
import { BOOK_SEEDS } from './library.seed'
import { ENTITLEMENT_SEED, PREFERENCES_SEED, QUOTA_SEED } from './config.seed'
import {
  PODCAST_PROGRESS_SEEDS,
  PODCAST_SERIES_SEEDS,
  PODCAST_SUBTITLE_SRT,
} from './podcast.seed'
import {
  GRAPH_LINK_SEEDS,
  REVIEW_EVENT_LOG_SEED,
  VOCAB_CARD_SEEDS,
} from './vocabulary.seed'

export * from './account.seed'
export * from './library.seed'
export * from './config.seed'
export * from './podcast.seed'
export * from './vocabulary.seed'

/**
 * The single seed namespace. Group it by domain so callers read a coherent
 * SoT (`SEED.vocabulary.cards`, `SEED.library.books`, …) rather than a flat
 * bag of exports.
 */
export const SEED = {
  nowIso: SEED_NOW_ISO,
  account: ACCOUNT_SEED,
  notebooks: NOTEBOOK_SEEDS,
  vocabulary: {
    cards: VOCAB_CARD_SEEDS,
    graphLinks: GRAPH_LINK_SEEDS,
    reviewEventLog: REVIEW_EVENT_LOG_SEED,
  },
  podcast: {
    series: PODCAST_SERIES_SEEDS,
    progress: PODCAST_PROGRESS_SEEDS,
    subtitleSrt: PODCAST_SUBTITLE_SRT,
  },
  library: {
    books: BOOK_SEEDS,
  },
  config: {
    preferences: PREFERENCES_SEED,
    entitlement: ENTITLEMENT_SEED,
    quota: QUOTA_SEED,
  },
} as const
