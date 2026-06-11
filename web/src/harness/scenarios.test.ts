import { describe, expect, it } from 'vitest'
import { resolveHarnessConfig } from './scenarios'

describe('resolveHarnessConfig', () => {
  it('defaults to populated/light when query is empty', () => {
    expect(resolveHarnessConfig('')).toEqual({ scenario: 'populated', appearance: 'light' })
  })

  it('parses explicit scenario and appearance', () => {
    expect(resolveHarnessConfig('?scenario=empty&appearance=dark')).toEqual({
      scenario: 'empty',
      appearance: 'dark',
    })
    expect(resolveHarnessConfig('?scenario=single')).toEqual({
      scenario: 'single',
      appearance: 'light',
    })
  })

  it('falls back to defaults on unknown values (capture URLs are generated; never hard-fail)', () => {
    expect(resolveHarnessConfig('?scenario=nope&appearance=sepia')).toEqual({
      scenario: 'populated',
      appearance: 'light',
    })
  })
})
