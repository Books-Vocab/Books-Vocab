// Mini-player visibility + flow-stack helpers for the shell-gated podcast flow.
//
// The functional flow (PodcastHomeApiStore) lifts a SINGLE persistent <audio>
// element above the route swap so playback survives navigating between
// home / episode-list / player (iOS "now playing" continuity). The mini-player
// is the compact transport that appears whenever an episode is loaded but the
// full player screen is NOT the visible screen — tapping it re-pushes the player.
//
// Pure functions, no React, no DOM — so the visibility rule is unit-testable and
// the same predicate drives both the bar render and the AnimatePresence key.

import type { PodcastFlowScreen, PodcastFlowStack } from '../podcast/flowNav'
import { currentFlowScreen, pushFlow } from '../podcast/flowNav'

/** The episode currently loaded into the persistent audio element. */
export interface NowPlaying {
  seriesId: string
  epNum: number
  /** resolved series + episode titles for the mini-player label. */
  seriesTitle: string
  episodeTitle: string
}

/**
 * Show the mini-player iff playback has been ENGAGED for a loaded episode AND
 * the full player for THAT episode is not the visible screen. Requiring
 * `engaged` means merely navigating into the player (without pressing play)
 * never spawns a redundant bar. While the user is on the full player the compact
 * bar is redundant (and would double the transport), so it hides; the moment
 * they pop back to home / episode-list it animates in.
 */
export function shouldShowMiniPlayer(
  nowPlaying: NowPlaying | null,
  engaged: boolean,
  current: PodcastFlowScreen,
): boolean {
  if (!nowPlaying || !engaged) return false
  if (
    current.route === 'player' &&
    current.seriesId === nowPlaying.seriesId &&
    current.epNum === nowPlaying.epNum
  ) {
    return false
  }
  return true
}

/**
 * Tapping the mini-player returns to the full player for the loaded episode.
 * If that exact player screen is already the tail (defensive), this is a no-op
 * push-equivalent — callers gate on shouldShowMiniPlayer so the tap only fires
 * when the player is NOT current, but we still guard to keep the stack clean.
 */
export function reopenPlayer(stack: PodcastFlowStack, nowPlaying: NowPlaying): PodcastFlowStack {
  const tail = currentFlowScreen(stack)
  if (
    tail.route === 'player' &&
    tail.seriesId === nowPlaying.seriesId &&
    tail.epNum === nowPlaying.epNum
  ) {
    return stack
  }
  return pushFlow(stack, {
    route: 'player',
    seriesId: nowPlaying.seriesId,
    epNum: nowPlaying.epNum,
  })
}
