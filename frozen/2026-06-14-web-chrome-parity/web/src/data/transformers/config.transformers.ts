// Pure transformers: config seed → API-response shapes (user config bundle,
// entitlements, quota).

import type {
  EntitlementsResponse,
  QuotaResponse,
  UserConfigResponse,
} from '../../api/types'
import type {
  EntitlementSeed,
  PreferencesSeed,
  QuotaSeed,
} from '../seeds/config.seed'

export function toUserConfigResponse(p: PreferencesSeed): UserConfigResponse {
  return {
    translation: null,
    review_clock: {
      is_paused: p.reviewClock.isPaused,
      paused_at: p.reviewClock.pausedAt,
      updated_at: p.reviewClock.updatedAt,
    },
    review_mode: {
      mode: p.reviewMode.mode,
      custom_initial_interval_hours: p.reviewMode.customInitialIntervalHours,
      custom_remembered_multiplier: p.reviewMode.customRememberedMultiplier,
      custom_forgot_multiplier: p.reviewMode.customForgotMultiplier,
      custom_minimum_interval_hours: p.reviewMode.customMinimumIntervalHours,
      custom_maximum_interval_hours: p.reviewMode.customMaximumIntervalHours,
      updated_at: p.reviewMode.updatedAt,
    },
    vocab_ui: null,
    auto_link: null,
  }
}

export function toEntitlementsResponse(e: EntitlementSeed): EntitlementsResponse {
  return {
    pro: {
      is_active: e.isActive,
      product_id: null,
      plan_name: null,
      price_display: null,
      status: e.status,
      is_trial: e.isTrial,
      trial_days: null,
      will_renew: e.willRenew,
      expires_at: null,
      source: e.source,
      last_synced_at: null,
    },
  }
}

export function toQuotaResponse(q: QuotaSeed): QuotaResponse {
  return {
    fraction: q.fraction,
    reset_seconds: q.resetSeconds,
  }
}
