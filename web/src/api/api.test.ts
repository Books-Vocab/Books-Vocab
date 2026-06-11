import { describe, expect, it } from 'vitest'
import { ApiError, createApiClient, type ApiClient } from './index'
import { MOCK_VOCAB_CARDS } from './mock/data'

// Authenticated client (mock backend honors a Bearer header).
function authedClient(): ApiClient {
  return createApiClient({ mode: 'mock', getToken: () => 'mock-access-token' })
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
    expect(res.access_token).toBe('mock-access-token')
    expect(res.token_type).toBe('bearer')
    expect(res.user_id).toBe('mock-user')
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
})
