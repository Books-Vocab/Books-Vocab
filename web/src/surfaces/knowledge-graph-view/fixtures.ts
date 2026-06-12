import type { ComponentType } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import { PersonCircleBadgeExclamationIcon } from './icons'

type GlyphProps = { className?: string; size?: number }

export interface KnowledgeGraphFixture {
  icon: ComponentType<GlyphProps>
  title: string
  description: string
}

/**
 * KnowledgeGraphView 全屏 surface 的 catalog scenario 資料。
 *
 * Scene「Logged out · empty graph」注入 `CatalogPreviewAuth(isLoggedIn:false)`，
 * `coordinator.loadGraphData` 因 `guard authManager.isLoggedIn` no-op，圖無節點；
 * `KnowledgeGraphPresentation.emptyState(isLoggedIn:false)` 走第一分支 → 登入提示。
 * 文案逐字對齊 `KnowledgeGraphCopy.loginTitle / loginDescription`，無 CTA action。
 */
export const KNOWLEDGE_GRAPH_VIEW_FIXTURES: Record<
  ScenarioId<'knowledge-graph-view'>,
  KnowledgeGraphFixture
> = {
  // isLoggedIn=false → loginTitle / loginDescription / person.crop.circle.badge.exclamationmark
  'logged-out-empty-graph': {
    icon: PersonCircleBadgeExclamationIcon,
    title: '需登入帳號',
    description: '請至設定中登入以查閱您的知識關聯。',
  },
}
