import { describe, expect, it } from 'vitest'
import { initialsFor, projectIdentity } from './useAccountIdentityApiStore'
import type { SubscriptionStatusResponse, UserProfileResponse } from '../../api/types'

function profile(partial: Partial<UserProfileResponse>): UserProfileResponse {
  return { user_id: 'u-1', email: 'reader@example.com', display_name: '示範使用者', ...partial }
}

function pro(active: boolean): SubscriptionStatusResponse {
  return {
    is_active: active,
    product_id: null,
    plan_name: null,
    price_display: null,
    status: active ? 'active' : 'none',
    is_trial: false,
    trial_days: null,
    will_renew: active,
    expires_at: null,
    source: 'app_store',
    last_synced_at: null,
  }
}

describe('initialsFor', () => {
  it('takes first letters of two name parts (latin)', () => {
    expect(initialsFor('Chen Liang', 'chen@example.com')).toBe('CL')
  })
  it('takes first two letters of a single latin name', () => {
    expect(initialsFor('Reader', 'r@example.com')).toBe('RE')
  })
  it('takes a single glyph for a CJK single-segment name', () => {
    expect(initialsFor('麥克斯', null)).toBe('麥')
  })
  it('falls back to email local part when no name', () => {
    expect(initialsFor(null, 'reader@example.com')).toBe('RE')
  })
  it('falls back to ? when nothing available', () => {
    expect(initialsFor(null, null)).toBe('?')
  })
})

describe('projectIdentity', () => {
  it('maps null profile to the guest identity', () => {
    const id = projectIdentity(null, null)
    expect(id.isLoggedIn).toBe(false)
    expect(id.displayName).toBe('訪客')
    expect(id.email).toBeNull()
  })

  it('projects a logged-in identity with email + pro flag', () => {
    const id = projectIdentity(profile({ display_name: 'Chen Liang', email: 'chen@example.com' }), pro(true))
    expect(id.isLoggedIn).toBe(true)
    expect(id.displayName).toBe('Chen Liang')
    expect(id.email).toBe('chen@example.com')
    expect(id.initials).toBe('CL')
    expect(id.isPro).toBe(true)
  })

  it('derives display name from email when display_name is empty', () => {
    const id = projectIdentity(profile({ display_name: '', email: 'someone@example.com' }), pro(false))
    expect(id.displayName).toBe('someone')
    expect(id.isPro).toBe(false)
  })

  it('handles a null email (hidden email row)', () => {
    const id = projectIdentity(profile({ display_name: 'NoMail', email: null }), null)
    expect(id.email).toBeNull()
    expect(id.displayName).toBe('NoMail')
  })
})
