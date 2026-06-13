// Public entry point for the sync coordinator module.
//
//   import { useSyncCoordinator } from '../../sync'
//   const { state, start, cancel, retry } = useSyncCoordinator({ notebookId })
//
// Pure-logic core (state machine, outbox, coordinator) is framework-free and
// node-testable; useSyncCoordinator is the only React-aware export.

export { SyncCoordinator, STEP_LABELS, STEP_ORDER } from './coordinator'
export { createSyncApi } from './api'
export { Outbox, OUTBOX_STORAGE_KEY, parseBlob, makeEntryId } from './outbox'
export {
  isLegalState,
  isPending,
  showsInReader,
  resetFailedToPending,
  reconcileAdds,
  reconcileDeletes,
  applyDeleteReconcile,
  locallyResolvableDeletes,
} from './stateMachine'
export { useSyncCoordinator } from './useSyncCoordinator'
export type {
  ActionType,
  BatchDeleteResult,
  CoordinatorState,
  KVStorage,
  OutboxEntry,
  StepProgress,
  StepRunStatus,
  SyncApi,
  SyncEvent,
  SyncFailureKind,
  SyncListener,
  SyncPhase,
  SyncStatus,
  SyncStepId,
} from './types'
export type { CoordinatorOptions } from './coordinator'
export type { UseSyncOptions, UseSyncResult } from './useSyncCoordinator'
