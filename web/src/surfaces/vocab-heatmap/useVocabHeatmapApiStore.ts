import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import { deriveHeatmapFixture } from './derive'
import type { HeatmapScenario } from './fixtures'

/**
 * API-backed vocab-heatmap store — shell=1 時取代 fixture。從 GET /api/vocab/review-events
 * client-side 衍生活動量 + 自適應強度 thresholds，無新後端 stats endpoint。
 * 語意對齊 iOS ReviewActivityLog.activity + StatsPresentation 自適應分級。
 */

export type VocabHeatmapApiStatus = 'loading' | 'ready' | 'error'

export interface VocabHeatmapApiState {
  status: VocabHeatmapApiStatus
  fixture: HeatmapScenario | null
  retry: () => void
}

export function useVocabHeatmapApiStore(): VocabHeatmapApiState {
  const api = useApi()
  const [status, setStatus] = useState<VocabHeatmapApiStatus>('loading')
  const [fixture, setFixture] = useState<HeatmapScenario | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const res = await api.todayReview.events()
      setFixture(deriveHeatmapFixture(res.entries))
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
