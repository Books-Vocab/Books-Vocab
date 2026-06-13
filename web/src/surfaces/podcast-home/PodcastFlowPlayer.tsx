import { useMemo, useRef, useState } from 'react'
import type { ApiClient } from '../../api'
import type { PodcastSeriesSummary } from '../../api/types'
import demoAudioUrl from '../../assets/podcast_demo.mp3'
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
import './podcast-flow.css'

/**
 * Functional player for the shell-gated flow.
 *
 * Subtitle: parses the inline demo SRT (mock backend has no subtitle byte route)
 * and highlights the cue under the live <audio> currentTime — the web mirror of
 * iOS PodcastPlayerViewModel.subtitleState + SubtitleRenderState.
 *
 * Tier gate (PodcastAccess mirror):
 *   - guest  → sign-in gate (no player)
 *   - free   → ep1 = time-limited preview (banner + upgrade CTA); other eps locked
 *   - pro    → full playback
 *
 * Progress write-back: on pause/seek, POST /api/podcasts/{sid}/{ep}/progress
 * (LWW upsert) so the continue-shelf reflects where you stopped.
 */
export function PodcastFlowPlayer({
  seriesId,
  epNum,
  series,
  tier,
  api,
}: {
  seriesId: string
  epNum: number
  series: PodcastSeriesSummary | undefined
  tier: PodcastTier
  api: ApiClient
}) {
  const cues = useMemo(() => parseSrt(DEMO_SRT), [])
  const audioRef = useRef<HTMLAudioElement>(null)
  const seekRef = useRef<HTMLDivElement>(null)

  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [dragging, setDragging] = useState(false)

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

  const activeIdx = activeCueIndex(cues, currentTime)
  const progress = clamp01(currentTime / DEMO_DURATION_SEC)

  // Defensive deep-link gate: guest / locked episode → no player (mirrors iOS
  // PodcastPlayerLockedGateView + loadEpisode early-return).
  function persistProgress() {
    if (!playable) return
    void api.podcast
      .putProgress(seriesId, epNum, {
        position_sec: Math.round(currentTime),
        duration_sec: DEMO_DURATION_SEC,
        updated_at: new Date().toISOString(),
      })
      .catch(() => {
        /* best-effort; never block playback */
      })
  }

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

  return (
    <main className="ph-scroll pf-player">
      <audio
        ref={audioRef}
        src={demoAudioUrl}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => {
          setPlaying(false)
          persistProgress()
        }}
        onEnded={() => {
          setPlaying(false)
          persistProgress()
        }}
        onTimeUpdate={(e) => {
          if (!dragging) setCurrentTime(e.currentTarget.currentTime)
        }}
      />

      <header className="pf-player-head">
        <span className="pf-player-series">{String(series?.title ?? seriesId)}</span>
        <span className="pf-player-episode">{episodeTitle}</span>
      </header>

      {/* transcript: SRT cues, active cue tracks the playhead */}
      <div className="pf-transcript" data-testid="pf-transcript">
        {cues.map((cue, i) => (
          <p key={cue.index} className={i === activeIdx ? 'pf-cue pf-cue-active' : 'pf-cue'}>
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
            setDragging(true)
            seekToClientX(e.clientX)
          }}
          onPointerMove={(e) => {
            if (dragging) seekToClientX(e.clientX)
          }}
          onPointerUp={(e) => {
            ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
            setDragging(false)
            persistProgress()
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
          <button type="button" className="pf-control-btn" aria-label="後退 15 秒" onClick={() => skip(-15)}>
            <GoBackward15Icon size={28} />
          </button>
          <button
            type="button"
            className="pf-control-btn pf-play"
            aria-label={playing ? '暫停' : '播放'}
            onClick={togglePlay}
          >
            {playing ? <PauseFillIcon size={24} /> : <PlayFillIcon size={26} />}
          </button>
          <button type="button" className="pf-control-btn" aria-label="前進 15 秒" onClick={() => skip(15)}>
            <GoForward15Icon size={28} />
          </button>
        </div>
      </div>
    </main>
  )

  function togglePlay() {
    const a = audioRef.current
    if (!a) return
    if (a.paused) void a.play()
    else a.pause()
  }

  function skip(delta: number) {
    const a = audioRef.current
    if (!a) return
    const next = Math.min(DEMO_DURATION_SEC, Math.max(0, (a.currentTime || 0) + delta))
    a.currentTime = next
    setCurrentTime(next)
  }

  function seekToClientX(clientX: number) {
    const el = seekRef.current
    const a = audioRef.current
    if (!el || !a) return
    const rect = el.getBoundingClientRect()
    const ratio = clamp01((clientX - rect.left) / rect.width)
    const t = ratio * DEMO_DURATION_SEC
    a.currentTime = t
    setCurrentTime(t)
  }
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}
