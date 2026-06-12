import type { ScenarioId } from '../../harness/scenarios'

/**
 * LinkedCardOverlayStack fixtures — 鏡像 iOS `VocabScenarios` 的 `Vocabulary · Linked Card`。
 *
 * catalog 在 snapshot 下渲染的是 `WordDetailSheet` 的「載入中」placeholder（presenterState
 * 尚未在 Task.yield 後算出），所以每張卡的內容固定為 `VocabStateMessageCard(載入中 + ProgressView)`，
 * 而非完整 WordDetail。因此 fixture 只需描述「疊幾層」即可：
 *   - single → 1 層（index 0：header「Linked Card」，無 badge）
 *   - stacked → 3 層（index 0 後底、index 1「Nested Link +1」、index 2「Nested Link +2」最前）
 *
 * header 標題規則逐字對齊 iOS `LinkedCardOverlayStack.linkedCardLayer`：
 *   title = index == 0 ? "Linked Card" : "Nested Link"；badge = index > 0 ? "+\(index)" : nil。
 */
export interface LinkedCardFixture {
  /** 疊層數 = stack.count（iOS sampleEntry 數量）。 */
  depth: number
}

export const VOCAB_LINKED_CARD_FIXTURES: Record<
  ScenarioId<'vocab-linked-card'>,
  LinkedCardFixture
> = {
  'single-card': { depth: 1 },
  'stacked-3-deep': { depth: 3 },
}
