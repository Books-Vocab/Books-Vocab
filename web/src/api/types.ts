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

// ── notebook (api_models/notebook.py) ──────────────────────────────────────

/** GET /api/notebooks — api_models/notebook.py::NotebookResponse. */
export interface NotebookResponse {
  id: string
  name: string
  color: string | null
  coverPattern: string | null
  sortOrder: number
  isDefault: boolean
  isDeleted: boolean
  cardCount: number
  updatedAt: string | null
}

/** POST /api/notebooks — api_models/notebook.py::NotebookCreateRequest. */
export interface NotebookCreateRequest {
  name: string
  color?: string | null
  cover_pattern?: string | null
}

/** PATCH /api/notebooks/{id} — api_models/notebook.py::NotebookUpdateRequest. */
export interface NotebookUpdateRequest {
  name?: string | null
  color?: string | null
  sort_order?: number | null
  cover_pattern?: string | null
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

// ── library (api_models/library.py) ──────────────────────────────────────────

/** GET /api/library/books — api_models/library.py::BookMetadataResponse. */
export interface BookMetadataResponse {
  id: string
  client_book_id: string | null
  title: string
  author: string | null
  language: string | null
  format: string | null // epub | pdf | txt | md
  notebook_id: string | null
  is_deleted: boolean
  updated_at: string | null // ISO8601
  locator: string | null
  progression: number | null // 0..1
  position_updated_at: string | null // ISO8601
}

/** POST /api/library/books — api_models/library.py::BookCreateRequest. */
export interface BookCreateRequest {
  client_book_id: string
  title: string
  author?: string | null
  language?: string | null
  format?: string | null
}

/** PATCH /api/library/books/{id} — api_models/library.py::BookUpdateRequest. */
export interface BookUpdateRequest {
  title?: string | null
  author?: string | null
  language?: string | null
  format?: string | null
  notebook_id?: string | null
}

/** PUT /api/library/books/{id}/position — api_models/library.py::BookPositionRequest. */
export interface BookPositionRequest {
  locator?: string | null
  progression?: number | null
  updated_at: string // ISO8601 LWW timestamp
}

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

// ── translate (api_models/translate.py) ────────────────────────────────────
// Response shapes are intentionally TERSE single-letter fields — copied
// verbatim from the pydantic models. DO NOT expand/rename.

/** POST /api/translate/* request — api_models/translate.py::TranslateRequest. */
export interface TranslateRequest {
  word: string
  context?: string
  source_lang?: string | null
  target_lang?: string | null
}

/** POST /api/translate/quick — api_models/translate.py::QuickTranslateResponse. */
export interface QuickTranslateResponse {
  t: string // translation
  p?: string | null // pronunciation
  r?: string | null // root form (lemma)
}

/** POST /api/translate/phrase — api_models/translate.py::PhraseTranslateResponse. */
export interface PhraseTranslateResponse {
  t: string // translation
}

/** POST /api/translate/explain — api_models/translate.py::ExplainResponse. */
export interface ExplainResponse {
  e: string // explanation
}

// ── graph links (api_models/graph.py) ──────────────────────────────────────

/** GET/POST /api/graph/links — api_models/graph.py::GraphLinkResponse. */
export interface GraphLinkResponse {
  id: string
  fromId: string
  toId: string
  kind: string
  confidence: number
  reason: string
}

/** POST /api/graph/links request — api_models/graph.py::ManualLinkRequest. */
export interface ManualLinkRequest {
  from_id: string
  to_id: string
}

// ── vocabulary mutations (api_models/vocab.py) ─────────────────────────────

/** PATCH /api/vocab/{word}/archive request — api_models/vocab.py::ArchiveWordRequest. */
export interface ArchiveWordRequest {
  archived: boolean
}

/** PATCH /api/vocab/{word}/archive — api_models/vocab.py::ArchiveWordResponse. */
export interface ArchiveWordResponse {
  word: string
  id: string
  archived: boolean
}

/** DELETE /api/vocab/{word} — api_models/vocab.py::DeleteWordResponse. */
export interface DeleteWordResponse {
  deleted: string
  id: string
}

/** POST /api/vocab/batch-delete request — api_models/vocab.py::BatchDeleteRequest. */
export interface BatchDeleteRequest {
  words: string[]
}

/** POST /api/vocab/batch-delete — api_models/vocab.py::BatchDeleteResponse. */
export interface BatchDeleteResponse {
  deleted: number
  deleted_words: string[]
  not_found: string[]
  /** Words whose graph cleanup failed — card still exists; clients must retry. */
  failed: string[]
}

/** PATCH /api/vocab/batch-archive request — api_models/vocab.py::BatchArchiveRequest. */
export interface BatchArchiveRequest {
  words: string[]
  archived?: boolean
}

/** PATCH /api/vocab/batch-archive — api_models/vocab.py::BatchArchiveResponse. */
export interface BatchArchiveResponse {
  updated: number
  updated_words: string[]
  not_found: string[]
  /** Words whose graph cleanup/restore failed — clients must retry. */
  failed: string[]
}

/**
 * PATCH /api/vocab/{word} request — NEW backend (mock-only for now).
 * Partial content edit; only the provided fields are applied.
 */
export interface VocabContentPatch {
  meaning?: string
  note?: string | null
  explanation?: string
}

// ── user (api_models/auth.py + NEW profile) ────────────────────────────────

/** DELETE /api/user/account — api_models/auth.py::DeleteAccountResponse. */
export interface DeleteAccountResponse {
  deleted_user_id: string
  linked_ids: string[]
  deleted_dirs: string[]
}

/**
 * GET /api/user/profile — NEW backend (mock-only for now). The backend has no
 * displayName/email surface today (config only carries LWW settings groups), so
 * this is a forward-declared contract the mock owns until the route lands.
 */
export interface UserProfileResponse {
  user_id: string
  email: string | null
  display_name: string | null
}

// ── pipeline (api_models/system.py) ────────────────────────────────────────

/** POST /api/pipeline — api_models/system.py::PipelineQueueResponse. */
export interface PipelineQueueResponse {
  status: string
  message: string
}
