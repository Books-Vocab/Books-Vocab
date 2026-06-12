import type { ReactElement } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { REVIEW_BANNER_FIXTURES } from './fixtures'
import { PlayFillIcon, ClockBadgeIcon, SparklesIcon } from './icons'
import './review-banner.css'

/**
 * review-banner surface — iOS `VocabReviewBanner`（複習 CTA banner）+ `DemoBanner`
 * （Demo 模式提示帶）的 web 鏡像。兩組 catalog scene 收進同一 surface：
 *   review-* → 「Banners · Review」（VocabReviewBanner，.fillH 透明卡片 scene）
 *   demo-*   → 「Banners · Demo」（DemoBanner，.fill 不透明全幀 scene）
 *
 * VocabReviewBanner：HStack(center, inlineGap 8)[VStack(microGap 2)[今日複習 sectionTitle(serif 18 bold) +
 *   statsText caption(12) secondaryText] · Spacer · CTA]。.padding(cardPadding 18) +
 *   card 白底 radius card(8)。CTA = AppCompactActionButtonStyle(.primary)：caption(12 semibold) /
 *   fg onBrandHero #1C1A17 / bg+border brandHero #FCDE9A / capsule / pad .h s3=12 .v s2=8。
 *   CTA 內容依狀態：hasBothTypes→「開始複習（54）」play.fill；due-only→「到期複習」clock.badge；
 *   unlearned-only→「未學複習」sparkles。
 *
 * DemoBanner：HStack(s2)[play.circle.fill + 「Demo 模式」caption medium · Spacer · 「結束」caption semibold accent]，
 *   fg secondaryText、.padding(.h pageHorizontalPadding 20 .v s2=8)、bg accent.opacity(0.08)。
 *   .fill scene VStack(0)[DemoBanner, Spacer] 於 pageBackground 全幀；strip 背景延伸至 status bar。
 */
export function ReviewBannerScreen({ scenario }: { scenario: ScenarioId<'review-banner'> }) {
  const fixture = REVIEW_BANNER_FIXTURES[scenario]

  if (fixture.kind === 'demo') {
    return (
      <div className="rb-demo-surface">
        <div className="rb-demo-strip">
          <span className="rb-demo-icon">
            <PlayCircleFill />
          </span>
          <span className="rb-demo-label">Demo 模式</span>
          <span className="rb-demo-spacer" />
          {/* i18n-allow: catalog scene 逐字對齊 iOS DemoBanner */}
          <span className="rb-demo-exit">結束</span>
        </div>
      </div>
    )
  }

  const { dueCount, unlearnedCount } = fixture
  const total = dueCount + unlearnedCount
  const hasBoth = dueCount > 0 && unlearnedCount > 0

  let ctaText: string
  let CtaIcon: (props: { size?: number; className?: string }) => ReactElement
  if (hasBoth) {
    ctaText = `開始複習（${total}）`
    CtaIcon = PlayFillIcon
  } else if (dueCount > 0) {
    ctaText = '到期複習'
    CtaIcon = ClockBadgeIcon
  } else {
    ctaText = '未學複習'
    CtaIcon = SparklesIcon
  }

  return (
    <div className="rb-component-surface">
      <div className="rb-card">
        <div className="rb-text">
          <div className="rb-title">今日複習</div>
          <div className="rb-stats">
            {dueCount > 0 && <span>{`${dueCount} 張到期`}</span>}
            {hasBoth && <span>·</span>}
            {unlearnedCount > 0 && <span>{`${unlearnedCount} 未學習`}</span>}
          </div>
        </div>
        <span className="rb-spacer" />
        <span className="rb-cta">
          <CtaIcon className="rb-cta-icon" size={12} />
          <span className="rb-cta-label">{ctaText}</span>
        </span>
      </div>
    </div>
  )
}

/** SF `play.circle.fill` — DemoBanner leading（caption medium / secondaryText）。 */
function PlayCircleFill() {
  return (
    <svg viewBox="0 0 24 24" width={13} height={13} fill="currentColor" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.5 7.6v8.8l7-4.4z" fill="var(--page-bg)" />
    </svg>
  )
}
