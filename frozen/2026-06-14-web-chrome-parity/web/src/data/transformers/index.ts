// Pure transformer layer: SEED → API-response shapes.
//
// `toMockBackend(seed)` assembles the full set of derived MOCK_* payloads the
// mock backend serves. api/mock/data.ts consumes this so every MOCK_* constant
// is derived (zero hand-duplicated literals); the drift guard asserts the
// derived output equals transformer(SEED).

import type {
  BookMetadataResponse,
  CardResponse,
  DeleteAccountResponse,
  EntitlementsResponse,
  NotebookResponse,
  PodcastProgressListResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
  QuotaResponse,
  ReviewEventsResponse,
  UserConfigResponse,
  UserProfileResponse,
} from '../../api/types'
import type { SEED } from '../seeds'
import {
  toDeleteAccountResponse,
  toNotebookResponses,
  toUserProfileResponse,
} from './account.transformers'
import { toEntitlementsResponse, toQuotaResponse, toUserConfigResponse } from './config.transformers'
import { toBookMetadataResponses } from './library.transformers'
import {
  toPodcastProgressList,
  toPodcastSeriesDetail,
  toPodcastSeriesSummaries,
} from './podcast.transformers'
import {
  toCardResponses,
  toMockGraphLinks,
  toReviewEventsResponse,
  type MockGraphLink,
} from './vocabulary.transformers'

export * from './account.transformers'
export * from './config.transformers'
export * from './library.transformers'
export * from './podcast.transformers'
export * from './vocabulary.transformers'

type Seed = typeof SEED

/** The full derived mock backend payload set. */
export interface MockBackend {
  nowIso: string
  libraryBooks: BookMetadataResponse[]
  notebooks: NotebookResponse[]
  vocabCards: CardResponse[]
  graphLinks: MockGraphLink[]
  reviewEvents: ReviewEventsResponse
  podcastSeries: PodcastSeriesSummary[]
  podcastDetail: PodcastSeriesDetail
  podcastProgress: PodcastProgressListResponse
  userConfig: UserConfigResponse
  entitlements: EntitlementsResponse
  quota: QuotaResponse
  userProfile: UserProfileResponse
  deleteAccount: DeleteAccountResponse
  subtitleSrt: string
  accessToken: string
}

/** Derive the complete mock backend payload set from the unified SEED. */
export function toMockBackend(seed: Seed): MockBackend {
  const nowIso = seed.nowIso
  return {
    nowIso,
    libraryBooks: toBookMetadataResponses(seed.library.books, nowIso),
    notebooks: toNotebookResponses(seed.notebooks, nowIso),
    vocabCards: toCardResponses(seed.vocabulary.cards, nowIso),
    graphLinks: toMockGraphLinks(seed.vocabulary.graphLinks),
    reviewEvents: toReviewEventsResponse(seed.vocabulary.reviewEventLog),
    podcastSeries: toPodcastSeriesSummaries(seed.podcast.series),
    // The single seeded series is the detail payload's source.
    podcastDetail: toPodcastSeriesDetail(seed.podcast.series[0]!),
    podcastProgress: toPodcastProgressList(seed.podcast.progress),
    userConfig: toUserConfigResponse(seed.config.preferences),
    entitlements: toEntitlementsResponse(seed.config.entitlement),
    quota: toQuotaResponse(seed.config.quota),
    userProfile: toUserProfileResponse(seed.account),
    deleteAccount: toDeleteAccountResponse(seed.account),
    subtitleSrt: seed.podcast.subtitleSrt,
    accessToken: seed.account.accessToken,
  }
}
