import type { ScenarioId } from '../../harness/scenarios'
import { PODCAST_EPISODE_ROW_FIXTURES, type EpisodeFixture } from './fixtures'
import {
  CaptionsBubbleFillIcon,
  CheckmarkCircleFillIcon,
  ICloudSlashIcon,
  LockFillIcon,
  PlayCircleFillIcon,
} from './icons'
import './podcast-episode-row.css'

/**
 * Podcast · Episode Row surface — iOS `PodcastEpisodeRow` 的 web 鏡像。
 *
 * Row（HStack(.top, spacing wordRowHorizontalGap=10)）：
 *   leading VStack(.leading, spacing wordRowVerticalGap=4)[
 *     Text(title) sectionTitle(serif 18 bold)/primaryText（audio 不可用→tertiaryText）, lineLimit 2
 *     metadataLine: HStack(spacing metadataGap=4)[Ep N · 今天 · 15:32 (· captions.bubble.fill)] monoLabel(mono 10 bold)
 *       Ep→secondaryText、·→quaternaryText、date→tertiaryText、duration→tertiaryText、bubble→success(iconTiny 10 thin)
 *     (hasProgress) ProgressCapsule(height 3, fill accent, track progressBarBackground=black .07)
 *       .padding(.top, tinyGap=4)
 *   ].frame(maxWidth:∞,.leading)
 *   trailingAccessory（iconSmall 12 medium）.padding(.top, compactRowAccessoryTopInset=2)
 *     play.circle.fill/accent · checkmark.circle.fill/success · lock.fill/tertiaryText · icloud.slash/quaternaryText
 * Row .padding(.vertical compactRowVerticalPadding=10) .padding(.horizontal cardPadding=18)
 *
 * Scene（.fill layout 1179×2556，corner srgba 0,0,0,0 透明）= VStack(spacing 0)[5 rows]
 *   .padding(.vertical)（系統預設 16）.background(pageBackground)。畫布角透明，內容帶 page-bg。
 * → 全 phone-frame 透明捕捉：surface 撐滿、垂直置中 page-bg 內容帶；phone-frame 透明，shots transparent。
 */
export function PodcastEpisodeRowScreen({ scenario: _scenario }: { scenario: ScenarioId<'podcast-episode-row'> }) {
  return (
    <div className="podcast-episode-row-surface">
      <div className="podcast-episode-row-stack">
        {PODCAST_EPISODE_ROW_FIXTURES.map((ep) => (
          <EpisodeRow key={ep.episodeNumber} ep={ep} />
        ))}
      </div>
    </div>
  )
}

function EpisodeRow({ ep }: { ep: EpisodeFixture }) {
  const hasProgress = ep.progressFraction != null && ep.progressFraction > 0
  return (
    <div className="podcast-episode-row">
      <div className="podcast-episode-row-main">
        <div className="podcast-episode-row-title" data-muted={ep.audioAvailable ? undefined : '1'}>
          {ep.title}
        </div>
        <div className="podcast-episode-row-meta">
          <span className="podcast-episode-row-ep">Ep {ep.episodeNumber}</span>
          <span className="podcast-episode-row-sep">·</span>
          <span className="podcast-episode-row-date">{ep.date}</span>
          <span className="podcast-episode-row-sep">·</span>
          <span className="podcast-episode-row-duration">{ep.duration}</span>
          {ep.subtitleAvailable ? (
            <CaptionsBubbleFillIcon className="podcast-episode-row-captions" size={10} />
          ) : null}
        </div>
        {hasProgress ? (
          <div className="podcast-episode-row-progress">
            <div className="podcast-episode-row-progress-fill" style={{ width: `${ep.progressFraction! * 100}%` }} />
          </div>
        ) : null}
      </div>
      <Accessory ep={ep} />
    </div>
  )
}

function Accessory({ ep }: { ep: EpisodeFixture }) {
  switch (ep.accessory) {
    case 'completed':
      return <CheckmarkCircleFillIcon className="podcast-episode-row-accessory accessory-completed" size={12} />
    case 'locked':
      return <LockFillIcon className="podcast-episode-row-accessory accessory-locked" size={12} />
    case 'unavailable':
      return <ICloudSlashIcon className="podcast-episode-row-accessory accessory-unavailable" size={12} />
    default:
      return <PlayCircleFillIcon className="podcast-episode-row-accessory accessory-play" size={12} />
  }
}
