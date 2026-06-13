/**
 * Reader 引擎選擇純邏輯（Phase 2）。
 *
 * 契約（shell/nav.ts ScreenParams.format）：PDF/EPUB/TXT/MD 皆 push 同一 `reader`
 * screen；reader-live 依 nav param `format` 切渲染引擎（'pdf' → pdfjs-dist，其餘 →
 * epub.js）。param 省略時落回該書 metadata 的 format（BookMetadataResponse.format）。
 *
 * 把此選擇抽成純函式，令引擎路由可單測，並令 LiveReaderScreen 只負責 wiring
 * （讀 nav param / book metadata → 決定掛 PDF 還是 EPUB 引擎）。
 */

/** reader-live 目前真實支援的兩種渲染引擎。txt/md 尚未實作引擎 → 落回 epub 殼層提示。 */
export type ReaderEngine = 'pdf' | 'epub'

/** nav param / metadata 可能攜帶的書籍格式字串（寬鬆輸入，含大小寫雜訊）。 */
type RawFormat = string | null | undefined

/** 是否為 PDF 引擎格式（大小寫不敏感）。 */
export function isPdfFormat(raw: RawFormat): boolean {
  return (raw ?? '').trim().toLowerCase() === 'pdf'
}

/**
 * 解析有效渲染引擎：nav param 優先，省略時落回 book metadata format。
 *
 * - 'pdf'（任一來源，大小寫不敏感）→ 'pdf'（pdfjs-dist 引擎）。
 * - 其餘已知格式（epub/txt/md）或未知格式 → 'epub'（epub.js 路徑，與既有相容）。
 *   保守落回 epub：未知格式不貿然丟給 PDF 引擎（會直接解析失敗）。
 *
 * @param navFormat  nav.params.format（深層導航旗標；省略 = undefined）
 * @param bookFormat BookMetadataResponse.format（後端落回值）
 */
export function resolveReaderFormat(navFormat: RawFormat, bookFormat: RawFormat): ReaderEngine {
  const effective = navFormat ?? bookFormat
  return isPdfFormat(effective) ? 'pdf' : 'epub'
}
