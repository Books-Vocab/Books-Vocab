import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiClient } from '../../api'
import demoAudioUrl from '../../assets/podcast_demo.mp3'
import { DEMO_DURATION_SEC } from '../podcast/timeline'
import type { NowPlaying } from './miniPlayer'

/**
 * Shared playback engine for the shell-gated podcast flow.
 *
 * WHY a hook (not per-screen <audio>): the mini-player must keep audio alive
 * while you navigate home ↔ episode-list ↔ player. If each screen mounted its
 * own <audio>, popping back would tear it down and stop playback. Instead the
 * flow root owns ONE persistent <audio> (via `audioRef`, attached by the root)
 * and this hook is the single source of transport state. The full player and the
 * mini-player are both thin views over the same state — tapping play in either
 * controls the same element, the iOS "now playing" continuity.
 *
 * Progress write-back is preserved verbatim from PodcastFlowPlayer: on
 * pause/seek/end we POST /api/podcasts/{sid}/{ep}/progress (best-effort LWW).
 *
 * Pure-DOM-free where possible; the only side effects are HTMLAudioElement calls
 * the caller wires through the returned handlers + `bindAudio` props.
 */

export interface PodcastPlaybackState {
  /** the episode currently loaded into the audio element (null = nothing). */
  nowPlaying: NowPlaying | null
  /**
   * true once the user has actually started playback for the loaded episode.
   * Drives mini-player visibility so merely navigating into the player screen
   * (without pressing play) doesn't spawn a redundant mini bar.
   */
  engaged: boolean
  playing: boolean
  currentTime: number
  /** total demo clip length (fixed; the mock has one demo asset). */
  duration: number
  /** [0,1] clamp(currentTime / duration). */
  progress: number
  /** load a (playable) episode and autoplay it. */
  load: (np: NowPlaying) => void
  togglePlay: () => void
  skip: (delta: number) => void
  /** seek to a [0,1] fraction of the clip (mini-player + full scrubber share). */
  seekToFraction: (fraction: number) => void
  setDragging: (dragging: boolean) => void
  /** props the flow root spreads onto the single persistent <audio> element. */
  audioRef: React.RefObject<HTMLAudioElement | null>
  audioProps: {
    src: string
    preload: 'metadata'
    onPlay: () => void
    onPause: () => void
    onEnded: () => void
    onTimeUpdate: (e: React.SyntheticEvent<HTMLAudioElement>) => void
  }
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

export function usePodcastPlayback(api: ApiClient): PodcastPlaybackState {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [nowPlaying, setNowPlaying] = useState<NowPlaying | null>(null)
  const [engaged, setEngaged] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const dragging = useRef(false)

  // nowPlaying lives in a ref too so the stable persistProgress closure always
  // reads the latest loaded episode without re-subscribing the audio handlers.
  const nowPlayingRef = useRef<NowPlaying | null>(null)
  const currentTimeRef = useRef(0)
  useEffect(() => {
    nowPlayingRef.current = nowPlaying
  }, [nowPlaying])
  useEffect(() => {
    currentTimeRef.current = currentTime
  }, [currentTime])

  const persistProgress = useCallback(() => {
    const np = nowPlayingRef.current
    if (!np) return
    void api.podcast
      .putProgress(np.seriesId, np.epNum, {
        position_sec: Math.round(currentTimeRef.current),
        duration_sec: DEMO_DURATION_SEC,
        updated_at: new Date().toISOString(),
      })
      .catch(() => {
        /* best-effort; never block playback */
      })
  }, [api])

  const load = useCallback((np: NowPlaying) => {
    const prev = nowPlayingRef.current
    const sameEpisode = !!prev && prev.seriesId === np.seriesId && prev.epNum === np.epNum
    if (sameEpisode) return
    // Switching episodes (or first load) restarts the clip. We set the loaded
    // episode but do NOT autoplay — playback waits for an explicit user gesture
    // (browser autoplay policy + matches the prior player behaviour). The mini-
    // player only appears once the user has engaged play (see `engaged`).
    const a = audioRef.current
    if (a) a.currentTime = 0
    setCurrentTime(0)
    setEngaged(false)
    setNowPlaying(np)
  }, [])

  const togglePlay = useCallback(() => {
    const a = audioRef.current
    if (!a) return
    if (a.paused) void a.play().catch(() => {})
    else a.pause()
  }, [])

  const skip = useCallback((delta: number) => {
    const a = audioRef.current
    if (!a) return
    const next = Math.min(DEMO_DURATION_SEC, Math.max(0, (a.currentTime || 0) + delta))
    a.currentTime = next
    setCurrentTime(next)
  }, [])

  const seekToFraction = useCallback((fraction: number) => {
    const a = audioRef.current
    if (!a) return
    const t = clamp01(fraction) * DEMO_DURATION_SEC
    a.currentTime = t
    setCurrentTime(t)
  }, [])

  const setDragging = useCallback((d: boolean) => {
    const wasDragging = dragging.current
    dragging.current = d
    // Drag release = a seek committed → persist where we landed.
    if (wasDragging && !d) persistProgress()
  }, [persistProgress])

  const audioProps = {
    src: demoAudioUrl,
    preload: 'metadata' as const,
    onPlay: () => {
      setPlaying(true)
      setEngaged(true)
    },
    onPause: () => {
      setPlaying(false)
      persistProgress()
    },
    onEnded: () => {
      setPlaying(false)
      persistProgress()
    },
    onTimeUpdate: (e: React.SyntheticEvent<HTMLAudioElement>) => {
      if (!dragging.current) setCurrentTime(e.currentTarget.currentTime)
    },
  }

  const progress = clamp01(currentTime / DEMO_DURATION_SEC)

  return {
    nowPlaying,
    engaged,
    playing,
    currentTime,
    duration: DEMO_DURATION_SEC,
    progress,
    load,
    togglePlay,
    skip,
    seekToFraction,
    setDragging,
    audioRef,
    audioProps,
  }
}
