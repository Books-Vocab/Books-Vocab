// React binding for SyncCoordinator. Subscribes to the coordinator's event
// stream and re-renders on every state change. Keeps the coordinator instance
// stable for the lifetime of the component (one notebook == one coordinator).
//
// Storage: window.localStorage when present (browser/shell); a no-op in-memory
// shim otherwise (SSR / test render without jsdom) so import never throws.

import { useCallback, useMemo, useRef, useState } from 'react'
import { createSyncApi } from './api'
import { SyncCoordinator } from './coordinator'
import type {
  CoordinatorState,
  KVStorage,
  SyncApi,
} from './types'
import type { ReviewEventEntry, ReviewStateEntry } from '../api/types'

function safeStorage(): KVStorage {
  if (typeof window !== 'undefined' && window.localStorage) {
    return window.localStorage
  }
  const mem = new Map<string, string>()
  return {
    getItem: (k) => mem.get(k) ?? null,
    setItem: (k, v) => void mem.set(k, v),
    removeItem: (k) => void mem.delete(k),
  }
}

export interface UseSyncOptions {
  notebookId?: string
  api?: SyncApi
  storage?: KVStorage
  reviewEvents?: ReviewEventEntry[]
  reviewStates?: ReviewStateEntry[]
}

export interface UseSyncResult {
  coordinator: SyncCoordinator
  state: CoordinatorState
  start: () => void
  cancel: () => void
  retry: () => void
}

export function useSyncCoordinator(opts: UseSyncOptions = {}): UseSyncResult {
  const notebookId = opts.notebookId ?? 'default'

  const coordinator = useMemo(
    () =>
      new SyncCoordinator({
        notebookId,
        api: opts.api ?? createSyncApi(),
        storage: opts.storage ?? safeStorage(),
        reviewEvents: opts.reviewEvents,
        reviewStates: opts.reviewStates,
      }),
    // Coordinator identity is keyed on the notebook only; other deps are seeds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [notebookId],
  )

  const [state, setState] = useState<CoordinatorState>(() => coordinator.getState())

  // Subscribe once per coordinator; unsubscribe on swap/unmount.
  const subRef = useRef<(() => void) | null>(null)
  if (subRef.current === null) {
    subRef.current = coordinator.subscribe((event) => {
      if (event.type === 'state') setState(event.state)
      else setState(coordinator.getState())
    })
  }

  const start = useCallback(() => void coordinator.start(), [coordinator])
  const cancel = useCallback(() => coordinator.cancel(), [coordinator])
  const retry = useCallback(() => void coordinator.retry(), [coordinator])

  return { coordinator, state, start, cancel, retry }
}
