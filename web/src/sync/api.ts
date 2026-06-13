// Default SyncApi adapter — binds the coordinator's narrow port to the FROZEN
// typed client (web/src/api). Mock-first: createApiClient() defaults to mock
// mode, so this works fully offline.
//
// Route availability vs the frozen foundation:
//   uploadAdd   → POST /api/vocab                  (exists, mock-backed)
//   pushReview  → PATCH /api/vocab/review-events
//                 + PATCH /api/vocab/review         (exist, mock-backed)
//   pull        → GET /api/vocab                    (exists, mock-backed)
//   batchDelete → POST /api/vocab/batch-delete      (NOT in frozen client/mock)
//   trigger     → POST /api/pipeline                (NOT in frozen client/mock)
//
// The two missing routes are deliberately left UNBOUND (optional port methods):
// the coordinator reports those steps as `skipped` rather than fabricating a
// result. When the foundation adds VocabularyClient.batchDelete /
// PipelineClient.trigger + their mock routes, bind them here (one line each) —
// the state-machine reconcile (stateMachine.applyDeleteReconcile) is already
// wired and unit-tested for the three-bucket response.

import { createApiClient, type ApiClient } from '../api'
import type { SyncApi } from './types'

export interface SyncApiOptions {
  /** Pre-built client (tests). Defaults to createApiClient() (mock by env). */
  client?: ApiClient
  /** Bearer token provider for the default client. */
  getToken?: () => string | null
}

export function createSyncApi(opts: SyncApiOptions = {}): SyncApi {
  const api =
    opts.client ?? createApiClient({ getToken: opts.getToken ?? (() => 'mock-access-token') })

  return {
    async uploadAdd(entries, notebookId) {
      return api.vocabulary.add(entries, { notebookId })
    },

    // batchDelete / triggerPipeline intentionally omitted — see file header.

    async pushReview({ events, states }) {
      let insertedEvents = 0
      let updatedStates = 0
      if (events.length > 0) {
        const r = await api.todayReview.submitEvents({ entries: events })
        insertedEvents = r.inserted
      }
      if (states.length > 0) {
        const r = await api.todayReview.submitState({ entries: states })
        updatedStates = r.updated
      }
      return { insertedEvents, updatedStates }
    },

    async pull(notebookId) {
      const cards = await api.vocabulary.list({ notebookId })
      return { count: cards.length }
    },
  }
}
