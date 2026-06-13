import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient, type ApiClient } from './index'
import { MOCK_VOCAB_CARDS } from './mock/data'

// Authenticated client (mock backend honors a Bearer header).
function authedClient(): ApiClient {
  return createApiClient({ mode: 'mock', getToken: () => 'demo-access-token' })
}

// Logged-out client — no token → protected routes reply 401.
function anonClient(): ApiClient {
  return createApiClient({ mode: 'mock', getToken: () => null })
}

/** Run a call and capture the thrown ApiError (fails the test if none thrown). */
async function expectApiError(fn: () => Promise<unknown>): Promise<ApiError> {
  try {
    await fn()
  } catch (e) {
    if (e instanceof ApiError) return e
    throw e
  }
  throw new Error('expected ApiError, but call resolved')
}

describe('api client — mode wiring', () => {
  it('defaults to mock mode and uses an empty base URL', () => {
    expect(createApiClient().mode).toBe('mock')
  })

  it('respects an explicit real mode', () => {
    const api = createApiClient({ mode: 'real', baseUrl: 'https://wordnexus.lol' })
    expect(api.mode).toBe('real')
  })
})

describe('auth', () => {
  it('verify() exchanges a provider token for an access token (happy path)', async () => {
    const res = await anonClient().auth.verify({ provider: 'apple', token: 'tok' })
    expect(res.access_token).toBe('demo-access-token')
    expect(res.token_type).toBe('bearer')
    expect(res.user_id).toBe('demo-user')
    expect(res.expires_in).toBeGreaterThan(0)
  })

  it('verify() surfaces a 422 on an invalid request', async () => {
    const err = await expectApiError(() =>
      // @ts-expect-error — deliberately invalid provider to exercise validation
      anonClient().auth.verify({ provider: 'nope', token: '' }),
    )
    expect(err.status).toBe(422)
  })
})

describe('vocabulary', () => {
  it('list() returns the seeded cards (happy path)', async () => {
    const cards = await authedClient().vocabulary.list()
    expect(cards).toHaveLength(MOCK_VOCAB_CARDS.length)
    expect(cards[0].content).toBe(MOCK_VOCAB_CARDS[0].content)
    expect(cards[0]).toHaveProperty('reviewIntervalHours')
  })

  it('detail() returns a single card by word', async () => {
    const word = MOCK_VOCAB_CARDS[0].content
    const card = await authedClient().vocabulary.detail(word)
    expect(card.content).toBe(word)
  })

  it('detail() 404s on an unknown word', async () => {
    const err = await expectApiError(() => authedClient().vocabulary.detail('zzznope'))
    expect(err.status).toBe(404)
  })

  it('add() reports created count', async () => {
    const res = await authedClient().vocabulary.add([
      { word: 'ephemeral', translation: '短暫的' },
    ])
    expect(res.created).toBe(1)
    expect(res.skipped).toBe(0)
  })

  // Regression: the sync SoT (docs/reference/sync_lifecycle.md §cardIds 不變式)
  // requires response.cardIds to be keyed by the client-submitted word as a
  // BYTE-EXACT echo (no NFC / case / trim). Previously mockVocabAdd keyed by
  // `pending-${i}` (index), which silently broke per-word reconcile.
  it('add() echoes the submitted word byte-exactly as the cardIds key', async () => {
    const entries = [
      { word: 'serendipity', translation: '機緣' },
      { word: 'ÉPHÉMÈRE', translation: '短暫' }, // accents + uppercase: no normalization
      { word: '  spaced  ', translation: '空白' }, // surrounding whitespace: no trim
    ]
    const res = await authedClient().vocabulary.add(entries)
    expect(res.created).toBe(entries.length)
    // Every submitted word is present as a key, byte-for-byte.
    for (const e of entries) {
      expect(res.cardIds).toHaveProperty(e.word)
      expect(typeof res.cardIds[e.word]).toBe('string')
      expect(res.cardIds[e.word].length).toBeGreaterThan(0)
    }
    // Keys are exactly the submitted words — no index keys, no normalized keys.
    expect(Object.keys(res.cardIds).sort()).toEqual(entries.map((e) => e.word).sort())
  })

  it('list() with notebookId filters by notebook_id query param', async () => {
    const cards = await authedClient().vocabulary.list({ notebookId: 'editorial-picks' })
    // The demo dataset assigns every card to a named notebook; editorial-picks
    // holds 5. Filtering must return only that notebook's cards.
    expect(cards.length).toBeGreaterThan(0)
    expect(cards.every((c) => c.notebookId === 'editorial-picks')).toBe(true)
  })

  it('list() with unknown notebookId returns empty', async () => {
    const cards = await authedClient().vocabulary.list({ notebookId: 'unknown-nb' })
    expect(cards).toHaveLength(0)
  })

  it('list() throws a 401 when logged out', async () => {
    const err = await expectApiError(() => anonClient().vocabulary.list())
    expect(err.isUnauthorized).toBe(true)
    expect(err.status).toBe(401)
    expect(err.code).toBe('auth_required')
  })
})

describe('today review', () => {
  it('queue() returns cards with SRS state (happy path)', async () => {
    const cards = await authedClient().todayReview.queue()
    expect(cards.length).toBeGreaterThan(0)
    expect(cards[0]).toHaveProperty('nextReviewAt')
  })

  it('submitState() acks the pushed entries', async () => {
    const res = await authedClient().todayReview.submitState({
      entries: [
        {
          word: 'ephemeral',
          review_interval_hours: 12,
          next_review_at: '2026-06-12T00:00:00Z',
          last_reviewed_at: '2026-06-11T00:00:00Z',
          review_count: 1,
          lapse_count: 0,
          review_streak: 1,
          last_review_feedback: 1,
        },
      ],
    })
    expect(res.updated).toBe(1)
  })

  it('submitEvents() acks appended events', async () => {
    const res = await authedClient().todayReview.submitEvents({
      entries: [
        {
          event_id: 'evt-1',
          word_snapshot: 'ephemeral',
          notebook_id: 'default',
          feedback: 1,
          reviewed_at: '2026-06-11T00:00:00Z',
          created_at: '2026-06-11T00:00:00Z',
          is_synthetic: false,
        },
      ],
    })
    expect(res.inserted).toBe(1)
  })

  it('submitState() throws 401 when logged out', async () => {
    const err = await expectApiError(() =>
      anonClient().todayReview.submitState({ entries: [] }),
    )
    expect(err.status).toBe(401)
  })
})

describe('podcast', () => {
  it('series() is reachable for guests (anonymous browse)', async () => {
    const series = await anonClient().podcast.series()
    expect(Array.isArray(series)).toBe(true)
    expect(series.length).toBeGreaterThan(0)
  })

  it('seriesDetail() returns editorial metadata for guests', async () => {
    const detail = await anonClient().podcast.seriesDetail('pride-and-prejudice')
    expect(detail).toHaveProperty('episodes')
  })

  it('progress() returns per-user items (happy path)', async () => {
    const res = await authedClient().podcast.progress()
    expect(res.items.length).toBeGreaterThan(0)
    expect(res.items[0]).toHaveProperty('position_sec')
  })

  it('putProgress() echoes the upserted progress', async () => {
    const res = await authedClient().podcast.putProgress('pride-and-prejudice', 2, {
      position_sec: 100,
      duration_sec: 1740,
      updated_at: '2026-06-11T00:00:00Z',
    })
    expect(res.series_id).toBe('pride-and-prejudice')
    expect(res.ep_num).toBe(2)
    expect(res.position_sec).toBe(100)
  })

  it('progress() throws 401 when logged out', async () => {
    const err = await expectApiError(() => anonClient().podcast.progress())
    expect(err.status).toBe(401)
  })
})

describe('user config', () => {
  it('config() returns the settings bundle (happy path)', async () => {
    const cfg = await authedClient().user.config()
    expect(cfg.review_mode?.mode).toBe('relaxed')
  })

  it('updateConfig() merges the patch', async () => {
    const cfg = await authedClient().user.updateConfig({
      review_clock: { is_paused: true, paused_at: '2026-06-11T00:00:00Z', updated_at: 1 },
    })
    expect(cfg.review_clock?.is_paused).toBe(true)
  })

  it('entitlements() returns pro status', async () => {
    const ent = await authedClient().user.entitlements()
    expect(ent.pro).toHaveProperty('is_active')
  })

  it('quota() returns a fraction in [0,1]', async () => {
    const q = await authedClient().user.quota()
    expect(q.fraction).toBeGreaterThanOrEqual(0)
    expect(q.fraction).toBeLessThanOrEqual(1)
  })

  it('config() throws 401 when logged out', async () => {
    const err = await expectApiError(() => anonClient().user.config())
    expect(err.status).toBe(401)
  })

  it('profile() returns identity (mock-only NEW contract)', async () => {
    const p = await authedClient().user.profile()
    expect(p.user_id).toBe('demo-user')
    expect(p).toHaveProperty('email')
    expect(p).toHaveProperty('display_name')
  })

  it('deleteAccount() returns the deletion summary (200 + body)', async () => {
    const res = await authedClient().user.deleteAccount()
    expect(res.deleted_user_id).toBe('demo-user')
    expect(Array.isArray(res.linked_ids)).toBe(true)
    expect(Array.isArray(res.deleted_dirs)).toBe(true)
  })
})

describe('translate', () => {
  it('quick() mirrors the terse {t,p,r} shape', async () => {
    const res = await authedClient().translate.quick({ word: 'serendipity' })
    expect(typeof res.t).toBe('string')
    expect(res.t.length).toBeGreaterThan(0)
    expect(res).toHaveProperty('p')
    expect(res).toHaveProperty('r')
  })

  it('phrase() mirrors the terse {t} shape', async () => {
    const res = await authedClient().translate.phrase({ word: 'a good fortune' })
    expect(typeof res.t).toBe('string')
    expect(res.t.length).toBeGreaterThan(0)
  })

  it('explain() mirrors the terse {e} shape', async () => {
    const res = await authedClient().translate.explain({ word: 'ineffable' })
    expect(typeof res.e).toBe('string')
    expect(res.e.length).toBeGreaterThan(0)
  })

  it('quick() throws 401 when logged out', async () => {
    const err = await expectApiError(() => anonClient().translate.quick({ word: 'x' }))
    expect(err.status).toBe(401)
  })
})

describe('graph links', () => {
  it('list() returns the seeded visible links with the full typed shape', async () => {
    // The demo dataset scopes links to named notebooks; editorial-picks holds 3.
    const links = await authedClient().graph.list('editorial-picks')
    expect(links.length).toBeGreaterThan(0)
    // Every link mirrors GraphLinkResponse: id/fromId/toId/kind/confidence/reason.
    for (const l of links) {
      expect(typeof l.id).toBe('string')
      expect(typeof l.fromId).toBe('string')
      expect(typeof l.toId).toBe('string')
      expect(typeof l.kind).toBe('string')
      expect(typeof l.confidence).toBe('number')
      expect(l.confidence).toBeGreaterThanOrEqual(0)
      expect(l.confidence).toBeLessThanOrEqual(1)
      expect(typeof l.reason).toBe('string')
    }
  })

  it('create() returns a new link', async () => {
    const link = await authedClient().graph.create({ from_id: 'card-1', to_id: 'card-4' })
    expect(link.fromId).toBe('card-1')
    expect(link.toId).toBe('card-4')
    expect(link.id).toMatch(/^link-/)
  })

  it('hide() then unhide() round-trips (link reappears in list)', async () => {
    const api = authedClient()
    // link-1 lives in editorial-picks; scope list/toggle to that notebook.
    await api.graph.hide('link-1') // 204, no body
    let links = await api.graph.list('editorial-picks')
    expect(links.some((l) => l.id === 'link-1')).toBe(false)
    await api.graph.unhide('link-1')
    links = await api.graph.list('editorial-picks')
    expect(links.some((l) => l.id === 'link-1')).toBe(true)
  })

  it('delete() removes a link', async () => {
    const api = authedClient()
    // link-3 lives in editorial-picks; delete then re-list that notebook.
    await api.graph.delete('link-3')
    const links = await api.graph.list('editorial-picks')
    expect(links.some((l) => l.id === 'link-3')).toBe(false)
  })

  it('list() throws 401 when logged out', async () => {
    const err = await expectApiError(() => anonClient().graph.list())
    expect(err.status).toBe(401)
  })
})

describe('pipeline', () => {
  it('trigger() returns a queued status', async () => {
    const res = await authedClient().pipeline.trigger('default')
    expect(res.status).toBe('queued')
    expect(typeof res.message).toBe('string')
  })

  it('trigger() throws 401 when logged out', async () => {
    const err = await expectApiError(() => anonClient().pipeline.trigger())
    expect(err.status).toBe(401)
  })
})

describe('podcast media', () => {
  it('subtitle() returns raw SRT text', async () => {
    const srt = await authedClient().podcast.subtitle('pride-and-prejudice', 1)
    expect(typeof srt).toBe('string')
    expect(srt).toContain('-->')
  })

  it('audioUrl() composes the episode audio path (no fetch)', () => {
    const url = authedClient().podcast.audioUrl('pride-and-prejudice', 2)
    expect(url).toBe('/api/podcasts/pride-and-prejudice/2/audio')
  })

  it('subtitle() throws 401 when logged out', async () => {
    const err = await expectApiError(() =>
      anonClient().podcast.subtitle('pride-and-prejudice', 1),
    )
    expect(err.status).toBe(401)
  })
})

// Destructive vocab-mutation tests run last: they mutate the shared mock store
// (archive flips in place; delete removes rows). They target words/links not
// asserted by earlier tests so ordering stays safe.
describe('vocabulary mutations', () => {
  it('archive() then restore round-trips the flag', async () => {
    const api = authedClient()
    const archived = await api.vocabulary.archive('meticulous', true)
    expect(archived.word).toBe('meticulous')
    expect(archived.archived).toBe(true)
    const restored = await api.vocabulary.archive('meticulous', false)
    expect(restored.archived).toBe(false)
  })

  it('updateContent() applies a partial patch (mock-only NEW route)', async () => {
    const card = await authedClient().vocabulary.updateContent('discerning', {
      meaning: '有洞察力的（已編輯）',
      note: '使用者註記',
    })
    expect(card.content).toBe('discerning')
    expect(card.meaning).toBe('有洞察力的（已編輯）')
    expect(card.note).toBe('使用者註記')
  })

  it('updateContent() 404s on an unknown word', async () => {
    const err = await expectApiError(() =>
      authedClient().vocabulary.updateContent('zzznope', { meaning: 'x' }),
    )
    expect(err.status).toBe(404)
  })

  it('batchArchive() partitions into updated / not_found', async () => {
    const res = await authedClient().vocabulary.batchArchive(['evoke', 'zzznope'], true)
    expect(res.updated_words).toContain('evoke')
    expect(res.not_found).toContain('zzznope')
    expect(res.failed).toEqual([])
  })

  it('batchDelete() removes matched words and reports not_found', async () => {
    const res = await authedClient().vocabulary.batchDelete(['luminous', 'zzznope'])
    expect(res.deleted_words).toContain('luminous')
    expect(res.not_found).toContain('zzznope')
    expect(res.deleted).toBe(1)
  })

  it('delete() removes a single card', async () => {
    const res = await authedClient().vocabulary.delete('nuance')
    expect(res.deleted).toBe('nuance')
    expect(res.id).toBeTruthy()
    const err = await expectApiError(() => authedClient().vocabulary.detail('nuance'))
    expect(err.status).toBe(404)
  })

  it('delete() 404s on an unknown word', async () => {
    const err = await expectApiError(() => authedClient().vocabulary.delete('zzznope'))
    expect(err.status).toBe(404)
  })
})

describe('library mutations', () => {
  it('delete() returns { deleted } and removes the book from list()', async () => {
    const api = authedClient()
    const before = await api.library.list()
    const target = before[before.length - 1]
    const deleted = await api.library.delete(target.id)
    expect(deleted).toEqual({ deleted: target.id })
    const after = await api.library.list()
    expect(after.some((b) => b.id === target.id)).toBe(false)
  })

  it('delete() 404s on an unknown book', async () => {
    const err = await expectApiError(() => authedClient().library.delete('book-nope'))
    expect(err.status).toBe(404)
  })
})
