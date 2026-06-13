import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabAccessoryIconButton scenario fixtures — 對齊
 * VocabShellChromeScenarios.swift「Vocab Shell · Accessory Icon Button」。
 * 單一態：systemImage "trash"、tone .red（SwiftUI 系統紅）、a11y「刪除」。
 */
export const VOCAB_ACCESSORY_ICON_BUTTON_FIXTURES: Record<
  ScenarioId<'vocab-accessory-icon-button'>,
  { accessibilityLabel: string }
> = {
  default: { accessibilityLabel: '刪除' },
}
