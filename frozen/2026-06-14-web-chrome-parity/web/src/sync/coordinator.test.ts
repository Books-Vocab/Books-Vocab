import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SyncCoordinator } from './coordinator'
import { createSyncApi } from './api'
import { createApiClient } from '../api'
import type {
  BatchDeleteResult,
  KVStorage,
  StepProgress,
  SyncApi,
  SyncEvent,
  SyncStepId,
} from './types'
import type { VocabAddResponse, VocabEntry } from '../api/types'

function memStorage(): KVStorage {
  const m = new Map<string, string>()
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, v),
    removeItem: (k) => void m.delete(k),
  }
}

// A fake SyncApi whose every method is controllable per-test.
function fakeApi(over: Partial<SyncApi> = {}): SyncApi {
  return {
    uploadAdd: async (entries: VocabEntry[]): Promise<VocabAddResponse> => ({
      created: entries.length,
      skipped: 0,
      duplicates: [],
      // echo cardIds by RAW word (SoT-correct; lets reconcile converge).
      cardIds: Object.fromEntries(entries.map((e, i) => [e.word, `card-${i}`])),
    }),
    pushReview: async () => ({ insertedEvents: 0, updatedStates: 0 }),
    pull: async () => ({ count: 7 }),
    ...over,
  }
}

// A fully-bound SyncApi: every port method present (mirrors the default adapter
// once batchDelete + triggerPipeline are wired). Used to prove the coordinator
// runs the complete pipeline with NO step skipped.
function fullApi(over: Partial<SyncApi> = {}): SyncApi {
  return fakeApi({
    batchDelete: async (words: string[]): Promise<BatchDeleteResult> => ({
      deleted_words: words,
      not_found: [],
      failed: [],
    }),
    triggerPipeline: async (): Promise<void> => undefined,
    ...over,
  })
}

function stepOf(state: { steps: StepProgress[] }, id: SyncStepId): StepProgress {
  return state.steps.find((s) => s.id === id)!
}

describe('SyncCoordinator — happy path', () => {
  let storage: KVStorage

  beforeEach(() => {
    storage = memStorage()
  })

  it('runs the full pipeline → completed; adds converge to synced', async () => {
    const coord = new SyncCoordinator({ notebookId: 'default', api: fakeApi(), storage })
    coord.queueAdd({ word: 'ephemeral', translation: '短暫的' })
    coord.queueAdd({ word: 'ineffable', translation: '難以言喻的' })

    const final = await coord.start()
    expect(final.phase).toBe('completed')
    expect(final.failureKind).toBeNull()
    // all adds converged → no pending left.
    expect(final.pending).toHaveLength(0)
    // upload_add reported created count.
    expect(stepOf(final, 'upload_add').status).toBe('done')
    expect(stepOf(final, 'upload_add').detail).toContain('2 新增')
    expect(stepOf(final, 'pull').status).toBe('done')
    expect(stepOf(final, 'pull').detail).toContain('本地單字已建立完成')
  })

  it('emits a step-progress event stream in pipeline order', async () => {
    const coord = new SyncCoordinator({ notebookId: 'default', api: fakeApi(), storage })
    coord.queueAdd({ word: 'w', translation: 't' })
    const stepEvents: SyncStepId[] = []
    coord.subscribe((e: SyncEvent) => {
      if (e.type === 'step' && e.step.status === 'running') stepEvents.push(e.step.id)
    })
    await coord.start()
    // running-step order respects the fixed pipeline order (subset that runs).
    const order: SyncStepId[] = ['upload_add', 'pull']
    const filtered = stepEvents.filter((id) => order.includes(id))
    expect(filtered).toEqual(order)
  })
})

describe('SyncCoordinator — missing routes are skipped (frozen foundation)', () => {
  it('skips upload_delete + trigger when the port lacks them (no failure)', async () => {
    const storage = memStorage()
    const coord = new SyncCoordinator({ notebookId: 'default', api: fakeApi(), storage })
    coord.queueAdd({ word: 'w', translation: 't' })
    coord.queueDelete('old')
    const final = await coord.start()
    // delete step skipped (no batchDelete bound) → delete stays pending, so the
    // run is NOT 'completed' (outstanding delete), but it is not a hard failure.
    expect(stepOf(final, 'upload_delete').status).toBe('skipped')
    expect(stepOf(final, 'trigger').status).toBe('skipped')
    // the still-pending delete makes phase failed/partial, never throws.
    expect(['failed', 'completed']).toContain(final.phase)
  })
})

describe('SyncCoordinator — three-bucket delete reconcile (route present)', () => {
  it('converges deleted ∪ not_found, retries failed + missing', async () => {
    const storage = memStorage()
    const result: BatchDeleteResult = {
      deleted_words: ['gone'],
      not_found: ['race'],
      failed: ['rollback'],
    }
    const batchDelete = vi.fn(async (): Promise<BatchDeleteResult> => result)
    const coord = new SyncCoordinator({
      notebookId: 'default',
      api: fakeApi({ batchDelete }),
      storage,
    })
    coord.queueDelete('gone')
    coord.queueDelete('race')
    coord.queueDelete('rollback')
    const final = await coord.start()
    expect(batchDelete).toHaveBeenCalledOnce()
    // resolved leave; rollback stays failed+delete.
    const remaining = final.pending.filter((e) => e.action === 'delete')
    expect(remaining.map((e) => e.word)).toEqual(['rollback'])
    expect(remaining[0].status).toBe('failed')
    expect(stepOf(final, 'upload_delete').status).toBe('error')
    expect(final.phase).toBe('failed')
  })
})

describe('SyncCoordinator — failure classification', () => {
  it('full failure when nothing lands (first step throws, no success)', async () => {
    const storage = memStorage()
    const api = fakeApi({
      uploadAdd: async () => {
        throw new Error('network')
      },
    })
    const coord = new SyncCoordinator({ notebookId: 'default', api, storage })
    coord.queueAdd({ word: 'w', translation: 't' })
    const final = await coord.start()
    expect(final.phase).toBe('failed')
    // adds flipped to failed; still pending.
    expect(final.pending.map((e) => e.status)).toContain('failed')
  })

  it('partial failure when some adds converge and pull fails', async () => {
    const storage = memStorage()
    const api = fakeApi({
      pull: async () => {
        throw new Error('pull down')
      },
    })
    const coord = new SyncCoordinator({ notebookId: 'default', api, storage })
    coord.queueAdd({ word: 'w', translation: 't' })
    const final = await coord.start()
    expect(final.phase).toBe('failed')
    expect(final.failureKind).toBe('partial')
    expect(stepOf(final, 'pull').status).toBe('error')
  })
})

describe('SyncCoordinator — retry flips failed→pending', () => {
  it('a second run after a transient failure completes', async () => {
    const storage = memStorage()
    let calls = 0
    const api = fakeApi({
      uploadAdd: async (entries: VocabEntry[]): Promise<VocabAddResponse> => {
        calls += 1
        if (calls === 1) throw new Error('transient')
        return {
          created: entries.length,
          skipped: 0,
          duplicates: [],
          cardIds: Object.fromEntries(entries.map((e, i) => [e.word, `c${i}`])),
        }
      },
    })
    const coord = new SyncCoordinator({ notebookId: 'default', api, storage })
    coord.queueAdd({ word: 'w', translation: 't' })

    const first = await coord.start()
    expect(first.phase).toBe('failed')
    expect(first.pending.map((e) => e.status)).toContain('failed')

    const second = await coord.retry()
    expect(second.phase).toBe('completed')
    expect(second.pending).toHaveLength(0)
  })
})

describe('SyncCoordinator — per-notebook isolation', () => {
  it('two coordinators on one storage never see each other’s entries', async () => {
    const storage = memStorage()
    const a = new SyncCoordinator({ notebookId: 'nbA', api: fakeApi(), storage })
    const b = new SyncCoordinator({ notebookId: 'nbB', api: fakeApi(), storage })
    a.queueAdd({ word: 'alpha', translation: 't' })
    b.queueAdd({ word: 'beta', translation: 't' })
    expect(a.getState().pending.map((e) => e.word)).toEqual(['alpha'])
    expect(b.getState().pending.map((e) => e.word)).toEqual(['beta'])

    const pull = vi.fn(async () => ({ count: 1 }))
    const a2 = new SyncCoordinator({
      notebookId: 'nbA',
      api: fakeApi({ pull }),
      storage,
    })
    await a2.start()
    // pull was called with nbA only.
    expect(pull).toHaveBeenCalledWith('nbA')
    // nbB entry untouched after nbA's run.
    const bAfter = new SyncCoordinator({ notebookId: 'nbB', api: fakeApi(), storage })
    expect(bAfter.getState().pending.map((e) => e.word)).toEqual(['beta'])
  })
})

describe('SyncCoordinator — review push step', () => {
  it('pushes review events + states and reports the count', async () => {
    const storage = memStorage()
    const pushReview = vi.fn(async () => ({ insertedEvents: 5, updatedStates: 3 }))
    const coord = new SyncCoordinator({
      notebookId: 'default',
      api: fakeApi({ pushReview }),
      storage,
      reviewEvents: [
        {
          event_id: 'e1',
          word_snapshot: 'w',
          notebook_id: 'default',
          feedback: 1,
          reviewed_at: '2026-06-11T00:00:00Z',
          created_at: '2026-06-11T00:00:00Z',
          is_synthetic: false,
        },
      ],
      reviewStates: [],
    })
    const final = await coord.start()
    expect(pushReview).toHaveBeenCalledOnce()
    expect(stepOf(final, 'push_review').detail).toContain('5')
    expect(final.phase).toBe('completed')
  })
})

describe('SyncCoordinator — full pipeline, no step skipped (routes bound)', () => {
  const ALL_STEPS: SyncStepId[] = [
    'upload_delete',
    'upload_add',
    'trigger',
    'push_review',
    'pull',
  ]

  it('runs every step (delete → add → trigger → push_review → pull) → completed', async () => {
    const storage = memStorage()
    const batchDelete = vi.fn(async (words: string[]): Promise<BatchDeleteResult> => ({
      deleted_words: words,
      not_found: [],
      failed: [],
    }))
    const triggerPipeline = vi.fn(async (): Promise<void> => undefined)
    const pushReview = vi.fn(async () => ({ insertedEvents: 1, updatedStates: 1 }))
    const coord = new SyncCoordinator({
      notebookId: 'default',
      api: fullApi({ batchDelete, triggerPipeline, pushReview }),
      storage,
      reviewEvents: [
        {
          event_id: 'e1',
          word_snapshot: 'gone',
          notebook_id: 'default',
          feedback: 1,
          reviewed_at: '2026-06-13T00:00:00Z',
          created_at: '2026-06-13T00:00:00Z',
          is_synthetic: false,
        },
      ],
      reviewStates: [],
    })
    coord.queueDelete('gone')
    coord.queueAdd({ word: 'ephemeral', translation: '短暫的' })

    const final = await coord.start()

    // Every bound step actually RAN — none skipped.
    for (const id of ALL_STEPS) {
      expect(stepOf(final, id).status).not.toBe('skipped')
    }
    expect(stepOf(final, 'upload_delete').status).toBe('done')
    expect(stepOf(final, 'upload_add').status).toBe('done')
    expect(stepOf(final, 'trigger').status).toBe('done')
    expect(stepOf(final, 'push_review').status).toBe('done')
    expect(stepOf(final, 'pull').status).toBe('done')

    expect(batchDelete).toHaveBeenCalledOnce()
    expect(batchDelete).toHaveBeenCalledWith(['gone'], 'default')
    expect(triggerPipeline).toHaveBeenCalledOnce()
    expect(triggerPipeline).toHaveBeenCalledWith('default')
    expect(pushReview).toHaveBeenCalledOnce()

    // delete converged (deleted_words bucket) + add converged → nothing pending.
    expect(final.pending).toHaveLength(0)
    expect(final.phase).toBe('completed')
    expect(final.failureKind).toBeNull()
  })

  it('emits the running-step stream in full pipeline order', async () => {
    const storage = memStorage()
    const coord = new SyncCoordinator({
      notebookId: 'default',
      api: fullApi(),
      storage,
      reviewEvents: [
        {
          event_id: 'e1',
          word_snapshot: 'gone',
          notebook_id: 'default',
          feedback: 1,
          reviewed_at: '2026-06-13T00:00:00Z',
          created_at: '2026-06-13T00:00:00Z',
          is_synthetic: false,
        },
      ],
    })
    coord.queueDelete('gone')
    coord.queueAdd({ word: 'w', translation: 't' })

    const running: SyncStepId[] = []
    coord.subscribe((e: SyncEvent) => {
      if (e.type === 'step' && e.step.status === 'running') running.push(e.step.id)
    })
    await coord.start()
    expect(running).toEqual(ALL_STEPS)
  })

  it('default adapter (createSyncApi) binds batchDelete + triggerPipeline against the mock', async () => {
    // Drives the REAL default adapter over the mock ApiClient end-to-end. Both
    // previously-skipped steps must now run against mock-backed routes.
    const storage = memStorage()
    const api = createSyncApi({ client: createApiClient({ getToken: () => 'mock' }) })
    expect(typeof api.batchDelete).toBe('function')
    expect(typeof api.triggerPipeline).toBe('function')

    const coord = new SyncCoordinator({ notebookId: 'default', api, storage })
    // A word the mock store does not know → not_found bucket = locally resolvable
    // (success semantics, never an infinite-retry failure per sync_lifecycle.md).
    coord.queueDelete('definitely-not-a-seeded-word')
    coord.queueAdd({ word: 'serendipity', translation: '機緣' })

    const final = await coord.start()

    for (const id of ALL_STEPS) {
      expect(stepOf(final, id).status).not.toBe('skipped')
    }
    expect(stepOf(final, 'upload_delete').status).toBe('done')
    expect(stepOf(final, 'trigger').status).toBe('done')
    expect(final.phase).toBe('completed')
    expect(final.pending).toHaveLength(0)
  })
})
