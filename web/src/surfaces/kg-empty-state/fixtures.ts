import type { ComponentType } from 'react'
import type { ScenarioId } from '../../harness/scenarios'
import {
  BooksVerticalIcon,
  MagnifyingGlassIcon,
  CheckmarkSealIcon,
  FilterCircleIcon,
  RefreshIcon,
} from './icons'

type GlyphProps = { className?: string; size?: number; strokeWidth?: number }

export interface EmptyStateAction {
  title: string
  icon: ComponentType<GlyphProps>
}

export interface EmptyStateFixture {
  icon: ComponentType<GlyphProps>
  title: string
  description: string
  action?: EmptyStateAction
}

/**
 * KGVocabEmptyState resolver（title/description/systemImage 純分支）× 各 catalog
 * scenario 的解析結果。文案與 icon 直接對應 resolver 的 if 鏈，CTA 由 scene 的
 * showsAction 決定（"重新整理" / arrow.clockwise）。
 */
export const KG_EMPTY_STATE_FIXTURES: Record<ScenarioId<'kg-empty-state'>, EmptyStateFixture> = {
  // hasNoEntries=true, showsAction=true
  'no-entries-cta': {
    icon: BooksVerticalIcon,
    title: '尚無已收錄單字',
    description: '在書架閱讀時長按生字加入單字本，或重新整理以拉取雲端已有資料。',
    action: { title: '重新整理', icon: RefreshIcon },
  },
  // hasNoEntries=true, showsAction=false
  'no-entries-logged-out': {
    icon: BooksVerticalIcon,
    title: '尚無已收錄單字',
    description: '在書架閱讀時長按生字加入單字本，或重新整理以拉取雲端已有資料。',
  },
  // searchText="serendipity"
  'search-no-match': {
    icon: MagnifyingGlassIcon,
    title: '沒有符合的單字',
    description: '試試其他關鍵字，或取消部分篩選條件。',
  },
  // filters=[.due] → 單一篩選專屬圖示 checkmark.seal
  'single-filter-due': {
    icon: CheckmarkSealIcon,
    title: '目前沒有符合篩選條件的單字',
    description: '試試取消部分篩選條件，或切換排序方式。',
  },
  // filters=[.unlearned,.reviewed] → 多選通用篩選圖示
  'multi-filter': {
    icon: FilterCircleIcon,
    title: '目前沒有符合篩選條件的單字',
    description: '試試取消部分篩選條件，或切換排序方式。',
  },
}
