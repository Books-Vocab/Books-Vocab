// Singleton podcast playback engine — the SINGLE source of now-playing truth for
// the shell-gated functional flow.
//
// WHY a module singleton (not a per-surface hook): in the real app shell the
// podcast tab navigates podcast-home → podcast-episode-list → podcast(player) as
// SEPARATE surface components that AppShell mounts/unmounts via renderScreen. A
// per-screen <audio> would be torn down on every push/pop, killing playback. So
// the engine lives OUTSIDE React: it owns one <audio> appended to document.body
// (survives all surface remounts) and broadcasts state via useSyncExternalStore.
// The mini-player and the full player are thin views over this one engine — the
// iOS "now playing" continuity, achieved without touching the frozen shell.
//
// Pure playback policy (next-episode, preview cap, …) is delegated to nowPlaying.ts
// so it stays unit-testable; this module is the imperative <audio> + pub/sub glue.

import type { ApiClient } from '../../api'
import type { PodcastTier } from './tier'
import {
  applyPreviewCap,
  FREE_PREVIEW_CAP_SEC,
  nextPlayableEpisode,
  previewCapSec,
  sleepTick,
  type SubtitleSize,
} from './nowPlaying'
import type { PodcastSeriesSummary } from '../../api/types'

/** The episode currently loaded into the engine. */
export interface EngineNowPlaying {
  seriesId: string
  epNum: number
  seriesTitle: string
  episodeTitle: string
  /** the series catalog dict — needed for continuous-playback (next episode). */
  series: PodcastSeriesSummary | undefined
  tier: PodcastTier
  /** true when this is the time-capped free preview. */
  preview: boolean
}

/** Immutable snapshot the React views subscribe to. */
export interface PlaybackSnapshot {
  nowPlaying: EngineNowPlaying | null
  /** true once the user actually pressed play for the loaded episode. */
  engaged: boolean
  playing: boolean
  currentTime: number
  duration: number
  /** [0,1] clamp(currentTime / duration). */
  progress: number
  // ── now-playing preferences (persist across episodes within a session) ──
  subtitleSize: SubtitleSize
  /** auto-scroll the active cue into view. */
  subtitleFollow: boolean
  /** auto-advance to the next playable episode on end. */
  continuous: boolean
  /** sleep-timer total seconds (0 = off). */
  sleepSec: number
  /** seconds remaining on the sleep timer (0 when off / fired). */
  sleepRemaining: number
}

function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0
  return v < 0 ? 0 : v > 1 ? 1 : v
}

class PodcastPlaybackEngine {
  private audio: HTMLAudioElement | null = null
  private listeners = new Set<() => void>()
  private api: ApiClient | null = null
  private srcUrl = ''
  private sleepInterval: ReturnType<typeof setInterval> | null = null

  private snapshot: PlaybackSnapshot = {
    nowPlaying: null,
    engaged: false,
    playing: false,
    currentTime: 0,
    duration: 0,
    progress: 0,
    subtitleSize: 'm',
    subtitleFollow: true,
    continuous: true,
    sleepSec: 0,
    sleepRemaining: 0,
  }

  // ── pub/sub (useSyncExternalStore) ────────────────────────────────────────
  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  getSnapshot = (): PlaybackSnapshot => this.snapshot

  private emit(patch: Partial<PlaybackSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch }
    for (const fn of this.listeners) fn()
  }

  // ── configuration the views inject once data is available ─────────────────
  /**
   * Register the demo audio src + api client (idempotent; first wins). Robust to
   * effect ordering: if the audio element was already created by an earlier
   * load() before configure() ran (child effects fire before the parent's), this
   * backfills the src so playback is never left source-less.
   */
  configure(opts: { srcUrl: string; api: ApiClient }) {
    if (!this.srcUrl) this.srcUrl = opts.srcUrl
    if (!this.api) this.api = opts.api
    const a = this.ensureAudio()
    if (a && this.srcUrl && !a.src) a.src = this.srcUrl
  }

  private ensureAudio(): HTMLAudioElement | null {
    if (this.audio) return this.audio
    if (typeof document === 'undefined') return null
    const a = document.createElement('audio')
    a.preload = 'metadata'
    a.setAttribute('data-podcast-engine', 'true')
    if (this.srcUrl) a.src = this.srcUrl
    a.addEventListener('play', () => this.emit({ playing: true, engaged: true }))
    a.addEventListener('pause', () => {
      this.emit({ playing: false })
      this.persistProgress()
    })
    a.addEventListener('ended', () => this.handleEnded())
    a.addEventListener('timeupdate', () => this.handleTimeUpdate())
    a.addEventListener('loadedmetadata', () => {
      const d = Number.isFinite(a.duration) ? a.duration : 0
      this.emit({ duration: d, progress: clamp01(a.currentTime / (d || 1)) })
    })
    document.body.appendChild(a)
    this.audio = a
    return a
  }

  private handleTimeUpdate() {
    const a = this.audio
    if (!a) return
    const np = this.snapshot.nowPlaying
    const cap = np?.preview ? previewCapSec(np.tier, np.epNum, true) ?? FREE_PREVIEW_CAP_SEC : null
    const { time, pause } = applyPreviewCap(a.currentTime, cap)
    const d = this.snapshot.duration || a.duration || 0
    if (pause) {
      a.pause()
      a.currentTime = time
    }
    this.emit({ currentTime: time, progress: clamp01(time / (d || 1)) })
  }

  private handleEnded() {
    this.emit({ playing: false })
    this.persistProgress()
    if (this.snapshot.continuous) this.advance()
  }

  // ── transport ─────────────────────────────────────────────────────────────
  /**
   * Load an episode into the persistent audio. Switching episodes restarts the
   * clip; same-episode reload is a no-op (so re-entering the player screen does
   * not rewind). Does NOT autoplay — waits for an explicit user gesture.
   */
  load(np: EngineNowPlaying) {
    const a = this.ensureAudio()
    const prev = this.snapshot.nowPlaying
    const same = !!prev && prev.seriesId === np.seriesId && prev.epNum === np.epNum
    if (same) {
      // keep playing; just refresh metadata (tier/series may have resolved late).
      this.emit({ nowPlaying: np })
      return
    }
    if (a) {
      if (this.srcUrl && a.src !== this.srcUrl && a.src.indexOf(this.srcUrl) < 0) a.src = this.srcUrl
      a.currentTime = 0
    }
    this.emit({ nowPlaying: np, engaged: false, playing: false, currentTime: 0, progress: 0 })
  }

  togglePlay() {
    const a = this.audio
    if (!a) return
    if (a.paused) void a.play().catch(() => {})
    else a.pause()
  }

  play() {
    const a = this.audio
    if (a && a.paused) void a.play().catch(() => {})
  }

  skip(delta: number) {
    const a = this.audio
    if (!a) return
    const max = this.cappedMax()
    const next = Math.min(max, Math.max(0, (a.currentTime || 0) + delta))
    a.currentTime = next
    this.emit({ currentTime: next, progress: clamp01(next / (this.snapshot.duration || 1)) })
  }

  seekToFraction(fraction: number) {
    const a = this.audio
    if (!a) return
    const d = this.snapshot.duration || a.duration || 0
    const max = this.cappedMax()
    const t = Math.min(max, clamp01(fraction) * (d || max))
    a.currentTime = t
    this.emit({ currentTime: t, progress: clamp01(t / (d || 1)) })
  }

  /** Seek ceiling respecting the free-preview cap. */
  private cappedMax(): number {
    const np = this.snapshot.nowPlaying
    const d = this.snapshot.duration || 0
    if (np?.preview) {
      const cap = previewCapSec(np.tier, np.epNum, true) ?? FREE_PREVIEW_CAP_SEC
      return d > 0 ? Math.min(cap, d) : cap
    }
    return d || Number.MAX_SAFE_INTEGER
  }

  // ── now-playing preferences ────────────────────────────────────────────────
  setSubtitleSize(size: SubtitleSize) {
    this.emit({ subtitleSize: size })
  }

  setSubtitleFollow(follow: boolean) {
    this.emit({ subtitleFollow: follow })
  }

  setContinuous(on: boolean) {
    this.emit({ continuous: on })
  }

  setSleep(sec: number) {
    this.clearSleep()
    if (sec <= 0) {
      this.emit({ sleepSec: 0, sleepRemaining: 0 })
      return
    }
    this.emit({ sleepSec: sec, sleepRemaining: sec })
    this.sleepInterval = setInterval(() => {
      const { remaining, fired } = sleepTick(this.snapshot.sleepRemaining)
      if (fired) {
        this.clearSleep()
        this.audio?.pause()
        this.emit({ sleepSec: 0, sleepRemaining: 0 })
      } else {
        this.emit({ sleepRemaining: remaining })
      }
    }, 1000)
  }

  private clearSleep() {
    if (this.sleepInterval) {
      clearInterval(this.sleepInterval)
      this.sleepInterval = null
    }
  }

  // ── continuous playback (auto-advance) ─────────────────────────────────────
  /** Load + play the next playable episode, if any. Returns the loaded ep_num. */
  advance(): number | null {
    const np = this.snapshot.nowPlaying
    if (!np) return null
    const next = nextPlayableEpisode(np.series, np.epNum, np.tier)
    if (!next) return null
    this.load({
      seriesId: np.seriesId,
      epNum: next.epNum,
      seriesTitle: np.seriesTitle,
      episodeTitle: next.title,
      series: np.series,
      tier: np.tier,
      preview: false, // next is only reached for pro → never the preview slot
    })
    // auto-advance keeps playing (continuous listening).
    this.play()
    return next.epNum
  }

  // ── progress write-back (best-effort LWW) ──────────────────────────────────
  private persistProgress() {
    const np = this.snapshot.nowPlaying
    const api = this.api
    if (!np || !api) return
    void api.podcast
      .putProgress(np.seriesId, np.epNum, {
        position_sec: Math.round(this.snapshot.currentTime),
        duration_sec: Math.round(this.snapshot.duration) || 0,
        updated_at: new Date().toISOString(),
      })
      .catch(() => {
        /* best-effort; never block playback */
      })
  }
}

/** The one engine instance shared across all podcast surfaces. */
export const playbackEngine = new PodcastPlaybackEngine()
