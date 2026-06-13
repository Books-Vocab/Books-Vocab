import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabSliderRow scenario fixtures — 對齊 VocabShellChromeScenarios.swift
 * 「Vocab Shell · Slider Row」的唯一 scene：
 *   VocabSliderRow(label: "間隔", value: $0.6, range: 0...1, format: "%.1f")
 * valueText = String(format: "%.1f", 0.6) = "0.6"。
 */
export const VOCAB_SLIDER_ROW_FIXTURES: Record<
  ScenarioId<'vocab-slider-row'>,
  { label: string; value: number; range: [number, number]; valueText: string }
> = {
  interactive: { label: '間隔', value: 0.6, range: [0, 1], valueText: '0.6' },
}
