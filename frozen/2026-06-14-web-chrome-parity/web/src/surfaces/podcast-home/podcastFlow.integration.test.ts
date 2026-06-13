import { describe, expect, it } from 'vitest'
import { createApiClient } from '../../api'
import { buildContinueShelf, indexCatalog } from '../podcast/continueShelf'
import { activeCueIndex, parseSrt } from '../podcast/srt'
import { DEMO_SRT } from '../podcast/demoSrt'
import { tierFromEntitlements } from '../podcast/tier'

// End-to-end against the in-process mock backend (VITE_API_MODE default 'mock'):
// proves the shell-gated functional flow works fully offline, exercising the
// same call sequence usePodcastData drives — anonymous browse, /auth/verify to
// mint a token, then the authed progress + entitlements calls — and the pure
// derivations (tier, continue-shelf, subtitle) that the UI renders from them.

function mockClient() {
  let token: string | null = null
  const api = createApiClient({ getToken: () => token })
  return { api, setToken: (t: string | null) => (token = t) }
}

describe('podcast functional flow (mock-first, offline)', () => {
  it('browses series anonymously', async () => {
    const { api } = mockClient()
    const series = await api.podcast.series()
    expect(series.length).toBeGreaterThan(0)
    expect(series[0].id).toBe('pride-and-prejudice')
  })

  it('authed progress + entitlements require a minted token', async () => {
    const { api, setToken } = mockClient()
    // without a token the mock backend 401s the authed routes
    await expect(api.podcast.progress()).rejects.toMatchObject({ status: 401 })

    const auth = await api.auth.verify({ provider: 'apple', token: 'mock-provider-token' })
    expect(auth.access_token).toBeTruthy()
    setToken(auth.access_token)

    const progress = await api.podcast.progress()
    const entitlements = await api.user.entitlements()
    expect(progress.items.length).toBeGreaterThan(0)
    expect(entitlements.pro.is_active).toBe(false)
  })

  it('resolves to free tier under the default mock (logged in, no pro)', async () => {
    const { api, setToken } = mockClient()
    const auth = await api.auth.verify({ provider: 'apple', token: 'mock-provider-token' })
    setToken(auth.access_token)
    const entitlements = await api.user.entitlements()
    expect(tierFromEntitlements(entitlements, true)).toBe('free')
    // logged-out view of the same payload is a guest
    expect(tierFromEntitlements(entitlements, false)).toBe('guest')
  })

  it('derives the continue shelf from progress joined to the catalog', async () => {
    const { api, setToken } = mockClient()
    const series = await api.podcast.series()
    const detail = await api.podcast.seriesDetail(String(series[0].id))
    const auth = await api.auth.verify({ provider: 'apple', token: 'mock-provider-token' })
    setToken(auth.access_token)
    const progress = await api.podcast.progress()

    // mock progress: pride ep1 @ 6.09/1832 (unfinished) → one continue row
    const shelf = buildContinueShelf(progress, indexCatalog([detail]))
    expect(shelf).toHaveLength(1)
    expect(shelf[0].seriesId).toBe('pride-and-prejudice')
    expect(shelf[0].epNum).toBe(1)
    expect(shelf[0].episodeDisplay).toBe('Ep 1 · Chapter 1')
    expect(shelf[0].fraction).toBeCloseTo(6.09 / 1832, 6)
  })

  it('writes progress back via putProgress (LWW upsert)', async () => {
    const { api, setToken } = mockClient()
    const auth = await api.auth.verify({ provider: 'apple', token: 'mock-provider-token' })
    setToken(auth.access_token)
    const res = await api.podcast.putProgress('pride-and-prejudice', 1, {
      position_sec: 42,
      duration_sec: 1832,
      updated_at: '2026-06-13T00:00:00Z',
    })
    expect(res).toMatchObject({ series_id: 'pride-and-prejudice', ep_num: 1, position_sec: 42 })
  })

  it('subtitle SRT highlights the cue under the playhead', () => {
    const cues = parseSrt(DEMO_SRT)
    expect(cues).toHaveLength(5)
    // catalog playhead 6.09s lands in the 3rd cue [4.8, 7.2)
    expect(activeCueIndex(cues, 6.09)).toBe(2)
    expect(cues[2].text).toContain('quietly erodes our focus')
    // start of clip → first cue
    expect(activeCueIndex(cues, 0)).toBe(0)
  })
})
