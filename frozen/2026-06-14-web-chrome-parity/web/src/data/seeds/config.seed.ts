// Config domain seed — user preferences (review mode/clock), entitlements, and
// quota. Lifted verbatim from the legacy api/mock/data.ts (MOCK_USER_CONFIG /
// MOCK_ENTITLEMENTS / MOCK_QUOTA).

export interface ReviewClockSeed {
  isPaused: boolean
  pausedAt: string | null
  updatedAt: number | null
}

export interface ReviewModeSeed {
  mode: string
  customInitialIntervalHours: number
  customRememberedMultiplier: number
  customForgotMultiplier: number
  customMinimumIntervalHours: number
  customMaximumIntervalHours: number
  updatedAt: number | null
}

export interface PreferencesSeed {
  reviewClock: ReviewClockSeed
  reviewMode: ReviewModeSeed
}

export const PREFERENCES_SEED: PreferencesSeed = {
  reviewClock: { isPaused: false, pausedAt: null, updatedAt: null },
  reviewMode: {
    mode: 'relaxed',
    customInitialIntervalHours: 12,
    customRememberedMultiplier: 1.9,
    customForgotMultiplier: 0.45,
    customMinimumIntervalHours: 6,
    customMaximumIntervalHours: 1440,
    updatedAt: null,
  },
}

export interface EntitlementSeed {
  isActive: boolean
  status: string
  isTrial: boolean
  willRenew: boolean
  source: string
}

export const ENTITLEMENT_SEED: EntitlementSeed = {
  isActive: false,
  status: 'none',
  isTrial: false,
  willRenew: false,
  source: 'app_store',
}

export interface QuotaSeed {
  fraction: number
  resetSeconds: number
}

export const QUOTA_SEED: QuotaSeed = {
  fraction: 0.12,
  resetSeconds: 43200,
}
