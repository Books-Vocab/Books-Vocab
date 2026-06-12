import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabSectionHeader scenario fixtures — 對齊 VocabShellChromeScenarios.swift
 * 「Vocab Shell · Section Header」2 態（.fillH 滿寬列）。
 *   title-only       → VocabSectionHeader(title: "已收錄")
 *   icon-trailing    → VocabSectionHeader(title:"待複習", systemImage:"clock.badge",
 *                                          trailingText:"5")
 */
export const VOCAB_SECTION_HEADER_FIXTURES: Record<
  ScenarioId<'vocab-section-header'>,
  { title: string; icon: boolean; trailingText?: string }
> = {
  'title-only': { title: '已收錄', icon: false },
  'icon-trailing': { title: '待複習', icon: true, trailingText: '5' },
}
