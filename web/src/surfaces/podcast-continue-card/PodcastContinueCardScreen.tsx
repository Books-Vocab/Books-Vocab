import type { ComponentType } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { PODCAST_CONTINUE_CARD_FIXTURES, type ContinueCard, type DiscIcon } from './fixtures'
import {
  PlayFillIcon,
  LockFillIcon,
  PersonCropCircleIcon,
  ICloudSlashIcon,
  ChevronRightIcon,
} from './icons'
import './podcast-continue-card.css'

/**
 * PodcastContinueCard surface — iOS `PodcastContinueCard`（PodcastSeriesHero.swift）
 * 的 web 鏡像，series-hero 主 CTA。
 *
 * view tree：HStack(spacing cardPadding=18){
 *   ZStack[Circle().fill(actionable ? brandHero : progressBarBackground) +
 *          Image(discIcon, iconSmall=symbol12)].frame(46×46),
 *   VStack(.leading, spacing tinyGap=4)[ eyebrow(caption sans12 bold) +
 *          title(sectionTitle serif18 bold) + (resume) ProgressCapsule(accent, h3) +
 *          (resume) remaining(monoLabel mono10) ].frame(maxWidth:.infinity,.leading),
 *   Spacer,
 *   Image(chevron.right | lock.fill, iconTiny=symbol10, quaternaryText, opacity actionable?1:.6)
 * }.padding(cardPadding=18).background(RoundedRectangle(lg=12).fill(cardBackground)).appElevation(.z1)
 *
 * catalog scene = .fillH，corner srgba(0,0,0,0) 透明 → component crop（透明畫布）。
 * surface wrapper = scene 的 .padding(s4=16)；gated 變體 = VStack(spacing s4=16) 三卡。
 */

const DISC_ICONS: Record<DiscIcon, ComponentType<{ size?: number; className?: string }>> = {
  play: PlayFillIcon,
  lock: LockFillIcon,
  person: PersonCropCircleIcon,
  'icloud-slash': ICloudSlashIcon,
}

function ContinueCardRow({ card }: { card: ContinueCard }) {
  const DiscIconCmp = DISC_ICONS[card.disc]
  return (
    <div className={`pcc-card${card.actionable ? '' : ' pcc-card-muted'}`}>
      {/* disc：Circle().fill(actionable ? brandHero : progressBarBackground) 46×46 */}
      <div className="pcc-disc">
        <DiscIconCmp size={card.disc === 'play' ? 14 : 16} className="pcc-disc-icon" />
      </div>

      {/* VStack(.leading, spacing tinyGap) */}
      <div className="pcc-body">
        <div className="pcc-eyebrow">{card.eyebrow}</div>
        <div className="pcc-title">{card.title}</div>

        {card.progressFraction > 0 && (
          // ProgressCapsule(accent fill, progressBarBackground track, h3) .padding(.top tinyGap)
          <div className="pcc-progress">
            <div className="pcc-progress-fill" style={{ width: `${card.progressFraction * 100}%` }} />
          </div>
        )}

        {card.remaining && <div className="pcc-remaining">{card.remaining}</div>}
      </div>

      {/* trailing：chevron.right | lock.fill，quaternaryText，opacity actionable?1:.6 */}
      <span className="pcc-trailing">
        {card.navigatesToPlayer ? <ChevronRightIcon size={20} /> : <LockFillIcon size={18} />}
      </span>
    </div>
  )
}

export function PodcastContinueCardScreen({ scenario }: { scenario: ScenarioId<'podcast-continue-card'> }) {
  const { cards } = PODCAST_CONTINUE_CARD_FIXTURES[scenario]
  return (
    <div className="pcc-surface">
      <div className="pcc-stack">
        {cards.map((card, i) => (
          <ContinueCardRow key={i} card={card} />
        ))}
      </div>
    </div>
  )
}
