import { describe, expect, it } from 'vitest'
import { ApiError } from '../api'
import { shouldRetry } from './queryClient'

/**
 * Retry 策略契約 — TanStack Query 的 query retry predicate。
 *
 * 原則：ApiError 的 http 4xx（client error：400/401/403/404/422…）重試無意義
 * （請求本身錯，重送結果相同），立即失敗交 UI；network / parse / http 5xx
 * （暫時性）才退避重試，上限 2 次（共 3 次嘗試）。
 */

function httpError(status: number): ApiError {
  return new ApiError(`HTTP ${status}`, { kind: 'http', status })
}

describe('shouldRetry', () => {
  it('不重試 http 4xx（client error）', () => {
    for (const s of [400, 401, 403, 404, 409, 422]) {
      expect(shouldRetry(0, httpError(s))).toBe(false)
    }
  })

  it('重試 http 5xx（server error，暫時性）直到上限', () => {
    expect(shouldRetry(0, httpError(500))).toBe(true)
    expect(shouldRetry(1, httpError(503))).toBe(true)
    expect(shouldRetry(2, httpError(500))).toBe(false) // 第 3 次失敗 → 停
  })

  it('重試 network / parse 錯誤直到上限', () => {
    const network = new ApiError('offline', { kind: 'network', status: 0 })
    const parse = new ApiError('bad json', { kind: 'parse', status: 0 })
    expect(shouldRetry(0, network)).toBe(true)
    expect(shouldRetry(2, network)).toBe(false)
    expect(shouldRetry(0, parse)).toBe(true)
  })

  it('非 ApiError（未知例外）仍受上限保護', () => {
    expect(shouldRetry(0, new Error('boom'))).toBe(true)
    expect(shouldRetry(2, new Error('boom'))).toBe(false)
  })
})
