// Typed domain clients. Each method maps 1:1 onto a backend route (path +
// method verified against backend/src/kg/routers/*.py) and returns the
// hand-mirrored response type from ./types.

import type { Transport } from './transport'
import type {
  AuthVerifyRequest,
  AuthVerifyResponse,
  BookCreateRequest,
  BookMetadataResponse,
  BookPositionRequest,
  BookUpdateRequest,
  CardResponse,
  EntitlementsResponse,
  NotebookCreateRequest,
  NotebookResponse,
  NotebookUpdateRequest,
  PodcastProgressListResponse,
  PodcastProgressRequest,
  PodcastProgressResponse,
  PodcastSeriesDetail,
  PodcastSeriesSummary,
  QuotaResponse,
  ReviewEventsPushRequest,
  ReviewEventsPushResponse,
  ReviewEventsResponse,
  ReviewStatePushRequest,
  ReviewStatePushResponse,
  UserConfigRequest,
  UserConfigResponse,
  VocabAddResponse,
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
}
