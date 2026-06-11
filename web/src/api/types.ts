// Hand-written TypeScript mirrors of backend pydantic schemas.
// SoT = backend/src/kg/api_models/*.py. Field names are copied verbatim from
// the pydantic models — DO NOT invent or rename fields. When a backend schema
// changes, update here in the same PR (see web/src/api/README.md).

// ── auth (api_models/auth.py) ──────────────────────────────────────────────

/** POST /auth/verify request — api_models/auth.py::AuthVerifyRequest. */
export interface AuthVerifyRequest {
  provider: 'apple' | 'google'
  token: string
  /** Accepted-and-ignored by server (trusts provider-token email only). */
  email?: string | null
}

/** POST /auth/verify response — api_models/auth.py::AuthVerifyResponse. */
export interface AuthVerifyResponse {
  access_token: string
  token_type: string // "bearer"
  user_id: string
  expires_in: number // seconds
}

// ── user config (api_models/auth.py + review.py + notebook.py + graph.py) ──

/** api_models/translate.py::TranslationLanguageConfig (opaque to web layer). */
export interface TranslationLanguageConfig {
  [key: string]: unknown
}

/** api_models/review.py::ReviewClockConfig. */
export interface ReviewClockConfig {
  is_paused: boolean
  paused_at?: string | null // ISO8601; only meaningful when is_paused
  updated_at?: number | null // LWW epoch seconds
}

/** api_models/review.py::ReviewModeConfig. */
export interface ReviewModeConfig {
  mode: string // relaxed / intensive / custom
  custom_initial_interval_hours: number
  custom_remembered_multiplier: number
  custom_forgot_multiplier: number
  custom_minimum_interval_hours: number
  custom_maximum_interval_hours: number
  updated_at?: number | null
}

/** api_models/notebook.py::VocabUIConfig (opaque to web layer). */
export interface VocabUIConfig {
  [key: string]: unknown
}

/** api_models/graph.py::AutoLinkConfig (opaque to web layer). */
export interface AutoLinkConfig {
  [key: string]: unknown
}

/** PUT /api/user/config request — api_models/auth.py::UserConfigRequest. */
export interface UserConfigRequest {
  translation?: TranslationLanguageConfig | null
  review_clock?: ReviewClockConfig | null
  review_mode?: ReviewModeConfig | null
  vocab_ui?: VocabUIConfig | null
  auto_link?: AutoLinkConfig | null
}

/** GET/PUT /api/user/config response — api_models/auth.py::UserConfigResponse. */
export interface UserConfigResponse {
  translation?: TranslationLanguageConfig | null
  review_clock?: ReviewClockConfig | null
  review_mode?: ReviewModeConfig | null
  vocab_ui?: VocabUIConfig | null
  auto_link?: AutoLinkConfig | null
}

/** api_models/billing.py::SubscriptionStatusResponse. */
export interface SubscriptionStatusResponse {
  is_active: boolean
  product_id?: string | null
  plan_name?: string | null
  price_display?: string | null
  status: string
  is_trial: boolean
  trial_days?: number | null
  will_renew: boolean
  expires_at?: string | null
  source: string // "app_store"
  last_synced_at?: string | null
}

/** GET /api/user/entitlements — api_models/billing.py::EntitlementsResponse. */
export interface EntitlementsResponse {
  pro: SubscriptionStatusResponse
}

/** GET /api/user/quota — api_models/billing.py::QuotaResponse. */
export interface QuotaResponse {
  fraction: number // 0..1
  reset_seconds: number
}

// ── vocabulary (api_models/cards.py + vocab.py) ────────────────────────────

/** api_models/common.py::VocabSource (string enum; opaque). */
export type VocabSource = string

/** api_models/cards.py::CardLinkSummaryResponse. */
export interface CardLinkSummaryResponse {
  id: string
  cardId: string
  word: string
  kind: string
  label: string
  confidence: number
  reason: string
  hidden: boolean
}

/** GET /api/vocab + GET /api/vocab/{word} — api_models/cards.py::CardResponse. */
export interface CardResponse {
  id: string
  content: string
  meaning: string
  pos: string | null
  difficulty: number | null
  difficultyTier: string | null
  note: string | null
  collocations: string[]
  examples: string[]
  mode: string
  isDeleted: boolean
  isArchived: boolean
  inflections: string[]
  linksByKind: Record<string, CardLinkSummaryResponse[]>
  notebookId: string
  source?: VocabSource | null
  updatedAt?: string | null
  // Review state
  reviewIntervalHours: number
  nextReviewAt?: string | null
  lastReviewedAt?: string | null
  reviewCount: number
  lapseCount: number
  reviewStreak: number
  lastReviewFeedback: number
}

/** POST /api/vocab entry — api_models/vocab.py::VocabEntry. */
export interface VocabEntry {
  word: string
  translation: string
  context?: string
  root_form?: string | null
  source?: VocabSource | null
}

/** POST /api/vocab response — api_models/vocab.py::VocabAddResponse. */
export interface VocabAddResponse {
  created: number
  skipped: number
  duplicates: string[]
  cardIds: Record<string, string>
}

// ── today review (api_models/review.py) ───────────────────────────────────

/** api_models/review.py::ReviewStateEntry. */
export interface ReviewStateEntry {
  word: string
  card_id?: string | null
  review_interval_hours: number
  next_review_at: string // ISO8601
  last_reviewed_at: string // ISO8601
  review_count: number
  lapse_count: number
  review_streak: number
  last_review_feedback: number // -1..1
}

/** PATCH /api/vocab/review request — ReviewStatePushRequest. */
export interface ReviewStatePushRequest {
  entries: ReviewStateEntry[]
}

/** PATCH /api/vocab/review response — ReviewStatePushResponse. */
export interface ReviewStatePushResponse {
  updated: number
  skipped: number
}

/** api_models/review.py::ReviewEventEntry. */
export interface ReviewEventEntry {
  event_id: string
  card_id?: string | null
  word_snapshot: string
  notebook_id: string
  feedback: number // 0..1
  reviewed_at: string
  created_at: string
  interval_before?: number | null
  interval_after?: number | null
  next_review_before?: string | null
  next_review_after?: string | null
  review_count_after?: number | null
  streak_after?: number | null
  lapse_after?: number | null
  is_synthetic: boolean
}

/** GET /api/vocab/review-events — ReviewEventsResponse. */
export interface ReviewEventsResponse {
  entries: ReviewEventEntry[]
  cursor?: string | null
}

/** PATCH /api/vocab/review-events request — ReviewEventsPushRequest. */
export interface ReviewEventsPushRequest {
  entries: ReviewEventEntry[]
}

/** PATCH /api/vocab/review-events response — ReviewEventsPushResponse. */
export interface ReviewEventsPushResponse {
  inserted: number
  skipped: number
}

// ── podcast (api_models/podcast.py) ────────────────────────────────────────
// PodcastSeriesSummary / PodcastSeriesDetail are RootModel[dict[str, Any]] on
// the backend — the producer owns the editorial JSON shape and it is
// intentionally opaque. We model it as an open record.

/** GET /api/podcasts item — api_models/podcast.py::PodcastSeriesSummary. */
export interface PodcastSeriesSummary {
  [key: string]: unknown
}

/** GET /api/podcasts/{series_id} — api_models/podcast.py::PodcastSeriesDetail. */
export interface PodcastSeriesDetail {
  [key: string]: unknown
}

/** api_models/podcast.py::PodcastProgressResponse. */
export interface PodcastProgressResponse {
  series_id: string
  ep_num: number
  position_sec: number
  duration_sec: number
  updated_at: string
}

/** GET /api/podcasts/progress — PodcastProgressListResponse. */
export interface PodcastProgressListResponse {
  items: PodcastProgressResponse[]
}

/** POST /api/podcasts/{sid}/{ep}/progress request — PodcastProgressRequest. */
export interface PodcastProgressRequest {
  position_sec: number
  duration_sec: number
  updated_at: string
}
