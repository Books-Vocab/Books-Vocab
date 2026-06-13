import type { ComponentType, SVGProps } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import {
  ArrowClockwiseIcon,
  BookIcon,
  ExclamationmarkTriangleIcon,
  MagnifyingGlassIcon,
  SparklesIcon,
} from './icons'

type GlyphComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number; strokeWidth?: number }>

interface ShellAction {
  title: string
  icon: GlyphComponent
}

/** 對齊 iOS `VocabScenePhase`。loading/error → 居中 message card；empty → 居中 empty
 *  card；loadingSkeleton → 頂部對齊骨架列；content → pass-through 範例卡。 */
export type SceneShellFixture =
  | { phase: 'loading'; icon: GlyphComponent; title: string }
  | { phase: 'loadingSkeleton'; rowCount: number }
  | { phase: 'empty'; icon: GlyphComponent; title: string; description: string; action?: ShellAction }
  | { phase: 'error'; icon: GlyphComponent; title: string; description: string; retryTitle: string }
  | { phase: 'content' }

/**
 * Vocab · Scene Shell fixtures — 對齊 VocabSceneShellScenarios.swift 六態
 * （`VocabSceneShell` 統一四態容器：loading / loadingSkeleton / empty / error /
 * content）。文案、SF symbol、CTA 與 iOS 逐字對齊。
 */
export const VOCAB_SCENE_SHELL_FIXTURES: Record<ScenarioId<'vocab-scene-shell'>, SceneShellFixture> = {
  'loading-spinner': {
    phase: 'loading',
    icon: ArrowClockwiseIcon,
    title: '載入單字中…',
  },
  'loading-skeleton': {
    phase: 'loadingSkeleton',
    rowCount: 6,
  },
  'empty-cta': {
    phase: 'empty',
    icon: SparklesIcon,
    title: '尚無已收錄單字',
    description: '同步完成後，這裡會顯示你的雲端單字。',
    action: { title: '前往閱讀', icon: BookIcon },
  },
  'empty-no-action': {
    phase: 'empty',
    icon: MagnifyingGlassIcon,
    title: '沒有符合的單字',
    description: '換個關鍵字或篩選條件試試。',
  },
  'error-retry': {
    phase: 'error',
    icon: ExclamationmarkTriangleIcon,
    title: '無法載入單字',
    description: '請檢查網路連線後重試。',
    retryTitle: '重試',
  },
  content: {
    phase: 'content',
  },
}
