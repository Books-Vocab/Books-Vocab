import { describe, expect, it } from 'vitest'
import { isPdfFormat, resolveReaderFormat } from './readerFormat'

/**
 * Reader 引擎選擇純邏輯（Phase 2）。
 *
 * 契約（nav.ts ScreenParams.format）：reader-live route 由 nav param `format`
 * 攜帶（'pdf' → pdfjs-dist，其餘 → epub.js）；param 省略時落回書 metadata 的
 * format。此模組把「nav param + book metadata → 有效引擎」抽成純函式，令引擎
 * 路由可單測，並令 LiveReaderScreen 只負責 wiring。
 */
describe('resolveReaderFormat（nav param 優先，落回 book metadata）', () => {
  it('nav param 為 pdf → pdf（不看 metadata）', () => {
    expect(resolveReaderFormat('pdf', 'epub')).toBe('pdf')
  })

  it('nav param 為 epub → epub', () => {
    expect(resolveReaderFormat('epub', 'pdf')).toBe('epub')
  })

  it('nav param 省略 → 落回 book metadata format（pdf）', () => {
    expect(resolveReaderFormat(undefined, 'pdf')).toBe('pdf')
  })

  it('nav param 省略 → 落回 book metadata format（epub）', () => {
    expect(resolveReaderFormat(undefined, 'epub')).toBe('epub')
  })

  it('nav param 與 metadata 皆缺 → 預設 epub（與既有路徑相容）', () => {
    expect(resolveReaderFormat(undefined, null)).toBe('epub')
    expect(resolveReaderFormat(undefined, undefined)).toBe('epub')
  })

  it('metadata 大小寫不一致（PDF）→ 正規化為 pdf', () => {
    expect(resolveReaderFormat(undefined, 'PDF')).toBe('pdf')
  })

  it('未知 metadata format → 落回 epub（保守，不嘗試 pdf 引擎）', () => {
    expect(resolveReaderFormat(undefined, 'cbz')).toBe('epub')
  })
})

describe('isPdfFormat', () => {
  it('pdf → true', () => {
    expect(isPdfFormat('pdf')).toBe(true)
  })
  it('epub → false', () => {
    expect(isPdfFormat('epub')).toBe(false)
  })
})
