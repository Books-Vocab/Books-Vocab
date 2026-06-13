import { useCallback, useMemo, useState } from 'react'
import { useApi } from '../../api/ApiContext'
import {
  detectFormat,
  parseEpub,
  parseMarkdown,
  parseTxt,
  epubjsExtractor,
} from '../../import'
import {
  applyParseOutcome,
  confirmableCount,
  isConfirmable,
  removeItem,
  toParsing,
  toUploading,
  updateItem,
  uploadItem,
  type ImportItem,
  type LibraryLike,
  type ParseOutcome,
} from './importFlowMachine'

/**
 * import-flow surface hook — picked Files → drafts (via the import engine) →
 * per-file status machine → on confirm, LibraryClient.create per book with the
 * draft's idempotent clientBookId, optimistic per-item status + error/retry.
 *
 * The status transitions are PURE (importFlowMachine.ts, unit-tested without
 * jsdom against a mock client). This hook only owns React state + browser I/O
 * (reading File bytes) + the real engine binding + the real LibraryClient.
 *
 * Honest boundary: confirm-import POSTs to /api/library/books (idempotent via
 * client_book_id). The "open import from the bookshelf" entry-point is OUT OF
 * SCOPE here (it touches the shell/bookshelf surface owned by a concurrent run)
 * — this surface is reachable standalone at ?surface=import-flow.
 */

export interface ImportFlowState {
  items: ImportItem[]
  /** How many items the confirm action will (re)upload. */
  confirmableCount: number
  /** True while any item is parsing or uploading. */
  isBusy: boolean
  /** Pick new files (appends, parses each). */
  addFiles: (files: File[]) => void
  /** Drop an item from the list (cancel before/after upload). */
  remove: (id: string) => void
  /** Upload every confirmable item. */
  confirmImport: () => Promise<void>
  /** Re-upload a single previously-failed item. */
  retry: (id: string) => Promise<void>
}

/** Read a File's bytes / text and run the right engine parser → ParseOutcome. */
async function parseFile(file: File): Promise<ParseOutcome> {
  const detected = detectFormat(file.name, file.type)
  if (!detected.ok) {
    return { ok: false, code: detected.code, message: detected.message }
  }

  try {
    if (detected.format === 'epub') {
      const data = await file.arrayBuffer()
      const result = await parseEpub({
        filename: file.name,
        data,
        sizeBytes: file.size,
        extractor: epubjsExtractor,
      })
      return result.ok
        ? { ok: true, draft: result.draft }
        : { ok: false, code: result.code, message: result.message }
    }

    const content = await file.text()
    const result =
      detected.format === 'md'
        ? parseMarkdown({ filename: file.name, content, sizeBytes: file.size })
        : parseTxt({ filename: file.name, content, sizeBytes: file.size })
    return result.ok
      ? { ok: true, draft: result.draft }
      : { ok: false, code: result.code, message: result.message }
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err)
    return { ok: false, code: 'parse_failed', message: `Failed to read file: ${detail}` }
  }
}

/** Stable per-pick id (NOT the idempotency key; that's draft.clientBookId). */
let pickSeq = 0
function nextPickId(): string {
  pickSeq += 1
  return `pick-${Date.now()}-${pickSeq}`
}

export function useImportFlow(): ImportFlowState {
  const api = useApi()
  const client: LibraryLike = api.library
  const [items, setItems] = useState<ImportItem[]>([])

  const addFiles = useCallback((files: File[]) => {
    const fresh = files.map<ImportItem>((file) => ({
      id: nextPickId(),
      filename: file.name,
      sizeBytes: file.size,
      status: 'pending',
    }))
    setItems((prev) => [...prev, ...fresh])

    // Parse each newly-picked file; fold the outcome back by id.
    fresh.forEach((item, i) => {
      const file = files[i]
      setItems((prev) => updateItem(prev, item.id, toParsing))
      void parseFile(file).then((outcome) => {
        setItems((prev) => updateItem(prev, item.id, (it) => applyParseOutcome(it, outcome)))
      })
    })
  }, [])

  const remove = useCallback((id: string) => {
    setItems((prev) => removeItem(prev, id))
  }, [])

  /** Upload one item by id (used by both confirmImport and retry). */
  const uploadOne = useCallback(
    async (id: string) => {
      // Snapshot the item; bail if it is no longer confirmable.
      let target: ImportItem | undefined
      setItems((prev) => {
        target = prev.find((it) => it.id === id)
        if (target == null || !isConfirmable(target)) return prev
        return updateItem(prev, id, toUploading)
      })
      if (target == null || !isConfirmable(target)) return
      const next = await uploadItem(target, client)
      setItems((prev) => updateItem(prev, id, () => next))
    },
    [client],
  )

  const confirmImport = useCallback(async () => {
    // Capture the current confirmable ids; uploadOne re-checks each at run time.
    const ids = items.filter(isConfirmable).map((it) => it.id)
    await Promise.all(ids.map((id) => uploadOne(id)))
  }, [items, uploadOne])

  const retry = useCallback(
    async (id: string) => {
      await uploadOne(id)
    },
    [uploadOne],
  )

  const isBusy = useMemo(
    () => items.some((it) => it.status === 'parsing' || it.status === 'uploading'),
    [items],
  )

  return {
    items,
    confirmableCount: confirmableCount(items),
    isBusy,
    addFiles,
    remove,
    confirmImport,
    retry,
  }
}
