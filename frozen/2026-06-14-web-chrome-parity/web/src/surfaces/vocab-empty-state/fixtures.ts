import type { ComponentType, SVGProps } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import {
  BookClosedIcon,
  BookIcon,
  CheckmarkCircleIcon,
  ListBulletIcon,
  MagnifyingGlassIcon,
  TrayIcon,
} from './icons'

type GlyphComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

export interface EmptyStateAction {
  title: string
  icon: GlyphComponent
}

export interface EmptyStateFixture {
  /** `card` = AppEmptyStateCard（包卡片）；`content` = AppEmptyStateContent（裸內容）。 */
  kind: 'card' | 'content'
  icon: GlyphComponent
  title: string
  description: string
  guidance?: string
  action?: EmptyStateAction
}

/**
 * Vocab · Empty State fixtures — 對齊 VocabComponentScenarios.swift
 * 「Vocab Components · Empty State」4 態（VocabEmptyStateContent /
 * VocabEmptyStateCard，皆 .vocab(skin) style）。文案、SF symbol、CTA 與
 * iOS 逐字對齊。
 */
export const VOCAB_EMPTY_STATE_FIXTURES: Record<ScenarioId<'vocab-empty-state'>, EmptyStateFixture> = {
  'card-no-action': {
    kind: 'card',
    icon: MagnifyingGlassIcon,
    title: '找不到符合的單字',
    description: '試試調整篩選條件或搜尋關鍵字。',
  },
  'card-with-action': {
    kind: 'card',
    icon: TrayIcon,
    title: '詞庫是空的',
    description: '開始閱讀並選詞，建立你的第一批單字。',
    action: { title: '開始閱讀', icon: BookIcon },
  },
  'content-basic': {
    kind: 'content',
    icon: BookClosedIcon,
    title: '尚無單字',
    description: '在閱讀時選取詞彙即可加入詞庫。',
  },
  'content-guidance-action': {
    kind: 'content',
    icon: CheckmarkCircleIcon,
    title: '今天沒有要複習的單字',
    description: '所有到期單字都已複習完成。',
    guidance: '明天再回來繼續累積記憶。',
    action: { title: '查看全部單字', icon: ListBulletIcon },
  },
}
