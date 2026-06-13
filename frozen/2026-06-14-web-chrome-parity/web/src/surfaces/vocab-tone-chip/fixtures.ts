import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabToneChip scenario fixtures — 對齊 VocabComponentScenarios.swift
 * 「Vocab Components · Tone Chip」2 態。
 *
 * tone = SwiftUI 系統色（Color.blue/.green/.red/.purple/.indigo），文字用該 tone
 * 全色、背景用 tone.opacity(0.08)。這些是平台系統色，無 AppColors provenance，
 * 以 --tone-* design token 承載（light 模式 canonical 值）。
 *
 * - Variants：VStack(alignment:.leading, spacing:16) 4 chips（blue/green/red/purple）
 * - Long text：單一 chip（indigo），長文字驗證 capsule 隨內容延展
 */
type Tone = 'blue' | 'green' | 'red' | 'purple' | 'indigo'

export const VOCAB_TONE_CHIP_FIXTURES: Record<
  ScenarioId<'vocab-tone-chip'>,
  { chips: { text: string; tone: Tone }[] }
> = {
  variants: {
    chips: [
      { text: '正式', tone: 'blue' },
      { text: '口語', tone: 'green' },
      { text: '貶義', tone: 'red' },
      { text: '文學', tone: 'purple' },
    ],
  },
  'long-text': {
    chips: [{ text: '正式而帶有書面語色彩的語氣', tone: 'indigo' }],
  },
}
