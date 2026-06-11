import type { ScenarioId } from '../../harness/scenarios'
import { PODCAST_FIXTURES } from './fixtures'
import type { PodcastPlayerFixture, PodcastSentence } from './fixtures'
import {
  GoBackward15Icon,
  GoForward15Icon,
  LockCircleFillIcon,
  LockFillIcon,
  PersonCropCircleIcon,
  PlayFillIcon,
} from './icons'
import './podcast.css'

/**
 * Podcast player surface — iOS PodcastPlayerView 的 web 重寫（catalog 的
 * `Preview episode · player` + `Locked · sign-in gate` 兩態）。
 *
 * preview-player 結構 = PodcastPlayerScene.playerContent(.ready)：
 *   transcript bubble column（PodcastTranscriptColumn）→ preview banner
 *   （PodcastPlayerPreviewBanner）→ controls（PodcastControlsView：seek bar +
 *   時鐘 + transport）。幾何常數逐一對齊 iOS（見 podcast.css 的 px 註解）。
 *
 * locked-gate 結構 = PodcastPlayerLockedGateView：lock hero + 標題 + 說明 +
 *   sign-in CTA，垂直置中。
 */

/** 一個字幕氣泡。slot 0（單一講者）→ accent tint、左對齊、無 speaker label。
 *  active 句 tint 0.18 + border 0.22，其餘 0.08。playback 底線畫在 active word 下。 */
function Bubble({ sentence }: { sentence: PodcastSentence }) {
  const words = sentence.text.split(' ')
  return (
    <div className={`pc-bubble${sentence.isActive ? ' pc-bubble-active' : ''}`}>
      <p className="pc-bubble-text">
        {words.map((w, i) => (
          <span
            key={i}
            className={
              sentence.isActive && i === sentence.activeWordIndex
                ? 'pc-word pc-word-active'
                : 'pc-word'
            }
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
  return (
    <div className="pc-player">
      {/* transcript column — fills，scroll offset 0（靜態快照不 auto-scroll） */}
      <div className="pc-transcript">
        <div className="pc-transcript-inner">
          {fixture.sentences.map((s, i) => (
            <Bubble key={i} sentence={s} />
          ))}
        </div>
      </div>

      {/* preview banner — brandHero 圓角條（PodcastPlayerPreviewBanner） */}
      <div className="pc-banner">
        <LockCircleFillIcon className="pc-banner-lock" size={20} />
        <span className="pc-banner-msg">免費試聽 · 升級聽完整單集</span>
        <span className="pc-banner-cta">升級 Pro</span>
      </div>

      {/* controls cluster（PodcastControlsView） */}
      <div className="pc-controls">
        {/* seek bar：track + accent fill + thumb */}
        <div className="pc-seek">
          <span className="pc-seek-track" />
          <span className="pc-seek-fill" style={{ width: `${fixture.progress * 100}%` }} />
          <span className="pc-seek-thumb" style={{ left: `${fixture.progress * 100}%` }} />
        </div>
        {/* 時鐘列 */}
        <div className="pc-clock">
          <span className="pc-clock-elapsed">{fixture.elapsed}</span>
          <span className="pc-clock-total">{fixture.total}</span>
        </div>
        {/* transport：rewind15 · play · forward15 中置；rate pill 靠右 */}
        <div className="pc-transport">
          <div className="pc-transport-center">
            <span className="pc-skip">
              <GoBackward15Icon size={28} />
            </span>
            <span className="pc-play">
              <PlayFillIcon size={26} />
            </span>
            <span className="pc-skip">
              <GoForward15Icon size={28} />
            </span>
          </div>
          <span className="pc-rate">{fixture.rate}</span>
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

export function PodcastScreen({ scenario }: { scenario: ScenarioId<'podcast'> }) {
  const fixture = PODCAST_FIXTURES[scenario]
  return (
    <div className="podcast">
      {fixture.kind === 'preview-player' ? (
        <PlayerScene fixture={fixture} />
      ) : (
        <LockedGate />
      )}
    </div>
  )
}
