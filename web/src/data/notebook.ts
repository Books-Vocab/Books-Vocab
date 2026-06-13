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
 * Notebook domain 的 TanStack Query hooks — P2.2② surface 遷移的範式（樂觀寫入）。
 *
 * 取代手刻 useNotebookApiStore（useState(raw) + useEffect(fetch) + 三個 mutation
 * 各自手管 optimistic/rollback）：list 走 useQuery（cache / dedup / retry / staleTime），
 * 寫入走 useMutation 並在 query cache 上做樂觀更新——onMutate 先 cancel + snapshot +
 * 樂觀套用，onError rollback 回 snapshot，onSettled 一律 invalidate notebooks.all 對齊
 * 伺服器真相。樂觀邏輯下沉到 cache 層而非 component state，故跨 surface 共享同一份。
 *
 * 純 helper（buildOptimisticNotebook / appendNotebook / replaceNotebookId /
 * renameNotebookName / removeNotebook）抽出做為無 DOM 可單元測的 seam；mutation 的
 * onMutate 只是組合這些 helper + cache I/O。
 *
 * 錯誤型別一律 ApiError，呼叫端讀 .status / .code / isUnauthorized 分流無需 instanceof。
 *
 * 已知限制（可接受）：rollback 是 whole-list snapshot。若 mutation A、B 同時 in-flight
 * 且 A 失敗，A 的 onError 還原的是「B 套用前」的快照 → 暫時蓋掉 B 的樂觀 delta，直到
 * B 自己的 onSettled invalidate 重抓對齊伺服器。這是 list-snapshot recipe 的標準取捨；
 * notebook 為單人低並發 surface，且 always-invalidate 保證最終收斂，故不額外做 per-id 合併。
 */

// ─── 純 helper（可單元測，無 react-query / DOM 依賴）─────────────────────────

/** 組一個樂觀 notebook（尚未落地，id 為 temp 佔位）。 */
export function buildOptimisticNotebook(name: string, tempId: string): NotebookResponse {
  return {
    id: tempId,
    name,
    color: '#AFC2D3',
    coverPattern: null,
    sortOrder: 999,
    isDefault: false,
    isDeleted: false,
    cardCount: 0,
    updatedAt: null,
  }
}

/** 樂觀插入到列表尾端。 */
export function appendNotebook(
  list: NotebookResponse[],
  nb: NotebookResponse,
): NotebookResponse[] {
  return [...list, nb]
}

/** 伺服器回真實 record 後，用真 id 取代 temp 佔位（避免 invalidate 前的 id 抖動）。 */
export function replaceNotebookId(
  list: NotebookResponse[],
  tempId: string,
  real: NotebookResponse,
): NotebookResponse[] {
  return list.map((n) => (n.id === tempId ? real : n))
}

/** 樂觀改名（依 id 命中）。 */
export function renameNotebookName(
  list: NotebookResponse[],
  id: string,
  name: string,
): NotebookResponse[] {
  return list.map((n) => (n.id === id ? { ...n, name } : n))
}

/** 樂觀移除（依 id 命中）。 */
export function removeNotebook(list: NotebookResponse[], id: string): NotebookResponse[] {
  return list.filter((n) => n.id !== id)
}

// ─── hooks ──────────────────────────────────────────────────────────────────

/** GET /api/notebooks — 單字本列表。 */
export function useNotebooksQuery() {
  const api = useApi()
  return useQuery<NotebookResponse[], ApiError>({
    queryKey: queryKeys.notebooks.all,
    queryFn: () => api.notebook.list(),
  })
}

type CreateContext = { previous: NotebookResponse[] | undefined; tempId: string }

/** POST /api/notebooks — 樂觀新增；失敗 rollback，落定後 invalidate。 */
export function useCreateNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<NotebookResponse, ApiError, NotebookCreateRequest, CreateContext>({
    mutationFn: (req) => api.notebook.create(req),
    onMutate: async (req) => {
      await qc.cancelQueries({ queryKey: queryKeys.notebooks.all })
      const previous = qc.getQueryData<NotebookResponse[]>(queryKeys.notebooks.all)
      const tempId = `optimistic-${Date.now()}`
      const optimistic = buildOptimisticNotebook(req.name, tempId)
      qc.setQueryData<NotebookResponse[]>(queryKeys.notebooks.all, (old) =>
        appendNotebook(old ?? [], optimistic),
      )
      return { previous, tempId }
    },
    onSuccess: (created, _req, ctx) => {
      if (!ctx) return
      qc.setQueryData<NotebookResponse[]>(queryKeys.notebooks.all, (old) =>
        replaceNotebookId(old ?? [], ctx.tempId, created),
      )
    },
    onError: (_err, _req, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.notebooks.all, ctx.previous)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    },
  })
}

type ListContext = { previous: NotebookResponse[] | undefined }

/** PATCH /api/notebooks/{id} — 樂觀改名；失敗 rollback，落定後 invalidate。 */
export function useUpdateNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<
    NotebookResponse,
    ApiError,
    { id: string; req: NotebookUpdateRequest },
    ListContext
  >({
    mutationFn: ({ id, req }) => api.notebook.update(id, req),
    onMutate: async ({ id, req }) => {
      await qc.cancelQueries({ queryKey: queryKeys.notebooks.all })
      const previous = qc.getQueryData<NotebookResponse[]>(queryKeys.notebooks.all)
      if (req.name != null) {
        const name = req.name
        qc.setQueryData<NotebookResponse[]>(queryKeys.notebooks.all, (old) =>
          renameNotebookName(old ?? [], id, name),
        )
      }
      return { previous }
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.notebooks.all, ctx.previous)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    },
  })
}

/** DELETE /api/notebooks/{id} — 樂觀移除；失敗 rollback，落定後 invalidate。 */
export function useDeleteNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<{ deleted: string; cardsDeleted: number }, ApiError, string, ListContext>({
    mutationFn: (id) => api.notebook.delete(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: queryKeys.notebooks.all })
      const previous = qc.getQueryData<NotebookResponse[]>(queryKeys.notebooks.all)
      qc.setQueryData<NotebookResponse[]>(queryKeys.notebooks.all, (old) =>
        removeNotebook(old ?? [], id),
      )
      return { previous }
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.notebooks.all, ctx.previous)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    },
  })
}
