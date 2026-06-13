// Layered podcast access policy — web mirror of iOS `PodcastAccess.swift`
// (which itself mirrors backend `podcast_access.py`). Pure functions, no DOM.
//
// Tier resolution (iOS `PodcastAccess.tier(hasProAccess:hasToken:)`):
//   pro wins → has a token (logged in) = free → otherwise guest.
// Free preview: ep 1 only is previewable for free users (FREE_PREVIEW_EP_NUM).
// The server remains the security boundary; this is the UX-layer pre-gate
// (locked badge / sign-in / paywall / preview marker) so we never optimistically
// request a 403/404 dead end.

import type { EntitlementsResponse } from '../../api/types'

export type PodcastTier = 'guest' | 'free' | 'pro'

/** ep_01 only — mirrors backend `podcast_access.FREE_PREVIEW_EP_NUM`. */
export const FREE_PREVIEW_EP_NUM = 1

/** pro > free(token) > guest — mirrors `PodcastAccess.tier`. */
export function resolveTier(hasProAccess: boolean, hasToken: boolean): PodcastTier {
  if (hasProAccess) return 'pro'
  if (hasToken) return 'free'
  return 'guest'
}

/** Derive tier from the entitlements payload + login state. */
export function tierFromEntitlements(
  entitlements: EntitlementsResponse | null,
  hasToken: boolean,
): PodcastTier {
  const hasPro = entitlements?.pro?.is_active === true
  return resolveTier(hasPro, hasToken)
}

/** ep-num policy: only ep 1 is the free preview slot. */
export function isFreePreviewable(episodeNumber: number): boolean {
  return episodeNumber === FREE_PREVIEW_EP_NUM
}

/**
 * Can this tier play this episode in full?
 *  - pro: always
 *  - free: only the preview episode (and only when the preview asset exists)
 *  - guest: never (must sign in first)
 * `previewAvailable` lets the client be one notch stricter than the server: a
 * free user only treats ep1 as playable when the preview asset is actually
 * present (legacy series without backfill show the Pro lock instead of a 404).
 */
export function canPlay(
  tier: PodcastTier,
  episodeNumber: number,
  previewAvailable: boolean,
): boolean {
  if (tier === 'pro') return true
  if (tier === 'free') return isFreePreviewable(episodeNumber) && previewAvailable
  return false
}

/** True when playback is the time-limited free preview (banner + upgrade CTA). */
export function isPreviewPlayback(
  tier: PodcastTier,
  episodeNumber: number,
  previewAvailable: boolean,
): boolean {
  return tier === 'free' && isFreePreviewable(episodeNumber) && previewAvailable
}

/** True when the episode should show a Pro lock for this tier. */
export function showsProLock(
  tier: PodcastTier,
  episodeNumber: number,
  previewAvailable: boolean,
): boolean {
  if (tier === 'guest') return false // guests see the sign-in gate, not a Pro lock
  return !canPlay(tier, episodeNumber, previewAvailable)
}
