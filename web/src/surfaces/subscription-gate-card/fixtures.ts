import type { ComponentType, SVGProps } from 'react'
import {
  SparklesIcon,
  GraduationCapFillIcon,
  ClockBadgeCheckmarkIcon,
  HeadphonesIcon,
} from './icons'

type GlyphComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

export interface GateCardFixture {
  icon: GlyphComponent
  /** light-weight stroke glyph 對應 symbolHero light；fill glyph 無 strokeWidth 作用 */
  iconStrokeWidth?: number
  title: string
  description: string
  actionTitle: string
  /** iOS scenario 的 .frame(maxWidth:) — 僅 Narrow width 320pt 設值 */
  maxWidth?: number
}

/**
 * iOS SubscriptionViewsScenarios.swift 的 4 個 GateCardScene。systemImage →
 * 對應 glyph。symbolHero = symbol 44 light，故 stroke glyph 用淡 strokeWidth。
 * Dynamic Type accessibility3 不影響字級（AppFonts 回傳固定 size CTFont，忽略
 * Dynamic Type），故與 Happy path 同字級、僅 icon/copy 不同。
 */
export const SUBSCRIPTION_GATE_CARD_FIXTURES = {
  'happy-path': {
    icon: SparklesIcon,
    title: '解鎖知識圖譜',
    description: '升級至 Pro 即可使用知識圖譜、Today Review 與播客功能。',
    actionTitle: '升級 Pro',
  },
  'long-copy-stress': {
    icon: GraduationCapFillIcon,
    title: '解鎖完整 Pro 學習體驗與全部進階功能',
    description:
      '升級後可無限使用知識圖譜連結推薦、每日 Today Review 排程複習、整本書播客生成、跨裝置同步詞庫，以及未來所有新增的進階學習工具。',
    actionTitle: '立即升級至 Pro 解鎖全部功能',
  },
  'narrow-width-320pt': {
    icon: ClockBadgeCheckmarkIcon,
    iconStrokeWidth: 1.5,
    title: '解鎖 Today Review',
    description: '升級至 Pro 解鎖間隔重複複習排程。',
    actionTitle: '升級 Pro',
    maxWidth: 320,
  },
  'dynamic-type-accessibility3': {
    icon: HeadphonesIcon,
    title: '解鎖播客',
    description: '升級至 Pro 即可把整本書轉成播客。',
    actionTitle: '升級 Pro',
  },
} satisfies Record<string, GateCardFixture>

export type SubscriptionGateCardScenario = keyof typeof SUBSCRIPTION_GATE_CARD_FIXTURES
