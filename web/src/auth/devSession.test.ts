import { describe, expect, it } from 'vitest'
import { MOCK_ACCESS_TOKEN } from '../api/mock/data'
import {
  buildMockSession,
  isDevLoginEnabled,
  MOCK_USER_ID,
  resolveShellAccess,
} from './devSession'

describe('isDevLoginEnabled', () => {
  it('true when import.meta.env.DEV', () => {
    expect(isDevLoginEnabled({ DEV: true, VITE_API_MODE: 'real' })).toBe(true)
  })

  it('true when VITE_API_MODE=mock (even in prod build)', () => {
    expect(isDevLoginEnabled({ DEV: false, VITE_API_MODE: 'mock' })).toBe(true)
  })

  it('false in prod + real backend', () => {
    expect(isDevLoginEnabled({ DEV: false, VITE_API_MODE: 'real' })).toBe(false)
  })

  it('false when env is empty', () => {
    expect(isDevLoginEnabled({})).toBe(false)
  })
})

describe('buildMockSession', () => {
  it('reuses the exact literal token the mock handler accepts', () => {
    expect(buildMockSession()).toEqual({ token: MOCK_ACCESS_TOKEN, userId: MOCK_USER_ID })
  })

  it('token is a non-empty Bearer-shaped string (mock requires /^Bearer\\s+\\S+/)', () => {
    const { token } = buildMockSession()
    expect(token.length).toBeGreaterThan(0)
    expect(/^Bearer\s+\S+/.test(`Bearer ${token}`)).toBe(true)
  })
})

describe('resolveShellAccess', () => {
  it("hydrating → 'loading' (preserves existing spinner branch)", () => {
    expect(resolveShellAccess({ isLoading: true, isLoggedIn: false })).toBe('loading')
    expect(resolveShellAccess({ isLoading: true, isLoggedIn: true })).toBe('loading')
  })

  it("logged in → 'full'", () => {
    expect(resolveShellAccess({ isLoading: false, isLoggedIn: true })).toBe('full')
  })

  it("not logged in → 'guest' (mirrors iOS guest tier; no hard LoginGate block)", () => {
    expect(resolveShellAccess({ isLoading: false, isLoggedIn: false })).toBe('guest')
  })
})
