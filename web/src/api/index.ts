// Public entry point for the web data layer.
//
//   import { createApiClient } from './api'
//   const api = createApiClient()              // reads VITE_API_MODE (default mock)
//   const cards = await api.vocabulary.list()
//
// mock mode (default) serves the in-process mock backend — full functionality,
// zero network. real mode points the transport at VITE_API_BASE_URL. Switching
// modes only swaps the fetch transport + base URL; the domain client surface is
// identical, so surfaces written against it need no changes when real wiring
// (CORS, live base URL) lands later.

import {
  AuthClient,
  GraphClient,
  LibraryClient,
  NotebookClient,
  PipelineClient,
  PodcastClient,
  TodayReviewClient,
  TranslateClient,
  UserClient,
  VocabularyClient,
} from './clients'
import { createMockFetch } from './mock/handler'
import { Transport, type FetchLike, type TokenProvider } from './transport'

export type ApiMode = 'mock' | 'real'

export interface ApiClientConfig {
  /** 'mock' (default) or 'real'. */
  mode?: ApiMode
  /** Base URL for real mode. Ignored in mock mode (forced to ""). */
  baseUrl?: string
  /** Bearer token provider (re-read per request). */
  getToken?: TokenProvider
  /** Test seam: override the fetch transport directly. */
  fetch?: FetchLike
}

export interface ApiClient {
  readonly mode: ApiMode
  readonly auth: AuthClient
  readonly library: LibraryClient
  readonly notebook: NotebookClient
  readonly vocabulary: VocabularyClient
  readonly todayReview: TodayReviewClient
  readonly podcast: PodcastClient
  readonly user: UserClient
  readonly translate: TranslateClient
  readonly graph: GraphClient
  readonly pipeline: PipelineClient
}

/** Read VITE_* config from import.meta.env, tolerating absence (tests/node). */
function readEnv(): { mode: ApiMode; baseUrl: string } {
  const env =
    (typeof import.meta !== 'undefined' &&
      (import.meta as { env?: Record<string, string | undefined> }).env) ||
    {}
  const mode: ApiMode = env.VITE_API_MODE === 'real' ? 'real' : 'mock'
  const baseUrl = env.VITE_API_BASE_URL ?? ''
  return { mode, baseUrl }
}

export function createApiClient(config: ApiClientConfig = {}): ApiClient {
  const envCfg = readEnv()
  const mode = config.mode ?? envCfg.mode

  let fetchImpl: FetchLike | undefined = config.fetch
  let baseUrl: string

  if (mode === 'mock') {
    // Mock mode never hits the network; base URL is irrelevant.
    fetchImpl = fetchImpl ?? createMockFetch()
    baseUrl = ''
  } else {
    baseUrl = config.baseUrl ?? envCfg.baseUrl
  }

  const transport = new Transport({
    baseUrl,
    getToken: config.getToken,
    fetch: fetchImpl,
  })

  return {
    mode,
    auth: new AuthClient(transport),
    library: new LibraryClient(transport),
    notebook: new NotebookClient(transport),
    vocabulary: new VocabularyClient(transport),
    todayReview: new TodayReviewClient(transport),
    podcast: new PodcastClient(transport),
    user: new UserClient(transport),
    translate: new TranslateClient(transport),
    graph: new GraphClient(transport),
    pipeline: new PipelineClient(transport),
  }
}

export { ApiError } from './errors'
export type { ApiErrorBody, ApiErrorKind } from './errors'
export { Transport } from './transport'
export type {
  FetchLike,
  RequestOptions,
  TokenProvider,
  TransportConfig,
} from './transport'
export {
  AuthClient,
  GraphClient,
  LibraryClient,
  NotebookClient,
  PipelineClient,
  PodcastClient,
  TodayReviewClient,
  TranslateClient,
  UserClient,
  VocabularyClient,
} from './clients'
export { createMockFetch } from './mock/handler'
export * from './types'
export type {
  BookCreateRequest,
  BookMetadataResponse,
  BookPositionRequest,
  BookUpdateRequest,
  NotebookCreateRequest,
  NotebookResponse,
  NotebookUpdateRequest,
} from './types'
