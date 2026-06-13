import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { SubscriptionStatusResponse } from '../../api/types'
import { projectSubscription, type SubscriptionView } from './subscriptionProjection'

/**
 * 訂閱權限 API store — shell=1 時取代 fixture。GET /api/user/entitlements → pro，
 * 投影成 SubscriptionView（純資訊；web 無 StoreKit 故無實際購買/恢復 IO）。
 *
 * 由 settings-subscription / paywall 共用（同一 read-only 載入語意）。
 */

export type EntitlementsStatus = 'loading' | 'ready'

export interface EntitlementsApiState {
  status: EntitlementsStatus
  view: SubscriptionView
  /** 原始 pro 狀態（缺則 null）。供需要原欄位的 surface 取用。 */
  pro: SubscriptionStatusResponse | null
}

export function useEntitlementsApiStore(): EntitlementsApiState {
  const api = useApi()
  const [status, setStatus] = useState<EntitlementsStatus>('loading')
  const [pro, setPro] = useState<SubscriptionStatusResponse | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const ent = await api.user.entitlements()
      setPro(ent?.pro ?? null)
    } catch {
      setPro(null)
    } finally {
      setStatus('ready')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  return { status, view: projectSubscription(pro), pro }
}
