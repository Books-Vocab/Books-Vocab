import { describe, expect, it } from 'vitest'
import type { NotebookResponse } from '../api/types'
import {
  appendNotebook,
  buildOptimisticNotebook,
  removeNotebook,
  renameNotebookName,
  replaceNotebookId,
} from './notebook'

/**
 * Notebook 樂觀更新的純 cache-transform helper 契約。
 *
 * 樂觀更新邏輯（onMutate setQueryData / onError rollback / onSuccess 對換）裡真正的
 * 資料變換抽成純函式於此測；hook 的 react-query 接線（cancelQueries / 快照 / invalidate）
 * 由 headless tools/interaction.mjs 在真實瀏覽器覆蓋（notebook add/edit/delete）。
 */

const BASE: NotebookResponse = {
  id: 'nb-1',
  name: '科普閱讀',
  color: '#AFC2D3',
  coverPattern: null,
  sortOrder: 0,
  isDefault: false,
  isDeleted: false,
  cardCount: 5,
  updatedAt: null,
}

describe('notebook 樂觀 cache helpers', () => {
  it('buildOptimisticNotebook 從 create request 造出佔位實體', () => {
    const o = buildOptimisticNotebook('optimistic-1', { name: '  新單字本  '.trim() })
    expect(o.id).toBe('optimistic-1')
    expect(o.name).toBe('新單字本')
    expect(o.cardCount).toBe(0)
    expect(o.isDeleted).toBe(false)
    expect(o.color).toBeNull() // 未指定 → null（toFixtureCard 再套 UI 預設）
    expect(o.coverPattern).toBeNull()
  })

  it('buildOptimisticNotebook 帶 color/cover 時保留', () => {
    const o = buildOptimisticNotebook('optimistic-2', {
      name: 'x',
      color: '#FF0000',
      cover_pattern: 'dots',
    })
    expect(o.color).toBe('#FF0000')
    expect(o.coverPattern).toBe('dots')
  })

  it('appendNotebook 樂觀插入到列尾（不變原陣列）', () => {
    const o = buildOptimisticNotebook('optimistic-3', { name: 'new' })
    const next = appendNotebook([BASE], o)
    expect(next).toHaveLength(2)
    expect(next[1].id).toBe('optimistic-3')
    expect(next[0]).toBe(BASE) // 原元素 reference 保留
  })

  it('replaceNotebookId 以真實實體換掉樂觀佔位（add 成功對換）', () => {
    const optimistic = buildOptimisticNotebook('optimistic-4', { name: 'new' })
    const real: NotebookResponse = { ...optimistic, id: 'nb-real', cardCount: 0 }
    const next = replaceNotebookId([BASE, optimistic], 'optimistic-4', real)
    expect(next.map((n) => n.id)).toEqual(['nb-1', 'nb-real'])
  })

  it('renameNotebookName 樂觀改名（只動目標 id）', () => {
    const other: NotebookResponse = { ...BASE, id: 'nb-2', name: '其他' }
    const next = renameNotebookName([BASE, other], 'nb-1', '新名稱')
    expect(next.find((n) => n.id === 'nb-1')?.name).toBe('新名稱')
    expect(next.find((n) => n.id === 'nb-2')?.name).toBe('其他')
  })

  it('removeNotebook 樂觀刪除（按 id 濾除）', () => {
    const other: NotebookResponse = { ...BASE, id: 'nb-2' }
    const next = removeNotebook([BASE, other], 'nb-1')
    expect(next.map((n) => n.id)).toEqual(['nb-2'])
  })
})
