import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import { reduced, sheet, snappy } from '../../motion'
import { PauseFillIcon, PlayFillIcon } from '../podcast/icons'
import type { PodcastPlaybackState } from './usePodcastPlayback'
import './mini-player.css'

/**
 * PodcastMiniPlayer — the persistent compact transport for the shell-gated
 * podcast flow (web mirror of the iOS now-playing mini bar).
 *
 * Mounted ONLY behind ?shell=1 (the functional flow), never on the parity
 * capture path — so it cannot touch the byte-identical fixture render.
 *
 * Motion (reuses the shared spring layer — no hand-rolled physics):
 *   - present/dismiss with `sheet` spring sliding up from the bottom (AnimatePresence)
 *   - play/pause glyph swap with `snappy` (decisive small change)
 *   - prefers-reduced-motion → instant (the `reduced` transition + zeroed slide)
 *
 * Tapping the bar (outside the play button) re-opens the full player; the play
 * button toggles the shared <audio> without navigating.
 */
export function PodcastMiniPlayer({
  visible,
  playback,
  onOpen,
}: {
  visible: boolean
  playback: PodcastPlaybackState
  onOpen: () => void
}) {
  const prefersReduced = useReducedMotion() ?? false
  const np = playback.nowPlaying
  const slideY = prefersReduced ? 0 : 24
  const transition = prefersReduced ? reduced : sheet

  return (
    <AnimatePresence>
      {visible && np && (
        <motion.div
          className="pf-mini"
          role="button"
          tabIndex={0}
          aria-label={`繼續播放 ${np.episodeTitle}`}
          onClick={onOpen}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onOpen()
            }
          }}
          initial={{ y: slideY + 16, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: slideY + 16, opacity: 0 }}
          transition={transition}
        >
          {/* progress hairline across the top of the bar */}
          <span className="pf-mini-progress" aria-hidden="true">
            <span
              className="pf-mini-progress-fill"
              style={{ width: `${playback.progress * 100}%` }}
            />
          </span>
          <span className="pf-mini-art" aria-hidden="true">
            {np.seriesTitle.slice(0, 1)}
          </span>
          <span className="pf-mini-label">
            <span className="pf-mini-title">{np.episodeTitle}</span>
            <span className="pf-mini-series">{np.seriesTitle}</span>
          </span>
          <button
            type="button"
            className="pf-mini-play"
            aria-label={playback.playing ? '暫停' : '播放'}
            onClick={(e) => {
              e.stopPropagation()
              playback.togglePlay()
            }}
          >
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.span
                key={playback.playing ? 'pause' : 'play'}
                initial={{ scale: prefersReduced ? 1 : 0.6, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: prefersReduced ? 1 : 0.6, opacity: 0 }}
                transition={prefersReduced ? reduced : snappy}
                className="pf-mini-play-glyph"
              >
                {playback.playing ? <PauseFillIcon size={20} /> : <PlayFillIcon size={20} />}
              </motion.span>
            </AnimatePresence>
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
