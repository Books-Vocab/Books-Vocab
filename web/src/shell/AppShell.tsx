import { useState } from 'react'
import type { Appearance, HarnessConfig, SurfaceId } from '../harness/scenarios'
import { SURFACE_SCENARIOS } from '../harness/scenarios'
import { BookshelfScreen } from '../surfaces/bookshelf/BookshelfScreen'
import { NotebookScreen } from '../surfaces/notebook/NotebookScreen'
import { SettingsScreen } from '../surfaces/settings/SettingsScreen'
import { DEFAULT_TAB_ID, SHELL_TABS, type TabSpec } from './tabs'
import './shell.css'

/**
 * Web app 殼層 — 像素對齊 iOS TabView（ContentView.swift）的第一刀：把目前各自
 * 孤島的 web surface（bookshelf、notebook、settings）裝進同一個底部 tab bar 殼。
 *
 * 純 UI：點 tab 只切 surface 渲染，無其他功能。未在 web 重寫的 tab（播客 / 總覽）
 * 為灰態 placeholder、不可選。
 *
 * URL 契約：殼層由 PhoneFrame 在 ?shell=1 時掛載，預設不啟用——既有
 * ?surface=&scenario=&appearance= 行為完全不變（parity capture rig 依賴它，
 * 零影響）。殼層初始 tab 對齊 URL 的 surface（若該 surface 有對應 tab），
 * appearance 沿用；切到其他 surface tab 時用該 surface 的預設 scenario。
 */
function renderSurface(surface: SurfaceId, config: HarnessConfig) {
  // 初始 tab 命中 URL surface 時沿用 URL scenario，否則落該 surface 預設。
  const scenario = surface === config.surface ? config.scenario : SURFACE_SCENARIOS[surface][0]
  switch (surface) {
    case 'bookshelf':
      return <BookshelfScreen scenario={scenario as never} />
    case 'notebook':
      return <NotebookScreen scenario={scenario as never} />
    case 'settings':
      return <SettingsScreen scenario={scenario as never} />
  }
}

/** URL 的 surface 對應哪個殼層 tab id（找不到 → 預設 bookshelf tab）。 */
function initialTabId(config: HarnessConfig): string {
  const match = SHELL_TABS.find((t) => t.kind === 'surface' && t.surface === config.surface)
  return match?.id ?? DEFAULT_TAB_ID
}

function Placeholder({ label }: { label: string }) {
  return (
    <div className="shell-placeholder" role="status">
      <p className="shell-placeholder-title">{label}</p>
      <p className="shell-placeholder-note">尚未在 web 重寫</p>
    </div>
  )
}

function TabButton({
  tab,
  selected,
  onSelect,
}: {
  tab: TabSpec
  selected: boolean
  onSelect: () => void
}) {
  const Icon = tab.icon
  const disabled = tab.kind === 'placeholder'
  return (
    <button
      type="button"
      className="shell-tab"
      data-selected={selected}
      data-disabled={disabled}
      aria-pressed={selected}
      aria-disabled={disabled}
      disabled={disabled}
      onClick={onSelect}
    >
      <span className="shell-tab-icon">
        <Icon size={25} />
      </span>
      <span className="shell-tab-label">{tab.label}</span>
    </button>
  )
}

export function AppShell({ config }: { config: HarnessConfig }) {
  const [selectedId, setSelectedId] = useState(() => initialTabId(config))
  const activeTab = SHELL_TABS.find((t) => t.id === selectedId) ?? SHELL_TABS[0]
  const appearance: Appearance = config.appearance

  return (
    <div className="app-shell" data-appearance={appearance}>
      <div className="shell-content">
        {activeTab.kind === 'surface' ? (
          renderSurface(activeTab.surface, config)
        ) : (
          <Placeholder label={activeTab.label} />
        )}
      </div>
      <nav className="shell-tab-bar" aria-label="主導航">
        {SHELL_TABS.map((tab) => (
          <TabButton
            key={tab.id}
            tab={tab}
            selected={tab.id === selectedId}
            onSelect={() => {
              if (tab.kind === 'surface') setSelectedId(tab.id)
            }}
          />
        ))}
      </nav>
    </div>
  )
}
