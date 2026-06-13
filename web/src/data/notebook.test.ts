import { describe, expect, it } from 'vitest'
import type { NotebookResponse } from '../api/types'
import {
  appendNotebook,
  buildOptimisticNotebook,
  removeNotebook,
  renameNotebookName,
  replaceNotebookId,
} from './notebook'

function nb(id: string, name: string): NotebookResponse {
  return {
    id,
    name,
    color: '#AFC2D3',
    coverPattern: null,
    sortOrder: 0,
    isDefault: false,
    isDeleted: false,
    cardCount: 0,
    updatedAt: null,
  }
}

describe('notebook optimistic helpers', () => {
  it('buildOptimisticNotebook 帶 temp id 與預設封面，無實際卡片', () => {
    const o = buildOptimisticNotebook('新本', 'optimistic-1')
    expect(o.id).toBe('optimistic-1')
    expect(o.name).toBe('新本')
    expect(o.cardCount).toBe(0)
    expect(o.color).toBe('#AFC2D3')
  })

  it('appendNotebook 不可變地插入尾端', () => {
    const list = [nb('a', 'A')]
    const next = appendNotebook(list, nb('b', 'B'))
    expect(next).toHaveLength(2)
    expect(next[1].id).toBe('b')
    expect(list).toHaveLength(1) // 原陣列未被改動
  })

  it('replaceNotebookId 用真 record 換掉 temp 佔位', () => {
    const list = [nb('a', 'A'), nb('optimistic-1', '新本')]
    const real = nb('real-9', '新本')
    const next = replaceNotebookId(list, 'optimistic-1', real)
    expect(next.map((n) => n.id)).toEqual(['a', 'real-9'])
  })

  it('replaceNotebookId 找不到 temp 時為 no-op', () => {
    const list = [nb('a', 'A')]
    expect(replaceNotebookId(list, 'missing', nb('x', 'X'))).toEqual(list)
  })

  it('renameNotebookName 依 id 命中改名，其餘不動', () => {
    const list = [nb('a', 'A'), nb('b', 'B')]
    const next = renameNotebookName(list, 'b', 'B2')
    expect(next.find((n) => n.id === 'b')?.name).toBe('B2')
    expect(next.find((n) => n.id === 'a')?.name).toBe('A')
  })

  it('removeNotebook 依 id 移除', () => {
    const list = [nb('a', 'A'), nb('b', 'B')]
    expect(removeNotebook(list, 'a').map((n) => n.id)).toEqual(['b'])
  })
})
