/**
 * Query key 工廠 — TanStack Query cache / invalidation 的單一真相。
 *
 * 設計（正規化契約，每個 domain 一致）：每域恆有 `all` collection root；detail /
 * 過濾型 key 一律以 `all` 為前綴。如此 `invalidateQueries({ queryKey: <domain>.all })`
 * 會 partial-match 命中該 domain 的所有 query（list + 各 detail/filtered），mutation
 * 後一次失效、自動重抓。新增 domain 必須沿用 `{ all, detail?, <filtered>? }` 形狀，
 * 新增 query 一律從此檔取 key，禁止在 hook 內手寫字串陣列（否則 invalidation 會因
 * key 漂移而漏命中）。
 *
 * 維護鐵則：root segment（陣列首元素）跨 domain 必須互異，避免跨域誤命中。
 */
export const queryKeys = {
  library: {
    all: ['library'] as const,
  },
  notebooks: {
    all: ['notebooks'] as const,
    detail: (id: string) => ['notebooks', id] as const,
  },
  vocab: {
    all: ['vocab'] as const,
    /** 卡片列表，可選 notebook 過濾維度（缺省 null = 全部）。 */
    cards: (notebookId?: string) => ['vocab', 'cards', notebookId ?? null] as const,
  },
  todayReview: {
    all: ['today-review'] as const,
  },
  podcast: {
    all: ['podcast'] as const,
    series: ['podcast', 'series'] as const,
  },
  user: {
    all: ['user'] as const,
    profile: ['user', 'profile'] as const,
  },
} as const
