import { describe, expect, it } from 'vitest'
import { SURFACE_SCENARIOS } from '../harness/scenarios'
import { DEFAULT_TAB_ID, SHELL_TABS } from './tabs'

describe('SHELL_TABS', () => {
  it('mirrors iOS AppPrimarySection: 4 tabs, order/id/label 對齊', () => {
    expect(SHELL_TABS.map((t) => t.id)).toEqual(['bookshelf', 'podcasts', 'notebooks', 'overview'])
    expect(SHELL_TABS.map((t) => t.label)).toEqual(['書庫', '播客', '單字本', '總覽'])
  })

  it('全四 tab 皆路由到真實 web surface（overview 統計儀表板已重寫，無 placeholder）', () => {
    const surfaceTabs = SHELL_TABS.filter((t) => t.kind === 'surface')
    expect(surfaceTabs.map((t) => t.id)).toEqual(['bookshelf', 'podcasts', 'notebooks', 'overview'])
    // bookshelf→bookshelf、podcasts→podcast(player)、notebooks→notebook、overview→overview
    expect(surfaceTabs.map((t) => (t.kind === 'surface' ? t.surface : null))).toEqual([
      'bookshelf',
      'podcast',
      'notebook',
      'overview',
    ])
    // 四 tab 全真實化 → 無 placeholder tab
    expect(SHELL_TABS.filter((t) => t.kind === 'placeholder')).toEqual([])
  })

  it('每個 surface tab 的目標 surface 都有合法 scenario taxonomy', () => {
    for (const tab of SHELL_TABS) {
      if (tab.kind === 'surface') {
        expect(SURFACE_SCENARIOS[tab.surface]).toBeDefined()
        expect(SURFACE_SCENARIOS[tab.surface].length).toBeGreaterThan(0)
      }
    }
  })

  it('預設 tab id = iOS selectedSection 預設 (.bookshelf)', () => {
    expect(DEFAULT_TAB_ID).toBe('bookshelf')
    expect(SHELL_TABS[0].id).toBe(DEFAULT_TAB_ID)
  })
})
