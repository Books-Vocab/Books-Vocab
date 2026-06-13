import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { CardResponse, ReviewEventEntry, ReviewStateEntry } from '../../api/types'
import type { ReviewCard, RevealStage } from './fixtures'
import type { Grade, TodayReviewInteraction } from './store'

/**
 * API-backed today-review store — 當 shell=1 時取代 fixture-driven useTodayReviewStore。
 * 從後端 GET /api/vocab?notebook_id=xxx 拉取卡片，篩出 due 卡建 review queue。
 * Grade 本地推進，session 結束後批次 submit review events + state。
 */

export type TodayReviewApiStatus = 'loading' | 'ready' | 'error'

export interface TodayReviewApiState extends TodayReviewInteraction {
  status: TodayReviewApiStatus
  retry: () => void
}

/** 把 CardResponse 轉成 ReviewCard（fixture 形狀）。 */
function toReviewCard(card: CardResponse): ReviewCard {
  const mode: ReviewCard['mode'] = card.mode === 'production' ? 'production' : 'recognition'
  return {
    mode,
    word: card.content,
    translation: card.meaning,
    partOfSpeech: card.pos ? `${card.pos}.` : null,
    difficultyTier: card.difficultyTier,
    links: Object.entries(card.linksByKind).map(([label, items]) => ({
      label,
      words: items.slice(0, 2).map((i) => i.word),
      overflowCount: Math.max(0, items.length - 2),
    })),
    exampleBack: card.examples.length > 0
      ? [{ text: card.examples[0]!, mark: true }]
      : [],
    exampleFront: mode === 'production' && card.examples.length > 0
      ? [{ text: '…' }, { blank: true, text: '______' }, { text: '…' }]
      : [],
    explanation: card.note ?? '（尚無詳細釋義）',
  }
}

export function useTodayReviewApiStore(notebookId: string | null): TodayReviewApiState {
  const api = useApi()
  const [status, setStatus] = useState<TodayReviewApiStatus>('loading')
  const [queue, setQueue] = useState<ReviewCard[]>([])
  const [index, setIndex] = useState(0)
  const [reveal, setReveal] = useState<RevealStage>('front')
  const [forgotCount, setForgotCount] = useState(0)
  const [rememberedCount, setRememberedCount] = useState(0)
  const [done, setDone] = useState(false)
  // 累積 review events 待 session 結束後批次送出
  const [pendingEvents, setPendingEvents] = useState<ReviewEventEntry[]>([])
  const [pendingState, setPendingState] = useState<ReviewStateEntry[]>([])

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const cards = await api.todayReview.queue(notebookId ? { notebookId } : {})
      // 篩出 due 卡：reviewCount=0（unlearned）或 nextReviewAt 已過期
      const now = new Date()
      const dueCards = cards.filter((c) => {
        if (c.reviewCount === 0) return true
        if (!c.nextReviewAt) return true
        return new Date(c.nextReviewAt) <= now
      })
      setQueue(dueCards.map(toReviewCard))
      setIndex(0)
      setReveal('front')
      setForgotCount(0)
      setRememberedCount(0)
      setDone(false)
      setPendingEvents([])
      setPendingState([])
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  const currentCard = queue[Math.min(index, queue.length - 1)] ?? queue[0]
  const total = queue.length

  const flip = useCallback(() => {
    if (done) return
    setReveal((r) => (r === 'front' ? 'back' : 'front'))
  }, [done])

  const grade = useCallback((g: Grade) => {
    if (done || !currentCard) return
    const isForgot = g === 'forgot'
    const nextForgot = forgotCount + (isForgot ? 1 : 0)
    const nextRemembered = rememberedCount + (isForgot ? 0 : 1)
    const nextIndex = index + 1

    // 累積 event + state（批次送出）
    const nowIso = new Date().toISOString()
    const eventId = `evt-${currentCard.word}-${index}-${Date.now()}`
    const feedback = isForgot ? 0 : 1

    setPendingEvents((prev) => [
      ...prev,
      {
        event_id: eventId,
        card_id: null,
        word_snapshot: currentCard.word,
        notebook_id: notebookId ?? 'default',
        feedback,
        reviewed_at: nowIso,
        created_at: nowIso,
        is_synthetic: false,
      },
    ])

    setPendingState((prev) => [
      ...prev,
      {
        word: currentCard.word,
        review_interval_hours: 12, // 簡化：後端會重算
        next_review_at: nowIso,    // 簡化：後端會重算
        last_reviewed_at: nowIso,
        review_count: 1,
        lapse_count: isForgot ? 1 : 0,
        review_streak: isForgot ? 0 : 1,
        last_review_feedback: feedback,
      },
    ])

    if (nextIndex >= total) {
      setDone(true)
      setForgotCount(nextForgot)
      setRememberedCount(nextRemembered)
      // session 結束：批次送出
      api.todayReview.submitEvents({ entries: [...pendingEvents, {
        event_id: eventId,
        card_id: null,
        word_snapshot: currentCard.word,
        notebook_id: notebookId ?? 'default',
        feedback,
        reviewed_at: nowIso,
        created_at: nowIso,
        is_synthetic: false,
      }] }).catch(() => { /* silent fail; events are best-effort */ })
      api.todayReview.submitState({ entries: [...pendingState, {
        word: currentCard.word,
        review_interval_hours: 12,
        next_review_at: nowIso,
        last_reviewed_at: nowIso,
        review_count: 1,
        lapse_count: isForgot ? 1 : 0,
        review_streak: isForgot ? 0 : 1,
        last_review_feedback: feedback,
      }] }).catch(() => { /* silent fail */ })
    } else {
      setIndex(nextIndex)
      setReveal('front')
      setForgotCount(nextForgot)
      setRememberedCount(nextRemembered)
    }
  }, [api, currentCard, done, forgotCount, index, notebookId, pendingEvents, pendingState, rememberedCount, total])

  return {
    status,
    currentCard,
    reveal,
    progressText: `${done ? total : index + 1} / ${total}`,
    forgotCount,
    rememberedCount,
    done,
    flip,
    grade,
    retry: load,
  }
}
