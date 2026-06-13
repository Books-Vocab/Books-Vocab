// localStorage-backed outbox with per-notebook isolation.
//
// Persistence model mirrors the chrome-extension vocab_outbox (sync_lifecycle.md
// §Chrome extension notebook-scoped add outbox): entries carry a notebookId and
// dedup is scoped to (notebook + raw word + action). The same raw word in two
// notebooks is two legitimate cards and must NOT cross-dedup.
//
// Storage is injected (KVStorage) so the pure logic is node-testable; the React
// hook supplies window.localStorage. A single JSON blob under one key holds all
// notebooks' entries; reads/writes are whole-blob (small, human-scale data).

import type { KVStorage, OutboxEntry } from './types'
import type { VocabEntry } from '../api/types'

const STORAGE_KEY = 'kg.sync.outbox.v1'

type Blob = Record<string, OutboxEntry[]> // notebookId -> entries

function isEntry(x: unknown): x is OutboxEntry {
  if (!x || typeof x !== 'object') return false
  const e = x as Record<string, unknown>
  return (
    typeof e.id === 'string' &&
    typeof e.word === 'string' &&
    typeof e.notebookId === 'string' &&
    (e.action === 'add' || e.action === 'delete') &&
    (e.status === 'pending' || e.status === 'synced' || e.status === 'failed')
  )
}

/** Parse the persisted blob defensively — corrupt/foreign data → empty. */
export function parseBlob(raw: string | null): Blob {
  if (!raw) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return {}
  }
  if (!parsed || typeof parsed !== 'object') return {}
  const out: Blob = {}
  for (const [nb, list] of Object.entries(parsed as Record<string, unknown>)) {
    if (!Array.isArray(list)) continue
    out[nb] = list.filter(isEntry)
  }
  return out
}

let counter = 0
/** Local id for a new outbox entry. Deterministic-ish; collision-safe within a
 *  process via the monotonic counter, unique-enough across reloads via time. */
export function makeEntryId(): string {
  counter += 1
  return `ob_${Date.now().toString(36)}_${counter.toString(36)}`
}

export class Outbox {
  private blob: Blob

  constructor(private readonly storage: KVStorage) {
    this.blob = parseBlob(storage.getItem(STORAGE_KEY))
  }

  private persist(): void {
    this.storage.setItem(STORAGE_KEY, JSON.stringify(this.blob))
  }

  private list(notebookId: string): OutboxEntry[] {
    return this.blob[notebookId] ?? []
  }

  /** All entries for one notebook (per-notebook isolation boundary). */
  entries(notebookId: string): OutboxEntry[] {
    return this.list(notebookId).map((e) => ({ ...e }))
  }

  /** Notebooks that currently hold any entry. */
  notebookIds(): string[] {
    return Object.keys(this.blob).filter((nb) => this.list(nb).length > 0)
  }

  /** Enqueue an add. Dedups an UNRESOLVED add for the same (notebook + raw
   *  word); returns the existing entry if already queued (idempotent). */
  enqueueAdd(notebookId: string, entry: VocabEntry): OutboxEntry {
    const list = this.list(notebookId)
    const existing = list.find(
      (e) => e.action === 'add' && e.word === entry.word && e.status !== 'synced',
    )
    if (existing) return { ...existing }
    const created: OutboxEntry = {
      id: makeEntryId(),
      word: entry.word,
      notebookId,
      action: 'add',
      status: 'pending',
      entry,
    }
    this.blob[notebookId] = [...list, created]
    this.persist()
    return { ...created }
  }

  /** Enqueue a delete for an existing word. Dedups unresolved deletes. */
  enqueueDelete(notebookId: string, word: string): OutboxEntry {
    const list = this.list(notebookId)
    const existing = list.find(
      (e) => e.action === 'delete' && e.word === word && e.status !== 'synced',
    )
    if (existing) return { ...existing }
    const created: OutboxEntry = {
      id: makeEntryId(),
      word,
      notebookId,
      action: 'delete',
      status: 'pending',
    }
    this.blob[notebookId] = [...list, created]
    this.persist()
    return { ...created }
  }

  /** Replace the entry set for a notebook (used after a reconcile). */
  replace(notebookId: string, entries: OutboxEntry[]): void {
    if (entries.length === 0) {
      delete this.blob[notebookId]
    } else {
      this.blob[notebookId] = entries.map((e) => ({ ...e }))
    }
    this.persist()
  }

  /** Remove specific entries (by id) from a notebook. */
  remove(notebookId: string, ids: Iterable<string>): void {
    const drop = new Set(ids)
    const remaining = this.list(notebookId).filter((e) => !drop.has(e.id))
    this.replace(notebookId, remaining)
  }

  /** Clear one notebook (per-notebook isolation: never touches others). */
  clear(notebookId: string): void {
    delete this.blob[notebookId]
    this.persist()
  }
}

export { STORAGE_KEY as OUTBOX_STORAGE_KEY }
