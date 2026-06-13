// Default SyncApi adapter — binds the coordinator's narrow port to the typed
// client (web/src/api). Mock-first: createApiClient() defaults to mock mode, so
// this works fully offline.
//
// Route availability (all exist on the client + are mock-backed):
//   uploadAdd   → POST /api/vocab                  (VocabularyClient.add)
//   batchDelete → POST /api/vocab/batch-delete     (VocabularyClient.batchDelete)
//   trigger     → POST /api/pipeline               (PipelineClient.trigger)
//   pushReview  → PATCH /api/vocab/review-events
//                 + PATCH /api/vocab/review         (TodayReviewClient)
//   pull        → GET /api/vocab                    (VocabularyClient.list)
//
// batchDelete + trigger were previously left UNBOUND because the frozen base
// lacked VocabularyClient.batchDelete / PipelineClient.trigger; the coordinator
// then reported those steps as `skipped`. Both client methods + their mock
// routes now exist, so the steps are bound and RUN. The three-bucket delete
// reconcile (stateMachine.applyDeleteReconcile, transcribed from
// docs/reference/sync_lifecycle.md §批次刪除) consumes the deleted_words /
// not_found / failed buckets directly from the BatchDeleteResponse.

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

    async batchDelete(words, notebookId) {
      // BatchDeleteResponse is a superset of the port's BatchDeleteResult; map
      // the three reconcile buckets (the `deleted` count is derivable and unused
      // by the state machine, which keys off deleted_words/not_found/failed).
      const r = await api.vocabulary.batchDelete(words, { notebookId })
      return {
        deleted_words: r.deleted_words,
        not_found: r.not_found,
        failed: r.failed,
      }
    },

    async triggerPipeline(notebookId) {
      // POST /api/pipeline — fire-and-forget background enrichment. The backend
      // returns immediately with a queued status; the coordinator's trigger step
      // is soft (never flips the run verdict), so we await + discard the body.
      await api.pipeline.trigger(notebookId)
    },

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
