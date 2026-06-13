import { useMemo, useRef, useState } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { PodcastHomeApiStore } from '../podcast-home/PodcastHomeApiStore'
import { PODCAST_FIXTURES } from './fixtures'
import type { PodcastPlayerFixture } from './fixtures'
import demoAudioUrl from '../../assets/podcast_demo.mp3'
import {
  GoBackward15Icon,
  GoForward15Icon,
  LockCircleFillIcon,
  LockFillIcon,
  PauseFillIcon,
  PersonCropCircleIcon,
  PlayFillIcon,
} from './icons'
import {
  activeSpanAt,
  buildWordSpans,
  DEMO_DURATION_SEC,
  formatClock,
  nextRate,
  rateLabel,
  type PlaybackRate,
} from './timeline'
import './podcast.css'
import './interactive.css'

/**
 * Podcast player surface — iOS PodcastPlayerView 的 web 重寫，現為**真播放**互動版。
 *
 * preview-player 結構 = PodcastPlayerScene.playerContent(.ready)：transcript bubble
 *   column → preview banner → controls（seek bar + 時鐘 + transport）。幾何常數逐一
 *   對齊 iOS（見 podcast.css 的 px 註解）。
 *
 * 互動層（HTML5 <audio> 接 demo 音檔；fixtures 當資料層、in-memory、無持久化）：
 *   - play/pause（disc 切 play.fill ↔ pause.fill）
 *   - seek（點/拖進度條 → audio.currentTime）
 *   - 進度條 + 時鐘真連動 timeupdate
 *   - 字幕逐句 + 逐詞 highlight 跟隨 currentTime（demo timing，見 timeline.ts）
 *   - speed 控制（rate pill 循環 ×1/×1.5/×2/×0.75 → audio.playbackRate）
 *
 * **Parity 不變式**：未播放前（started=false）一律渲染 fixture 的靜態值（active 句、
 *   activeWordIndex、elapsed/total、progress、rate ×1），故 capture URL 首屏與靜態版
 *   逐位元相同。只有使用者按下 play / seek 後才切到 audio-derived。
 *
 * locked-gate 結構 = PodcastPlayerLockedGateView：維持靜態（無播放器）。
 */

/** 一個字幕氣泡。slot 0（單一講者）→ 左對齊、無 speaker label。active 句加強 tint，
 *  active word 下方畫 playback 底線。 */
function Bubble({
  words,
  isActive,
  activeWordIndex,
}: {
  words: string[]
  isActive: boolean
  activeWordIndex: number
}) {
  return (
    <div className={`pc-bubble${isActive ? ' pc-bubble-active' : ''}`}>
      <p className="pc-bubble-text">
        {words.map((w, i) => (
          <span
            key={i}
            className={isActive && i === activeWordIndex ? 'pc-word pc-word-active' : 'pc-word'}
          >
            {w}
            {i < words.length - 1 ? ' ' : ''}
          </span>
        ))}
      </p>
    </div>
  )
}

function PlayerScene({ fixture }: { fixture: PodcastPlayerFixture }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const seekRef = useRef<HTMLDivElement>(null)
  const wordSpans = useMemo(() => buildWordSpans(fixture.sentences), [fixture.sentences])
  const sentenceWordLists = useMemo(
    () => fixture.sentences.map((s) => s.text.split(' ')),
    [fixture.sentences],
  )

  // started=false 時一律渲染 fixture 靜態值（parity 首屏鎖定）。
  const [started, setStarted] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [rate, setRate] = useState<PlaybackRate>(1)
  const [dragging, setDragging] = useState(false)

  // active 句/詞：started 後由 currentTime 推，否則用 fixture 靜態值。
  const derived = started
    ? activeSpanAt(wordSpans, currentTime)
    : (() => {
        const si = fixture.sentences.findIndex((s) => s.isActive)
        const idx = si < 0 ? -1 : si
        return { sentenceIndex: idx, wordIndex: idx < 0 ? -1 : fixture.sentences[idx].activeWordIndex }
      })()

  const progress = started ? clamp01(currentTime / DEMO_DURATION_SEC) : fixture.progress
  const elapsed = started ? formatClock(currentTime) : fixture.elapsed
  const total = started ? formatClock(DEMO_DURATION_SEC) : fixture.total
  const rateText = started ? rateLabel(rate) : fixture.rate

  function ensureStarted() {
    if (!started) setStarted(true)
  }

  function togglePlay() {
    const a = audioRef.current
    if (!a) return
    ensureStarted()
    if (a.paused) {
      void a.play()
    } else {
      a.pause()
    }
  }

  function skip(delta: number) {
    const a = audioRef.current
    if (!a) return
    ensureStarted()
    const next = Math.min(DEMO_DURATION_SEC, Math.max(0, (a.currentTime || 0) + delta))
    a.currentTime = next
    setCurrentTime(next)
  }

  function cycleRate() {
    const a = audioRef.current
    ensureStarted()
    const next = nextRate(rate)
    setRate(next)
    if (a) a.playbackRate = next
  }

  function seekToClientX(clientX: number) {
    const el = seekRef.current
    const a = audioRef.current
    if (!el || !a) return
    const rect = el.getBoundingClientRect()
    const ratio = clamp01((clientX - rect.left) / rect.width)
    const t = ratio * DEMO_DURATION_SEC
    ensureStarted()
    a.currentTime = t
    setCurrentTime(t)
  }

  return (
    <div className="pc-player">
      {/* 真實 <audio> 元素：demo 音檔；timeupdate 驅動所有 UI。隱藏（player 自繪控制）。 */}
      <audio
        ref={audioRef}
        src={demoAudioUrl}
        preload="metadata"
        data-pc-audio
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => {
          if (!dragging) setCurrentTime(e.currentTarget.currentTime)
        }}
      />

      {/* transcript column */}
      <div className="pc-transcript">
        <div className="pc-transcript-inner">
          {fixture.sentences.map((_, i) => (
            <Bubble
              key={i}
              words={sentenceWordLists[i]}
              isActive={i === derived.sentenceIndex}
              activeWordIndex={i === derived.sentenceIndex ? derived.wordIndex : -1}
            />
          ))}
        </div>
      </div>

      {/* preview banner */}
      <div className="pc-banner">
        <LockCircleFillIcon className="pc-banner-lock" size={20} />
        <span className="pc-banner-msg">免費試聽 · 升級聽完整單集</span>
        <span className="pc-banner-cta">升級 Pro</span>
      </div>

      {/* controls cluster */}
      <div className="pc-controls">
        {/* seek bar：點/拖整條 hit area */}
        <div
          ref={seekRef}
          className="pc-seek"
          data-pc-seek
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
          }}
        >
          <span className="pc-seek-track" />
          <span className="pc-seek-fill" style={{ width: `${progress * 100}%` }} />
          <span className="pc-seek-thumb" style={{ left: `${progress * 100}%` }} />
        </div>
        {/* 時鐘列 */}
        <div className="pc-clock">
          <span className="pc-clock-elapsed" data-pc-elapsed>
            {elapsed}
          </span>
          <span className="pc-clock-total">{total}</span>
        </div>
        {/* transport：rewind15 · play/pause · forward15 中置；rate pill 靠右 */}
        <div className="pc-transport">
          <div className="pc-transport-center">
            <button type="button" className="pc-skip pc-control-btn" aria-label="後退 15 秒" onClick={() => skip(-15)}>
              <GoBackward15Icon size={28} />
            </button>
            <button
              type="button"
              className="pc-play pc-control-btn"
              aria-label={playing ? '暫停' : '播放'}
              data-pc-play
              data-playing={playing}
              onClick={togglePlay}
            >
              {playing ? <PauseFillIcon size={24} /> : <PlayFillIcon size={26} />}
            </button>
            <button type="button" className="pc-skip pc-control-btn" aria-label="前進 15 秒" onClick={() => skip(15)}>
              <GoForward15Icon size={28} />
            </button>
          </div>
          <button type="button" className="pc-rate pc-control-btn" aria-label="播放速度" data-pc-rate onClick={cycleRate}>
            {rateText}
          </button>
        </div>
      </div>
    </div>
  )
}

function LockedGate() {
  return (
    <div className="pc-gate">
      <LockFillIcon className="pc-gate-lock" size={64} />
      <h2 className="pc-gate-title">登入後收聽</h2>
      <p className="pc-gate-body">登入即可播放單集並解鎖完整內容。</p>
      <button className="pc-gate-cta" type="button">
        <PersonCropCircleIcon size={22} />
        <span>登入後收聽</span>
      </button>
    </div>
  )
}

/** ?shell=1 opt-in: web app shell mounts the functional flow. */
function isShellMode(): boolean {
  if (typeof window === 'undefined') return false
  return new URLSearchParams(window.location.search).get('shell') === '1'
}

export function PodcastScreen({ scenario }: { scenario: ScenarioId<'podcast'> }) {
  // Shell-gated functional flow (home → episode-list → player, live API,
  // subtitle SRT sync, tier gating, continue-shelf). Parity capture path
  // (no ?shell=1) renders the untouched fixture branch below, byte-identical.
  if (isShellMode()) return <PodcastHomeApiStore />

  const fixture = PODCAST_FIXTURES[scenario]
  return (
    <div className="podcast">
      {fixture.kind === 'preview-player' ? <PlayerScene fixture={fixture} /> : <LockedGate />}
    </div>
  )
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v
}
