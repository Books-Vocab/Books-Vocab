/**
 * CollocationExplainSheet catalog 場景資料 — 對應
 * ios/BooksAndVocab/Debug/Scenarios/CollocationExplainScenarios.swift。
 *
 * 三場景皆傳非 nil `existingExplanation` → 同步解析為 `.loaded`，且
 * `existingExplanation != nil` → footer 同時顯示 trash + xmark 兩鈕、無 save。
 * 場景僅以 collocation 標題與 explanation 文字長度區分。
 */

export type CollocationExplainFixture = {
  collocation: string
  explanation: string
}

export const COLLOCATION_EXPLAIN_FIXTURES: Record<string, CollocationExplainFixture> = {
  'loaded-short': {
    collocation: 'take into account',
    explanation: '片語動詞，意為「將……納入考量」，常用於正式決策語境。',
  },
  'loaded-long': {
    collocation: 'come to terms with',
    explanation:
      '此搭配表示「接受並適應某件難以面對的事實或情況」，語氣帶有心理層面的調適過程。常見於描述失去、改變或無法逆轉的處境。例如：to come to terms with one’s mortality（接受自己終將一死）。與單純的 accept 相比，本搭配更強調歷時性的內在和解，而非當下的同意。',
  },
  'loaded-with-delete': {
    collocation: 'on the verge of',
    explanation: '意為「瀕臨、即將……」，後接名詞或動名詞，描述某事即將發生的臨界狀態。',
  },
}
