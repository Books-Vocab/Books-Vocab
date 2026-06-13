import { describe, expect, it } from 'vitest'
import { toFixtureCard } from './useNotebookApiStore'
import type { NotebookResponse } from '../../api/types'

describe('toFixtureCard', () => {
  it('maps API response to fixture card shape', () => {
    const api: NotebookResponse = {
      id: 'nb-1',
      name: '我的單字本',
      color: '#AFC2D3',
      coverPattern: null,
      sortOrder: 0,
      isDefault: true,
      isDeleted: false,
      cardCount: 3,
      updatedAt: '2026-06-11T00:00:00Z',
    }
    const card = toFixtureCard(api, 'nb-1')
    expect(card).toEqual({
      name: '我的單字本',
      color: '#AFC2D3',
      cardCount: 3,
      actionableCount: 3,
      reviewProgress: 0,
      isActive: true,
    })
  })

  it('marks non-matching id as inactive', () => {
    const api: NotebookResponse = {
      id: 'nb-2',
      name: '經典文學',
      color: '#AFC2D3',
      coverPattern: null,
      sortOrder: 1,
      isDefault: false,
      isDeleted: false,
      cardCount: 2,
      updatedAt: '2026-06-11T00:00:00Z',
    }
    const card = toFixtureCard(api, 'nb-1')
    expect(card.isActive).toBe(false)
  })

  it('falls back to default color when null', () => {
    const api: NotebookResponse = {
      id: 'nb-3',
      name: '無色本',
      color: null,
      coverPattern: null,
      sortOrder: 2,
      isDefault: false,
      isDeleted: false,
      cardCount: 0,
      updatedAt: null,
    }
    const card = toFixtureCard(api, null)
    expect(card.color).toBe('#AFC2D3')
  })
})
