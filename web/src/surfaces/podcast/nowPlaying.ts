// Pure helpers for the persistent now-playing experience: episode-list reading,
// continuous-playback (auto-advance) gating, free-preview time cap, sleep-timer
// option ladder, and subtitle-size cycling.
//
// All pure functions, no React, no DOM — so the playback policy is unit-testable
// independently of the singleton engine that consumes them.

import type { PodcastSeriesSummary } from '../../api/types'
import { canPlay, isFreePreviewable, type PodcastTier } from './tier'

/** A minimally-resolved episode read out of an opaque series dict. */
export interface FlowEpisode {
  epNum: number
  title: string
  durationSec: number
}

/** Free-preview hard cap (seconds): ~3 minutes of ep1 for free/guest-preview. */
export const FREE_PREVIEW_CAP_SEC = 180

/** Subtitle size ladder (small → extra-large). Drives a CSS data-attr. */
export const SUBTITLE_SIZES = ['s', 'm', 'l', 'xl'] as const
export type SubtitleSize = (typeof SUBTITLE_SIZES)[number]

/** Sleep-timer durations in seconds; 0 = off. */
export const SLEEP_OPTIONS = [0, 5 * 60, 15 * 60, 30 * 60, 60 * 60] as const
export type SleepOption = (typeof SLEEP_OPTIONS)[number]

function num(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function str(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** Read ordered, valid episodes from an opaque series dict (ascending ep_num). */
export function episodesOf(series: PodcastSeriesSummary | undefined): FlowEpisode[] {
  const eps = series?.episodes
  if (!Array.isArray(eps)) return []
  return eps
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({
      epNum: num(e.ep_num),
      title: str(e.title) || `Ep ${num(e.ep_num)}`,
      durationSec: num(e.duration_sec),
    }))
    .filter((e) => e.epNum > 0)
    .sort((a, b) => a.epNum - b.epNum)
}

/** The episode immediately after `epNum` in series order, or null at the end. */
export function nextEpisode(
  series: PodcastSeriesSummary | undefined,
  epNum: number,
): FlowEpisode | null {
  const eps = episodesOf(series)
  const idx = eps.findIndex((e) => e.epNum === epNum)
  if (idx < 0 || idx + 1 >= eps.length) return null
  return eps[idx + 1]
}

/**
 * The next episode this tier may auto-advance into (continuous playback).
 *  - pro: the next episode, always.
 *  - free: only ep1 is playable, so there is never a playable "next".
 *  - guest: never auto-advances.
 * Mirrors the per-episode `canPlay` gate so we never auto-roll into a 403/404.
 */
export function nextPlayableEpisode(
  series: PodcastSeriesSummary | undefined,
  epNum: number,
  tier: PodcastTier,
): FlowEpisode | null {
  const next = nextEpisode(series, epNum)
  if (!next) return null
  // ep1 is the only preview slot; for free/guest the next episode is Pro-locked.
  const previewAvailable = isFreePreviewable(next.epNum)
  return canPlay(tier, next.epNum, previewAvailable) ? next : null
}

/**
 * The playback time cap (seconds) for a free preview, or null when uncapped.
 * Free users get ~3 min of the ep1 preview; pro is uncapped; guests can't play.
 */
export function previewCapSec(
  tier: PodcastTier,
  epNum: number,
  previewAvailable: boolean,
): number | null {
  if (tier === 'free' && isFreePreviewable(epNum) && previewAvailable) {
    return FREE_PREVIEW_CAP_SEC
  }
  return null
}

/**
 * Resolve a timeupdate against an optional preview cap. Returns the clamped time
 * and whether the engine should pause (cap reached). Pure so the cap behaviour is
 * testable without a DOM/audio element.
 */
export function applyPreviewCap(
  rawTime: number,
  cap: number | null,
): { time: number; pause: boolean } {
  if (cap != null && rawTime >= cap) return { time: cap, pause: true }
  return { time: rawTime, pause: false }
}

/** One sleep-timer tick: decrement, clamp at 0, signal when it fires. */
export function sleepTick(remaining: number): { remaining: number; fired: boolean } {
  const next = remaining - 1
  if (next <= 0) return { remaining: 0, fired: true }
  return { remaining: next, fired: false }
}

/** Next size on the ladder, wrapping xl → s. */
export function cycleSubtitleSize(size: SubtitleSize): SubtitleSize {
  const i = SUBTITLE_SIZES.indexOf(size)
  return SUBTITLE_SIZES[(i + 1) % SUBTITLE_SIZES.length]
}

/** Human label for a sleep option. */
export function sleepLabel(sec: number): string {
  if (sec <= 0) return '關閉'
  return `${Math.round(sec / 60)} 分鐘`
}
