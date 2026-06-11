import { describe, expect, it } from 'vitest'
import { resolveHarnessConfig } from './scenarios'

describe('resolveHarnessConfig', () => {
  it('defaults to bookshelf/populated/light when query is empty', () => {
    expect(resolveHarnessConfig('')).toEqual({
      surface: 'bookshelf',
      scenario: 'populated',
      appearance: 'light',
    })
  })

  it('parses explicit scenario and appearance（無 surface 參數 = bookshelf，既有 capture URL 不變）', () => {
    expect(resolveHarnessConfig('?scenario=empty&appearance=dark')).toEqual({
      surface: 'bookshelf',
      scenario: 'empty',
      appearance: 'dark',
    })
    expect(resolveHarnessConfig('?scenario=single')).toEqual({
      surface: 'bookshelf',
      scenario: 'single',
      appearance: 'light',
    })
  })

  it('routes settings surface with its own scenario taxonomy', () => {
    expect(resolveHarnessConfig('?surface=settings&scenario=logged-out&appearance=dark')).toEqual({
      surface: 'settings',
      scenario: 'logged-out',
      appearance: 'dark',
    })
    expect(resolveHarnessConfig('?surface=settings&scenario=pricing-unavailable')).toEqual({
      surface: 'settings',
      scenario: 'pricing-unavailable',
      appearance: 'light',
    })
  })

  it('falls back to the surface default scenario when scenario belongs to another surface', () => {
    // bookshelf 的 'populated' 不是 settings 的合法 scenario → settings 預設
    expect(resolveHarnessConfig('?surface=settings&scenario=populated')).toEqual({
      surface: 'settings',
      scenario: 'subscribed-active',
      appearance: 'light',
    })
  })

  it('falls back symmetrically: settings scenario on bookshelf surface → bookshelf default', () => {
    expect(resolveHarnessConfig('?surface=bookshelf&scenario=logged-out')).toEqual({
      surface: 'bookshelf',
      scenario: 'populated',
      appearance: 'light',
    })
  })

  it('routes notebook surface with its own scenario taxonomy', () => {
    expect(resolveHarnessConfig('?surface=notebook&scenario=populated&appearance=dark')).toEqual({
      surface: 'notebook',
      scenario: 'populated',
      appearance: 'dark',
    })
    expect(resolveHarnessConfig('?surface=notebook&scenario=single')).toEqual({
      surface: 'notebook',
      scenario: 'single',
      appearance: 'light',
    })
  })

  it('notebook defaults to its first scenario (populated) when scenario belongs to another surface', () => {
    // settings 的 'logged-out' 不是 notebook 的合法 scenario → notebook 預設
    expect(resolveHarnessConfig('?surface=notebook&scenario=logged-out')).toEqual({
      surface: 'notebook',
      scenario: 'populated',
      appearance: 'light',
    })
  })

  it('routes reader surface with its own scenario taxonomy', () => {
    expect(resolveHarnessConfig('?surface=reader&scenario=reading-expanded&appearance=light')).toEqual({
      surface: 'reader',
      scenario: 'reading-expanded',
      appearance: 'light',
    })
    expect(resolveHarnessConfig('?surface=reader&scenario=error-open-failed')).toEqual({
      surface: 'reader',
      scenario: 'error-open-failed',
  it('routes today-review surface with its own scenario taxonomy', () => {
    expect(resolveHarnessConfig('?surface=today-review&scenario=production-back&appearance=dark')).toEqual({
      surface: 'today-review',
      scenario: 'production-back',
      appearance: 'dark',
    })
    expect(resolveHarnessConfig('?surface=today-review&scenario=back')).toEqual({
      surface: 'today-review',
      scenario: 'back',
  it('routes podcast surface with its own scenario taxonomy', () => {
    expect(resolveHarnessConfig('?surface=podcast&scenario=preview-player&appearance=dark')).toEqual({
      surface: 'podcast',
      scenario: 'preview-player',
      appearance: 'dark',
    })
    expect(resolveHarnessConfig('?surface=podcast&scenario=locked-gate')).toEqual({
      surface: 'podcast',
      scenario: 'locked-gate',
      appearance: 'light',
    })
  })

  it('reader defaults to its first scenario (reading-compact) when scenario belongs to another surface', () => {
    // notebook 的 'populated' 不是 reader 的合法 scenario → reader 預設
    expect(resolveHarnessConfig('?surface=reader&scenario=populated')).toEqual({
      surface: 'reader',
      scenario: 'reading-compact',
  it('today-review defaults to its first scenario (front) when scenario belongs to another surface', () => {
    expect(resolveHarnessConfig('?surface=today-review&scenario=logged-out')).toEqual({
      surface: 'today-review',
      scenario: 'front',
  it('podcast defaults to its first scenario (preview-player) when scenario belongs to another surface', () => {
    expect(resolveHarnessConfig('?surface=podcast&scenario=logged-out')).toEqual({
      surface: 'podcast',
      scenario: 'preview-player',
      appearance: 'light',
    })
  })

  it('re-evaluates scenario against the fallback surface（未知 surface + 他 surface 合法 scenario）', () => {
    expect(resolveHarnessConfig('?surface=nope&scenario=logged-out')).toEqual({
      surface: 'bookshelf',
      scenario: 'populated',
      appearance: 'light',
    })
  })

  it('falls back to defaults on unknown values (capture URLs are generated; never hard-fail)', () => {
    expect(resolveHarnessConfig('?surface=nope&scenario=nope&appearance=sepia')).toEqual({
      surface: 'bookshelf',
      scenario: 'populated',
      appearance: 'light',
    })
  })
})
