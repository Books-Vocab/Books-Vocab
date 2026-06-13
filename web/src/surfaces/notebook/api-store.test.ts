import { describe, expect, it } from 'vitest'
import { toFixtureCard } from './useNotebookApiStore'
import type { NotebookResponse } from '../../api/types'

const BASE: NotebookResponse = {
  id: 'nb-1',
  name: '測試本',
  color: '#FF0000',
  coverPattern: null,
  sortOrder: 0,
  isDefault: false,
  isDeleted: false,
  cardCount: 5,
  updatedAt: '2026-06-11T00:00:00Z',
}

describe('toFixtureCard', () => {
  it('maps name, color, cardCount, actionableCount, reviewProgress, isActive', () => {
    const result = toFixtureCard(BASE, 'nb-1')
    expect(result).toEqual({
      name: '測試本',
      color: '#FF0000',
      cardCount: 5,
      actionableCount: 5,
      reviewProgress: 0,
      isActive: true,
    })
  })

  it('falls back to default color when color is null', () => {
    const result = toFixtureCard({ ...BASE, color: null }, 'nb-2')
    expect(result.color).toBe('#AFC2D3')
  })

  it('isActive = false when id does not match activeId', () => {
    const result = toFixtureCard(BASE, 'other-id')
    expect(result.isActive).toBe(false)
  })
})
