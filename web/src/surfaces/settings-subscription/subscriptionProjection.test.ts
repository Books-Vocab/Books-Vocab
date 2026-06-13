import { describe, expect, it } from 'vitest'
import { isAdminSource, projectSubscription } from './subscriptionProjection'
import type { SubscriptionStatusResponse } from '../../api/types'

function pro(partial: Partial<SubscriptionStatusResponse>): SubscriptionStatusResponse {
  return {
    is_active: false,
    product_id: null,
    plan_name: null,
    price_display: null,
    status: 'none',
    is_trial: false,
    trial_days: null,
    will_renew: false,
    expires_at: null,
    source: 'app_store',
    last_synced_at: null,
    ...partial,
  }
}

describe('isAdminSource', () => {
  it('recognises admin-family sources', () => {
    expect(isAdminSource('admin')).toBe(true)
    expect(isAdminSource('admin_grant')).toBe(true)
  })
  it('rejects app_store and empty', () => {
    expect(isAdminSource('app_store')).toBe(false)
    expect(isAdminSource(null)).toBe(false)
    expect(isAdminSource(undefined)).toBe(false)
  })
})

describe('projectSubscription', () => {
  it('maps null entitlement to the free (inactive) view', () => {
    const v = projectSubscription(null)
    expect(v.isActive).toBe(false)
    expect(v.isAdmin).toBe(false)
    expect(v.planName).toBe('免費方案')
    expect(v.badgeTone).toBe('neutral')
    expect(v.ctaTitle).toBe('升級 Pro')
    expect(v.sourceLabel).toBe('無')
  })

  it('maps an active app_store subscription to the active view with expiry', () => {
    const v = projectSubscription(pro({ is_active: true, source: 'app_store', expires_at: '2027-03-10', price_display: 'NT$90 / 月' }))
    expect(v.isActive).toBe(true)
    expect(v.isAdmin).toBe(false)
    expect(v.badgeText).toBe('啟用中')
    expect(v.badgeTone).toBe('success')
    expect(v.summary).toContain('2027-03-10')
    expect(v.priceDisplay).toBe('NT$90 / 月')
    expect(v.expiryNote).toContain('2027-03-10')
    expect(v.ctaTitle).toBe('管理訂閱')
    expect(v.sourceLabel).toBe('App Store')
  })

  it('maps an admin grant to the admin view (no App Store management / restore)', () => {
    const v = projectSubscription(pro({ is_active: true, source: 'admin_grant' }))
    expect(v.isActive).toBe(true)
    expect(v.isAdmin).toBe(true)
    expect(v.sourceLabel).toBe('管理員授權')
    expect(v.isRestoreAvailable).toBe(false)
    expect(v.priceDisplay).toBe('管理員授權')
  })

  it('falls back to a price placeholder when price_display is absent', () => {
    const v = projectSubscription(pro({ is_active: false, price_display: null }))
    expect(v.priceDisplay).toContain('App Store')
  })
})
