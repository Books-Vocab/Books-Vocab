import { describe, expect, it } from 'vitest'
import {
  applyDeleteReconcile,
  isLegalState,
  isPending,
  locallyResolvableDeletes,
  reconcileAdds,
  reconcileDeletes,
  resetFailedToPending,
  showsInReader,
} from './stateMachine'
import type { BatchDeleteResult, OutboxEntry } from './types'
import type { VocabAddResponse } from '../api/types'

function entry(p: Partial<OutboxEntry> & Pick<OutboxEntry, 'word' | 'action'>): OutboxEntry {
  return {
    id: p.id ?? `id_${p.word}_${p.action}`,
    word: p.word,
    notebookId: p.notebookId ?? 'default',
    action: p.action,
    status: p.status ?? 'pending',
    entry: p.entry,
    cardId: p.cardId,
  }
}

// ── 規則表 legality (sync_lifecycle.md §核心欄位 / 規則表) ─────────────────────
describe('state machine — legal (status, action) combos', () => {
  it('accepts the 5 resting states from the SoT 規則表', () => {
    expect(isLegalState('pending', 'add')).toBe(true)
    expect(isLegalState('synced', 'add')).toBe(true)
    expect(isLegalState('pending', 'delete')).toBe(true)
    expect(isLegalState('failed', 'add')).toBe(true)
    expect(isLegalState('failed', 'delete')).toBe(true)
  })

  it('rejects synced+delete (terminal: entry leaves the outbox)', () => {
    expect(isLegalState('synced', 'delete')).toBe(false)
  })
})

describe('待同步 / 閱讀器 visibility (規則表 columns)', () => {
  it('pending|failed (add+delete) count as 待同步; synced+add does not', () => {
    expect(isPending(entry({ word: 'a', action: 'add', status: 'pending' }))).toBe(true)
    expect(isPending(entry({ word: 'a', action: 'add', status: 'failed' }))).toBe(true)
    expect(isPending(entry({ word: 'a', action: 'delete', status: 'pending' }))).toBe(true)
    expect(isPending(entry({ word: 'a', action: 'add', status: 'synced' }))).toBe(false)
  })

  it('add shows in reader; delete is always hidden', () => {
    expect(showsInReader(entry({ word: 'a', action: 'add' }))).toBe(true)
    expect(showsInReader(entry({ word: 'a', action: 'delete' }))).toBe(false)
  })
})

describe('failed → pending before retry (§同步失敗後重試 step 3)', () => {
  it('flips failed to pending, leaves others untouched', () => {
    expect(resetFailedToPending(entry({ word: 'a', action: 'add', status: 'failed' })).status).toBe('pending')
    expect(resetFailedToPending(entry({ word: 'a', action: 'add', status: 'synced' })).status).toBe('synced')
    expect(resetFailedToPending(entry({ word: 'a', action: 'add', status: 'pending' })).status).toBe('pending')
  })
})

// ── add reconcile (§本地新增上傳成功) ────────────────────────────────────────
describe('reconcileAdds — cardId echo invariant', () => {
  const adds = [
    entry({ word: 'chateau,', action: 'add' }), // trailing punctuation
    entry({ word: 'Ephemeral', action: 'add' }), // capitalized
    entry({ word: 'orphan', action: 'add' }),
  ]

  it('converges only entries whose RAW word is echoed in cardIds (byte-exact)', () => {
    const resp: VocabAddResponse = {
      created: 2,
      skipped: 0,
      duplicates: [],
      // cardIds keyed by the RAW submitted word (SoT byte-exact echo).
      cardIds: { 'chateau,': 'card-1', Ephemeral: 'card-2' },
    }
    const { synced, stillPending } = reconcileAdds(adds, resp)
    expect(synced.map((e) => e.word).sort()).toEqual(['Ephemeral', 'chateau,'])
    expect(synced.every((e) => e.status === 'synced')).toBe(true)
    expect(synced.find((e) => e.word === 'chateau,')!.cardId).toBe('card-1')
    // 'orphan' had no echo → stays pending+add for retry.
    expect(stillPending.map((e) => e.word)).toEqual(['orphan'])
    expect(stillPending[0].status).toBe('pending')
  })

  it('does NOT converge on content-normalized keys (cleaned word must miss)', () => {
    // backend _clean_content would strip the comma; if the response keyed by the
    // CLEANED word, byte-exact lookup on the raw word must NOT match.
    const resp: VocabAddResponse = {
      created: 1,
      skipped: 0,
      duplicates: [],
      cardIds: { chateau: 'card-x' }, // cleaned key, not the raw 'chateau,'
    }
    const { synced, stillPending } = reconcileAdds(
      [entry({ word: 'chateau,', action: 'add' })],
      resp,
    )
    expect(synced).toHaveLength(0)
    expect(stillPending.map((e) => e.word)).toEqual(['chateau,'])
  })
})

// ── delete reconcile (§批次刪除 三個 bucket) ─────────────────────────────────
describe('reconcileDeletes — three buckets', () => {
  const deletes = [
    entry({ word: 'gone', action: 'delete' }),
    entry({ word: 'race', action: 'delete' }),
    entry({ word: 'rollback', action: 'delete' }),
    entry({ word: 'silent', action: 'delete' }),
  ]
  const result: BatchDeleteResult = {
    deleted_words: ['gone'],
    not_found: ['race'], // already gone — locally resolvable (success semantics)
    failed: ['rollback'], // graph rollback — card still on server — retry
    // 'silent' is in NONE of the buckets → must also retry (不變式 2)
  }

  it('locally-resolvable = deleted ∪ not_found', () => {
    expect([...locallyResolvableDeletes(result)].sort()).toEqual(['gone', 'race'])
  })

  it('not_found is success (不變式 1), failed + missing-bucket retry (不變式 2)', () => {
    const { resolvedWords, failedWords } = reconcileDeletes(deletes, result)
    expect(resolvedWords.sort()).toEqual(['gone', 'race'])
    expect(failedWords.sort()).toEqual(['rollback', 'silent'])
  })

  it('applyDeleteReconcile drops resolved, flips the rest to failed+delete', () => {
    const { remaining } = applyDeleteReconcile(deletes, result)
    expect(remaining.map((e) => e.word).sort()).toEqual(['rollback', 'silent'])
    expect(remaining.every((e) => e.status === 'failed' && e.action === 'delete')).toBe(true)
  })
})
