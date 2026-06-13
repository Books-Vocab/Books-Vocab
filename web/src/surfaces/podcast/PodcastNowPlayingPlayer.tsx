import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { PodcastSeriesSummary } from '../../api/types'
import { reduced, snappy, Sheet } from '../../motion'
import { DEMO_SRT } from './demoSrt'
import { activeCueIndex, parseSrt } from './srt'
import { DEMO_DURATION_SEC, formatClock } from './timeline'
import { canPlay, isFreePreviewable, isPreviewPlayback, type PodcastTier } from './tier'
import { episodesOf, SLEEP_OPTIONS, SUBTITLE_SIZES, sleepLabel } from './nowPlaying'
import { playbackEngine } from './playbackEngine'
import { useSharedPlayback } from './useSharedPlayback'
import {
  CaptionsIcon,
  CheckmarkIcon,
  ForwardEndFillIcon,
  GoBackward15Icon,
  GoForward15Icon,
  LockFillIcon,
  MoonIcon,
  PauseFillIcon,
  PersonCropCircleIcon,
  PlayFillIcon,
} from './icons'
import './now-playing-player.css'

/**
 * Full now-playing player — engine-driven view for the shell master-detail
 * player surface. Unlike the prior PodcastFlowPlayer (which took a per-mount
 * playback hook), this reads the singleton playbackEngine so playback, the
 * mini-player and continuous auto-advance all share ONE source of truth and
 * survive surface remounts.
 *
 * On mount it loads the chosen episode into the engine (guarded by tier so a
 * locked/guest deep-link never loads audio). It then follows engine.nowPlaying,
 * so when continuous playback auto-advances to the next episode the screen
 * updates in place. Subtitle size/follow + sleep timer + continuous are surfaced
 * here AND in the mini-player's option sheets (shared engine state).
 *
 * Shell-gated; motion reuses the shared springs + <Sheet>; honours
 * prefers-reduced-motion.
 */
export function PodcastNowPlayingPlayer({
  seriesId,
  epNum,
  series,
  tier,
}: {
  seriesId: string
  epNum: number
  series: PodcastSeriesSummary | undefined
  tier: PodcastTier
}) {
  const pb = useSharedPlayback()
  const cues = useMemo(() => parseSrt(DEMO_SRT), [])
  const seekRef = useRef<HTMLDivElement>(null)
  const transcriptRef = useRef<HTMLDivElement>(null)
  const prefersReduced = useReducedMotion() ?? false
  const [subtitleOpen, setSubtitleOpen] = useState(false)
  const [sleepOpen, setSleepOpen] = useState(false)

  const previewAvailable = isFreePreviewable(epNum)
  const playable = canPlay(tier, epNum, previewAvailable)
  const preview = isPreviewPlayback(tier, epNum, previewAvailable)

  const episodeTitle = useMemo(() => {
    const found = episodesOf(series).find((e) => e.epNum === epNum)
    return found?.title ?? `Ep ${epNum}`
  }, [series, epNum])
  const seriesTitle = String(series?.title ?? seriesId)

  // Load this episode into the shared engine when the player mounts / the chosen
  // episode changes. Guarded by playability (mirrors iOS loadEpisode gate).
  // The engine is already configured (srcUrl + api) by the loader before render.
  useEffect(() => {
    if (!playable) return
    playbackEngine.load({
      seriesId,
      epNum,
      seriesTitle,
      episodeTitle,
      series,
      tier,
      preview,
    })
  }, [playable, seriesId, epNum, seriesTitle, episodeTitle, series, tier, preview])

  // Follow the engine's loaded episode (continuous playback advances it).
  const np = pb.nowPlaying
  const liveEpNum = np?.epNum ?? epNum
  const liveEpisodeTitle = np?.episodeTitle ?? episodeTitle
  const liveSeriesTitle = np?.seriesTitle ?? seriesTitle
  const isCurrent = np?.seriesId === seriesId // same series; ep may have advanced
  const currentTime = isCurrent ? pb.currentTime : 0
  const playing = isCurrent && pb.playing
  const progress = isCurrent ? pb.progress : 0
  const duration = pb.duration || DEMO_DURATION_SEC
  const activeIdx = activeCueIndex(cues, currentTime)

  // Subtitle follow: smoothly scroll the active cue to centre (engine pref + RM).
  useEffect(() => {
    if (!pb.subtitleFollow || activeIdx < 0) return
    const container = transcriptRef.current
    if (!container) return
    const el = container.querySelector<HTMLElement>(`[data-cue='${activeIdx}']`)
    if (!el) return
    el.scrollIntoView({ block: 'center', behavior: prefersReduced ? 'auto' : 'smooth' })
  }, [activeIdx, pb.subtitleFollow, prefersReduced])

  const canSkipNext = useMemo(() => {
    const eps = episodesOf(series)
    const i = eps.findIndex((e) => e.epNum === liveEpNum)
    if (i < 0 || i + 1 >= eps.length) return false
    const next = eps[i + 1]
    return canPlay(tier, next.epNum, isFreePreviewable(next.epNum))
  }, [series, liveEpNum, tier])

  if (tier === 'guest') {
    return (
      <main className="ph-scroll npp-gate">
        <LockFillIcon className="npp-gate-lock" size={64} />
        <h2 className="npp-gate-title">登入後收聽</h2>
        <p className="npp-gate-body">登入即可播放單集並解鎖完整內容。</p>
        <button className="npp-gate-cta" type="button">
          <PersonCropCircleIcon size={22} />
          <span>登入後收聽</span>
        </button>
      </main>
    )
  }

  if (!playable) {
    return (
      <main className="ph-scroll npp-gate">
        <LockFillIcon className="npp-gate-lock" size={64} />
        <h2 className="npp-gate-title">升級 Pro 解鎖</h2>
        <p className="npp-gate-body">此單集需要 Pro 訂閱才能收聽。</p>
        <button className="npp-gate-cta" type="button">
          <span>升級 Pro</span>
        </button>
      </main>
    )
  }

  function seekToClientX(clientX: number) {
    const el = seekRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    playbackEngine.seekToFraction((clientX - rect.left) / rect.width)
  }

  return (
    <main className="ph-scroll npp-player">
      <header className="npp-head">
        <span className="npp-series">{liveSeriesTitle}</span>
        <span className="npp-episode">{liveEpisodeTitle}</span>
      </header>

      <div
        className="npp-transcript"
        data-testid="npp-transcript"
        data-subtitle-size={pb.subtitleSize}
        ref={transcriptRef}
      >
        {cues.map((cue, i) => (
          <p
            key={cue.index}
            data-cue={i}
            className={i === activeIdx ? 'npp-cue npp-cue-active' : 'npp-cue'}
          >
            {cue.text}
          </p>
        ))}
      </div>

      {preview && (
        <div className="npp-banner">
          <LockFillIcon className="npp-banner-lock" size={18} />
          <span className="npp-banner-msg">免費試聽 · 升級聽完整單集</span>
          <span className="npp-banner-cta">升級 Pro</span>
        </div>
      )}

      <div className="npp-controls">
        <div
          ref={seekRef}
          className="npp-seek"
          role="slider"
          aria-label="播放進度"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          onPointerDown={(e) => {
            ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
            seekToClientX(e.clientX)
          }}
          onPointerMove={(e) => {
            if (e.buttons === 1) seekToClientX(e.clientX)
          }}
          onPointerUp={(e) => {
            ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
            seekToClientX(e.clientX)
          }}
        >
          <span className="npp-seek-track" />
          <span className="npp-seek-fill" style={{ width: `${progress * 100}%` }} />
          <span className="npp-seek-thumb" style={{ left: `${progress * 100}%` }} />
        </div>
        <div className="npp-clock">
          <span>{formatClock(currentTime)}</span>
          <span>{formatClock(duration)}</span>
        </div>

        <div className="npp-transport">
          <button
            type="button"
            className="npp-ctl"
            aria-label="後退 15 秒"
            onClick={() => playbackEngine.skip(-15)}
          >
            <GoBackward15Icon size={28} />
          </button>
          <button
            type="button"
            className="npp-ctl npp-play"
            aria-label={playing ? '暫停' : '播放'}
            onClick={() => playbackEngine.togglePlay()}
          >
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={playing ? 'pause' : 'play'}
                className="npp-play-glyph"
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
            className="npp-ctl"
            aria-label="前進 15 秒"
            onClick={() => playbackEngine.skip(15)}
          >
            <GoForward15Icon size={28} />
          </button>
        </div>

        {/* secondary controls: subtitle / sleep / continuous / next-episode */}
        <div className="npp-secondary">
          <button
            type="button"
            className="npp-sec-btn"
            aria-label="字幕設定"
            onClick={() => setSubtitleOpen(true)}
          >
            <CaptionsIcon size={20} />
          </button>
          <button
            type="button"
            className="npp-sec-btn"
            data-active={pb.sleepSec > 0 || undefined}
            aria-label="睡眠定時"
            onClick={() => setSleepOpen(true)}
          >
            <MoonIcon size={20} />
            {pb.sleepSec > 0 ? <span className="npp-sec-badge">{Math.ceil(pb.sleepRemaining / 60)}</span> : null}
          </button>
          <button
            type="button"
            className="npp-sec-btn npp-sec-toggle"
            data-active={pb.continuous || undefined}
            aria-pressed={pb.continuous}
            aria-label="連續播放"
            onClick={() => playbackEngine.setContinuous(!pb.continuous)}
          >
            <span className="npp-sec-glyph">連</span>
          </button>
          <button
            type="button"
            className="npp-sec-btn"
            aria-label="下一集"
            disabled={!canSkipNext}
            onClick={() => playbackEngine.advance()}
          >
            <ForwardEndFillIcon size={20} />
          </button>
        </div>
      </div>

      {/* Subtitle sheet */}
      <Sheet open={subtitleOpen} onClose={() => setSubtitleOpen(false)} ariaLabel="字幕設定">
        <div className="np-sheet">
          <h2 className="np-sheet-title">字幕</h2>
          <p className="np-sheet-section">字級</p>
          <div className="np-size-row" role="radiogroup" aria-label="字幕字級">
            {SUBTITLE_SIZES.map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={pb.subtitleSize === s}
                className={`np-size-chip${pb.subtitleSize === s ? ' np-size-chip-on' : ''}`}
                data-size={s}
                onClick={() => playbackEngine.setSubtitleSize(s)}
              >
                <span className="np-size-glyph">A</span>
                <span className="np-size-name">{SIZE_LABELS[s]}</span>
              </button>
            ))}
          </div>
          <button
            type="button"
            className="np-opt-row np-opt-toggle np-sheet-toggle"
            aria-pressed={pb.subtitleFollow}
            onClick={() => playbackEngine.setSubtitleFollow(!pb.subtitleFollow)}
          >
            <CaptionsIcon size={22} className="np-opt-icon" />
            <span className="np-opt-text">自動跟隨</span>
            <span className={`np-switch${pb.subtitleFollow ? ' np-switch-on' : ''}`} aria-hidden="true">
              <span className="np-switch-knob" />
            </span>
          </button>
        </div>
      </Sheet>

      {/* Sleep sheet */}
      <Sheet open={sleepOpen} onClose={() => setSleepOpen(false)} ariaLabel="睡眠定時">
        <div className="np-sheet">
          <h2 className="np-sheet-title">睡眠定時</h2>
          <ul className="np-opt-list">
            {SLEEP_OPTIONS.map((sec) => (
              <li key={sec}>
                <button
                  type="button"
                  className="np-opt-row"
                  aria-pressed={pb.sleepSec === sec}
                  onClick={() => {
                    playbackEngine.setSleep(sec)
                    setSleepOpen(false)
                  }}
                >
                  <span className="np-opt-text">{sleepLabel(sec)}</span>
                  {pb.sleepSec === sec ? <CheckmarkIcon size={18} className="np-opt-check" /> : null}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </Sheet>
    </main>
  )
}

const SIZE_LABELS: Record<(typeof SUBTITLE_SIZES)[number], string> = {
  s: '小',
  m: '中',
  l: '大',
  xl: '特大',
}
