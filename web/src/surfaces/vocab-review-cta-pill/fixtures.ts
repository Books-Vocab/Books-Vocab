import type { ComponentType, SVGProps } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { ClockBadgeIcon, PlayFillIcon, SparklesIcon } from './icons'

type GlyphComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

/**
 * VocabReviewCTAPill scenario fixtures — 對齊 VocabShellComponentsScenarios.swift
 * 「Vocab Shell · Review CTA Pill」3 態。pill 內容 = pillLabel(count, systemImage)：
 * HStack(spacing microGap)[Image(systemImage) + Text(count).monospacedDigit()]。
 *   - both types(menu) → play.fill,  count = due + unlearned = 5 + 12 = 17
 *   - due only         → clock.badge, count = due = 5
 *   - unlearned only   → sparkles,    count = unlearned = 8
 */
export const VOCAB_REVIEW_CTA_PILL_FIXTURES: Record<
  ScenarioId<'vocab-review-cta-pill'>,
  { count: number; Icon: GlyphComponent; iconSize: number; ariaLabel: string }
> = {
  'both-types': { count: 17, Icon: PlayFillIcon, iconSize: 15, ariaLabel: '開始複習，共 17 張' },
  'due-only': { count: 5, Icon: ClockBadgeIcon, iconSize: 13, ariaLabel: '開始到期複習，5 張' },
  'unlearned-only': { count: 8, Icon: SparklesIcon, iconSize: 13, ariaLabel: '開始未學複習，8 張' },
}
