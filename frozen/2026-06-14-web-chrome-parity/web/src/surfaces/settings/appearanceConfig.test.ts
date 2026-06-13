import { describe, expect, it } from 'vitest'
import { appearanceFromConfig, buildAppearancePatch } from './appearanceConfig'
import type { UserConfigResponse } from '../../api/types'

function cfg(vocab_ui: Record<string, unknown> | null): UserConfigResponse {
  return { translation: null, review_clock: null, review_mode: null, vocab_ui, auto_link: null }
}

describe('appearanceFromConfig', () => {
  it('reads a stored appearance from vocab_ui', () => {
    expect(appearanceFromConfig(cfg({ appearance: 'dark' }))).toBe('dark')
  })
  it('defaults to system when vocab_ui is null', () => {
    expect(appearanceFromConfig(cfg(null))).toBe('system')
  })
  it('defaults to system when config is null', () => {
    expect(appearanceFromConfig(null)).toBe('system')
  })
  it('rejects invalid appearance values', () => {
    expect(appearanceFromConfig(cfg({ appearance: 'sepia' }))).toBe('system')
    expect(appearanceFromConfig(cfg({ appearance: 7 }))).toBe('system')
  })
})

describe('buildAppearancePatch', () => {
  it('writes appearance while preserving other vocab_ui keys', () => {
    const patch = buildAppearancePatch(cfg({ sortOrder: 'recent', appearance: 'system' }), 'light')
    expect(patch).toEqual({ vocab_ui: { sortOrder: 'recent', appearance: 'light' } })
  })
  it('writes appearance when no prior vocab_ui exists', () => {
    expect(buildAppearancePatch(cfg(null), 'dark')).toEqual({ vocab_ui: { appearance: 'dark' } })
  })
  it('writes appearance when config is null', () => {
    expect(buildAppearancePatch(null, 'light')).toEqual({ vocab_ui: { appearance: 'light' } })
  })
})
