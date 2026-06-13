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
 * Notebook domain 的 TanStack Query hooks — P2 資料層的範式 exemplar。
 *
 * 取代手刻 useXApiStore（useState(status) + useEffect(fetch) + 自管 retry）：
 * useQuery 提供 data / isPending / isError / refetch + 跨 surface cache 共享 + dedup；
 * mutation onSuccess 走 queryKeys.notebooks.all 一次 invalidate → list 與所有 detail
 * 自動重抓，寫入後 UI 即時一致。所有 key 取自 queryKeys（禁止 hook 內手寫陣列）。
 *
 * 邊界：hooks 依賴 <ApiProvider>（useApi）與 <QueryProvider>（QueryClientProvider）
 * 雙 context；兩者皆由 shell 路徑掛載，parity capture 路徑不呼叫這些 hooks。
 *
 * 錯誤型別：query/mutation 一律以 ApiError 為 error generic，呼叫端讀 mutation.error /
 * query.error 時無需 instanceof 收窄即可拿 .status / .code / isUnauthorized /
 * isForbidden 做分流（paywall / 重新登入）。queryFn 拋的恆是 ApiError（transport 層
 * 統一封裝 http/network/parse），故型別誠實。
 */

/** GET /api/notebooks — 單字本列表。 */
export function useNotebooksQuery() {
  const api = useApi()
  return useQuery<NotebookResponse[], ApiError>({
    queryKey: queryKeys.notebooks.all,
    queryFn: () => api.notebook.list(),
  })
}

/** POST /api/notebooks — 建立單字本，成功後失效列表。 */
export function useCreateNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<NotebookResponse, ApiError, NotebookCreateRequest>({
    mutationFn: (req) => api.notebook.create(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    },
  })
}

/** PATCH /api/notebooks/{id} — 更新單字本，成功後失效整個 domain（all 前綴已涵蓋 detail）。 */
export function useUpdateNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<NotebookResponse, ApiError, { id: string; req: NotebookUpdateRequest }>({
    mutationFn: ({ id, req }) => api.notebook.update(id, req),
    onSuccess: () => {
      // all 是 detail 的前綴 → partial-match 一併失效 list 與該 detail，無需再點名 detail。
      qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    },
  })
}

/** DELETE /api/notebooks/{id} — 刪除單字本，成功後失效列表。 */
export function useDeleteNotebookMutation() {
  const api = useApi()
  const qc = useQueryClient()
  return useMutation<{ deleted: string; cardsDeleted: number }, ApiError, string>({
    mutationFn: (id) => api.notebook.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.notebooks.all })
    },
  })
}
