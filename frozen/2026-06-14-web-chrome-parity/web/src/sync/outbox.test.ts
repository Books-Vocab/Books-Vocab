import { beforeEach, describe, expect, it } from 'vitest'
import { Outbox, OUTBOX_STORAGE_KEY, parseBlob } from './outbox'
import type { KVStorage } from './types'

function memStorage(): KVStorage & { dump: () => Record<string, string> } {
  const m = new Map<string, string>()
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, v),
    removeItem: (k) => void m.delete(k),
    dump: () => Object.fromEntries(m),
  }
}

describe('parseBlob — defensive load', () => {
  it('null / garbage / wrong-shape → empty blob', () => {
    expect(parseBlob(null)).toEqual({})
    expect(parseBlob('not json')).toEqual({})
    expect(parseBlob('[]')).toEqual({})
    expect(parseBlob('123')).toEqual({})
  })

  it('drops non-conforming entries but keeps valid ones', () => {
    const raw = JSON.stringify({
      default: [
        { id: 'a', word: 'x', notebookId: 'default', action: 'add', status: 'pending' },
        { id: 'b', word: 'y' }, // malformed → dropped
      ],
    })
    const blob = parseBlob(raw)
    expect(blob.default).toHaveLength(1)
    expect(blob.default[0].word).toBe('x')
  })
})

describe('Outbox — enqueue + dedup', () => {
  let storage: ReturnType<typeof memStorage>
  let ob: Outbox

  beforeEach(() => {
    storage = memStorage()
    ob = new Outbox(storage)
  })

  it('enqueueAdd persists and is reloadable', () => {
    ob.enqueueAdd('default', { word: 'ephemeral', translation: '短暫的' })
    const reloaded = new Outbox(storage)
    expect(reloaded.entries('default').map((e) => e.word)).toEqual(['ephemeral'])
    expect(storage.dump()[OUTBOX_STORAGE_KEY]).toContain('ephemeral')
  })

  it('dedups an unresolved add for the same (notebook + raw word)', () => {
    const a = ob.enqueueAdd('default', { word: 'dup', translation: 't' })
    const b = ob.enqueueAdd('default', { word: 'dup', translation: 't2' })
    expect(b.id).toBe(a.id)
    expect(ob.entries('default')).toHaveLength(1)
  })

  it('does NOT cross-dedup the same word across notebooks (per-notebook cards)', () => {
    ob.enqueueAdd('nbA', { word: 'same', translation: 't' })
    ob.enqueueAdd('nbB', { word: 'same', translation: 't' })
    expect(ob.entries('nbA')).toHaveLength(1)
    expect(ob.entries('nbB')).toHaveLength(1)
    expect(ob.notebookIds().sort()).toEqual(['nbA', 'nbB'])
  })

  it('re-enqueues a synced word as a fresh entry (synced is not unresolved)', () => {
    const a = ob.enqueueAdd('default', { word: 'w', translation: 't' })
    ob.replace('default', [{ ...a, status: 'synced', cardId: 'c1' }])
    const b = ob.enqueueAdd('default', { word: 'w', translation: 't' })
    expect(b.id).not.toBe(a.id)
    expect(ob.entries('default')).toHaveLength(2)
  })
})

describe('Outbox — per-notebook isolation on mutation', () => {
  it('clear(nb) never touches other notebooks', () => {
    const storage = memStorage()
    const ob = new Outbox(storage)
    ob.enqueueAdd('nbA', { word: 'a', translation: 't' })
    ob.enqueueAdd('nbB', { word: 'b', translation: 't' })
    ob.clear('nbA')
    expect(ob.entries('nbA')).toHaveLength(0)
    expect(ob.entries('nbB')).toHaveLength(1)
  })

  it('replace([]) prunes the notebook key entirely', () => {
    const storage = memStorage()
    const ob = new Outbox(storage)
    ob.enqueueAdd('nbA', { word: 'a', translation: 't' })
    ob.replace('nbA', [])
    expect(ob.notebookIds()).toEqual([])
  })

  it('remove drops only the targeted ids', () => {
    const storage = memStorage()
    const ob = new Outbox(storage)
    const a = ob.enqueueAdd('default', { word: 'a', translation: 't' })
    ob.enqueueAdd('default', { word: 'b', translation: 't' })
    ob.remove('default', [a.id])
    expect(ob.entries('default').map((e) => e.word)).toEqual(['b'])
  })
})
