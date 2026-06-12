import type { ScenarioId } from '../../harness/scenarios'

/** VocabHighlightColorPreset — swatch 色用 iOS `swiftUIColor(for: .light)`（Color(red:green:blue:)
 *  字面值；非 reader band 的 cssColor）。label = zh-Hant Localizable。 */
export interface HighlightPreset {
  key: 'paper' | 'blue' | 'sage' | 'rose'
  label: string
  /** swiftUIColor(for: .light) — rgb(round(c×255))。無 DS token（highlight 專屬）。 */
  color: string
}

export const HIGHLIGHT_PRESETS: HighlightPreset[] = [
  { key: 'paper', label: '紙色', color: 'rgb(230, 214, 145)' }, // Color(0.90,0.84,0.57)
  { key: 'blue', label: '藍色', color: 'rgb(77, 115, 150)' }, //  Color(0.30,0.45,0.59)
  { key: 'sage', label: '鼠尾草', color: 'rgb(107, 145, 105)' }, // Color(0.42,0.57,0.41)
  { key: 'rose', label: '玫瑰', color: 'rgb(179, 115, 133)' }, // Color(0.70,0.45,0.52)
]

/**
 * Vocab · Highlight Picker fixtures — 對齊 VocabHighlightPickerScenarios.swift。
 * picker 永遠顯示 4 個 preset tile；scenario 只決定哪個 selected（selection chrome）。
 * Dark mode scene deferred（catalog .preferredColorScheme(.dark) 語意未定，見 dark 探測）。
 */
export const VOCAB_HIGHLIGHT_PICKER_FIXTURES: Record<ScenarioId<'vocab-highlight-picker'>, HighlightPreset['key']> = {
  'paper-selected': 'paper',
  'blue-selected': 'blue',
  'sage-selected': 'sage',
  'rose-selected': 'rose',
}
