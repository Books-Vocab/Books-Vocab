/**
 * Vocab · Add Link fixtures — 逐字對齊 iOS VocabScenarios.swift
 * 「Vocabulary · Add Link」addScenarios 的兩個 Scenario。
 *
 * 關鍵：AddLinkSheet 初始 `searchText == ""`，`filteredEntries` 在空查詢時固定回傳 []，
 * 兩 scene（With candidates / No candidates）渲染當下皆顯示**空查詢空態**
 * （AppEmptyStateContent title「搜尋單字」desc「輸入單字名稱來建立連結」），
 * 與候選清單有無無關 → 兩 scene 視覺等同（catalog 兩 PNG byte-identical 已證實）。
 * 因此 fixture 只需 prompt + 空態文案；candidates 數量僅作語意註記，不影響渲染。
 */

export interface AddLinkFixture {
  /** searchField placeholder — iOS TextField("搜尋單字…") */
  searchPrompt: string
  /** 空查詢空態 title — AppEmptyStateContent(title:"搜尋單字") */
  emptyTitle: string
  /** 空查詢空態 description — AppEmptyStateContent(description:"輸入單字名稱來建立連結") */
  emptyDescription: string
}

const SHARED: AddLinkFixture = {
  searchPrompt: '搜尋單字…',
  emptyTitle: '搜尋單字',
  emptyDescription: '輸入單字名稱來建立連結',
}

export const VOCAB_ADD_LINK_FIXTURES: Record<'with-candidates' | 'no-candidates', AddLinkFixture> = {
  // Scenario("With candidates")：source serendipity + 3 候選；空查詢下仍顯示空態
  'with-candidates': SHARED,
  // Scenario("No candidates")：source serendipity + 0 候選；亦為空態
  'no-candidates': SHARED,
}
