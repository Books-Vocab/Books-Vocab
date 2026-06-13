import type { ScenarioId } from '../../harness/scenarios'

/**
 * VocabSearchField scenario fixtures — 對齊 VocabShellChromeScenarios.swift
 * 「Vocab Shell · Search Field」2 態。`VocabSearchField(text:prompt:)`，prompt
 * 恆為「搜尋單字」；text 空 → 顯示 prompt + 無 clear button；text 非空 → 顯示
 * query 文字 + trailing clear button（xmark.circle.fill）。
 */
export const VOCAB_SEARCH_FIELD_FIXTURES: Record<
  ScenarioId<'vocab-search-field'>,
  { text: string; prompt: string }
> = {
  empty: { text: '', prompt: '搜尋單字' },
  'with-query': { text: 'serendipity', prompt: '搜尋單字' },
}
