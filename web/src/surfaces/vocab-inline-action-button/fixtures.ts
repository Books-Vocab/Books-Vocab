import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabInlineActionButton scenario fixtures — 對齊
 * VocabShellChromeScenarios.swift「Vocab Shell · Inline Action Button」2 態。
 *
 * iOS：`VocabInlineActionButton(title:tone:)` = 純文字 Button
 *   .font(appSkin.typography.body)   // = AppFonts.sans(size:15) → --text-subhead
 *   .foregroundStyle(tone ?? accent) // accent 預設；Toned 傳 Color.secondary
 *
 * - accent-default：title「全部選取」、tone nil → palette.accent。
 * - toned：title「取消」、tone .secondary（SwiftUI 系統 secondary label）
 *   → web --text-secondary。
 */
export const VOCAB_INLINE_ACTION_BUTTON_FIXTURES: Record<
  ScenarioId<'vocab-inline-action-button'>,
  { title: string; tone: 'accent' | 'secondary' }
> = {
  'accent-default': { title: '全部選取', tone: 'accent' },
  toned: { title: '取消', tone: 'secondary' },
}
