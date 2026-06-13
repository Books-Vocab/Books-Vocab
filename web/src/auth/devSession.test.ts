import { describe, expect, it } from 'vitest'
import { MOCK_ACCESS_TOKEN } from '../api/mock/data'
import {
  buildMockSession,
  classifyDataState,
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

describe('classifyDataState（guest 空態 vs 真錯誤的單一真相）', () => {
  // 殼層提供的純分類器：data fetch 失敗時，未登入（guest）不是「錯誤」而是
  // 「尚未登入 → 空態 + 登入引導」；已登入仍失敗才是真錯誤。Phase-2 bookshelf
  // 以此把 status='error' 分流成 guest-empty vs error，不再把 401/無 token 誤報
  // 成系統錯誤。
  it("logged-out + 失敗 → 'guest-empty'（顯示登入引導空態，非錯誤）", () => {
    expect(classifyDataState({ isLoggedIn: false, failed: true })).toBe('guest-empty')
  })
  it("logged-out + 成功 → 'guest-empty'（guest 無資料仍導向登入空態）", () => {
    expect(classifyDataState({ isLoggedIn: false, failed: false })).toBe('guest-empty')
  })
  it("logged-in + 失敗 → 'error'（真錯誤，可重試）", () => {
    expect(classifyDataState({ isLoggedIn: true, failed: true })).toBe('error')
  })
  it("logged-in + 成功 → 'ok'（正常顯示資料）", () => {
    expect(classifyDataState({ isLoggedIn: true, failed: false })).toBe('ok')
  })
})
