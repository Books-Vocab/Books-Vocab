// P2 資料層 barrel — TanStack Query 接 ApiClient domain clients。
// 用法：surface 從此匯入 query/mutation hooks，取代手刻 useXApiStore。
export { createQueryClient, shouldRetry } from './queryClient'
export { QueryProvider } from './QueryProvider'
export { queryKeys } from './queryKeys'
export {
  useNotebooksQuery,
  useCreateNotebookMutation,
  useUpdateNotebookMutation,
  useDeleteNotebookMutation,
} from './notebook'
