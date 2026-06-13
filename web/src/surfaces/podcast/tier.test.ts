import { describe, expect, it } from 'vitest'
import type { EntitlementsResponse } from '../../api/types'
import {
  canPlay,
  isFreePreviewable,
  isPreviewPlayback,
  resolveTier,
  showsProLock,
  tierFromEntitlements,
} from './tier'

function entitlements(isActive: boolean): EntitlementsResponse {
  return {
    pro: {
      is_active: isActive,
      product_id: null,
      plan_name: null,
      price_display: null,
      status: isActive ? 'active' : 'none',
      is_trial: false,
      trial_days: null,
      will_renew: isActive,
      expires_at: null,
      source: 'app_store',
      last_synced_at: null,
    },
  }
}

describe('resolveTier', () => {
  it('pro wins over token', () => {
    expect(resolveTier(true, true)).toBe('pro')
    expect(resolveTier(true, false)).toBe('pro')
  })
  it('token without pro = free', () => {
    expect(resolveTier(false, true)).toBe('free')
  })
  it('no token, no pro = guest', () => {
    expect(resolveTier(false, false)).toBe('guest')
  })
})

describe('tierFromEntitlements', () => {
  it('active pro → pro regardless of nothing else', () => {
    expect(tierFromEntitlements(entitlements(true), true)).toBe('pro')
  })
  it('inactive pro + token → free', () => {
    expect(tierFromEntitlements(entitlements(false), true)).toBe('free')
  })
  it('null entitlements + no token → guest', () => {
    expect(tierFromEntitlements(null, false)).toBe('guest')
  })
  it('null entitlements + token → free', () => {
    expect(tierFromEntitlements(null, true)).toBe('free')
  })
})

describe('isFreePreviewable', () => {
  it('only ep 1', () => {
    expect(isFreePreviewable(1)).toBe(true)
    expect(isFreePreviewable(2)).toBe(false)
  })
})

describe('canPlay', () => {
  it('pro plays everything', () => {
    expect(canPlay('pro', 1, false)).toBe(true)
    expect(canPlay('pro', 9, false)).toBe(true)
  })
  it('free plays only ep1 when preview asset exists', () => {
    expect(canPlay('free', 1, true)).toBe(true)
    expect(canPlay('free', 1, false)).toBe(false) // legacy series → Pro lock not 404
    expect(canPlay('free', 2, true)).toBe(false)
  })
  it('guest plays nothing', () => {
    expect(canPlay('guest', 1, true)).toBe(false)
  })
})

describe('isPreviewPlayback', () => {
  it('true only for free + ep1 + asset present', () => {
    expect(isPreviewPlayback('free', 1, true)).toBe(true)
    expect(isPreviewPlayback('free', 1, false)).toBe(false)
    expect(isPreviewPlayback('free', 2, true)).toBe(false)
    expect(isPreviewPlayback('pro', 1, true)).toBe(false)
    expect(isPreviewPlayback('guest', 1, true)).toBe(false)
  })
})

describe('showsProLock', () => {
  it('free locks non-previewable episodes', () => {
    expect(showsProLock('free', 2, true)).toBe(true)
    expect(showsProLock('free', 1, true)).toBe(false)
    expect(showsProLock('free', 1, false)).toBe(true) // legacy ep1 → Pro lock
  })
  it('pro never sees a lock', () => {
    expect(showsProLock('pro', 9, false)).toBe(false)
  })
  it('guest sees the sign-in gate, not a Pro lock', () => {
    expect(showsProLock('guest', 2, true)).toBe(false)
  })
})
