import { describe, expect, it } from 'vitest'
import {
  adjustParam,
  clockConfigFromState,
  fixtureFromState,
  formatHours,
  formatMultiplier,
  modeConfigFromState,
  REVIEW_SETTINGS_DEFAULT,
  stateFromConfig,
  type ReviewSettingsState,
} from './derive'
import { SETTINGS_REVIEW_FIXTURES } from './fixtures'
import type { ReviewModeConfig } from '../../api/types'

describe('formatHours', () => {
  it('renders whole days when >=24 and divisible by 24', () => {
    expect(formatHours(24)).toBe('1天')
    expect(formatHours(1440)).toBe('60天')
    expect(formatHours(2160)).toBe('90天')
  })
  it('renders hours otherwise', () => {
    expect(formatHours(8)).toBe('8h')
    expect(formatHours(4)).toBe('4h')
    expect(formatHours(36)).toBe('36h') // 36 not divisible by 24
  })
})

describe('formatMultiplier', () => {
  it('renders %.2f×', () => {
    expect(formatMultiplier(2.5)).toBe('2.50×')
    expect(formatMultiplier(0.35)).toBe('0.35×')
    expect(formatMultiplier(2.1)).toBe('2.10×')
  })
})

describe('fixtureFromState parity with static fixtures', () => {
  it('relaxed (not paused) matches the relaxed fixture footer + rows', () => {
    const state: ReviewSettingsState = { ...REVIEW_SETTINGS_DEFAULT, mode: 'relaxed' }
    const fx = fixtureFromState(state)
    expect(fx.mode).toBe('relaxed')
    expect(fx.isPaused).toBe(false)
    expect(fx.customRows).toBeNull()
    expect(fx.footer).toBe(SETTINGS_REVIEW_FIXTURES.relaxed.footer)
    expect(fx.pauseDescription).toBe(SETTINGS_REVIEW_FIXTURES.relaxed.pauseDescription)
  })

  it('intensive footer matches the intensive fixture', () => {
    const fx = fixtureFromState({ ...REVIEW_SETTINGS_DEFAULT, mode: 'intensive' })
    expect(fx.footer).toBe(SETTINGS_REVIEW_FIXTURES.intensive.footer)
  })

  it('frozen (paused) renders 目前停在 {date} matching the frozen fixture', () => {
    const fx = fixtureFromState({
      ...REVIEW_SETTINGS_DEFAULT,
      mode: 'relaxed',
      isPaused: true,
      pausedAt: '2024-12-06T08:00:00',
    })
    expect(fx.isPaused).toBe(true)
    expect(fx.pauseDescription).toBe(SETTINGS_REVIEW_FIXTURES.frozen.pauseDescription)
  })

  it('custom rows + footer match the custom fixture verbatim', () => {
    const fx = fixtureFromState({
      mode: 'custom',
      customInitialIntervalHours: 24,
      customRememberedMultiplier: 2.1,
      customForgotMultiplier: 0.35,
      customMinimumIntervalHours: 4,
      customMaximumIntervalHours: 2160,
      isPaused: false,
      pausedAt: null,
    })
    expect(fx.customRows).toEqual(SETTINGS_REVIEW_FIXTURES.custom.customRows)
    expect(fx.footer).toBe(SETTINGS_REVIEW_FIXTURES.custom.footer)
  })
})

describe('custom param can-decrement / can-increment boundaries', () => {
  it('initial interval clamps to [4,72] step 4', () => {
    const fx = fixtureFromState({
      ...REVIEW_SETTINGS_DEFAULT,
      mode: 'custom',
      customInitialIntervalHours: 4,
    })
    const row = fx.customRows![0]!
    expect(row.canDecrement).toBe(false) // at min
    expect(row.canIncrement).toBe(true)
  })

  it('remembered multiplier uses epsilon at min 1.1', () => {
    const fx = fixtureFromState({
      ...REVIEW_SETTINGS_DEFAULT,
      mode: 'custom',
      customRememberedMultiplier: 1.1,
    })
    const row = fx.customRows![1]!
    expect(row.canDecrement).toBe(false)
    expect(row.canIncrement).toBe(true)
  })

  it('forgot multiplier at max 0.9 cannot increment', () => {
    const fx = fixtureFromState({
      ...REVIEW_SETTINGS_DEFAULT,
      mode: 'custom',
      customForgotMultiplier: 0.9,
    })
    const row = fx.customRows![2]!
    expect(row.canIncrement).toBe(false)
  })
})

describe('adjustParam', () => {
  it('steps and clamps to the spec range', () => {
    const s = { ...REVIEW_SETTINGS_DEFAULT, mode: 'custom' as const, customInitialIntervalHours: 70 }
    expect(adjustParam(s, 'customInitialIntervalHours', 4).customInitialIntervalHours).toBe(72) // clamped to max
    expect(adjustParam(s, 'customInitialIntervalHours', -4).customInitialIntervalHours).toBe(66)
  })

  it('rounds float steps to avoid drift (0.1 increments)', () => {
    const s = { ...REVIEW_SETTINGS_DEFAULT, mode: 'custom' as const, customRememberedMultiplier: 2.1 }
    expect(adjustParam(s, 'customRememberedMultiplier', 0.1).customRememberedMultiplier).toBe(2.2)
  })

  it('clamps forgot multiplier to [0.1,0.9]', () => {
    const s = { ...REVIEW_SETTINGS_DEFAULT, mode: 'custom' as const, customForgotMultiplier: 0.88 }
    expect(adjustParam(s, 'customForgotMultiplier', 0.05).customForgotMultiplier).toBe(0.9)
  })
})

describe('stateFromConfig / config payloads', () => {
  it('falls back to ReviewSettings.default when review_mode is null', () => {
    const s = stateFromConfig(null, null)
    expect(s).toEqual(REVIEW_SETTINGS_DEFAULT)
  })

  it('maps a backend review_mode + review_clock', () => {
    const mode: ReviewModeConfig = {
      mode: 'custom',
      custom_initial_interval_hours: 24,
      custom_remembered_multiplier: 2.1,
      custom_forgot_multiplier: 0.35,
      custom_minimum_interval_hours: 4,
      custom_maximum_interval_hours: 2160,
      updated_at: null,
    }
    const s = stateFromConfig(mode, { is_paused: true, paused_at: '2024-12-06T00:00:00', updated_at: null })
    expect(s.mode).toBe('custom')
    expect(s.customMaximumIntervalHours).toBe(2160)
    expect(s.isPaused).toBe(true)
    expect(s.pausedAt).toBe('2024-12-06T00:00:00')
  })

  it('normalizes unknown mode strings to relaxed', () => {
    const s = stateFromConfig(
      { ...modeConfigFromState(REVIEW_SETTINGS_DEFAULT), mode: 'bogus' },
      null,
    )
    expect(s.mode).toBe('relaxed')
  })

  it('round-trips state -> modeConfig -> state', () => {
    const orig: ReviewSettingsState = {
      mode: 'custom',
      customInitialIntervalHours: 24,
      customRememberedMultiplier: 2.1,
      customForgotMultiplier: 0.35,
      customMinimumIntervalHours: 4,
      customMaximumIntervalHours: 2160,
      isPaused: false,
      pausedAt: null,
    }
    const back = stateFromConfig(modeConfigFromState(orig), clockConfigFromState(orig))
    expect(back).toEqual(orig)
  })
})
