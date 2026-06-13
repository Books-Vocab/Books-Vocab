import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import {
  adjustParam,
  clockConfigFromState,
  fixtureFromState,
  modeConfigFromState,
  stateFromConfig,
  type ReviewSettingsState,
} from './derive'
import type { ReviewFixture, ReviewMode } from './fixtures'

/**
 * API-backed settings-review store — shell=1 時取代 fixture。GET /api/user/config 讀
 * review_mode + review_clock，PUT /api/user/config 寫回。互動（pause toggle / mode 選擇 /
 * custom 參數 stepper）全走樂觀更新 + push + 失敗 rollback，對齊 iOS coordinator 一條龍。
 */

export type SettingsReviewApiStatus = 'loading' | 'ready' | 'error'

type ParamKey = Parameters<typeof adjustParam>[1]

export interface SettingsReviewApiState {
  status: SettingsReviewApiStatus
  fixture: ReviewFixture | null
  retry: () => void
  togglePause: () => void
  selectMode: (mode: ReviewMode) => void
  stepParam: (key: ParamKey, direction: 'inc' | 'dec') => void
}

const STEP: Record<ParamKey, number> = {
  customInitialIntervalHours: 4,
  customRememberedMultiplier: 0.1,
  customForgotMultiplier: 0.05,
  customMinimumIntervalHours: 2,
  customMaximumIntervalHours: 120,
}

export function useSettingsReviewApiStore(): SettingsReviewApiState {
  const api = useApi()
  const [status, setStatus] = useState<SettingsReviewApiStatus>('loading')
  const [state, setState] = useState<ReviewSettingsState | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const config = await api.user.config()
      setState(stateFromConfig(config.review_mode, config.review_clock))
      setStatus('ready')
    } catch {
      setStatus('error')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  /**
   * 樂觀套用：以 transform 從目前 state 算出 next，單一 setState 內套用 next 並 fire
   * 對應 config 子組的 PUT；失敗則 rollback 回 prev。透過 functional updater 取最新
   * prev，避免 stale closure；push 在 updater 內 fire 屬於受控副作用（非渲染期 set）。
   */
  const optimistic = useCallback(
    (transform: (prev: ReviewSettingsState) => ReviewSettingsState, scope: 'mode' | 'clock') => {
      setState((prev) => {
        if (!prev) return prev
        const next = transform(prev)
        const patch =
          scope === 'mode'
            ? { review_mode: modeConfigFromState(next) }
            : { review_clock: clockConfigFromState(next) }
        api.user.updateConfig(patch).catch(() => {
          setState(prev)
        })
        return next
      })
    },
    [api],
  )

  const togglePause = useCallback(() => {
    optimistic((prev) => {
      const willPause = !prev.isPaused
      // pause：若無錨點則設 now（對齊 iOS pauseProgress）；resume：清錨點。
      return {
        ...prev,
        isPaused: willPause,
        pausedAt: willPause ? (prev.pausedAt ?? new Date().toISOString()) : null,
      }
    }, 'clock')
  }, [optimistic])

  const selectMode = useCallback(
    (mode: ReviewMode) => {
      optimistic((prev) => ({ ...prev, mode }), 'mode')
    },
    [optimistic],
  )

  const stepParam = useCallback(
    (key: ParamKey, direction: 'inc' | 'dec') => {
      const delta = direction === 'inc' ? STEP[key] : -STEP[key]
      optimistic((prev) => adjustParam(prev, key, delta), 'mode')
    },
    [optimistic],
  )

  return {
    status,
    fixture: state ? fixtureFromState(state) : null,
    retry: load,
    togglePause,
    selectMode,
    stepParam,
  }
}
