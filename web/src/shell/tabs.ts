import type { ComponentType, SVGProps } from 'react'
import type { SurfaceId } from '../harness/scenarios'
import { BooksVerticalIcon, ChartBarIcon, CharacterBookClosedIcon, WaveformIcon } from './icons'

type TabIcon = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

/**
 * 殼層 tab 模型 — 像素對齊鏡像 iOS AppPrimarySection（ContentView.swift）的
 * 四個主 tab，順序/icon/label 逐一對應，不增不減（iOS tab bar 就是這四格）。
 *
 *   AppPrimarySection.bookshelf → books.vertical → web bookshelf surface
 *   AppPrimarySection.podcasts  → waveform       → 灰態 placeholder（web 未重寫）
 *   AppPrimarySection.notebooks → character.book.closed → web notebook surface
 *   AppPrimarySection.overview  → chart.bar       → 灰態 placeholder（web 未重寫）
 *
 * `kind: 'surface'`：可路由到既有 web surface，點擊切換 SurfaceView 渲染。
 * `kind: 'placeholder'`：iOS 有、web 尚未重寫 → 灰態、不可選。
 *
 * label 逐字取自 ios/BooksAndVocab/zh-Hant.lproj/Localizable.strings（app.section.*）。
 */
export type TabSpec =
  | { id: string; label: string; icon: TabIcon; kind: 'surface'; surface: SurfaceId }
  | { id: string; label: string; icon: TabIcon; kind: 'placeholder' }

export const SHELL_TABS: readonly TabSpec[] = [
  { id: 'bookshelf', label: '書庫', icon: BooksVerticalIcon, kind: 'surface', surface: 'bookshelf' },
  { id: 'podcasts', label: '播客', icon: WaveformIcon, kind: 'placeholder' },
  { id: 'notebooks', label: '單字本', icon: CharacterBookClosedIcon, kind: 'surface', surface: 'notebook' },
  { id: 'overview', label: '總覽', icon: ChartBarIcon, kind: 'placeholder' },
] as const

/** 殼層啟動時的預設 tab id（= iOS selectedSection 預設 .bookshelf）。 */
export const DEFAULT_TAB_ID = 'bookshelf'
