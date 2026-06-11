import { describe, expect, it } from 'vitest'
import { ApiError } from './errors'
import { Transport, type FetchLike } from './transport'

function transportWith(fetchImpl: FetchLike, token?: string): Transport {
  return new Transport({ baseUrl: 'https://api.test', getToken: () => token ?? null, fetch: fetchImpl })
}

describe('Transport', () => {
  it('injects a Bearer header when a token is present', async () => {
    let seenAuth: string | null = null
    const t = transportWith(async (_url, init) => {
      seenAuth = new Headers(init?.headers).get('Authorization')
      return new Response('{}', { status: 200 })
    }, 'abc')
    await t.request('/x')
    expect(seenAuth).toBe('Bearer abc')
  })

  it('omits Authorization for anonymous calls even with a token', async () => {
    let seenAuth: string | null = 'sentinel'
    const t = transportWith(async (_url, init) => {
      seenAuth = new Headers(init?.headers).get('Authorization')
      return new Response('{}', { status: 200 })
    }, 'abc')
    await t.request('/x', { anonymous: true })
    expect(seenAuth).toBeNull()
  })

  it('appends query params, dropping null/undefined', async () => {
    let seenUrl = ''
    const t = transportWith(async (url) => {
      seenUrl = url
      return new Response('{}', { status: 200 })
    })
    await t.request('/x', { query: { a: '1', b: undefined, c: null, d: 2 } })
    expect(seenUrl).toBe('https://api.test/x?a=1&d=2')
  })

  it('returns undefined for 204 No Content', async () => {
    const t = transportWith(async () => new Response(null, { status: 204 }))
    expect(await t.request('/x', { method: 'DELETE' })).toBeUndefined()
  })

  it('normalizes a network failure into ApiError(kind=network, status=0)', async () => {
    const t = transportWith(async () => {
      throw new TypeError('connection refused')
    })
    const err = (await t.request('/x').catch((e) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.kind).toBe('network')
    expect(err.status).toBe(0)
  })

  it('normalizes invalid JSON into ApiError(kind=parse)', async () => {
    const t = transportWith(async () => new Response('not json', { status: 200 }))
    const err = (await t.request('/x').catch((e) => e)) as ApiError
    expect(err.kind).toBe('parse')
  })

  it('extracts a backend FastAPI detail-object code into ApiError.code', async () => {
    const t = transportWith(
      async () =>
        new Response(JSON.stringify({ detail: { code: 'upgrade_required' } }), {
          status: 403,
        }),
    )
    const err = (await t.request('/x').catch((e) => e)) as ApiError
    expect(err.status).toBe(403)
    expect(err.code).toBe('upgrade_required')
    expect(err.isForbidden).toBe(true)
  })
})
