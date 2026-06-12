import type { ScenarioId } from '../../harness/scenarios'

/**
 * LinkReasonSheet fixtures — 鏡像 iOS `LinkReasonSheetScenarios` 的合成
 * `KGCardLinkSummary`（label + word + reason）+ onHide 有無。
 *
 * label/word/reason 逐字對齊 iOS scenarios（forestall/deft/schadenfreude/laconic）；
 * withHide=false 僅「No hide action」場景（onHide=nil → 不顯示「隱藏此連結」鈕）。
 */
export interface LinkReasonFixture {
  /** link.label.localized — header caption（如「相似用法」）。 */
  label: string
  /** link.word — detailWord mono 標題。 */
  word: string
  /** link.reason — body 解釋；空字串 = Empty reason 邊界。 */
  reason: string
  /** onHide != nil → 顯示 destructive「隱藏此連結」ghost 鈕。 */
  withHide: boolean
}

const MEDIUM_REASON =
  '兩個單字都帶有「預先採取行動以阻止某事發生」的語意，常出現在談判、政策與風險管理的語境中，可互相對照記憶。'

const LONG_REASON =
  '兩者都描述「他人不幸所引發的情緒反應」，但細微差異值得注意：前者源自德語 Schaden（傷害）+ Freude（喜悅），強調看到他人受挫時心中浮現的隱密快感；後者則偏向中性的旁觀情緒，不必然帶有惡意。理解這條連結有助於在閱讀文學評論、心理學文本與社會議題討論時，準確掌握作者的情感立場與修辭意圖，並避免在翻譯時誤把幸災樂禍的貶義色彩抹平成中立描述。'

export const LINK_REASON_SHEET_FIXTURES: Record<
  ScenarioId<'link-reason-sheet'>,
  LinkReasonFixture
> = {
  'medium-reason': { label: '相似用法', word: 'forestall', reason: MEDIUM_REASON, withHide: true },
  'short-reason': { label: '同義詞', word: 'deft', reason: '皆指動作靈巧。', withHide: true },
  'long-reason': { label: '相關概念', word: 'schadenfreude', reason: LONG_REASON, withHide: true },
  'no-hide': { label: '相似用法', word: 'forestall', reason: MEDIUM_REASON, withHide: false },
  'empty-reason': { label: '相似用法', word: 'laconic', reason: '', withHide: true },
}
