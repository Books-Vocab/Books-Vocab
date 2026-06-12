// Lightweight in-process mock — a FetchLike that intercepts the same paths the
// real backend exposes and replies from ./data. Chosen over msw to add ZERO npm
// dependencies (the app already runs entirely on global fetch); the contract is
// identical from the client's view: same method+path → same JSON shape + status.
//
// Auth model (mirrors backend): browse podcast + /auth/verify are anonymous;
// every other route requires a Bearer header or replies 401 {code:auth_required},
// so the client's 401 path stays exercisable under mock mode.

import type { FetchLike } from '../transport'
import {
  MOCK_ACCESS_TOKEN,
  MOCK_ENTITLEMENTS,
  MOCK_NOTEBOOKS,
  MOCK_PODCAST_DETAIL,
  MOCK_PODCAST_PROGRESS,
  MOCK_PODCAST_SERIES,
  MOCK_QUOTA,
  MOCK_REVIEW_EVENTS,
  MOCK_USER_CONFIG,
  MOCK_VOCAB_CARDS,
  mockNotebookCreate,
  mockNotebookUpdate,
  mockVocabAdd,
  mockVocabByWord,
} from './data'

interface ParsedRequest {
  method: string
  path: string // pathname only, no query
  hasAuth: boolean
  body: unknown
}

function json(data: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
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
  return {
    method: (init?.method ?? 'GET').toUpperCase(),
    path: url.pathname,
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
    handle: () => json(MOCK_VOCAB_CARDS),
  },
  {
    method: 'POST',
    pattern: /^\/api\/vocab$/,
    handle: (req) => {
      const entries = Array.isArray(req.body) ? req.body : []
      return json(mockVocabAdd(entries.length))
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
    method: 'PATCH',
    pattern: /^\/api\/vocab\/review-events$/,
    handle: (req) => {
      const b = req.body as { entries?: unknown[] } | undefined
      const n = Array.isArray(b?.entries) ? b!.entries.length : 0
      return json({ inserted: n, skipped: 0 })
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
