import type { CardResponse } from '../../api/types'

/**
 * review-banner 計數的純衍生 — 鏡像 iOS `NotebookStatsCalculator.compute`
 * (ios/.../Components/NotebookStatsCalculator.swift) 的 due/unlearned 分支：
 *   dueCount       = reviewCount > 0 && nextReviewAt <= now
 *   unlearnedCount = reviewCount == 0
 *   （reviewCount > 0 但未到期 = 已學習未到期，兩者皆不計）
 *
 * 注意：此「due」語意與 today-review queue 的 due 篩選**不同** — banner 只把
 * 「已學過且已到期」算 due，未學卡單獨歸 unlearned；today-review queue 兩者都進佇列。
 * 兩者皆刻意對齊各自的 iOS 來源（NotebookStatsCalculator vs TodayReview filter）。
 */
export interface ReviewBannerCounts {
  dueCount: number
  unlearnedCount: number
}

export function deriveReviewBannerCounts(
  cards: CardResponse[],
  now: Date = new Date(),
): ReviewBannerCounts {
  let dueCount = 0
  let unlearnedCount = 0
  const nowMs = now.getTime()
  for (const card of cards) {
    // archived / deleted 卡不該膨脹複習計數（對齊 shouldAppearInKnowledgeList）。
    if (card.isArchived || card.isDeleted) continue
    if (card.reviewCount > 0) {
      const next = card.nextReviewAt ? new Date(card.nextReviewAt).getTime() : nowMs
      if (next <= nowMs) dueCount += 1
    } else {
      unlearnedCount += 1
    }
  }
  return { dueCount, unlearnedCount }
}
