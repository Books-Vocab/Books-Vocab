import { describe, expect, it } from 'vitest'
import { autoLinkEnabled, buildAutoLinkPatch, syncStatusFromSignals } from './syncConfig'
import type { UserConfigResponse } from '../../api/types'

function cfg(auto_link: Record<string, unknown> | null): UserConfigResponse {
  return { translation: null, review_clock: null, review_mode: null, vocab_ui: null, auto_link }
}

describe('autoLinkEnabled', () => {
  it('reads enabled=true from auto_link', () => {
    expect(autoLinkEnabled(cfg({ enabled: true }))).toBe(true)
  })
  it('reads enabled=false from auto_link', () => {
    expect(autoLinkEnabled(cfg({ enabled: false }))).toBe(false)
  })
  it('defaults to true when auto_link is null (backend default)', () => {
    expect(autoLinkEnabled(cfg(null))).toBe(true)
  })
  it('defaults to true when config is null', () => {
    expect(autoLinkEnabled(null)).toBe(true)
  })
  it('defaults to true when enabled key is missing or non-boolean', () => {
    expect(autoLinkEnabled(cfg({}))).toBe(true)
    expect(autoLinkEnabled(cfg({ enabled: 'yes' }))).toBe(true)
  })
})

describe('buildAutoLinkPatch', () => {
  it('writes enabled while preserving other auto_link keys', () => {
    const patch = buildAutoLinkPatch(cfg({ threshold: 0.8, enabled: true }), false)
    expect(patch.auto_link).toMatchObject({ threshold: 0.8, enabled: false })
  })
  it('writes enabled when no prior auto_link exists', () => {
    const patch = buildAutoLinkPatch(cfg(null), true)
    expect(patch.auto_link).toMatchObject({ enabled: true })
  })
  it('writes enabled when config is null', () => {
    expect(buildAutoLinkPatch(null, false).auto_link).toMatchObject({ enabled: false })
  })
  it('always clears updated_at to null so the server stamps LWW', () => {
    const patch = buildAutoLinkPatch(cfg({ enabled: true, updated_at: 1700000000 }), false)
    expect(patch.auto_link).toHaveProperty('updated_at', null)
  })
})

describe('syncStatusFromSignals', () => {
  it('reports paused when the review clock is paused (auto-sync off)', () => {
    const s = syncStatusFromSignals({ lastSyncedAt: null, isPaused: true, quotaFraction: 0.5 })
    expect(s.tone).toBe('paused')
    expect(s.label).toContain('暫停')
  })
  it('shows a relative last-sync time when last_synced_at is present', () => {
    const now = Date.parse('2026-06-13T12:00:00Z')
    const fiveMinAgo = new Date(now - 5 * 60_000).toISOString()
    const s = syncStatusFromSignals({ lastSyncedAt: fiveMinAgo, isPaused: false, now })
    expect(s.tone).toBe('synced')
    expect(s.label).toContain('5 分鐘前')
  })
  it('shows "剛剛" for a sync within the last minute', () => {
    const now = Date.parse('2026-06-13T12:00:00Z')
    const justNow = new Date(now - 10_000).toISOString()
    const s = syncStatusFromSignals({ lastSyncedAt: justNow, isPaused: false, now })
    expect(s.label).toContain('剛剛')
  })
  it('shows hours for a sync hours ago', () => {
    const now = Date.parse('2026-06-13T12:00:00Z')
    const threeHoursAgo = new Date(now - 3 * 3600_000).toISOString()
    const s = syncStatusFromSignals({ lastSyncedAt: threeHoursAgo, isPaused: false, now })
    expect(s.label).toContain('3 小時前')
  })
  it('falls back to a connected label when no last_synced_at is available', () => {
    const s = syncStatusFromSignals({ lastSyncedAt: null, isPaused: false })
    expect(s.tone).toBe('synced')
    expect(s.label).toContain('已連線')
  })
})
