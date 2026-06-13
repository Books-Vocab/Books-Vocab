// Typed domain clients. Each method maps 1:1 onto a backend route (path +
// method verified against backend/src/kg/routers/*.py) and returns the
// hand-mirrored response type from ./types.

import type { Transport } from './transport'
import type {
  ArchiveWordResponse,
  AuthVerifyRequest,
  AuthVerifyResponse,
  BatchArchiveResponse,
  BatchDeleteResponse,
  BookCreateRequest,
  BookMetadataResponse,
  BookPositionRequest,
  BookUpdateRequest,
  CardResponse,
  DeleteAccountResponse,
  DeleteWordResponse,
  EntitlementsResponse,
  ExplainResponse,
  GraphLinkResponse,
  ManualLinkRequest,
  NotebookCreateRequest,
  NotebookResponse,
  NotebookUpdateRequest,
  PhraseTranslateResponse,
  PipelineQueueResponse,
  PodcastProgressListResponse,
  PodcastProgressRequest,
  PodcastProgressResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
  QuickTranslateResponse,
  QuotaResponse,
  ReviewEventsPushRequest,
  ReviewEventsPushResponse,
  ReviewEventsResponse,
  ReviewStatePushRequest,
  ReviewStatePushResponse,
  TranslateRequest,
  UserConfigRequest,
  UserConfigResponse,
  UserProfileResponse,
  VocabAddResponse,
  VocabContentPatch,
  VocabEntry,
} from './types'

// ── auth ───────────────────────────────────────────────────────────────────
// Backend has NO username/password login and NO refresh endpoint. The only
// entry point is POST /auth/verify, which exchanges a provider (apple/google)
// OAuth token for a KG access_token. Token lifetime = `expires_in`; re-verify
// to renew. (Web OAuth redirect flow lives in web_auth.py and is out of scope
// for this typed JSON client.)
export class AuthClient {
  constructor(private readonly t: Transport) {}

  /** POST /auth/verify — exchange provider token for an access token. */
  verify(req: AuthVerifyRequest): Promise<AuthVerifyResponse> {
    return this.t.request<AuthVerifyResponse>('/auth/verify', {
      method: 'POST',
      body: req,
      anonymous: true, // no bearer yet — this call mints it
    })
  }
}

// ── notebook ─────────────────────────────────────────────────────────────────
export class NotebookClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/notebooks — list notebooks (optionally since cursor). */
  list(opts: { since?: string } = {}): Promise<NotebookResponse[]> {
    return this.t.request<NotebookResponse[]>('/api/notebooks', {
      query: { since: opts.since },
    })
  }

  /** POST /api/notebooks — create a notebook. */
  create(req: NotebookCreateRequest): Promise<NotebookResponse> {
    return this.t.request<NotebookResponse>('/api/notebooks', {
      method: 'POST',
      body: req,
    })
  }

  /** PATCH /api/notebooks/{id} — update a notebook. */
  update(id: string, req: NotebookUpdateRequest): Promise<NotebookResponse> {
    return this.t.request<NotebookResponse>(`/api/notebooks/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: req,
    })
  }

  /** DELETE /api/notebooks/{id} — delete a notebook. */
  delete(id: string): Promise<{ deleted: string; cardsDeleted: number }> {
    return this.t.request<{ deleted: string; cardsDeleted: number }>(
      `/api/notebooks/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    )
  }
}

// ── vocabulary ───────────────────────────────────────────────────────────────
export class VocabularyClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/vocab — list cards (optionally since cursor / notebook). */
  list(opts: { since?: string; notebookId?: string } = {}): Promise<CardResponse[]> {
    return this.t.request<CardResponse[]>('/api/vocab', {
      query: { since: opts.since, notebook_id: opts.notebookId },
    })
  }

  /** GET /api/vocab/{word} — single card detail. */
  detail(word: string): Promise<CardResponse> {
    return this.t.request<CardResponse>(`/api/vocab/${encodeURIComponent(word)}`)
  }

  /** POST /api/vocab — add one or more entries (body is a list). */
  add(
    entries: VocabEntry[],
    opts: { notebookId?: string } = {},
  ): Promise<VocabAddResponse> {
    return this.t.request<VocabAddResponse>('/api/vocab', {
      method: 'POST',
      body: entries,
      query: { notebook_id: opts.notebookId },
    })
  }

  /** PATCH /api/vocab/{word}/archive — archive (or restore) a single card. */
  archive(
    word: string,
    archived = true,
    opts: { notebookId?: string } = {},
  ): Promise<ArchiveWordResponse> {
    return this.t.request<ArchiveWordResponse>(
      `/api/vocab/${encodeURIComponent(word)}/archive`,
      {
        method: 'PATCH',
        body: { archived },
        query: { notebook_id: opts.notebookId },
      },
    )
  }

  /** DELETE /api/vocab/{word} — hard-delete a single card. */
  delete(word: string, opts: { notebookId?: string } = {}): Promise<DeleteWordResponse> {
    return this.t.request<DeleteWordResponse>(`/api/vocab/${encodeURIComponent(word)}`, {
      method: 'DELETE',
      query: { notebook_id: opts.notebookId },
    })
  }

  /** PATCH /api/vocab/batch-archive — archive (or restore) many cards. */
  batchArchive(
    words: string[],
    archived = true,
    opts: { notebookId?: string } = {},
  ): Promise<BatchArchiveResponse> {
    return this.t.request<BatchArchiveResponse>('/api/vocab/batch-archive', {
      method: 'PATCH',
      body: { words, archived },
      query: { notebook_id: opts.notebookId },
    })
  }

  /** POST /api/vocab/batch-delete — hard-delete many cards. */
  batchDelete(
    words: string[],
    opts: { notebookId?: string } = {},
  ): Promise<BatchDeleteResponse> {
    return this.t.request<BatchDeleteResponse>('/api/vocab/batch-delete', {
      method: 'POST',
      body: { words },
      query: { notebook_id: opts.notebookId },
    })
  }

  /**
   * PATCH /api/vocab/{word} — partial content edit (meaning/note/explanation).
   * NEW backend route: contract is encoded in the mock until the route lands.
   */
  updateContent(word: string, patch: VocabContentPatch): Promise<CardResponse> {
    return this.t.request<CardResponse>(`/api/vocab/${encodeURIComponent(word)}`, {
      method: 'PATCH',
      body: patch,
    })
  }
}

// ── graph links ──────────────────────────────────────────────────────────────
// Knowledge-graph edges between cards. list/create scope to a notebook; create
// runs the ManualLinkJudge (real LLM call) and is daily-quota gated. hide /
// unhide / delete reply 204 with no body.
export class GraphClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/graph/links — links for a notebook (default if omitted). */
  list(notebookId?: string): Promise<GraphLinkResponse[]> {
    return this.t.request<GraphLinkResponse[]>('/api/graph/links', {
      query: { notebook_id: notebookId },
    })
  }

  /** POST /api/graph/links — create a manual link (quota-gated LLM judge). */
  create(req: ManualLinkRequest, opts: { notebookId?: string } = {}): Promise<GraphLinkResponse> {
    return this.t.request<GraphLinkResponse>('/api/graph/links', {
      method: 'POST',
      body: req,
      query: { notebook_id: opts.notebookId },
    })
  }

  /** PATCH /api/graph/links/{id}/hide — soft-hide a link (204). */
  hide(linkId: string, opts: { notebookId?: string } = {}): Promise<void> {
    return this.t.request<void>(`/api/graph/links/${encodeURIComponent(linkId)}/hide`, {
      method: 'PATCH',
      query: { notebook_id: opts.notebookId },
    })
  }

  /** PATCH /api/graph/links/{id}/unhide — restore a hidden link (204). */
  unhide(linkId: string, opts: { notebookId?: string } = {}): Promise<void> {
    return this.t.request<void>(`/api/graph/links/${encodeURIComponent(linkId)}/unhide`, {
      method: 'PATCH',
      query: { notebook_id: opts.notebookId },
    })
  }

  /** DELETE /api/graph/links/{id} — hard-delete a link (204). */
  delete(linkId: string, opts: { notebookId?: string } = {}): Promise<void> {
    return this.t.request<void>(`/api/graph/links/${encodeURIComponent(linkId)}`, {
      method: 'DELETE',
      query: { notebook_id: opts.notebookId },
    })
  }
}

// ── translate ────────────────────────────────────────────────────────────────
// Quota-gated LLM translation. Response shapes are intentionally TERSE
// single-letter fields (t/p/r, t, e) — mirrored verbatim from the backend.
export class TranslateClient {
  constructor(private readonly t: Transport) {}

  /** POST /api/translate/quick — word translation + pronunciation + lemma. */
  quick(req: TranslateRequest): Promise<QuickTranslateResponse> {
    return this.t.request<QuickTranslateResponse>('/api/translate/quick', {
      method: 'POST',
      body: req,
    })
  }

  /** POST /api/translate/phrase — phrase translation. */
  phrase(req: TranslateRequest): Promise<PhraseTranslateResponse> {
    return this.t.request<PhraseTranslateResponse>('/api/translate/phrase', {
      method: 'POST',
      body: req,
    })
  }

  /** POST /api/translate/explain — contextual explanation. */
  explain(req: TranslateRequest): Promise<ExplainResponse> {
    return this.t.request<ExplainResponse>('/api/translate/explain', {
      method: 'POST',
      body: req,
    })
  }
}

// ── pipeline ─────────────────────────────────────────────────────────────────
// Kicks the enrich/embed/judge pipeline for a notebook (quota-gated, async on
// the backend — returns immediately with a queued status).
export class PipelineClient {
  constructor(private readonly t: Transport) {}

  /** POST /api/pipeline — queue a pipeline run for a notebook. */
  trigger(notebookId?: string): Promise<PipelineQueueResponse> {
    return this.t.request<PipelineQueueResponse>('/api/pipeline', {
      method: 'POST',
      query: { notebook_id: notebookId },
    })
  }
}

// ── today review ─────────────────────────────────────────────────────────────
// The "today review queue" is the set of cards due for review, derived from
// GET /api/vocab (cards carry SRS state: nextReviewAt / reviewIntervalHours).
// "submit" persists post-review SRS state via PATCH /api/vocab/review and the
// append-only event log via PATCH /api/vocab/review-events.
export class TodayReviewClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/vocab — review queue source (cards with SRS state). */
  queue(opts: { notebookId?: string } = {}): Promise<CardResponse[]> {
    return this.t.request<CardResponse[]>('/api/vocab', {
      query: { notebook_id: opts.notebookId },
    })
  }

  /** PATCH /api/vocab/review — push updated SRS state for reviewed cards. */
  submitState(req: ReviewStatePushRequest): Promise<ReviewStatePushResponse> {
    return this.t.request<ReviewStatePushResponse>('/api/vocab/review', {
      method: 'PATCH',
      body: req,
    })
  }

  /** GET /api/vocab/review-events — pull review event log (cursor watermark). */
  events(opts: { since?: string } = {}): Promise<ReviewEventsResponse> {
    return this.t.request<ReviewEventsResponse>('/api/vocab/review-events', {
      query: { since: opts.since },
    })
  }

  /** PATCH /api/vocab/review-events — append review events (idempotent). */
  submitEvents(req: ReviewEventsPushRequest): Promise<ReviewEventsPushResponse> {
    return this.t.request<ReviewEventsPushResponse>('/api/vocab/review-events', {
      method: 'PATCH',
      body: req,
    })
  }
}

// ── podcast ──────────────────────────────────────────────────────────────────
// Browse endpoints (series/episodes/cover) allow anonymous (guest) access;
// progress requires auth. Episode media/subtitle bytes are out of scope here
// (binary, tier-gated) — this client covers the JSON editorial + progress face.
export class PodcastClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/podcasts — editorial series catalog (guest-allowed). */
  series(): Promise<PodcastSeriesSummary[]> {
    return this.t.request<PodcastSeriesSummary[]>('/api/podcasts')
  }

  /** GET /api/podcasts/{series_id} — full series metadata incl. episodes. */
  seriesDetail(seriesId: string): Promise<PodcastSeriesDetail> {
    return this.t.request<PodcastSeriesDetail>(
      `/api/podcasts/${encodeURIComponent(seriesId)}`,
    )
  }

  /** GET /api/podcasts/progress — per-user LWW playback progress (auth). */
  progress(): Promise<PodcastProgressListResponse> {
    return this.t.request<PodcastProgressListResponse>('/api/podcasts/progress')
  }

  /** POST /api/podcasts/{series_id}/{ep_num}/progress — upsert progress (auth). */
  putProgress(
    seriesId: string,
    epNum: number,
    req: PodcastProgressRequest,
  ): Promise<PodcastProgressResponse> {
    return this.t.request<PodcastProgressResponse>(
      `/api/podcasts/${encodeURIComponent(seriesId)}/${epNum}/progress`,
      { method: 'POST', body: req },
    )
  }

  /** GET /api/podcasts/{series_id}/{ep_num}/subtitle — raw SRT text (tier-gated). */
  subtitle(seriesId: string, epNum: number): Promise<string> {
    return this.t.requestText(
      `/api/podcasts/${encodeURIComponent(seriesId)}/${epNum}/subtitle`,
    )
  }

  /**
   * Build the audio asset URL for an episode (URL builder only — does NOT fetch).
   * The browser <audio> element streams it directly (Range requests, tier gate
   * + auth enforced server-side). Bearer auth on media is out of scope here.
   */
  audioUrl(seriesId: string, epNum: number): string {
    return this.t.resolveUrl(
      `/api/podcasts/${encodeURIComponent(seriesId)}/${epNum}/audio`,
    )
  }
}

// ── library ──────────────────────────────────────────────────────────────────
export class LibraryClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/library/books — list books (optionally since cursor). */
  list(opts: { since?: string } = {}): Promise<BookMetadataResponse[]> {
    return this.t.request<BookMetadataResponse[]>('/api/library/books', {
      query: { since: opts.since },
    })
  }

  /** POST /api/library/books — create book metadata (idempotent via client_book_id). */
  create(req: BookCreateRequest): Promise<BookMetadataResponse> {
    return this.t.request<BookMetadataResponse>('/api/library/books', {
      method: 'POST',
      body: req,
    })
  }

  /** PATCH /api/library/books/{id} — partial update / notebook binding. */
  update(id: string, req: BookUpdateRequest): Promise<BookMetadataResponse> {
    return this.t.request<BookMetadataResponse>(`/api/library/books/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: req,
    })
  }

  /** PUT /api/library/books/{id}/position — LWW locator/progression. */
  putPosition(id: string, req: BookPositionRequest): Promise<BookMetadataResponse> {
    return this.t.request<BookMetadataResponse>(`/api/library/books/${encodeURIComponent(id)}/position`, {
      method: 'PUT',
      body: req,
    })
  }

  /**
   * DELETE /api/library/books/{id} — soft-delete a book.
   * NEW backend route: contract is encoded in the mock until the route lands.
   */
  delete(id: string): Promise<BookMetadataResponse> {
    return this.t.request<BookMetadataResponse>(`/api/library/books/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    })
  }
}

// ── user config ──────────────────────────────────────────────────────────────
export class UserClient {
  constructor(private readonly t: Transport) {}

  /** GET /api/user/config — per-user settings bundle. */
  config(): Promise<UserConfigResponse> {
    return this.t.request<UserConfigResponse>('/api/user/config')
  }

  /** PUT /api/user/config — partial update (LWW per sub-config). */
  updateConfig(req: UserConfigRequest): Promise<UserConfigResponse> {
    return this.t.request<UserConfigResponse>('/api/user/config', {
      method: 'PUT',
      body: req,
    })
  }

  /** GET /api/user/entitlements — pro subscription status. */
  entitlements(): Promise<EntitlementsResponse> {
    return this.t.request<EntitlementsResponse>('/api/user/entitlements')
  }

  /** GET /api/user/quota — daily LLM quota fraction + reset. */
  quota(): Promise<QuotaResponse> {
    return this.t.request<QuotaResponse>('/api/user/quota')
  }

  /** DELETE /api/user/account — irreversible account + linked-id deletion. */
  deleteAccount(): Promise<DeleteAccountResponse> {
    return this.t.request<DeleteAccountResponse>('/api/user/account', {
      method: 'DELETE',
    })
  }

  /**
   * GET /api/user/profile — identity (id/email/display name).
   * NEW backend route: the live backend has no profile surface (config carries
   * only LWW settings groups), so this contract lives in the mock for now.
   */
  profile(): Promise<UserProfileResponse> {
    return this.t.request<UserProfileResponse>('/api/user/profile')
  }
}
