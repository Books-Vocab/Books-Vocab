import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { deriveForecastBuckets } from './derive'
import type { ForecastBucket } from './fixtures'

/**
 * API-backed vocab-forecast store — shell=1 時取代 fixture。從 GET /api/vocab
 * （cards 帶 nextReviewAt）client-side 衍生 14 日複習排程預測桶，無新後端 stats endpoint。
 * 語意對齊 iOS StatsPresentation.buildSummary forecast。
 */

export type VocabForecastApiStatus = 'loading' | 'ready' | 'error'

export interface VocabForecastApiState {
  status: VocabForecastApiStatus
  buckets: ForecastBucket[]
  retry: () => void
}

export function useVocabForecastApiStore(notebookId: string | null): VocabForecastApiState {
  const api = useApi()
  const [status, setStatus] = useState<VocabForecastApiStatus>('loading')
  const [buckets, setBuckets] = useState<ForecastBucket[]>([])

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const cards = await api.vocabulary.list(notebookId ? { notebookId } : {})
      setBuckets(deriveForecastBuckets(cards))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api, notebookId])

  useEffect(() => {
    load()
  }, [load])

  return { status, buckets, retry: load }
}
