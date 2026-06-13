import { useEffect, useMemo, useRef } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion'
import type { PodcastSeriesSummary } from '../../api/types'
import { reduced, snappy } from '../../motion'
import { DEMO_SRT } from '../podcast/demoSrt'
import { activeCueIndex, parseSrt } from '../podcast/srt'
import { DEMO_DURATION_SEC, formatClock } from '../podcast/timeline'
import { canPlay, isPreviewPlayback, type PodcastTier } from '../podcast/tier'
import {
  GoBackward15Icon,
  GoForward15Icon,
  LockFillIcon,
  PauseFillIcon,
  PersonCropCircleIcon,
  PlayFillIcon,
} from '../podcast/icons'
import type { PodcastPlaybackState } from './usePodcastPlayback'
import './podcast-flow.css'

/**
 * Functional full-player view for the shell-gated podcast flow.
 *
 * Playback is NOT owned here — the flow root (PodcastHomeApiStore) owns the
 * single persistent <audio> + transport state via usePodcastPlayback, so the
 * mini-player can keep audio alive across navigation. This component is a thin
 * VIEW over that shared `playback` state: it loads the chosen episode on mount,
 * renders the transcript/banner/transport, and drives the shared engine.
 *
 * Subtitle: parses the inline demo SRT and highlights the cue under the live
 * playhead (web mirror of iOS PodcastPlayerViewModel.subtitleState) AND smoothly
 * scrolls the active cue into view (reduced-motion → instant).
 *
 * Tier gate (PodcastAccess mirror): guest → sign-in gate; free → ep1 preview
 * banner, others Pro-locked; pro → full playback.
 */
export function PodcastFlowPlayer({
  seriesId,
  epNum,
  series,
  tier,
  playback,
}: {
  seriesId: string
  epNum: number
  series: PodcastSeriesSummary | undefined
  tier: PodcastTier
  playback: PodcastPlaybackState
}) {
  const cues = useMemo(() => parseSrt(DEMO_SRT), [])
  const seekRef = useRef<HTMLDivElement>(null)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const prefersReduced = useReducedMotion() ?? false

  // ep1 free-preview asset assumed present under mock.
  const previewAvailable = epNum === 1
  const playable = canPlay(tier, epNum, previewAvailable)
  const preview = isPreviewPlayback(tier, epNum, previewAvailable)

  const episodeTitle = useMemo(() => {
    const eps = series?.episodes
    if (Array.isArray(eps)) {
      for (const e of eps) {
        if (e && typeof e === 'object' && Number((e as Record<string, unknown>).ep_num) === epNum) {
          const t = (e as Record<string, unknown>).title
          if (typeof t === 'string') return t
        }
      }
    }
    return `Ep ${epNum}`
  }, [series, epNum])

  const seriesTitle = String(series?.title ?? seriesId)

  // Load this episode into the shared engine when the player becomes visible
  // (and whenever the chosen episode changes). Guarded by playability so a
  // locked/guest deep-link never loads the audio (mirrors iOS loadEpisode gate).
  // `load` is referentially stable (useCallback in the playback hook), so the
  // effect re-runs only on episode-identity change — not every render.
  const load = playback.load
  useEffect(() => {
    if (!playable) return
    load({ seriesId, epNum, seriesTitle, episodeTitle })
  }, [load, seriesId, epNum, playable, seriesTitle, episodeTitle])

  const isCurrent =
    playback.nowPlaying?.seriesId === seriesId && playback.nowPlaying?.epNum === epNum
  const currentTime = isCurrent ? playback.currentTime : 0
  const playing = isCurrent && playback.playing
  const progress = isCurrent ? playback.progress : 0
  const activeIdx = activeCueIndex(cues, currentTime)

  // Subtitle follow: smoothly scroll the active cue to centre as it advances.
  useEffect(() => {
    if (activeIdx < 0) return
    const container = transcriptRef.current
    if (!container) return
    const el = container.querySelector<HTMLElement>(`[data-cue='${activeIdx}']`)
    if (!el) return
    el.scrollIntoView({
      block: 'center',
      behavior: prefersReduced ? 'auto' : 'smooth',
    })
  }, [activeIdx, prefersReduced])

  if (tier === 'guest') {
    return (
      <main className="ph-scroll pf-gate">
        <LockFillIcon className="pf-gate-lock" size={64} />
        <h2 className="pf-gate-title">登入後收聽</h2>
        <p className="pf-gate-body">登入即可播放單集並解鎖完整內容。</p>
        <button className="pf-gate-cta" type="button">
          <PersonCropCircleIcon size={22} />
          <span>登入後收聽</span>
        </button>
      </main>
    )
  }

  if (!playable) {
    return (
      <main className="ph-scroll pf-gate">
        <LockFillIcon className="pf-gate-lock" size={64} />
        <h2 className="pf-gate-title">升級 Pro 解鎖</h2>
        <p className="pf-gate-body">此單集需要 Pro 訂閱才能收聽。</p>
        <button className="pf-gate-cta" type="button">
          <span>升級 Pro</span>
        </button>
      </main>
    )
  }

  function seekToClientX(clientX: number) {
    const el = seekRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    playback.seekToFraction((clientX - rect.left) / rect.width)
  }

  return (
    <main className="ph-scroll pf-player">
      <header className="pf-player-head">
        <span className="pf-player-series">{seriesTitle}</span>
        <span className="pf-player-episode">{episodeTitle}</span>
      </header>

      {/* transcript: SRT cues, active cue tracks the playhead + auto-scrolls */}
      <div className="pf-transcript" data-testid="pf-transcript" ref={transcriptRef}>
        {cues.map((cue, i) => (
          <p
            key={cue.index}
            data-cue={i}
            className={i === activeIdx ? 'pf-cue pf-cue-active' : 'pf-cue'}
          >
            {cue.text}
          </p>
        ))}
      </div>

      {preview && (
        <div className="pf-banner">
          <LockFillIcon className="pf-banner-lock" size={18} />
          <span className="pf-banner-msg">免費試聽 · 升級聽完整單集</span>
          <span className="pf-banner-cta">升級 Pro</span>
        </div>
      )}

      <div className="pf-controls">
        <div
          ref={seekRef}
          className="pf-seek"
          role="slider"
          aria-label="播放進度"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          onPointerDown={(e) => {
            ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
            playback.setDragging(true)
            seekToClientX(e.clientX)
          }}
          onPointerMove={(e) => {
            if (e.buttons === 1) seekToClientX(e.clientX)
          }}
          onPointerUp={(e) => {
            ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
            seekToClientX(e.clientX)
            playback.setDragging(false)
          }}
        >
          <span className="pf-seek-track" />
          <span className="pf-seek-fill" style={{ width: `${progress * 100}%` }} />
          <span className="pf-seek-thumb" style={{ left: `${progress * 100}%` }} />
        </div>
        <div className="pf-clock">
          <span>{formatClock(currentTime)}</span>
          <span>{formatClock(DEMO_DURATION_SEC)}</span>
        </div>
        <div className="pf-transport">
          <button
            type="button"
            className="pf-control-btn"
            aria-label="後退 15 秒"
            onClick={() => playback.skip(-15)}
          >
            <GoBackward15Icon size={28} />
          </button>
          <button
            type="button"
            className="pf-control-btn pf-play"
            aria-label={playing ? '暫停' : '播放'}
            onClick={playback.togglePlay}
          >
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={playing ? 'pause' : 'play'}
                className="pf-play-glyph"
                initial={{ scale: prefersReduced ? 1 : 0.55, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: prefersReduced ? 1 : 0.55, opacity: 0 }}
                transition={prefersReduced ? reduced : snappy}
              >
                {playing ? <PauseFillIcon size={24} /> : <PlayFillIcon size={26} />}
              </motion.span>
            </AnimatePresence>
          </button>
          <button
            type="button"
            className="pf-control-btn"
            aria-label="前進 15 秒"
            onClick={() => playback.skip(15)}
          >
            <GoForward15Icon size={28} />
          </button>
        </div>
      </div>
    </main>
  )
}
