import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { motion } from 'framer-motion'
import { Sheet, snappy, usePreferredTransition } from '../../motion'
import type { ScenarioId } from '../../harness/scenarios'
import { useAppearance } from '../../harness/appearance'
import { useApi } from '../../api/ApiContext'
import type { QuotaResponse, SubscriptionStatusResponse, UserConfigResponse } from '../../api/types'
import { appearanceFromConfig, buildAppearancePatch, type AppearancePref } from './appearanceConfig'
import appIconUrl from '../../assets/app_icon.png'
import { SETTINGS_FIXTURES, PREFERENCE_ROWS, EXTERNAL_ROWS } from './fixtures'
import type { LoggedInAccount, LoggedOutAccount } from './fixtures'
import { useAuth } from '../../auth'
import {
  AppearanceIcon,
  AppleLogoIcon,
  CheckCircleFillIcon,
  ChevronRightIcon,
  DocTextIcon,
  EllipsisCircleIcon,
  HandRaisedIcon,
  LanguageBubbleIcon,
  PersonCircleIcon,
  QuestionCircleIcon,
  SealCheckFillIcon,
  SlidersIcon,
  SparklesIcon,
  StarIcon,
  SyncIcon,
  TimerIcon,
  TranslateIcon,
} from './icons'
import { useShellNav } from '../../shell/ShellNavContext'
import { pushTargetFor, screenFor, type NavIntent } from '../../shell/nav'
import './settings.css'
import './interactive.css'

/**
 * Settings surface — iOS SettingsView/SettingsPresenter 的 web 重寫，現為互動版。
 * 幾何常數逐一對齊 iOS（見 settings.css 的 px 註解）；結構順序 =
 * SettingsPresenter.swift：帳號 → 偏好 → 其他。
 *
 * 互動層（fixtures 當資料層、in-memory store、無持久化）：
 *   - 自動同步 toggle：真切換（樂觀本地 state + 膠囊色帶動畫）
 *   - 外觀 light/dark：即時改 phone-frame data-theme（AppearanceContext）
 *   - 選單列點擊（外觀/語言/翻譯語言/複習節奏）：開簡單浮層 sheet
 *   - 登入/登出：在 fixtures 雙態間切換（logged-in subscribed ↔ logged-out）
 *
 * **Parity 不變式**：所有互動 state 初值 = 該 scenario 的 fixture 形狀，故 capture
 * URL 的首次渲染 DOM / 像素與靜態版相同；只有使用者手勢後才變。
 */

const PREFERENCE_ICONS = {
  外觀: AppearanceIcon,
  翻譯語言: TranslateIcon,
  語言: LanguageBubbleIcon,
  複習節奏: TimerIcon,
} as const

const EXTERNAL_ICONS = {
  隱私政策: HandRaisedIcon,
  服務條款: DocTextIcon,
  支援: QuestionCircleIcon,
  '為 App 評分': StarIcon,
} as const

type PreferenceLabel = (typeof PREFERENCE_ROWS)[number]['label']

/** 簡單 sheet 浮層內容（外觀為真選項、其餘為 stub 候選）。 */
const SHEET_OPTIONS: Record<PreferenceLabel, string[]> = {
  外觀: ['跟隨系統', '淺色', '深色'],
  語言: ['繁體中文', 'English', '日本語'],
  翻譯語言: ['English → 繁體中文', 'English → 日本語'],
  複習節奏: ['寬鬆', '標準', '密集'],
}

/**
 * 偏好列 → shell 導航意圖（有對應子 surface 者）。iOS SettingsView 對應列為
 * NavigationLink；外觀 / 語言為就地 Menu picker（無子畫面）→ 不在此 map，shell
 * 路徑仍走 sheet。parity 路徑完全不查此 map。
 */
const NAV_PREFERENCE_INTENT: Partial<Record<PreferenceLabel, NavIntent>> = {
  翻譯語言: 'open-settings-translation-language',
  複習節奏: 'open-settings-review',
}

const PREFERENCES_FOOTNOTE_BASE = '切換後會立即套用到 app 介面。'
const PREFERENCES_FOOTNOTE_SYNC =
  PREFERENCES_FOOTNOTE_BASE + '開啟自動同步後，收錄滿 5 個單字會自動同步到雲端。'
/** logged-out → 重新登入時補的同步狀態值（fixtures 未帶時的合理預設）。 */
const FALLBACK_SYNC_STATUS = '已連線 · 128 張 · 剛剛'

function SectionHeader({ icon: Icon, label }: { icon: typeof PersonCircleIcon; label: string }) {
  return (
    <h2 className="settings-section-header">
      <Icon size={15} />
      {label}
    </h2>
  )
}

/** Menu picker 的上下小 chevron（iOS Menu 的 trailing 指示）。 */
function PickerChevrons() {
  return (
    <svg className="settings-picker-chevrons" viewBox="0 0 10 16" width="10" height="16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 6l3-3.4L8 6M2 10l3 3.4L8 10" />
    </svg>
  )
}

/**
 * 自動同步 toggle。
 *
 * parity 路徑（apiMode 省略）→ 維持空 <button data-on>，DOM/像素與靜態 PNG 逐位元
 * 一致（iOS Catalog 渲染為無 knob 純色膠囊，故 fixture 不畫 knob）。
 *
 * shell 路徑（apiMode）→ 疊一顆 spring-driven 的 knob：用 motion 基座的 `snappy`
 * 彈簧（response 0.3 / ζ 0.85）讓滑塊在 on/off 兩端帶 iOS UISwitch 的手感；位移
 * 由 `data-on` 決定。reduced-motion 經 usePreferredTransition 收斂為瞬時切換。
 */
function SyncToggle({
  on,
  apiMode,
  onToggle,
}: {
  on: boolean
  apiMode?: boolean
  onToggle: () => void
}) {
  const transition = usePreferredTransition(snappy)
  return (
    <button
      type="button"
      className="settings-toggle"
      data-on={on}
      role="switch"
      aria-checked={on}
      aria-label="自動同步"
      onClick={onToggle}
    >
      {apiMode && (
        <motion.span
          className="settings-toggle-knob"
          aria-hidden="true"
          animate={{ x: on ? 20 : 0 }}
          transition={transition}
        />
      )}
    </button>
  )
}

/**
 * 共用：把非互動的 settings-row div 變成可達導航熱區（shell 路徑）。無 onActivate
 * （parity 路徑）→ 回空 props，div 維持非互動，首屏 DOM 與靜態 PNG 逐位元一致。
 */
function rowNavProps(onActivate?: () => void) {
  if (!onActivate) return {}
  return {
    role: 'button' as const,
    tabIndex: 0,
    onClick: onActivate,
    onKeyDown: (e: ReactKeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        onActivate()
      }
    },
  }
}

/**
 * 帳號 / 登出 sheet（shell 路徑專用）— 用 motion 基座的共用 `Sheet`（vaul）承載
 * 登出流程：拖曳關閉 / 點 backdrop / Esc 皆關閉（vaul 內建，故 settings 不重造
 * Escape 處理）。primary 動作 = 登出；delete-account 刻意 SECONDARY 且二段守門
 * （先點「刪除帳號」才露出危險確認），避免誤觸不可逆操作。
 */
function AccountSheet({
  account,
  open,
  onClose,
  onConfirmLogout,
  onConfirmDelete,
}: {
  account: LoggedInAccount
  open: boolean
  onClose: () => void
  onConfirmLogout: () => void
  /** 可選：刪除帳號（不可逆）。未提供時不渲染此守門區塊。 */
  onConfirmDelete?: () => void
}) {
  const [armed, setArmed] = useState(false)
  // sheet 關閉時重置守門狀態，下次開啟回到安全預設。
  useEffect(() => {
    if (!open) setArmed(false)
  }, [open])
  return (
    <Sheet open={open} onClose={onClose} ariaLabel="帳號">
      <div className="settings-account-sheet">
        <div className="settings-account-sheet-head">
          <span className="settings-avatar settings-account-sheet-avatar">{account.initials}</span>
          <span className="settings-account-sheet-id">
            <span className="settings-account-sheet-name">{account.displayName}</span>
            <span className="settings-account-sheet-email">{account.email}</span>
          </span>
        </div>
        <button
          type="button"
          className="settings-account-sheet-logout"
          onClick={() => {
            onClose()
            onConfirmLogout()
          }}
        >
          登出帳號
        </button>
        {onConfirmDelete && (
          <div className="settings-account-sheet-danger">
            {armed ? (
              <>
                <p className="settings-account-sheet-danger-note">
                  此操作無法復原，將永久刪除你的帳號與雲端資料。
                </p>
                <div className="settings-account-sheet-danger-actions">
                  <button
                    type="button"
                    className="settings-account-sheet-cancel"
                    onClick={() => setArmed(false)}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    className="settings-account-sheet-delete-confirm"
                    onClick={() => {
                      onClose()
                      onConfirmDelete()
                    }}
                  >
                    確認刪除
                  </button>
                </div>
              </>
            ) : (
              <button
                type="button"
                className="settings-account-sheet-delete"
                onClick={() => setArmed(true)}
              >
                刪除帳號
              </button>
            )}
          </div>
        )}
      </div>
    </Sheet>
  )
}

function LoggedInCard({
  account,
  onSignOut,
  onOpenAccount,
  onOpenSubscription,
}: {
  account: LoggedInAccount
  onSignOut: () => void
  /** shell 路徑：點帳號列 → 帳號詳情。parity 路徑省略 → 非互動 div（DOM 不變）。 */
  onOpenAccount?: () => void
  /** shell 路徑：點訂閱列 → 訂閱詳情。parity 路徑省略 → 非互動 div（DOM 不變）。 */
  onOpenSubscription?: () => void
}) {
  const sub = account.subscription
  const accountNav = rowNavProps(onOpenAccount)
  const subNav = rowNavProps(onOpenSubscription)
  return (
    <div className="settings-card">
      <div className="settings-row settings-account-row" {...accountNav}>
        <span className="settings-avatar">{account.initials}</span>
        <span className="settings-account-id">
          <span className="settings-account-name-line">
            <span className="settings-account-name">{account.displayName}</span>
            {account.proBadge && (
              <span className="settings-pro-badge">
                <SparklesIcon size={12} />
                PRO
              </span>
            )}
          </span>
          <span className="settings-account-email">{account.email}</span>
        </span>
        <CheckCircleFillIcon className="settings-account-check" size={30} />
        <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
      </div>
      <div className="settings-divider" />
      <div className="settings-row settings-subscription-row" {...subNav}>
        <span className={sub.active ? 'settings-subscription-icon is-active' : 'settings-subscription-icon'}>
          {sub.active ? <SealCheckFillIcon size={15} /> : <SparklesIcon size={15} />}
        </span>
        <span className="settings-subscription-text">
          <span className="settings-subscription-title">{sub.title}</span>
          <span className="settings-subscription-detail">{sub.detail}</span>
        </span>
        <span className={sub.active ? 'settings-pill is-active' : 'settings-pill'}>{sub.pillLabel}</span>
        <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
      </div>
      <div className="settings-divider" />
      <div className="settings-signout-frame">
        <button className="settings-signout" type="button" onClick={onSignOut}>
          登出帳號
        </button>
      </div>
    </div>
  )
}

function LoggedOutCard({ account, onSignIn }: { account: LoggedOutAccount; onSignIn: () => void }) {
  return (
    <div className="settings-card settings-login-card">
      <div className="settings-login-hero">
        {/* 實際 app icon 資產（ios AppIconImage.imageset），非自繪 mock */}
        <img className="settings-login-appicon" src={appIconUrl} alt="" width={64} height={64} />
        <p className="settings-login-title">{account.heroTitle}</p>
        <p className="settings-login-subtitle">{account.heroSubtitle}</p>
      </div>
      <div className="settings-divider" />
      <div className="settings-login-actions">
        <button className="settings-login-button" type="button" onClick={onSignIn}>
          <span className="settings-social-badge is-google">G</span>
          <span className="settings-login-button-label">
            以 <strong>Google</strong> 繼續
          </span>
          <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
        </button>
        <button className="settings-login-button" type="button" onClick={onSignIn}>
          <span className="settings-social-badge is-apple">
            <AppleLogoIcon size={12} />
          </span>
          <span className="settings-login-button-label">
            以 <strong>Apple</strong> 繼續
          </span>
          <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
        </button>
      </div>
    </div>
  )
}

/** 偏好選項列表（fixture 浮層與 shell vaul Sheet 共用的內容本體）。 */
function PreferenceOptionList({
  label,
  current,
  onPick,
}: {
  label: PreferenceLabel
  current: string
  onPick: (value: string) => void
}) {
  return (
    <div className="settings-sheet-options">
      {SHEET_OPTIONS[label].map((opt) => (
        <button
          key={opt}
          type="button"
          className={opt === current ? 'settings-sheet-option is-selected' : 'settings-sheet-option'}
          onClick={() => onPick(opt)}
        >
          <span>{opt}</span>
          {opt === current && <CheckCircleFillIcon size={18} />}
        </button>
      ))}
    </div>
  )
}

/**
 * 偏好選單 sheet（fixture / parity 路徑）：就地底部浮層，點選項即套用並關閉。
 * 維持原 inline 實作（非 vaul portal），確保 parity 首屏與互動 DOM 不漂移。
 */
function PreferenceSheet({
  label,
  current,
  onPick,
  onClose,
}: {
  label: PreferenceLabel
  current: string
  onPick: (value: string) => void
  onClose: () => void
}) {
  return (
    <div className="settings-sheet-scrim" role="dialog" aria-modal="true" aria-label={label} onClick={onClose}>
      <div className="settings-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="settings-sheet-grabber" />
        <p className="settings-sheet-title">{label}</p>
        <PreferenceOptionList label={label} current={current} onPick={onPick} />
      </div>
    </div>
  )
}

/**
 * 偏好選單 sheet（shell 路徑）：用 motion 基座的共用 `Sheet`（vaul），帶 iOS
 * drag-to-dismiss 手感與 Esc/backdrop 關閉。內容本體與 fixture 浮層共用
 * PreferenceOptionList，避免雙面 drift。
 */
function PreferenceSheetVaul({
  label,
  current,
  open,
  onPick,
  onClose,
}: {
  label: PreferenceLabel
  current: string
  open: boolean
  onPick: (value: string) => void
  onClose: () => void
}) {
  return (
    <Sheet open={open} onClose={onClose} ariaLabel={label}>
      <div className="settings-sheet-vaul-body">
        <p className="settings-sheet-title">{label}</p>
        <PreferenceOptionList label={label} current={current} onPick={onPick} />
      </div>
    </Sheet>
  )
}

export function SettingsScreen({ scenario }: { scenario: ScenarioId<'settings'> }) {
  const shell = new URLSearchParams(window.location.search).get('shell') === '1'
  if (shell) {
    return <SettingsScreenApi />
  }
  return <SettingsScreenFixture scenario={scenario} />
}

function SettingsScreenFixture({ scenario }: { scenario: ScenarioId<'settings'> }) {
  const fixture = SETTINGS_FIXTURES[scenario]
  return <SettingsBody fixture={fixture} />
}

function SettingsScreenApi() {
  const api = useApi()
  const { logout } = useAuth()
  const { setAppearance } = useAppearance()
  const [config, setConfig] = useState<UserConfigResponse | null>(null)
  const [quota, setQuota] = useState<QuotaResponse | null>(null)
  const [entitlements, setEntitlements] = useState<SubscriptionStatusResponse | null>(null)
  const [profile, setProfile] = useState<{ displayName: string; email: string | null; initials: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [optimisticConfig, setOptimisticConfig] = useState<UserConfigResponse | null>(null)
  // 只在首次載入時 apply 一次持久化外觀（避免覆蓋使用者後續手動切換）。
  const appearanceApplied = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [cfg, q, ent, prof] = await Promise.all([
        api.user.config(),
        api.user.quota().catch(() => null),
        api.user.entitlements().catch(() => null),
        api.user.profile().catch(() => null),
      ])
      setConfig(cfg)
      setOptimisticConfig(cfg)
      setQuota(q)
      setEntitlements(ent?.pro ?? null)
      if (prof) {
        const name = prof.display_name?.trim() || prof.email?.split('@')[0] || '使用者'
        setProfile({ displayName: name, email: prof.email ?? null, initials: initialsFromProfile(name, prof.email) })
      }
      // 套用持久化外觀偏好（'light'/'dark' 顯式覆蓋；'system' 不動）。
      if (!appearanceApplied.current) {
        const pref: AppearancePref = appearanceFromConfig(cfg)
        if (pref === 'light' || pref === 'dark') setAppearance(pref)
        appearanceApplied.current = true
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [api, setAppearance])

  useEffect(() => {
    load()
  }, [load])

  // Build fixture from API data
  const fixture: SettingsFixture = useMemo(() => {
    if (loading || !config) {
      return {
        account: {
          kind: 'logged-out',
          heroTitle: '解鎖完整功能',
          heroSubtitle: 'AI 翻譯・知識圖譜・雲端同步',
        },
        autoSync: null,
        preferencesFootnote: PREFERENCES_FOOTNOTE_BASE,
        syncStatusValue: null,
      }
    }

    const isPro = entitlements?.is_active ?? false
    const account: LoggedInAccount = {
      kind: 'logged-in',
      displayName: profile?.displayName ?? '使用者',
      email: profile?.email ?? '',
      initials: profile?.initials ?? '?',
      proBadge: isPro,
      subscription: {
        active: isPro,
        title: isPro ? 'Pro 已啟用' : 'Pro',
        detail: isPro
          ? `年度方案，到期日 ${entitlements?.expires_at ?? '2027-03-10'}`
          : 'App Store 價格載入中，稍後會自動更新。',
        pillLabel: isPro ? '啟用中' : '升級',
      },
    }

    return {
      account,
      autoSync: true,
      preferencesFootnote: PREFERENCES_FOOTNOTE_SYNC,
      syncStatusValue: quota
        ? `已連線 · ${Math.round(quota.fraction * 100)}% 額度 · ${formatResetTime(quota.reset_seconds)}`
        : FALLBACK_SYNC_STATUS,
    }
  }, [loading, config, entitlements, quota, profile])

  const updateConfig = useCallback(
    async (patch: Partial<UserConfigResponse>) => {
      if (!optimisticConfig) return
      const next = { ...optimisticConfig, ...patch }
      setOptimisticConfig(next)
      try {
        const saved = await api.user.updateConfig(patch)
        setConfig(saved)
        setOptimisticConfig(saved)
      } catch {
        // rollback
        setOptimisticConfig(config)
      }
    },
    [api, optimisticConfig, config],
  )

  // 外觀偏好持久化：把 'system'|'light'|'dark' 併進 vocab_ui group（保留其他鍵）。
  const persistAppearance = useCallback(
    (pref: AppearancePref) => {
      void updateConfig(buildAppearancePatch(optimisticConfig, pref))
    },
    [updateConfig, optimisticConfig],
  )

  // 帳號 sheet 內守門確認後的「刪除帳號」：呼真實 DELETE /api/user/account
  // （不可逆），成功與否都登出收尾（清本地 session）。
  const deleteAccount = useCallback(() => {
    void (async () => {
      try {
        await api.user.deleteAccount()
      } catch {
        // 即便後端錯誤也登出，避免停在已嘗試刪除的帳號上。
      } finally {
        logout()
      }
    })()
  }, [api, logout])

  // shell 路徑：設定列點擊 → push 對應子 surface（master-detail detail pane）。
  // 鏡射 iOS SettingsView 的 NavigationLink；parity 路徑（fixture）不傳此 callback，
  // 列維持原互動（sheet / 純展示），故首屏 DOM 與靜態 PNG 逐位元一致。
  const nav = useShellNav()
  const navigateSetting = (intent: NavIntent) => {
    const target = pushTargetFor(screenFor('settings'), intent)
    if (target) nav.navigate(target)
  }

  return (
    <SettingsBody
      fixture={fixture}
      apiMode
      onLogout={logout}
      onDeleteAccount={deleteAccount}
      onUpdateConfig={updateConfig}
      onPersistAppearance={persistAppearance}
      onNavigateSetting={navigateSetting}
    />
  )
}

/** 頭像 initials（與帳號身分 store 同規則的精簡版，避免跨 surface 依賴）。 */
function initialsFromProfile(displayName: string, email: string | null): string {
  const name = displayName.trim()
  if (name.length > 0) {
    const parts = name.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
    const first = parts[0]
    if (/^[\x00-\x7F]+$/.test(first)) return first.slice(0, 2).toUpperCase()
    return Array.from(first)[0]
  }
  const local = (email ?? '').split('@')[0]
  return local.length > 0 ? local.slice(0, 2).toUpperCase() : '?'
}

function formatResetTime(sec: number): string {
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h > 0) return `${h} 小時後重置`
  return `${m} 分鐘後重置`
}

function SettingsBody({
  fixture,
  apiMode,
  onLogout,
  onDeleteAccount,
  onUpdateConfig,
  onPersistAppearance,
  onNavigateSetting,
}: {
  fixture: SettingsFixture
  apiMode?: boolean
  onLogout?: () => void
  /** shell 路徑：帳號 sheet 內守門的「刪除帳號」確認後呼叫（不可逆）。 */
  onDeleteAccount?: () => void
  onUpdateConfig?: (patch: Partial<UserConfigResponse>) => Promise<void>
  onPersistAppearance?: (pref: AppearancePref) => void
  /** shell 路徑：設定列 → push 子 surface。parity 路徑省略 → 維持 sheet / 純展示。 */
  onNavigateSetting?: (intent: NavIntent) => void
}) {
  const { appearance, setAppearance } = useAppearance()

  // 互動 state：初值取自 fixture，確保 parity 首屏不變。
  const [account, setAccount] = useState(fixture.account)
  const [autoSync, setAutoSync] = useState(fixture.autoSync)
  // 偏好選單目前值（外觀獨立由 AppearanceContext 管，其餘 in-memory）。
  const [prefValues, setPrefValues] = useState<Record<PreferenceLabel, string>>(() => {
    const init = {} as Record<PreferenceLabel, string>
    for (const row of PREFERENCE_ROWS) init[row.label] = row.value
    return init
  })
  const [openSheet, setOpenSheet] = useState<PreferenceLabel | null>(null)
  // 帳號 / 登出 sheet 開關（shell 路徑專用；fixture 路徑恆 false → 不掛 vaul portal）。
  const [accountSheetOpen, setAccountSheetOpen] = useState(false)
  // 是否曾手動動過外觀（用以把列值從「跟隨系統」改成 淺色/深色）。
  const [appearanceTouched, setAppearanceTouched] = useState(false)

  const isLoggedIn = account.kind === 'logged-in'
  // 登入/登出切換時，偏好區「自動同步」列與其他區「同步狀態」列跟著雙態。
  const showAutoSync = isLoggedIn ? autoSync : null
  const syncStatusValue = isLoggedIn ? fixture.syncStatusValue ?? FALLBACK_SYNC_STATUS : null

  // footnote：logged-out 用 fixture 原文案（避免首屏漂移）；logged-in 依 autoSync 推。
  const preferencesFootnote = !isLoggedIn
    ? fixture.preferencesFootnote
    : autoSync
      ? PREFERENCES_FOOTNOTE_SYNC
      : PREFERENCES_FOOTNOTE_BASE

  // shell 路徑：登出按鈕先開帳號 sheet（登出流程 + 守門的刪除帳號），由 sheet 內
  // primary 動作真正觸發 onLogout。fixture 路徑：直接在雙態 fixture 間切到登出態
  // （無 sheet，DOM 不漂移）。
  function onSignOutButton() {
    if (apiMode && onLogout) {
      setAccountSheetOpen(true)
    } else {
      setAccount(SETTINGS_FIXTURES['logged-out'].account)
    }
  }
  function signIn() {
    setAccount(SETTINGS_FIXTURES['subscribed-active'].account)
    setAutoSync(true) // 重新登入回到 logged-in 預設（on）
  }

  function pickPreference(label: PreferenceLabel, value: string) {
    if (label === '外觀') {
      if (value === '淺色') {
        setAppearance('light')
        setAppearanceTouched(true)
        if (apiMode) onPersistAppearance?.('light')
      } else if (value === '深色') {
        setAppearance('dark')
        setAppearanceTouched(true)
        if (apiMode) onPersistAppearance?.('dark')
      } else {
        // 「跟隨系統」：保留當前主題，僅清手動標記。
        setAppearanceTouched(false)
        if (apiMode) onPersistAppearance?.('system')
      }
    }
    setPrefValues((prev) => ({ ...prev, [label]: value }))
    setOpenSheet(null)

    // API mode: update config for review_mode / translation
    if (apiMode && onUpdateConfig) {
      if (label === '複習節奏') {
        const modeMap: Record<string, string> = {
          寬鬆: 'relaxed',
          標準: 'intensive',
          密集: 'custom',
        }
        void onUpdateConfig({
          review_mode: {
            mode: modeMap[value] ?? 'relaxed',
            custom_initial_interval_hours: 12,
            custom_remembered_multiplier: 1.9,
            custom_forgot_multiplier: 0.45,
            custom_minimum_interval_hours: 6,
            custom_maximum_interval_hours: 1440,
            updated_at: null,
          },
        })
      } else if (label === '翻譯語言') {
        // sheet 選項（顯示字串）→ source/target lang code 對。
        const pairMap: Record<string, { source: string; target: string }> = {
          'English → 繁體中文': { source: 'en', target: 'zh-Hant' },
          'English → 日本語': { source: 'en', target: 'ja' },
        }
        const pair = pairMap[value]
        if (pair) {
          void onUpdateConfig({
            translation: { source_lang: pair.source, target_lang: pair.target, updated_at: null },
          })
        }
      }
    }
  }

  function preferenceDisplayValue(label: PreferenceLabel): string {
    if (label === '外觀') {
      return appearanceTouched ? (appearance === 'dark' ? '深色' : '淺色') : '跟隨系統'
    }
    return prefValues[label]
  }

  return (
    <div className="settings">
      <header className="settings-nav">
        <h1 className="settings-nav-title">設定</h1>
      </header>
      <div className="settings-scroll">
        <section className="settings-section">
          <SectionHeader icon={PersonCircleIcon} label="帳號" />
          {account.kind === 'logged-in' ? (
            <LoggedInCard
              account={account}
              onSignOut={onSignOutButton}
              onOpenAccount={onNavigateSetting ? () => onNavigateSetting('open-settings-account') : undefined}
              onOpenSubscription={
                onNavigateSetting ? () => onNavigateSetting('open-settings-subscription') : undefined
              }
            />
          ) : (
            <LoggedOutCard account={account} onSignIn={signIn} />
          )}
        </section>

        <section className="settings-section">
          <SectionHeader icon={SlidersIcon} label="偏好" />
          <div className="settings-card">
            {PREFERENCE_ROWS.map((row, i) => {
              const Icon = PREFERENCE_ICONS[row.label]
              return (
                <div key={row.label}>
                  {i > 0 && <div className="settings-divider is-inset" />}
                  <button
                    type="button"
                    className="settings-row settings-row-button"
                    onClick={() => {
                      // shell 路徑：翻譯語言 / 複習節奏 列改為 push 子 surface
                      // （iOS 為 NavigationLink）；外觀 / 語言 仍走原 sheet。parity
                      // 路徑（無 onNavigateSetting）一律維持原 sheet 行為。
                      const intent = NAV_PREFERENCE_INTENT[row.label]
                      if (onNavigateSetting && intent) onNavigateSetting(intent)
                      else setOpenSheet(row.label)
                    }}
                  >
                    <span className="settings-row-icon">
                      <Icon size={row.iconSize} />
                    </span>
                    <span className="settings-row-label">{row.label}</span>
                    <span className="settings-row-value">{preferenceDisplayValue(row.label)}</span>
                    {row.nav ? (
                      <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
                    ) : (
                      <PickerChevrons />
                    )}
                  </button>
                </div>
              )
            })}
            {showAutoSync !== null && (
              <div>
                <div className="settings-divider is-inset" />
                <div className="settings-row">
                  <span className="settings-row-icon">
                    <SyncIcon size={15} />
                  </span>
                  <span className="settings-row-label">自動同步</span>
                  <SyncToggle
                    on={showAutoSync}
                    apiMode={apiMode}
                    onToggle={() => {
                      const next = !showAutoSync
                      setAutoSync(next)
                      if (apiMode && onUpdateConfig) {
                        void onUpdateConfig({
                          review_clock: {
                            is_paused: !next,
                            paused_at: next ? null : new Date().toISOString(),
                            updated_at: null,
                          },
                        })
                      }
                    }}
                  />
                </div>
              </div>
            )}
          </div>
          <p className="settings-footnote">{preferencesFootnote}</p>
        </section>

        <section className="settings-section">
          <SectionHeader icon={EllipsisCircleIcon} label="其他" />
          <div className="settings-card">
            {syncStatusValue !== null && (
              <>
                <div
                  className="settings-row"
                  {...rowNavProps(
                    onNavigateSetting ? () => onNavigateSetting('open-sync') : undefined,
                  )}
                >
                  <span className="settings-row-icon">
                    <SyncIcon size={15} />
                  </span>
                  <span className="settings-row-label">同步狀態</span>
                  <span className="settings-sync-status">
                    <span className="settings-sync-dot" />
                    {syncStatusValue}
                  </span>
                </div>
                <div className="settings-divider is-inset" />
              </>
            )}
            {EXTERNAL_ROWS.map((label, i) => {
              const Icon = EXTERNAL_ICONS[label]
              return (
                <div key={label}>
                  {i > 0 && <div className="settings-divider is-inset" />}
                  <div className="settings-row">
                    <span className="settings-row-icon">
                      <Icon size={15} />
                    </span>
                    <span className="settings-row-label">{label}</span>
                    <ChevronRightIcon className="settings-chevron" size={10} strokeWidth={1.2} />
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      </div>

      {/* 偏好選單 sheet：shell 路徑用 vaul Sheet（drag-dismiss 手感），fixture 路徑
          維持就地浮層（parity DOM 不漂移）。 */}
      {apiMode ? (
        <PreferenceSheetVaul
          label={openSheet ?? '外觀'}
          current={openSheet ? preferenceDisplayValue(openSheet) : ''}
          open={openSheet !== null}
          onPick={(value) => openSheet && pickPreference(openSheet, value)}
          onClose={() => setOpenSheet(null)}
        />
      ) : (
        openSheet && (
          <PreferenceSheet
            label={openSheet}
            current={preferenceDisplayValue(openSheet)}
            onPick={(value) => pickPreference(openSheet, value)}
            onClose={() => setOpenSheet(null)}
          />
        )
      )}

      {/* 帳號 / 登出 sheet（shell 路徑專用，fixture 恆 false → 不掛 vaul portal）。 */}
      {apiMode && account.kind === 'logged-in' && (
        <AccountSheet
          account={account}
          open={accountSheetOpen}
          onClose={() => setAccountSheetOpen(false)}
          onConfirmLogout={() => onLogout?.()}
          onConfirmDelete={onDeleteAccount}
        />
      )}
    </div>
  )
}

export interface SettingsFixture {
  account: LoggedInAccount | LoggedOutAccount
  autoSync: boolean | null
  preferencesFootnote: string
  syncStatusValue: string | null
}
