import { describe, expect, it } from 'vitest'
import { createApiClient, type ApiClient } from '../../api'

/**
 * P7b data-plane wiring — exercises the exact LibraryClient/NotebookClient calls
 * useBookshelfApiStore makes, against the in-process mock backend, proving the
 * contracts the store relies on actually hold: create (with author/language),
 * update notebook_id (bind / unbind), and durable soft-delete (DELETE).
 *
 * (The hook itself is React-stateful and the per-card menu UI is occluded by the
 * frozen AppShell `.shell-hot-bookgrid` overlay in shell mode — see store doc —
 * so we verify the API seam directly, which is what the store wires through.)
 */
function authed(): ApiClient {
  return createApiClient({ mode: 'mock', getToken: () => 'mock-access-token' })
}

describe('bookshelf API wiring (mock backend)', () => {
  it('create persists author + language metadata (epubjs parse path)', async () => {
    const api = authed()
    const created = await api.library.create({
      client_book_id: 'web-epub-12345-the-odyssey',
      title: 'The Odyssey',
      author: 'Homer',
      language: 'en',
      format: 'epub',
    })
    expect(created.title).toBe('The Odyssey')
    expect(created.author).toBe('Homer')
    expect(created.language).toBe('en')
    expect(created.format).toBe('epub')
    expect(created.is_deleted).toBe(false)

    const list = await api.library.list()
    expect(list.some((b) => b.id === created.id)).toBe(true)
  })

  it('create is idempotent on client_book_id', async () => {
    const api = authed()
    const req = { client_book_id: 'web-epub-999-dup', title: 'Dup', format: 'epub' }
    const a = await api.library.create(req)
    const b = await api.library.create(req)
    expect(b.id).toBe(a.id)
  })

  it('update binds and unbinds notebook_id (PATCH)', async () => {
    const api = authed()
    const book = await api.library.create({
      client_book_id: 'web-epub-555-bindable',
      title: 'Bindable',
      format: 'epub',
    })
    expect(book.notebook_id).toBeNull()

    const notebooks = await api.notebook.list()
    expect(notebooks.length).toBeGreaterThan(0)
    const nbId = notebooks[0].id

    const bound = await api.library.update(book.id, { notebook_id: nbId })
    expect(bound.notebook_id).toBe(nbId)

    const unbound = await api.library.update(book.id, { notebook_id: null })
    expect(unbound.notebook_id).toBeNull()
  })

  it('delete soft-deletes durably (DELETE) and drops from list', async () => {
    const api = authed()
    const book = await api.library.create({
      client_book_id: 'web-epub-777-deletable',
      title: 'Deletable',
      format: 'epub',
    })
    const before = await api.library.list()
    expect(before.some((b) => b.id === book.id)).toBe(true)

    const deleted = await api.library.delete(book.id)
    expect(deleted.deleted).toBe(book.id)

    const after = await api.library.list()
    expect(after.some((b) => b.id === book.id)).toBe(false)
  })
})
