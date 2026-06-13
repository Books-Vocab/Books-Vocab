import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { deriveCalendarFixture } from './derive'
import type { CalendarFixture } from './fixtures'

/**
 * API-backed vocab-calendar store — shell=1 時取代 fixture。從 GET /api/vocab/review-events
 * （複習活動 log）client-side 衍生「當月」每日活動量，無新後端 stats endpoint。
 * 語意對齊 iOS ReviewActivityLog.activity。
 */

export type VocabCalendarApiStatus = 'loading' | 'ready' | 'error'

export interface VocabCalendarApiState {
  status: VocabCalendarApiStatus
  fixture: CalendarFixture | null
  retry: () => void
}

export function useVocabCalendarApiStore(): VocabCalendarApiState {
  const api = useApi()
  const [status, setStatus] = useState<VocabCalendarApiStatus>('loading')
  const [fixture, setFixture] = useState<CalendarFixture | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const res = await api.todayReview.events()
      setFixture(deriveCalendarFixture(res.entries))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  return { status, fixture, retry: load }
}
