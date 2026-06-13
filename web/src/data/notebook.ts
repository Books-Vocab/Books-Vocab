import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api'
import { useApi } from '../api/ApiContext'
import type {
  NotebookCreateRequest,
  NotebookResponse,
  NotebookUpdateRequest,
} from '../api/types'
import { queryKeys } from './queryKeys'

/**
 * Notebook domain 的 TanStack Query hooks — P2 資料層的「樂觀 CRUD」範式 exemplar
 *（對照 vocab.ts 的 query-only 範式）。query 提供跨 surface cache / dedup；mutation
 * 採 react-query 標準樂觀更新：onMutate 取消在途、快照、setQueryData 樂觀寫入 →
 * onError 用快照 rollback → onSettled invalidate 與伺服器對帳。即時回饋 UX 由樂觀寫入
 * 提供，最終一致由 invalidate 保證。
 *
 * 樂觀寫入的純 cache-transform 抽成下方 helper（可單測，不需 jsdom）；hook 只做
 * react-query 接線。錯誤 generic = ApiError，呼叫端讀 .status/.code 無需收窄。
 *
 * 邊界：依賴 <ApiProvider>（useApi）與 <QueryProvider>（QueryClientProvider）雙
 * context，皆由 shell 路徑掛載；parity capture 路徑不呼叫這些 hooks。
 */

// ── 純 cache-transform helpers（樂觀更新的資料變換，單測於 notebook.test.ts）─────

/** 從 create request 造出樂觀佔位 NotebookResponse（伺服器回應前先上畫面）。 */
export function buildOptimisticNotebook(
  id: string,
  req: NotebookCreateRequest,
): NotebookResponse {
  return {
    id,
    name: req.name.trim(),
    color: req.color ?? null,
    coverPattern: req.cover_pattern ?? null,
    sortOrder: 999,
    isDefault: false,
    isDeleted: false,
    cardCount: 0,
    updatedAt: null,
  }
}

/** 樂觀插入到列尾（add）。 */
export function appendNotebook(
  list: NotebookResponse[],
  nb: NotebookResponse,
): NotebookResponse[] {
  return [...list, nb]
}

/** 以真實實體換掉樂觀佔位（add 成功對帳，避免 invalidate refetch 的閃動）。 */
export function replaceNotebookId(
  list: NotebookResponse[],
  id: string,
  replacement: NotebookResponse,
): NotebookResponse[] {
  return list.map((n) => (n.id === id ? replacement : n))
}

/** 樂觀改名（rename，只動目標 id）。 */
export function renameNotebookName(
  list: NotebookResponse[],
  id: string,
  name: string,
): NotebookResponse[] {
  return list.map((n) => (n.id === id ? { ...n, name } : n))
}

/** 樂觀刪除（delete，按 id 濾除）。 */
export function removeNotebook(
  list: NotebookResponse[],
  id: string,
): NotebookResponse[] {
  return list.filter((n) => n.id !== id)
}

// ── hooks ──────────────────────────────────────────────────────────────────

const ALL = queryKeys.notebooks.all

/** GET /api/notebooks — 單字本列表。 */
export function useNotebooksQuery() {
  const api = useApi()
  return useQuery<NotebookResponse[], ApiError>({
    queryKey: ALL,
    queryFn: () => api.notebook.list(),
  })
}

/** rollback context：onMutate 取得的列表快照，onError 還原用。 */
type NotebookRollback = { previous?: NotebookResponse[] }

/**
 * POST /api/notebooks — 樂觀建立：先插佔位 → 成功以真實實體對換 → 失敗 rollback →
 * 不論成敗 invalidate 對帳。回傳 onMutate 造的樂觀 id 供 onSuccess 對換。
 */
export function useCreateNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<
    NotebookResponse,
    ApiError,
    NotebookCreateRequest,
    NotebookRollback & { optimisticId: string }
  >({
    mutationFn: (req) => api.notebook.create(req),
    onMutate: async (req) => {
      await qc.cancelQueries({ queryKey: ALL })
      const previous = qc.getQueryData<NotebookResponse[]>(ALL)
      const optimisticId = `optimistic-${Date.now()}`
      const optimistic = buildOptimisticNotebook(optimisticId, req)
      qc.setQueryData<NotebookResponse[]>(ALL, (old) => appendNotebook(old ?? [], optimistic))
      return { previous, optimisticId }
    },
    onSuccess: (created, _req, ctx) => {
      qc.setQueryData<NotebookResponse[]>(ALL, (old) =>
        replaceNotebookId(old ?? [], ctx.optimisticId, created),
      )
    },
    onError: (_e, _req, ctx) => {
      if (ctx?.previous) qc.setQueryData(ALL, ctx.previous)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ALL })
    },
  })
}

/** PATCH /api/notebooks/{id} — 樂觀改名：快照 → 樂觀改 → 失敗 rollback → invalidate。 */
export function useUpdateNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<
    NotebookResponse,
    ApiError,
    { id: string; req: NotebookUpdateRequest },
    NotebookRollback
  >({
    mutationFn: ({ id, req }) => api.notebook.update(id, req),
    onMutate: async ({ id, req }) => {
      await qc.cancelQueries({ queryKey: ALL })
      const previous = qc.getQueryData<NotebookResponse[]>(ALL)
      if (typeof req.name === 'string') {
        qc.setQueryData<NotebookResponse[]>(ALL, (old) =>
          renameNotebookName(old ?? [], id, req.name as string),
        )
      }
      return { previous }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(ALL, ctx.previous)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ALL })
    },
  })
}

/** DELETE /api/notebooks/{id} — 樂觀刪除：快照 → 樂觀濾除 → 失敗 rollback（整列快照還原，
 * 順序精確）→ invalidate。 */
export function useDeleteNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<{ deleted: string; cardsDeleted: number }, ApiError, string, NotebookRollback>({
    mutationFn: (id) => api.notebook.delete(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ALL })
      const previous = qc.getQueryData<NotebookResponse[]>(ALL)
      qc.setQueryData<NotebookResponse[]>(ALL, (old) => removeNotebook(old ?? [], id))
      return { previous }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(ALL, ctx.previous)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ALL })
    },
  })
}
