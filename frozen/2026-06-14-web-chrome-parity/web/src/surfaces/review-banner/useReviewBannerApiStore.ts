import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { deriveReviewBannerCounts, type ReviewBannerCounts } from './derive'

/**
 * API-backed review-banner store — shell=1 時取代 fixture。從 GET /api/vocab
 * （cards 帶 SRS 狀態 reviewCount / nextReviewAt）client-side 衍生 due/unlearned
 * 計數，無新後端 stats endpoint。語意對齊 iOS NotebookStatsCalculator。
 */

export type ReviewBannerApiStatus = 'loading' | 'ready' | 'error'

export interface ReviewBannerApiState extends ReviewBannerCounts {
  status: ReviewBannerApiStatus
  retry: () => void
}

export function useReviewBannerApiStore(notebookId: string | null): ReviewBannerApiState {
  const api = useApi()
  const [status, setStatus] = useState<ReviewBannerApiStatus>('loading')
  const [counts, setCounts] = useState<ReviewBannerCounts>({ dueCount: 0, unlearnedCount: 0 })

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const cards = await api.vocabulary.list(notebookId ? { notebookId } : {})
      setCounts(deriveReviewBannerCounts(cards))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  return { status, ...counts, retry: load }
}
