// Lightweight in-process mock — a FetchLike that intercepts the same paths the
// real backend exposes and replies from ./data. Chosen over msw to add ZERO npm
// dependencies (the app already runs entirely on global fetch); the contract is
// identical from the client's view: same method+path → same JSON shape + status.
//
// Auth model (mirrors backend): browse podcast + /auth/verify are anonymous;
// every other route requires a Bearer header or replies 401 {code:auth_required},
// so the client's 401 path stays exercisable under mock mode.

import type { FetchLike } from '../transport'
import type { VocabEntry } from '../types'
import {
  MOCK_ACCESS_TOKEN,
  MOCK_DELETE_ACCOUNT,
  MOCK_ENTITLEMENTS,
  MOCK_LIBRARY_BOOKS,
  MOCK_NOTEBOOKS,
  MOCK_PODCAST_DETAIL,
  MOCK_PODCAST_PROGRESS,
  MOCK_PODCAST_SERIES,
  MOCK_QUOTA,
  MOCK_REVIEW_EVENTS,
  MOCK_SUBTITLE_SRT,
  MOCK_USER_CONFIG,
  MOCK_USER_PROFILE,
  MOCK_VOCAB_CARDS,
  mockGraphCreate,
  mockGraphDelete,
  mockGraphList,
  mockGraphSetHidden,
  mockLibraryCreate,
  mockLibraryDelete,
  mockLibraryUpdate,
  mockLibraryPosition,
  mockNotebookCreate,
  mockNotebookUpdate,
  mockTranslateExplain,
  mockTranslatePhrase,
  mockTranslateQuick,
  mockVocabAdd,
  mockVocabArchive,
  mockVocabByWord,
  mockVocabDelete,
  mockVocabUpdateContent,
} from './data'

interface ParsedRequest {
  method: string
  path: string // pathname only, no query
  query: Record<string, string>
  hasAuth: boolean
  body: unknown
}

function json(data: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function text(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  })
}

function unauthorized(): Response {
  return json({ detail: { code: 'auth_required' } }, 401)
}

function notFound(): Response {
  return json({ detail: 'not found' }, 404)
}

function parse(input: string, init?: RequestInit): ParsedRequest {
  // input may be absolute (real base) or relative ("" base). Normalize.
  const url = new URL(input, 'http://mock.local')
  const headers = new Headers(init?.headers)
  const auth = headers.get('Authorization') ?? ''
  let body: unknown
  if (typeof init?.body === 'string') {
    try {
      body = JSON.parse(init.body)
    } catch {
      body = undefined
    }
  }
  const query: Record<string, string> = {}
  for (const [k, v] of url.searchParams) {
    query[k] = v
  }
  return {
    method: (init?.method ?? 'GET').toUpperCase(),
    path: url.pathname,
    query,
    hasAuth: /^Bearer\s+\S+/.test(auth),
    body,
  }
}

type Route = {
  method: string
  /** RegExp over pathname; capture groups passed to handle. */
  pattern: RegExp
  /** When true, no Bearer required. */
  anonymous?: boolean
  handle: (req: ParsedRequest, match: RegExpMatchArray) => Response
}

const ROUTES: Route[] = [
  // auth
  {
    method: 'POST',
    pattern: /^\/auth\/verify$/,
    anonymous: true,
    handle: (req) => {
      const b = req.body as { provider?: unknown; token?: unknown } | undefined
      if (!b || (b.provider !== 'apple' && b.provider !== 'google') || !b.token) {
        return json({ detail: 'invalid provider token' }, 422)
      }
      return json({
        access_token: MOCK_ACCESS_TOKEN,
        token_type: 'bearer',
        user_id: 'mock-user',
        expires_in: 3600,
      })
    },
  },

  // notebook
  {
    method: 'GET',
    pattern: /^\/api\/notebooks$/,
    handle: () => json(MOCK_NOTEBOOKS.filter((n) => !n.isDeleted)),
  },
  {
    method: 'POST',
    pattern: /^\/api\/notebooks$/,
    handle: (req) => {
      const body = (req.body ?? {}) as { name?: unknown; color?: unknown; cover_pattern?: unknown }
      if (!body.name || typeof body.name !== 'string') {
        return json({ detail: 'name is required' }, 422)
      }
      const created = mockNotebookCreate({
        name: body.name,
        color: typeof body.color === 'string' ? body.color : null,
        cover_pattern: typeof body.cover_pattern === 'string' ? body.cover_pattern : null,
      })
      MOCK_NOTEBOOKS.push(created)
      return json(created, 201)
    },
  },
  {
    method: 'PATCH',
    pattern: /^\/api\/notebooks\/([^/]+)$/,
    handle: (req, m) => {
      const id = decodeURIComponent(m[1])
      const body = (req.body ?? {}) as Record<string, unknown>
      const updated = mockNotebookUpdate(id, {
        name: typeof body.name === 'string' ? body.name : undefined,
        color: body.color !== undefined ? (typeof body.color === 'string' ? body.color : null) : undefined,
        sort_order: typeof body.sort_order === 'number' ? body.sort_order : undefined,
        cover_pattern: body.cover_pattern !== undefined ? (typeof body.cover_pattern === 'string' ? body.cover_pattern : null) : undefined,
      })
      return updated ? json(updated) : notFound()
    },
  },
  {
    method: 'DELETE',
    pattern: /^\/api\/notebooks\/([^/]+)$/,
    handle: (_req, m) => {
      const id = decodeURIComponent(m[1])
      const idx = MOCK_NOTEBOOKS.findIndex((n) => n.id === id)
      if (idx < 0) return notFound()
      if (MOCK_NOTEBOOKS[idx].isDefault) {
        return json({ detail: 'cannot delete default notebook' }, 400)
      }
      const cardsDeleted = MOCK_NOTEBOOKS[idx].cardCount
      MOCK_NOTEBOOKS.splice(idx, 1)
      return json({ deleted: id, cardsDeleted })
    },
  },

  // vocabulary
  {
    method: 'GET',
    pattern: /^\/api\/vocab$/,
    handle: (req) => {
      const notebookId = req.query.notebook_id
      if (notebookId) {
        return json(MOCK_VOCAB_CARDS.filter((c) => c.notebookId === notebookId))
      }
      return json(MOCK_VOCAB_CARDS)
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/vocab$/,
    handle: (req) => {
      // Body is a list of VocabEntry; keep only well-formed rows so the response
      // cardIds echo the submitted word byte-exactly (sync reconcile contract).
      const entries = (Array.isArray(req.body) ? req.body : []).filter(
        (e): e is VocabEntry =>
          typeof e === 'object' && e !== null && typeof (e as { word?: unknown }).word === 'string',
      )
      return json(mockVocabAdd(entries))
    },
  },
  {
    method: 'PATCH',
    pattern: /^\/api\/vocab\/review$/,
    handle: (req) => {
      const b = req.body as { entries?: unknown[] } | undefined
      const n = Array.isArray(b?.entries) ? b!.entries.length : 0
      return json({ updated: n, skipped: 0 })
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/vocab\/review-events$/,
    handle: () => json(MOCK_REVIEW_EVENTS),
  },
  {
    // POST /api/vocab/batch-delete — partitions requested words into deleted /
    // not_found against the current store, then removes the matched cards.
    method: 'POST',
    pattern: /^\/api\/vocab\/batch-delete$/,
    handle: (req) => {
      const b = (req.body ?? {}) as { words?: unknown }
      const words = Array.isArray(b.words) ? b.words.filter((w): w is string => typeof w === 'string') : []
      const deleted_words: string[] = []
      const not_found: string[] = []
      for (const w of words) {
        if (mockVocabDelete(w)) deleted_words.push(w)
        else not_found.push(w)
      }
      return json({ deleted: deleted_words.length, deleted_words, not_found, failed: [] })
    },
  },
  {
    // PATCH /api/vocab/batch-archive — partitions then flips the archived flag.
    method: 'PATCH',
    pattern: /^\/api\/vocab\/batch-archive$/,
    handle: (req) => {
      const b = (req.body ?? {}) as { words?: unknown; archived?: unknown }
      const words = Array.isArray(b.words) ? b.words.filter((w): w is string => typeof w === 'string') : []
      const archived = typeof b.archived === 'boolean' ? b.archived : true
      const updated_words: string[] = []
      const not_found: string[] = []
      for (const w of words) {
        if (mockVocabArchive(w, archived)) updated_words.push(w)
        else not_found.push(w)
      }
      return json({ updated: updated_words.length, updated_words, not_found, failed: [] })
    },
  },
  {
    method: 'PATCH',
    pattern: /^\/api\/vocab\/review-events$/,
    handle: (req) => {
      const b = req.body as { entries?: unknown[] } | undefined
      const n = Array.isArray(b?.entries) ? b!.entries.length : 0
      return json({ inserted: n, skipped: 0 })
    },
  },
  {
    // PATCH /api/vocab/{word}/archive — single-card archive toggle. Registered
    // after batch-archive (a static path) so the {word} group can't swallow it.
    method: 'PATCH',
    pattern: /^\/api\/vocab\/([^/]+)\/archive$/,
    handle: (req, m) => {
      const word = decodeURIComponent(m[1])
      const b = (req.body ?? {}) as { archived?: unknown }
      const archived = typeof b.archived === 'boolean' ? b.archived : true
      const c = mockVocabArchive(word, archived)
      return c ? json({ word: c.content, id: c.id, archived: c.isArchived }) : notFound()
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/vocab\/([^/]+)$/,
    handle: (_req, m) => {
      const c = mockVocabByWord(decodeURIComponent(m[1]))
      return c ? json(c) : notFound()
    },
  },
  {
    method: 'DELETE',
    pattern: /^\/api\/vocab\/([^/]+)$/,
    handle: (_req, m) => {
      const word = decodeURIComponent(m[1])
      const c = mockVocabDelete(word)
      return c ? json({ deleted: word, id: c.id }) : notFound()
    },
  },
  {
    // PATCH /api/vocab/{word} — NEW backend partial content edit (mock-only).
    // Registered after the static PATCH vocab routes (review / review-events /
    // batch-archive) so those win for their reserved subpaths.
    method: 'PATCH',
    pattern: /^\/api\/vocab\/([^/]+)$/,
    handle: (req, m) => {
      const word = decodeURIComponent(m[1])
      const body = (req.body ?? {}) as Record<string, unknown>
      const c = mockVocabUpdateContent(word, {
        meaning: typeof body.meaning === 'string' ? body.meaning : undefined,
        note: body.note !== undefined ? (typeof body.note === 'string' ? body.note : null) : undefined,
        explanation: typeof body.explanation === 'string' ? body.explanation : undefined,
      })
      return c ? json(c) : notFound()
    },
  },

  // graph links
  {
    method: 'GET',
    pattern: /^\/api\/graph\/links$/,
    handle: (req) => json(mockGraphList(req.query.notebook_id ?? 'default')),
  },
  {
    method: 'POST',
    pattern: /^\/api\/graph\/links$/,
    handle: (req) => {
      const b = (req.body ?? {}) as { from_id?: unknown; to_id?: unknown }
      if (typeof b.from_id !== 'string' || !b.from_id || typeof b.to_id !== 'string' || !b.to_id) {
        return json({ detail: 'from_id and to_id are required' }, 422)
      }
      return json(mockGraphCreate({ from_id: b.from_id, to_id: b.to_id }, req.query.notebook_id ?? 'default'), 201)
    },
  },
  {
    method: 'PATCH',
    pattern: /^\/api\/graph\/links\/([^/]+)\/hide$/,
    handle: (_req, m) =>
      mockGraphSetHidden(decodeURIComponent(m[1]), true) ? json(null, 204) : notFound(),
  },
  {
    method: 'PATCH',
    pattern: /^\/api\/graph\/links\/([^/]+)\/unhide$/,
    handle: (_req, m) =>
      mockGraphSetHidden(decodeURIComponent(m[1]), false) ? json(null, 204) : notFound(),
  },
  {
    method: 'DELETE',
    pattern: /^\/api\/graph\/links\/([^/]+)$/,
    handle: (_req, m) =>
      mockGraphDelete(decodeURIComponent(m[1])) ? json(null, 204) : notFound(),
  },

  // translate — quota-gated LLM (terse t/p/r, t, e shapes)
  {
    method: 'POST',
    pattern: /^\/api\/translate\/quick$/,
    handle: (req) => {
      const b = (req.body ?? {}) as { word?: unknown }
      if (typeof b.word !== 'string' || !b.word) return json({ detail: 'word is required' }, 422)
      return json(mockTranslateQuick(b.word))
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/translate\/phrase$/,
    handle: (req) => {
      const b = (req.body ?? {}) as { word?: unknown }
      if (typeof b.word !== 'string' || !b.word) return json({ detail: 'word is required' }, 422)
      return json(mockTranslatePhrase(b.word))
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/translate\/explain$/,
    handle: (req) => {
      const b = (req.body ?? {}) as { word?: unknown }
      if (typeof b.word !== 'string' || !b.word) return json({ detail: 'word is required' }, 422)
      return json(mockTranslateExplain(b.word))
    },
  },

  // pipeline — queue an async run (returns immediately)
  {
    method: 'POST',
    pattern: /^\/api\/pipeline$/,
    handle: () => json({ status: 'queued', message: 'pipeline scheduled' }),
  },

  // library
  {
    method: 'GET',
    pattern: /^\/api\/library\/books$/,
    handle: (req) => {
      const since = req.query.since
      let books = MOCK_LIBRARY_BOOKS
      if (since) {
        books = books.filter((b) => b.updated_at && b.updated_at > since)
      }
      return json(books.filter((b) => !b.is_deleted))
    },
  },
  {
    method: 'POST',
    pattern: /^\/api\/library\/books$/,
    handle: (req) => {
      const body = (req.body ?? {}) as {
        client_book_id?: unknown
        title?: unknown
        author?: unknown
        language?: unknown
        format?: unknown
      }
      if (!body.client_book_id || typeof body.client_book_id !== 'string') {
        return json({ detail: 'client_book_id is required' }, 422)
      }
      if (!body.title || typeof body.title !== 'string') {
        return json({ detail: 'title is required' }, 422)
      }
      const created = mockLibraryCreate({
        client_book_id: body.client_book_id,
        title: body.title,
        author: typeof body.author === 'string' ? body.author : null,
        language: typeof body.language === 'string' ? body.language : null,
        format: typeof body.format === 'string' ? body.format : null,
      })
      return json(created, 201)
    },
  },
  {
    method: 'PATCH',
    pattern: /^\/api\/library\/books\/([^/]+)$/,
    handle: (req, m) => {
      const id = decodeURIComponent(m[1])
      const body = (req.body ?? {}) as Record<string, unknown>
      const updated = mockLibraryUpdate(id, {
        title: typeof body.title === 'string' ? body.title : undefined,
        author: body.author !== undefined ? (typeof body.author === 'string' ? body.author : null) : undefined,
        language: body.language !== undefined ? (typeof body.language === 'string' ? body.language : null) : undefined,
        format: body.format !== undefined ? (typeof body.format === 'string' ? body.format : null) : undefined,
        notebook_id: body.notebook_id !== undefined ? (typeof body.notebook_id === 'string' ? body.notebook_id : null) : undefined,
      })
      return updated ? json(updated) : notFound()
    },
  },
  {
    method: 'PUT',
    pattern: /^\/api\/library\/books\/([^/]+)\/position$/,
    handle: (req, m) => {
      const id = decodeURIComponent(m[1])
      const body = (req.body ?? {}) as {
        locator?: unknown
        progression?: unknown
        updated_at?: unknown
      }
      const updated = mockLibraryPosition(id, {
        locator: typeof body.locator === 'string' ? body.locator : null,
        progression: typeof body.progression === 'number' ? body.progression : null,
        position_updated_at: typeof body.updated_at === 'string' ? body.updated_at : null,
      })
      return updated ? json(updated) : notFound()
    },
  },
  {
    // DELETE /api/library/books/{id} — soft-delete; returns { deleted: id } and
    // tombstones the in-memory row so list() excludes it (matches backend).
    method: 'DELETE',
    pattern: /^\/api\/library\/books\/([^/]+)$/,
    handle: (_req, m) => {
      const deleted = mockLibraryDelete(decodeURIComponent(m[1]))
      return deleted ? json(deleted) : notFound()
    },
  },

  // podcast — browse is anonymous
  {
    method: 'GET',
    pattern: /^\/api\/podcasts$/,
    anonymous: true,
    handle: () => json(MOCK_PODCAST_SERIES),
  },
  {
    method: 'GET',
    pattern: /^\/api\/podcasts\/progress$/,
    handle: () => json(MOCK_PODCAST_PROGRESS),
  },
  {
    method: 'POST',
    pattern: /^\/api\/podcasts\/([^/]+)\/(\d+)\/progress$/,
    handle: (req, m) => {
      const b = (req.body ?? {}) as {
        position_sec?: number
        duration_sec?: number
        updated_at?: string
      }
      return json({
        series_id: decodeURIComponent(m[1]),
        ep_num: Number(m[2]),
        position_sec: b.position_sec ?? 0,
        duration_sec: b.duration_sec ?? 0,
        updated_at: b.updated_at ?? '2026-06-11T00:00:00Z',
      })
    },
  },
  {
    // GET /api/podcasts/{series}/{ep}/subtitle — raw SRT (text/plain).
    // Registered before the bare {series_id} route so it wins the match.
    method: 'GET',
    pattern: /^\/api\/podcasts\/([^/]+)\/(\d+)\/subtitle$/,
    handle: () => text(MOCK_SUBTITLE_SRT),
  },
  {
    method: 'GET',
    pattern: /^\/api\/podcasts\/([^/]+)$/,
    anonymous: true,
    handle: () => json(MOCK_PODCAST_DETAIL),
  },

  // user
  {
    method: 'GET',
    pattern: /^\/api\/user\/config$/,
    handle: () => json(MOCK_USER_CONFIG),
  },
  {
    method: 'PUT',
    pattern: /^\/api\/user\/config$/,
    handle: (req) => {
      // Echo merge: applied sub-configs overwrite, mirroring LWW upsert.
      const patch = (req.body ?? {}) as Record<string, unknown>
      return json({ ...MOCK_USER_CONFIG, ...patch })
    },
  },
  {
    method: 'GET',
    pattern: /^\/api\/user\/entitlements$/,
    handle: () => json(MOCK_ENTITLEMENTS),
  },
  {
    method: 'GET',
    pattern: /^\/api\/user\/quota$/,
    handle: () => json(MOCK_QUOTA),
  },
  {
    // GET /api/user/profile — NEW backend (mock-only) identity contract.
    method: 'GET',
    pattern: /^\/api\/user\/profile$/,
    handle: () => json(MOCK_USER_PROFILE),
  },
  {
    // DELETE /api/user/account — mirrors DeleteAccountResponse (200 + body),
    // matching backend/src/kg/routers/user.py:60 (response_model, not 204).
    method: 'DELETE',
    pattern: /^\/api\/user\/account$/,
    handle: () => json(MOCK_DELETE_ACCOUNT),
  },
]

/** Build a FetchLike that serves the mock backend. */
export function createMockFetch(): FetchLike {
  return async (input, init) => {
    const req = parse(input, init)
    for (const route of ROUTES) {
      if (route.method !== req.method) continue
      const match = req.path.match(route.pattern)
      if (!match) continue
      if (!route.anonymous && !req.hasAuth) return unauthorized()
      return route.handle(req, match)
    }
    return json({ detail: `no mock route for ${req.method} ${req.path}` }, 404)
  }
}
