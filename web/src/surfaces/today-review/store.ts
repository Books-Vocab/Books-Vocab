import { useMemo, useState } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import type { ReviewCard, RevealStage } from './fixtures'
import { SESSION_START_INDEX, SESSION_TOTAL, TODAY_REVIEW_FIXTURES, sessionQueue } from './fixtures'

/**
 * Today Review 互動 session store — 薄 in-memory，由 scenario fixture seed。
 *
 * parity 契約：初始狀態（index=SESSION_START_INDEX、reveal=scenario.reveal、
 * forgot/remembered=fixture seed）下，currentCard === scenario.card、progressText
 * === '3 / 12' → DOM 與靜態 PNG 逐像素一致。互動（flip / grade）只在使用者操作後
 * 改變 derived 結果。
 *
 * 推進模型（對齊 iOS TodayReviewSessionState）：flip 切 reveal；grade（答對/答錯）
 * 累計計數並前進 currentIndex；走完佇列 → done 完成態。
 */

export type Grade = 'forgot' | 'remembered'

export interface TodayReviewInteraction {
  /** 目前卡（done 時為最後一張，畫面改顯完成態）。 */
  currentCard: ReviewCard
  reveal: RevealStage
  /** 進度膠囊文字（'<n> / 12'）。 */
  progressText: string
  forgotCount: number
  rememberedCount: number
  /** 是否走完佇列 → 完成態。 */
  done: boolean
  /** 翻卡：front ↔ back。 */
  flip: () => void
  /** 評分：累計 + 前進下一張（走完 → done）。 */
  grade: (g: Grade) => void
}

interface SessionState {
  index: number
  reveal: RevealStage
  forgotCount: number
  rememberedCount: number
  done: boolean
}

export function useTodayReviewStore(scenario: ScenarioId<'today-review'>): TodayReviewInteraction {
  const fixture = TODAY_REVIEW_FIXTURES[scenario]
  const queue = useMemo(() => sessionQueue(scenario), [scenario])

  const [state, setState] = useState<SessionState>({
    index: SESSION_START_INDEX,
    reveal: fixture.reveal,
    forgotCount: fixture.forgotCount,
    rememberedCount: fixture.rememberedCount,
    done: false,
  })

  // queue 以 SESSION_START_INDEX 為 0 偏移：絕對 index → queue 索引。
  const queuePos = state.index - SESSION_START_INDEX
  const currentCard = queue[Math.min(queuePos, queue.length - 1)]

  const flip = () =>
    setState((s) => (s.done ? s : { ...s, reveal: s.reveal === 'front' ? 'back' : 'front' }))

  const grade = (g: Grade) =>
    setState((s) => {
      if (s.done) return s
      const forgotCount = s.forgotCount + (g === 'forgot' ? 1 : 0)
      const rememberedCount = s.rememberedCount + (g === 'remembered' ? 1 : 0)
      const nextIndex = s.index + 1
      // 走完最後一張（index 達 SESSION_TOTAL）→ 完成態。
      if (nextIndex >= SESSION_TOTAL) {
        return { ...s, forgotCount, rememberedCount, done: true }
      }
      return { ...s, index: nextIndex, reveal: 'front', forgotCount, rememberedCount }
    })

  return {
    currentCard,
    reveal: state.reveal,
    // 完成態進度顯示已全數完成（12 / 12）。
    progressText: `${state.done ? SESSION_TOTAL : state.index + 1} / ${SESSION_TOTAL}`,
    forgotCount: state.forgotCount,
    rememberedCount: state.rememberedCount,
    done: state.done,
    flip,
    grade,
  }
}
