import type { CSSProperties } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { SUBSCRIPTION_GATE_CARD_FIXTURES, type GateCardFixture } from './fixtures'
import './subscription-gate-card.css'

/**
 * Subscription Views · Gate Card surface — iOS `ProAccessGateCard`
 * （SubscriptionViews.swift）的 web 鏡像。
 *
 * iOS view tree（GateCardScene → ProAccessGateCard）：
 *   AppThemeContainer > ProAccessGateCard.frame(maxWidth: maxWidth).padding()
 *     .frame(maxWidth:∞,maxHeight:∞).background(pageBackground)
 *   ProAccessGateCard = VocabCard {            // AppSectionCard .vocab(skin)
 *     VStack(spacing: s4=16) {
 *       Image(systemImage).font(symbolHero=symbol44 light).foregroundStyle(accent)
 *       VStack(spacing: 6=microGap) {
 *         Text(title).font(sectionTitle=serif18 bold).foregroundStyle(primaryText)
 *         Text(desc).font(body=sans15).foregroundStyle(secondaryText)
 *           .multilineTextAlignment(.center).lineSpacing(4)
 *       }
 *       Button { Text(actionTitle).font(body.weight(.medium))
 *                  .frame(maxWidth:∞).padding(.v, rowContentSpacing=12) }
 *         .buttonStyle(.vocabAction(.primary))   // fg=pageBg, bg=primaryText,
 *                                                // border=primaryText, radius=control(6),
 *                                                // pad .h 16 .v 13
 *     }.padding(.v, inlineGap=8)
 *   }
 *   VocabCard chrome：padding cardPadding(18) · bg cardBackground · radius card(8)
 *                     · border cardBorder@0.7 1px · elevation z1
 *
 * catalog scene layout = .fillH（高度緊裁、寬度為裝置幀）：corner = page-bg
 * srgba(247,246,243,1) 不透明 → 元件級 crop（crop=component），surface = scene
 * 的 .padding(16) intrinsic box（撐滿 frame 寬、page-bg 背景），shots 截 surface DOM。
 * 非透明、bg = page-bg token。
 */
export function SubscriptionGateCardScreen({
  scenario,
}: {
  scenario: ScenarioId<'subscription-gate-card'>
}) {
  const fx: GateCardFixture = SUBSCRIPTION_GATE_CARD_FIXTURES[scenario]
  const Icon = fx.icon
  return (
    <div className="subscription-gate-card-surface">
      <div
        className="subscription-gate-card"
        style={fx.maxWidth ? ({ maxWidth: `${fx.maxWidth}px` } as CSSProperties) : undefined}
      >
        <div className="subscription-gate-card-stack">
          <Icon
            className="subscription-gate-card-icon"
            size={44}
            strokeWidth={fx.iconStrokeWidth ?? 1.5}
          />
          <div className="subscription-gate-card-text">
            <div className="subscription-gate-card-title">{fx.title}</div>
            <div className="subscription-gate-card-description">{fx.description}</div>
          </div>
          <button type="button" className="subscription-gate-card-action">
            <span className="subscription-gate-card-action-label">{fx.actionTitle}</span>
          </button>
        </div>
      </div>
    </div>
  )
}
