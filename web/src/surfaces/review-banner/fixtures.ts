import type { ScenarioId } from '../../harness/scenarios'

/**
 * review-banner fixtures — 逐字對齊 ios BannerScenarios.swift。
 *
 * 「Banners · Review」4 scene（VocabReviewBanner，dueCount/unlearnedCount 合成）：
 *   - review-both       → ReviewBannerScene(dueCount: 42,   unlearnedCount: 12)
 *   - review-due        → ReviewBannerScene(dueCount: 5,    unlearnedCount: 0)
 *   - review-unlearned  → ReviewBannerScene(dueCount: 0,    unlearnedCount: 3)
 *   - review-large      → ReviewBannerScene(dueCount: 1280, unlearnedCount: 999)
 * 「Banners · Demo」1 scene（DemoBanner）：
 *   - demo-default      → DemoBannerScene()
 */

export interface ReviewBannerFixture {
  kind: 'review'
  dueCount: number
  unlearnedCount: number
}

export interface DemoBannerFixture {
  kind: 'demo'
}

export type ReviewBannerScenarioFixture = ReviewBannerFixture | DemoBannerFixture

export const REVIEW_BANNER_FIXTURES: Record<
  ScenarioId<'review-banner'>,
  ReviewBannerScenarioFixture
> = {
  'review-both': { kind: 'review', dueCount: 42, unlearnedCount: 12 },
  'review-due': { kind: 'review', dueCount: 5, unlearnedCount: 0 },
  'review-unlearned': { kind: 'review', dueCount: 0, unlearnedCount: 3 },
  'review-large': { kind: 'review', dueCount: 1280, unlearnedCount: 999 },
  'demo-default': { kind: 'demo' },
}
