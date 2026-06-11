import { describe, expect, it } from 'vitest'
import {
  readerPanelKind,
  TOC_FIXTURES,
  SETTINGS_FIXTURES,
  NOTEBOOK_FIXTURES,
} from './panel-fixtures'

// 鏡像 ios/.../Debug/Scenarios/ReaderScenarios.swift（TOC / Settings）與
// ReaderNotebookPickerScenarios.swift 的 seed。前綴路由與每態 seed 必須對齊，否則
// parity diff 會在面板層失真。
describe('readerPanelKind', () => {
  it('routes panel scenarios by prefix; chrome scenarios return null', () => {
    expect(readerPanelKind('toc-loaded')).toBe('toc')
    expect(readerPanelKind('settings-bounds-max')).toBe('settings')
    expect(readerPanelKind('notebook-one-bound')).toBe('notebook')
    expect(readerPanelKind('reading-compact')).toBeNull()
    expect(readerPanelKind('error-open-failed')).toBeNull()
  })
})

describe('TOC_FIXTURES', () => {
  it('covers the 4 Reader · TOC states', () => {
    expect(Object.keys(TOC_FIXTURES).sort()).toEqual([
      'toc-empty',
      'toc-failed',
      'toc-loaded',
      'toc-loading',
    ])
  })

  it('loaded seeds the 5-chapter list', () => {
    expect(TOC_FIXTURES['toc-loaded']!.chapters).toEqual([
      '第一章',
      '第二章',
      '第三章',
      '第四章',
      '第五章',
    ])
  })

  it('failed carries the manifest parse message', () => {
    expect(TOC_FIXTURES['toc-failed']!.failedMessage).toBe('Publication manifest 解析失敗。')
  })
})

describe('SETTINGS_FIXTURES', () => {
  it('covers the 3 Reader · Settings states (bounds-max = PR #929)', () => {
    expect(Object.keys(SETTINGS_FIXTURES).sort()).toEqual([
      'settings-bounds-max',
      'settings-bounds-min',
      'settings-normal',
    ])
  })

  it('bounds-min disables decrease at 0.75x', () => {
    const f = SETTINGS_FIXTURES['settings-bounds-min']!
    expect(f.fontSizeText).toBe('0.75x')
    expect(f.canDecreaseFontSize).toBe(false)
    expect(f.canIncreaseFontSize).toBe(true)
  })

  it('bounds-max disables increase at 2.0x', () => {
    const f = SETTINGS_FIXTURES['settings-bounds-max']!
    expect(f.fontSizeText).toBe('2.0x')
    expect(f.canDecreaseFontSize).toBe(true)
    expect(f.canIncreaseFontSize).toBe(false)
  })

  it('normal allows both steppers at 1.0x', () => {
    const f = SETTINGS_FIXTURES['settings-normal']!
    expect(f.fontSizeText).toBe('1.0x')
    expect(f.canDecreaseFontSize).toBe(true)
    expect(f.canIncreaseFontSize).toBe(true)
  })
})

describe('NOTEBOOK_FIXTURES', () => {
  it('covers the 4 Reader Notebook Picker states', () => {
    expect(Object.keys(NOTEBOOK_FIXTURES).sort()).toEqual([
      'notebook-empty',
      'notebook-follow-global',
      'notebook-one-bound',
      'notebook-stress',
    ])
  })

  it('one-bound selects nb-green out of the 3 sample notebooks', () => {
    const f = NOTEBOOK_FIXTURES['notebook-one-bound']!
    expect(f.boundRemoteId).toBe('nb-green')
    expect(f.notebooks.map((n) => n.remoteId)).toEqual(['nb-default', 'nb-green', 'nb-blue'])
  })

  it('follow-global binds nothing (no row checked, per strict-binding source)', () => {
    expect(NOTEBOOK_FIXTURES['notebook-follow-global']!.boundRemoteId).toBeNull()
  })

  it('stress seeds 14 notebooks and binds nb-12', () => {
    const f = NOTEBOOK_FIXTURES['notebook-stress']!
    expect(f.notebooks).toHaveLength(14)
    expect(f.boundRemoteId).toBe('nb-12')
  })

  it('empty seeds no notebooks', () => {
    expect(NOTEBOOK_FIXTURES['notebook-empty']!.notebooks).toHaveLength(0)
  })
})
