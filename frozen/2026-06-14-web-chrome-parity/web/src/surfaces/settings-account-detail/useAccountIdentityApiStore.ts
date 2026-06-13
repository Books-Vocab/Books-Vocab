import { useCallback, useEffect, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import type { SubscriptionStatusResponse, UserProfileResponse } from '../../api/types'

/**
 * 帳號身分 API store — shell=1 時取代 fixture。
 *
 * 來源：GET /api/user/profile（id / email / display_name；NEW backend，目前由 mock
 * 持有契約）+ GET /api/user/entitlements（Pro 狀態）。settings-account-detail /
 * account-auth-summary / account-section 三 surface 共用同一身分讀取，故抽 pure 投影
 * + 共用 hook。
 */

export interface AccountIdentity {
  isLoggedIn: boolean
  userId: string | null
  displayName: string
  /** null = 無 email（顯示時隱藏該列）。 */
  email: string | null
  initials: string
  isPro: boolean
}

const GUEST: AccountIdentity = {
  isLoggedIn: false,
  userId: null,
  displayName: '訪客',
  email: null,
  initials: '?',
  isPro: false,
}

/**
 * 純函式：從 display_name / email 推導頭像 initials。
 *   - 含空白的名字取每段首字（最多 2 段）
 *   - 單段名字取前 2 字（涵蓋 CJK 單字名只回 1 字）
 *   - 皆缺則退到 email 本地端首字，再退 '?'
 * 匯出供測試。
 */
export function initialsFor(displayName: string | null, email: string | null): string {
  const name = (displayName ?? '').trim()
  if (name.length > 0) {
    const parts = name.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase()
    }
    // 單段：CJK 取單字，拉丁取前兩字。
    const first = parts[0]
    if (/^[\x00-\x7F]+$/.test(first)) {
      return first.slice(0, 2).toUpperCase()
    }
    return Array.from(first)[0]
  }
  const local = (email ?? '').split('@')[0]
  if (local.length > 0) return local.slice(0, 2).toUpperCase()
  return '?'
}

/**
 * 純函式：profile + pro → AccountIdentity。profile=null（未登入 / 取不到）→ 訪客。
 * 匯出供測試。
 */
export function projectIdentity(
  profile: UserProfileResponse | null,
  pro: SubscriptionStatusResponse | null,
): AccountIdentity {
  if (!profile) return GUEST
  const displayName = profile.display_name?.trim() || profile.email?.split('@')[0] || '使用者'
  const email = profile.email ?? null
  return {
    isLoggedIn: true,
    userId: profile.user_id,
    displayName,
    email,
    initials: initialsFor(profile.display_name, email),
    isPro: pro?.is_active ?? false,
  }
}

export type AccountIdentityStatus = 'loading' | 'ready'

export interface AccountIdentityApiState {
  status: AccountIdentityStatus
  identity: AccountIdentity
}

export function useAccountIdentityApiStore(): AccountIdentityApiState {
  const api = useApi()
  const [status, setStatus] = useState<AccountIdentityStatus>('loading')
  const [profile, setProfile] = useState<UserProfileResponse | null>(null)
  const [pro, setPro] = useState<SubscriptionStatusResponse | null>(null)

  const load = useCallback(async () => {
    setStatus('loading')
    try {
      const [p, ent] = await Promise.all([
        api.user.profile(),
        api.user.entitlements().catch(() => null),
      ])
      setProfile(p)
      setPro(ent?.pro ?? null)
    } catch {
      setProfile(null)
      setPro(null)
    } finally {
      setStatus('ready')
    }
  }, [api])

  useEffect(() => {
    load()
  }, [load])

  return { status, identity: projectIdentity(profile, pro) }
}
