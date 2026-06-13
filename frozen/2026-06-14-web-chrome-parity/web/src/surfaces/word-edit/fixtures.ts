import type { ScenarioId } from '../../harness/scenarios'

/**
 * WordEditSheet fixtures — 逐字鏡像 iOS `WordEditScenarios`（4 個 Scenario）。
 *
 * iOS scene = NavigationStack{ ScrollView{ VStack(sectionGap)[ 2× editSection ] } }
 * over `vocabCanvasBackground()`（page-bg 米色），inline nav title = entry.word（serif）。
 * 每個 editSection = caption(secondary) + bordered card 內 TextEditor(body/primary)。
 *
 * word/translation/explanation 全部逐字對齊 WordEditScenarios.sampleEntry(...)。
 * explanation=nil → 空編輯器（仍渲染 minHeight 卡）。
 */
export interface WordEditFixture {
  /** navigationTitle = entry.word（inline，serif，過長截斷）。 */
  word: string
  /** 翻譯結果編輯器內容（draftTranslation = entry.translation）。 */
  translation: string
  /** 教學筆記編輯器內容（draftExplanation = entry.explanation ?? ""，nil → ''）。 */
  explanation: string
}

export const WORD_EDIT_FIXTURES: Record<
  ScenarioId<'word-edit'>,
  WordEditFixture
> = {
  populated: {
    word: 'serendipity',
    translation: '機緣巧合',
    explanation: '意外發現美好事物的能力；無心插柳的幸運。',
  },
  'empty-explanation': {
    word: 'ephemeral',
    translation: '短暫的',
    explanation: '',
  },
  'long-content-stress': {
    word: 'verisimilitude',
    translation: '逼真；貌似真實的特質，常用於形容文學或藝術作品營造的可信感',
    // iOS: String(repeating: "...", count: 6)
    explanation: '這個詞描述作品在細節與情境上達到的真實感，使讀者願意暫時擱置懷疑。'.repeat(6),
  },
  'long-word-title': {
    word: 'antidisestablishmentarianism',
    translation: '反對廢除國教制度的立場',
    explanation: '一個常被引用為英語中最長單字之一的政治神學名詞。',
  },
}
