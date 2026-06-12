import type { ComponentType, SVGProps } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { FilterDecreaseIcon, XmarkIcon } from './icons'

type GlyphProps = SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }

/**
 * VocabChromeIconButton scenario fixtures — 對齊 VocabShellChromeScenarios.swift
 * 「Vocab Shell · Chrome Icon Button」2 態。
 *
 * - Close：systemImage xmark，tone = nil → secondaryText。
 * - Toned (filter)：systemImage line.3.horizontal.decrease，tone = .accentColor
 *   （SwiftUI 系統 accent，非 appSkin palette；catalog 渲染為系統藍 #0088FF）。
 *
 * `toned` 標記是否套用 system-accent tint；否則用 secondaryText。
 */
export const VOCAB_CHROME_ICON_BUTTON_FIXTURES: Record<
  ScenarioId<'vocab-chrome-icon-button'>,
  { Icon: ComponentType<GlyphProps>; ariaLabel: string; toned: boolean }
> = {
  close: { Icon: XmarkIcon, ariaLabel: 'xmark', toned: false },
  'toned-filter': { Icon: FilterDecreaseIcon, ariaLabel: 'line.3.horizontal.decrease', toned: true },
}
