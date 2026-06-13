import { useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { reduced, sheet, snappy, Sheet } from '../../motion'
import { useShellNav } from '../../shell/ShellNavContext'
import { pushTargetFor, screenFor } from '../../shell/nav'
import { useSharedPlayback } from './useSharedPlayback'
import { useIsActiveNowPlayingHost } from './nowPlayingHost'
import { playbackEngine } from './playbackEngine'
import {
  SLEEP_OPTIONS,
  SUBTITLE_SIZES,
  sleepLabel,
  type SubtitleSize,
} from './nowPlaying'
import {
  CaptionsIcon,
  CheckmarkIcon,
  EllipsisIcon,
  ListBulletIcon,
  MoonIcon,
  PauseFillIcon,
  PlayFillIcon,
} from './icons'
import './now-playing.css'

/**
 * PodcastNowPlaying — the PERSISTENT now-playing layer for the shell-gated
 * podcast flow (mini-player + option sheets), the iOS "now playing" mirror.
 *
 * WHY this lives here and is mounted by every podcast surface: in the real app
 * shell the podcasts tab navigates podcast-home → episode-list → player as
 * separate surfaces AppShell mounts/unmounts. The audio + transport state live
 * in the singleton playbackEngine (outside React), and this bar is portaled to
 * document.body so it survives every surface remount and floats above the route
 * swap. A single-renderer election (useIsActiveNowPlayingHost) guarantees exactly
 * one bar even while two surfaces overlap during a push.
 *
 * Shell-gated: every mount site only renders this behind ?shell=1, so the parity
 * capture DOM is never touched. Motion reuses the shared springs (sheet/snappy/
 * reduced) and the shared <Sheet> primitive; honours prefers-reduced-motion.
 */
export function PodcastNowPlaying() {
  const isHost = useIsActiveNowPlayingHost()
  // Only the elected host renders; the others are inert (no duplicate bars).
  if (!isHost) return null
  return <NowPlayingPortal />
}

function NowPlayingPortal() {
  const pb = useSharedPlayback()
  const nav = useShellNav()
  const prefersReduced = useReducedMotion() ?? false
  const [optionsOpen, setOptionsOpen] = useState(false)
  const [sleepOpen, setSleepOpen] = useState(false)
  const [subtitleOpen, setSubtitleOpen] = useState(false)

  if (typeof document === 'undefined') return null

  const np = pb.nowPlaying
  // Visible once the user has engaged playback for a loaded episode and the full
  // player surface is NOT the current screen. The player surface is the only one
  // in the podcast flow that carries an epNum param (home carries nothing,
  // episode-list carries only seriesId), so `epNum != null` reliably means "the
  // full player is showing" — hide the redundant compact bar there. On home /
  // episode-list the bar surfaces, mirroring iOS now-playing continuity.
  const onPlayerSurface = nav.params.epNum != null
  const visible = !!np && pb.engaged && !onPlayerSurface

  function openPlayer() {
    if (!np) return
    // Re-enter the full player for the loaded episode, pushing only the levels
    // missing from the CURRENT screen so we never duplicate a stack entry:
    //   - already on THIS series' episode-list → push only the player.
    //   - otherwise (home, or a different series' list) → push this series'
    //     episode-list, then the player.
    // (On the player surface the bar is hidden, so this never fires from there.)
    const list = screenFor('podcast-episode-list', { seriesId: np.seriesId })
    const alreadyOnThisList = nav.params.seriesId === np.seriesId && nav.params.epNum == null
    if (!alreadyOnThisList) {
      const listTarget = pushTargetFor(screenFor('podcast-home'), 'open-podcast-series', {
        seriesId: np.seriesId,
      })
      if (!listTarget) return
      nav.navigate(listTarget)
    }
    const player = pushTargetFor(list, 'open-podcast-episode', {
      seriesId: np.seriesId,
      epNum: np.epNum,
    })
    if (player) nav.navigate(player)
  }

  const slideY = prefersReduced ? 0 : 24
  const transition = prefersReduced ? reduced : sheet

  return createPortal(
    <>
      <AnimatePresence>
        {visible && np && (
          <motion.div
            className="np-mini"
            data-podcast-now-playing="true"
            initial={{ y: slideY + 16, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: slideY + 16, opacity: 0 }}
            transition={transition}
          >
            <span className="np-mini-progress" aria-hidden="true">
              <span className="np-mini-progress-fill" style={{ width: `${pb.progress * 100}%` }} />
            </span>

            <button
              type="button"
              className="np-mini-main"
              aria-label={`繼續播放 ${np.episodeTitle}`}
              onClick={openPlayer}
            >
              <span className="np-mini-art" aria-hidden="true">
                {np.seriesTitle.slice(0, 1)}
              </span>
              <span className="np-mini-label">
                <span className="np-mini-title">{np.episodeTitle}</span>
                <span className="np-mini-series">{np.seriesTitle}</span>
              </span>
            </button>

            <button
              type="button"
              className="np-mini-play"
              aria-label={pb.playing ? '暫停' : '播放'}
              onClick={() => playbackEngine.togglePlay()}
            >
              <AnimatePresence mode="popLayout" initial={false}>
                <motion.span
                  key={pb.playing ? 'pause' : 'play'}
                  className="np-mini-play-glyph"
                  initial={{ scale: prefersReduced ? 1 : 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: prefersReduced ? 1 : 0.6, opacity: 0 }}
                  transition={prefersReduced ? reduced : snappy}
                >
                  {pb.playing ? <PauseFillIcon size={20} /> : <PlayFillIcon size={20} />}
                </motion.span>
              </AnimatePresence>
            </button>

            <button
              type="button"
              className="np-mini-more"
              aria-label="播放選項"
              onClick={() => setOptionsOpen(true)}
            >
              <EllipsisIcon size={20} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Options sheet: entry to subtitle, sleep timer, continuous toggle. */}
      <Sheet open={optionsOpen} onClose={() => setOptionsOpen(false)} ariaLabel="播放選項">
        <div className="np-sheet">
          <h2 className="np-sheet-title">播放選項</h2>
          <ul className="np-opt-list">
            <li>
              <button
                type="button"
                className="np-opt-row"
                onClick={() => {
                  setOptionsOpen(false)
                  setSubtitleOpen(true)
                }}
              >
                <CaptionsIcon size={22} className="np-opt-icon" />
                <span className="np-opt-text">字幕</span>
                <span className="np-opt-value">
                  {SUBTITLE_LABELS[pb.subtitleSize]} · {pb.subtitleFollow ? '跟隨' : '手動'}
                </span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className="np-opt-row"
                onClick={() => {
                  setOptionsOpen(false)
                  setSleepOpen(true)
                }}
              >
                <MoonIcon size={22} className="np-opt-icon" />
                <span className="np-opt-text">睡眠定時</span>
                <span className="np-opt-value">
                  {pb.sleepSec > 0 ? formatCountdown(pb.sleepRemaining) : '關閉'}
                </span>
              </button>
            </li>
            <li>
              <button
                type="button"
                className="np-opt-row np-opt-toggle"
                aria-pressed={pb.continuous}
                onClick={() => playbackEngine.setContinuous(!pb.continuous)}
              >
                <ListBulletIcon size={22} className="np-opt-icon" />
                <span className="np-opt-text">連續播放</span>
                <span className={`np-switch${pb.continuous ? ' np-switch-on' : ''}`} aria-hidden="true">
                  <span className="np-switch-knob" />
                </span>
              </button>
            </li>
          </ul>
        </div>
      </Sheet>

      {/* Subtitle sheet: size ladder + follow toggle. */}
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
                <span className="np-size-name">{SUBTITLE_LABELS[s]}</span>
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

      {/* Sleep-timer sheet: option ladder with checkmark. */}
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
          {pb.sleepSec > 0 ? (
            <p className="np-sheet-foot">將於 {formatCountdown(pb.sleepRemaining)} 後暫停</p>
          ) : null}
        </div>
      </Sheet>
    </>,
    document.body,
  )
}

const SUBTITLE_LABELS: Record<SubtitleSize, string> = {
  s: '小',
  m: '中',
  l: '大',
  xl: '特大',
}

function formatCountdown(sec: number): string {
  const s = Math.max(0, Math.round(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${String(r).padStart(2, '0')}`
}
