import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabSortPill scenario fixtures — 對齊 VocabShellComponentsScenarios.swift
 * 「Vocab Shell · Sort Pill」3 態。label = KGVocabSortOption.label（pill 只顯示
 * 當前選項，icon 恆為 arrow.up.arrow.down）。
 */
export const VOCAB_SORT_PILL_FIXTURES: Record<ScenarioId<'vocab-sort-pill'>, { label: string }> = {
  default: { label: '複習優先' },
  alphabetical: { label: '字母序' },
  difficulty: { label: '難度' },
}
