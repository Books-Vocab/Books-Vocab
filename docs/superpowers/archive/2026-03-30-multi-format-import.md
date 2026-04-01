# Multi-Format Import (TXT / MD / PDF) Implementation Plan

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** iOS app 支援 TXT、MD、PDF 三種格式完整閱讀體驗，含劃線詞彙捕捉。
**Architecture:** TXT/MD on-device 轉 EPUB → 複用 Readium Reader；PDF 用 PDFKit 原生渲染 + UIEditMenuInteraction → 複用 `ReaderTranslationHandler`。Book model 加 `format` 欄位 + `@Attribute(originalName:)` 處理 `epubFileName→fileName` rename。
**Tech Stack:** SwiftUI, SwiftData (`@Attribute(originalName:)`), PDFKit, ZIPFoundation (SPM), apple/swift-markdown (SPM)

---

## File Map

### iOS — New
| File | Responsibility |
|------|---------------|
| `ios/BooksBrowser/Services/EPUBConverter.swift` | TXT/MD → EPUB3 zip 封裝 |
| `ios/BooksBrowser/Views/Reader/PDFReaderView.swift` | PDFKit reader + UIEditMenuInteraction + TranslationPanel 整合 |

### iOS — Modify
| File | Changes |
|------|---------|
| `ios/BooksBrowser/Models/Book.swift` | 加 `BookFormat` enum + `format` 欄位；`epubFileName → fileName`（`@Attribute(originalName:)`）；目錄改 `Books/` |
| `ios/BooksBrowser/Services/BookshelfImporting.swift` | `ImportedBookDraft` 加 `format`、`fileName`；加 TXT/MD/PDF import methods |
| `ios/BooksBrowser/Views/Bookshelf/BookshelfCoordinator.swift` | `importEPUB → importBook(url:format:)`，加 format dispatch；`deleteBook` 改用 `fileName` |
| `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift` | fileImporter 加三種 UTType；`navigationDestination` switch on format；format badge；空狀態文案 |
| `ios/BooksBrowser/Services/BookFileManaging.swift` | `deleteBookFile` 目錄改 `Books/`，加清理 `Originals/` 邏輯 |
| `ios/BooksBrowser/Services/ReaderPublicationLoader.swift` | `book.epubFileURL → book.fileURL` |
| `ios/BooksBrowser/Services/ReadiumService.swift` | `Book.epubsDirectory → Book.booksDirectory`，其他目錄常數 rename |
| `ios/BooksBrowser/Services/ICloudDownloadManager.swift` | 目錄常數 rename |
| `ios/BooksBrowser/BooksBrowserApp.swift` | 目錄常數 rename，`ModelContainer` 不需改（`@Attribute` 處理 migration） |

---

## Task 1: SPM Dependencies

**Files:**
- Modify: `ios/BooksBrowser.xcodeproj/project.pbxproj`（透過 Xcode SPM UI）

- [ ] **Step 1: 加入 ZIPFoundation**
  Xcode → Project → Package Dependencies → 加入：
  `https://github.com/weichsel/ZIPFoundation` 版本 ≥ 0.9.19

- [ ] **Step 2: 加入 swift-markdown**
  加入：`https://github.com/apple/swift-markdown` 版本 ≥ 0.4.0

- [ ] **Step 3: 確認編譯**
  ```bash
  ./ops/ios_build.sh
  ```
  Expected: Exit 0

---

## Task 2: Book Model

**Files:**
- Modify: `ios/BooksBrowser/Models/Book.swift`

- [ ] **Step 1: 在 Book.swift 檔頭加 `BookFormat` enum**

```swift
enum BookFormat: String, Codable {
    case epub, txt, md, pdf
}
```

- [ ] **Step 2: 在 `@Model final class Book` 中加兩個欄位**

  在現有欄位末尾（`progression` 後）加入：
  ```swift
  @Attribute(originalName: "epubFileName") var fileName: String
  var format: BookFormat
  ```
  同時刪除原本的 `var epubFileName: String`。

- [ ] **Step 3: 更新 `init`（加 `format` 參數，default `.epub`）**

```swift
init(
    title: String,
    author: String,
    coverImageData: Data? = nil,
    fileName: String,
    format: BookFormat = .epub
) {
    self.title = title
    self.author = author
    self.coverImageData = coverImageData
    self.fileName = fileName
    self.format = format
    self.dateAdded = Date()
}
```

- [ ] **Step 4: rename 目錄常數與 computed properties（Book.swift 內）**

  全檔 replace：
  - `iCloudEpubsDirectory` → `iCloudBooksDirectory`
  - `localEpubsDirectory` → `localBooksDirectory`
  - `epubsDirectory` → `booksDirectory`
  - `epubFileURL` → `fileURL`
  - 字串 `"EPUBs"` → `"Books"`（出現在目錄路徑的地方）

- [ ] **Step 5: 更新 BookshelfView.swift 的 preview data**

  搜尋 `epubFileName:` 的兩處建構呼叫（L426, L437），改為 `fileName:` + 加 `format: .epub`。

- [ ] **Step 6: 全專案 rename callers**

  用 grep 找出所有用到 `epubFileName`、`epubFileURL`、`iCloudEpubsDirectory`、`localEpubsDirectory`、`epubsDirectory` 的地方（預計出現在 `ReaderPublicationLoader.swift`、`ReadiumService.swift`、`ICloudDownloadManager.swift`、`BooksBrowserApp.swift`、`BookshelfCoordinator.swift`），逐一修正。

- [ ] **Step 7: 確認編譯**
  ```bash
  ./ops/ios_build.sh
  ```
  Expected: Exit 0

- [ ] **Step 8: Commit**
  ```
  ios: Book model — add BookFormat, rename epubFileName→fileName via @Attribute, Books/ directory
  ```

---

## Task 3: EPUBConverter

**Files:**
- Create: `ios/BooksBrowser/Services/EPUBConverter.swift`

- [ ] **Step 1: 建立 `EPUBConverter.swift`**

```swift
import Foundation
import ZIPFoundation
import Markdown

enum EPUBConverterError: Error, LocalizedError {
    case fileTooLarge(Int)
    case encodingFailed
    case archiveCreationFailed

    var errorDescription: String? {
        switch self {
        case .fileTooLarge(let mb): return "檔案過大（\(mb)MB），上限 20MB"
        case .encodingFailed: return "無法識別檔案編碼（請確認為 UTF-8）"
        case .archiveCreationFailed: return "EPUB 封裝失敗"
        }
    }
}

struct EPUBConverter {
    static let maxBytes = 20 * 1024 * 1024

    func convertTXT(at url: URL, title: String) throws -> URL {
        let data = try Data(contentsOf: url)
        guard data.count <= Self.maxBytes else {
            throw EPUBConverterError.fileTooLarge(data.count / 1024 / 1024)
        }
        guard let text = String(data: data, encoding: .utf8)
                      ?? String(data: data, encoding: .isoLatin1) else {
            throw EPUBConverterError.encodingFailed
        }
        let chapters = chapterize(text: text)
            .map { "<p>" + htmlEscape($0).replacingOccurrences(of: "\n", with: "</p><p>") + "</p>" }
        return try buildEPUB(title: title, chapters: chapters)
    }

    func convertMD(at url: URL, title: String) throws -> URL {
        let data = try Data(contentsOf: url)
        guard data.count <= Self.maxBytes else {
            throw EPUBConverterError.fileTooLarge(data.count / 1024 / 1024)
        }
        guard let md = String(data: data, encoding: .utf8) else {
            throw EPUBConverterError.encodingFailed
        }
        let doc = Document(parsing: md)
        var visitor = HTMLVisitor()
        let html = visitor.visit(doc)
        return try buildEPUB(title: title, chapters: [html])
    }

    // MARK: - Private

    private func chapterize(text: String, maxChars: Int = 5000) -> [String] {
        let paras = text.components(separatedBy: "\n\n").filter { !$0.isEmpty }
        var chapters: [String] = []
        var current = ""
        for para in paras {
            if current.count + para.count > maxChars, !current.isEmpty {
                chapters.append(current)
                current = para
            } else {
                current += current.isEmpty ? para : "\n\n" + para
            }
        }
        if !current.isEmpty { chapters.append(current) }
        return chapters.isEmpty ? [""] : chapters
    }

    private func htmlEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
         .replacingOccurrences(of: "<", with: "&lt;")
         .replacingOccurrences(of: ">", with: "&gt;")
    }

    private func buildEPUB(title: String, chapters: [String]) throws -> URL {
        let dest = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString + ".epub")

        guard let archive = Archive(url: dest, accessMode: .create) else {
            throw EPUBConverterError.archiveCreationFailed
        }

        // mimetype — MUST be first entry, stored (no compression)
        let mime = "application/epub+zip"
        try archive.addEntry(with: "mimetype", type: .file,
                             uncompressedSize: Int64(mime.utf8.count),
                             compressionMethod: .none) { _, _ in Data(mime.utf8) }

        // META-INF/container.xml
        try archive.addEntry(with: "META-INF/container.xml", data: Data("""
            <?xml version="1.0"?>
            <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OEBPS/content.opf"
                          media-type="application/oebps-package+xml"/>
              </rootfiles>
            </container>
            """.utf8))

        var items = "", spine = ""
        for (i, html) in chapters.enumerated() {
            let id = String(format: "ch%03d", i + 1)
            let xhtml = """
                <?xml version="1.0" encoding="UTF-8"?>
                <!DOCTYPE html>
                <html xmlns="http://www.w3.org/1999/xhtml">
                <head><meta charset="UTF-8"/><title>\(htmlEscape(title))</title></head>
                <body>\(html)</body>
                </html>
                """
            try archive.addEntry(with: "OEBPS/\(id).xhtml", data: Data(xhtml.utf8))
            items += "<item id=\"\(id)\" href=\"\(id).xhtml\" media-type=\"application/xhtml+xml\"/>\n"
            spine += "<itemref idref=\"\(id)\"/>\n"
        }

        try archive.addEntry(with: "OEBPS/content.opf", data: Data("""
            <?xml version="1.0" encoding="UTF-8"?>
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:title>\(htmlEscape(title))</dc:title>
                <dc:language>zh</dc:language>
              </metadata>
              <manifest>\(items)</manifest>
              <spine>\(spine)</spine>
            </package>
            """.utf8))

        return dest
    }
}

// MARK: - Markdown → HTML

private struct HTMLVisitor: MarkupVisitor {
    typealias Result = String

    mutating func defaultVisit(_ m: any Markup) -> String { children(m) }
    mutating func visitDocument(_ d: Document) -> String { children(d) }
    mutating func visitHeading(_ h: Heading) -> String {
        let n = min(h.level, 6)
        return "<h\(n)>\(children(h))</h\(n)>\n"
    }
    mutating func visitParagraph(_ p: Paragraph) -> String { "<p>\(children(p))</p>\n" }
    mutating func visitText(_ t: Text) -> String {
        t.string
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
    mutating func visitStrong(_ s: Strong) -> String { "<strong>\(children(s))</strong>" }
    mutating func visitEmphasis(_ e: Emphasis) -> String { "<em>\(children(e))</em>" }
    mutating func visitCodeBlock(_ c: CodeBlock) -> String { "<pre><code>\(c.code)</code></pre>\n" }
    mutating func visitInlineCode(_ c: InlineCode) -> String { "<code>\(c.code)</code>" }
    mutating func visitUnorderedList(_ l: UnorderedList) -> String { "<ul>\(children(l))</ul>\n" }
    mutating func visitOrderedList(_ l: OrderedList) -> String { "<ol>\(children(l))</ol>\n" }
    mutating func visitListItem(_ i: ListItem) -> String { "<li>\(children(i))</li>\n" }
    mutating func visitBlockQuote(_ q: BlockQuote) -> String { "<blockquote>\(children(q))</blockquote>\n" }
    mutating func visitSoftBreak(_: SoftBreak) -> String { " " }
    mutating func visitLineBreak(_: LineBreak) -> String { "<br/>" }

    private mutating func children(_ m: any Markup) -> String {
        m.children.map { visit($0) }.joined()
    }
}
```

- [ ] **Step 2: 編譯確認**
  ```bash
  ./ops/ios_build.sh
  ```
  Expected: Exit 0

- [ ] **Step 3: Commit**
  ```
  ios: add EPUBConverter for TXT/MD → EPUB3 conversion
  ```

---

## Task 4: PDFReaderView

**Files:**
- Create: `ios/BooksBrowser/Views/Reader/PDFReaderView.swift`

詞彙捕捉橋接策略：`UIEditMenuInteraction` 注入「翻譯」選項 → 取得 `PDFView.currentSelection?.string` + 當前頁文字作 context → 呼叫現有 `ReaderTranslationHandler.handleWordSelected(word:context:vocabularyContext:)`。

- [ ] **Step 1: 建立 `PDFReaderView.swift`**

```swift
import SwiftUI
import PDFKit
import SwiftData

struct PDFReaderView: View {
    let book: Book
    @Environment(\.modelContext) private var modelContext
    @Environment(\.authManager) private var authManager  // 與 ReaderView 相同注入方式
    @Query private var allVocabulary: [VocabularyEntry]
    @State private var pdfDocument: PDFDocument?
    @State private var loadError: String?
    @State private var handler = ReaderTranslationHandler()
    @State private var showTranslation = false

    // 鏡像 ReaderView+Panels.swift 的 vocabularyContext computed var
    private var vocabularyContext: ReaderVocabularyContext {
        ReaderVocabularyContext(
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: nil,   // PDF 無 Readium Locator，chapterTitle 為 nil 可接受
            notebookId: book.resolvedNotebookId
        )
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            if let doc = pdfDocument {
                PDFKitRepresentable(
                    document: doc,
                    book: book,
                    onWordSelected: { word, context in
                        handler.handleWordSelected(
                            word: word,
                            context: context,
                            vocabularyContext: vocabularyContext
                        )
                        withAnimation(AppMotion.panelState) { showTranslation = true }
                    }
                )
                .ignoresSafeArea()

                // 鏡像 ReaderView+Panels.swift 的 translationPanelContent
                if showTranslation, let selection = handler.wordSelection {
                    TranslationPanel(
                        word: selection.word,
                        result: handler.translationResult,
                        isLoading: handler.isTranslating,
                        isSaved: handler.isSaved,
                        isLoggedIn: authManager.isLoggedIn,
                        isExpanded: handler.isExpanded,
                        explanation: handler.explanationText,
                        isLoadingExplanation: handler.isLoadingExplanation,
                        statusMessage: handler.statusMessage,
                        isExplanationOnly: handler.isExplanationOnly,
                        translationErrorMessage: handler.translationErrorMessage,
                        explanationErrorMessage: handler.explanationErrorMessage,
                        onExpand: { handler.handleExpand() },
                        onDelete: {
                            handler.deleteFromVocabulary(selection.word, context: vocabularyContext)
                            withAnimation(AppMotion.panelState) { showTranslation = false }
                        },
                        onShowDetail: nil,   // PDF 場景不導航到 word detail
                        onDismiss: {
                            handler.dismiss()
                            withAnimation(AppMotion.panelState) { showTranslation = false }
                        }
                    )
                    .transition(.readerPanelReveal)
                }
            } else if let err = loadError {
                ContentUnavailableView(err, systemImage: "doc.fill.badge.exclamationmark")
            } else {
                ProgressView()
            }
        }
        .navigationTitle(book.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { loadPDF() }
    }

    private func loadPDF() {
        guard let url = book.fileURL else { loadError = "找不到 PDF 檔案"; return }
        if let doc = PDFDocument(url: url) { pdfDocument = doc }
        else { loadError = "無法開啟 PDF" }
    }
}

// MARK: - UIViewRepresentable

private struct PDFKitRepresentable: UIViewRepresentable {
    let document: PDFDocument
    let book: Book
    let onWordSelected: (String, String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(book: book, onWordSelected: onWordSelected) }

    func makeUIView(context: Context) -> PDFView {
        let v = PDFView()
        v.document = document
        v.displayMode = .singlePageContinuous
        v.autoScales = true

        // Restore last read page
        if let json = book.lastReadLocatorJSON,
           let data = json.data(using: .utf8),
           let pos = try? JSONDecoder().decode(PDFPosition.self, from: data),
           let page = document.page(at: pos.pageIndex) {
            v.go(to: PDFDestination(page: page, at: .zero))
        }

        // iOS 16+ Edit Menu injection
        let interaction = UIEditMenuInteraction(delegate: context.coordinator)
        v.addInteraction(interaction)
        context.coordinator.pdfView = v

        NotificationCenter.default.addObserver(
            context.coordinator,
            selector: #selector(Coordinator.pageChanged(_:)),
            name: .PDFViewPageChanged,
            object: v
        )
        return v
    }

    func updateUIView(_ uiView: PDFView, context: Context) {}
}

// MARK: - Coordinator

private final class Coordinator: NSObject, UIEditMenuInteractionDelegate {
    weak var pdfView: PDFView?
    private let book: Book
    private let onWordSelected: (String, String) -> Void

    init(book: Book, onWordSelected: @escaping (String, String) -> Void) {
        self.book = book
        self.onWordSelected = onWordSelected
    }

    func editMenuInteraction(
        _ interaction: UIEditMenuInteraction,
        menuFor configuration: UIEditMenuConfiguration,
        suggestedActions: [UIMenuElement]
    ) -> UIMenu? {
        let translateAction = UIAction(title: "翻譯 / 加詞彙") { [weak self] _ in
            guard let self,
                  let text = self.pdfView?.currentSelection?.string,
                  !text.trimmingCharacters(in: .whitespaces).isEmpty else { return }
            let context = self.pdfView?.currentPage?.string.map { String($0.prefix(500)) } ?? ""
            self.onWordSelected(text, context)
        }
        return UIMenu(children: suggestedActions + [translateAction])
    }

    @objc func pageChanged(_ notification: Notification) {
        guard let pdfView, let page = pdfView.currentPage,
              let doc = pdfView.document else { return }
        let idx = doc.index(for: page)
        let pos = PDFPosition(pageIndex: idx)
        if let data = try? JSONEncoder().encode(pos),
           let json = String(data: data, encoding: .utf8) {
            book.lastReadLocatorJSON = json
            book.progression = Double(idx) / Double(max(1, doc.pageCount - 1))
        }
    }
}

private struct PDFPosition: Codable { let pageIndex: Int }
```

- [ ] **Step 2: 確認 `ReaderTranslationHandler` 是否可從外部初始化**
  讀 `ReaderTranslationHandler.swift`，若有必要的 init 參數，調整 PDFReaderView 中的初始化方式。

- [ ] **Step 3: 編譯確認**
  ```bash
  ./ops/ios_build.sh
  ```
  Expected: Exit 0

- [ ] **Step 4: Commit**
  ```
  ios: add PDFReaderView with PDFKit + UIEditMenuInteraction vocab bridge
  ```

---

## Task 5: BookshelfImporting + Coordinator 擴充

**Files:**
- Modify: `ios/BooksBrowser/Services/BookshelfImporting.swift`
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfCoordinator.swift`

- [ ] **Step 1: 更新 `ImportedBookDraft`**

```swift
struct ImportedBookDraft {
    let title: String
    let author: String
    let coverImageData: Data?
    let fileName: String
    let format: BookFormat
}
```

- [ ] **Step 2: 擴充 `BookshelfImporting` protocol**

```swift
@MainActor protocol BookshelfImporting {
    func importBook(from url: URL) async throws -> ImportedBookDraft   // EPUB（保留現有）
    func importTXT(from url: URL) async throws -> ImportedBookDraft
    func importMD(from url: URL) async throws -> ImportedBookDraft
    func importPDF(from url: URL) async throws -> ImportedBookDraft
}
```

- [ ] **Step 3: 在 `BookshelfImportService` 實作三個新 method**

```swift
func importTXT(from url: URL) async throws -> ImportedBookDraft {
    guard url.startAccessingSecurityScopedResource() else { throw ImportError.accessDenied }
    defer { url.stopAccessingSecurityScopedResource() }
    let title = url.deletingPathExtension().lastPathComponent
    // Task.detached offloads 同步 I/O + zip 封裝離開 MainActor，避免 UI 凍結
    let epubTmp = try await Task.detached { try EPUBConverter().convertTXT(at: url, title: title) }.value
    let fileName = epubTmp.lastPathComponent
    let dest = Book.booksDirectory.appendingPathComponent(fileName)
    try FileManager.default.createDirectory(at: Book.booksDirectory,
                                            withIntermediateDirectories: true)
    try FileManager.default.moveItem(at: epubTmp, to: dest)
    // 保留原始檔
    let origDir = Book.booksDirectory.appendingPathComponent("Originals")
    try? FileManager.default.createDirectory(at: origDir, withIntermediateDirectories: true)
    try? FileManager.default.copyItem(at: url, to: origDir.appendingPathComponent(url.lastPathComponent))
    return ImportedBookDraft(title: title, author: "", coverImageData: nil,
                             fileName: fileName, format: .txt)
}

func importMD(from url: URL) async throws -> ImportedBookDraft {
    guard url.startAccessingSecurityScopedResource() else { throw ImportError.accessDenied }
    defer { url.stopAccessingSecurityScopedResource() }
    let title = url.deletingPathExtension().lastPathComponent
    let epubTmp = try await Task.detached { try EPUBConverter().convertMD(at: url, title: title) }.value
    let fileName = epubTmp.lastPathComponent
    let dest = Book.booksDirectory.appendingPathComponent(fileName)
    try FileManager.default.createDirectory(at: Book.booksDirectory,
                                            withIntermediateDirectories: true)
    try FileManager.default.moveItem(at: epubTmp, to: dest)
    let origDir = Book.booksDirectory.appendingPathComponent("Originals")
    try? FileManager.default.createDirectory(at: origDir, withIntermediateDirectories: true)
    try? FileManager.default.copyItem(at: url, to: origDir.appendingPathComponent(url.lastPathComponent))
    return ImportedBookDraft(title: title, author: "", coverImageData: nil,
                             fileName: fileName, format: .md)
}

func importPDF(from url: URL) async throws -> ImportedBookDraft {
    guard url.startAccessingSecurityScopedResource() else { throw ImportError.accessDenied }
    defer { url.stopAccessingSecurityScopedResource() }
    let title = url.deletingPathExtension().lastPathComponent
    // UUID prefix 避免同名 PDF 檔案衝突
    let fileName = UUID().uuidString + "_" + url.lastPathComponent
    let dest = Book.booksDirectory.appendingPathComponent(fileName)
    try FileManager.default.createDirectory(at: Book.booksDirectory,
                                            withIntermediateDirectories: true)
    if !FileManager.default.fileExists(atPath: dest.path) {
        try FileManager.default.copyItem(at: url, to: dest)
    }
    let coverData = PDFDocument(url: dest)
        .flatMap { $0.page(at: 0)?.thumbnail(of: CGSize(width: 300, height: 400), for: .artBox) }
        .flatMap { $0.jpegData(compressionQuality: 0.8) }
    return ImportedBookDraft(title: title, author: "", coverImageData: coverData,
                             fileName: fileName, format: .pdf)
}

enum ImportError: Error { case accessDenied }
```

- [ ] **Step 4: 更新 `BookshelfCoordinator.handleFileImport`**

  修改 `handleFileImport` 中原本的 `importEPUB(from:...)` 呼叫，改為依副檔名 dispatch：

  ```swift
  func handleFileImport(
      _ result: Result<[URL], Error>,
      modelContext: ModelContext,
      importService: any BookshelfImporting
  ) {
      switch result {
      case .success(let urls):
          guard let url = urls.first else { return }
          let ext = url.pathExtension.lowercased()
          let importMethod: (URL) async throws -> ImportedBookDraft
          switch ext {
          case "epub": importMethod = importService.importBook
          case "txt":  importMethod = importService.importTXT
          case "md":   importMethod = importService.importMD
          case "pdf":  importMethod = importService.importPDF
          default:
              errorMessage = "不支援的格式：.\(ext)"
              showError = true
              return
          }
          performImport(url: url, modelContext: modelContext, method: importMethod)
      case .failure(let error):
          errorMessage = error.localizedDescription
          showError = true
      }
  }
  ```

  新增 `performImport` private method（取代原有 `importEPUB`）：

  ```swift
  private func performImport(
      url: URL,
      modelContext: ModelContext,
      method: @escaping (URL) async throws -> ImportedBookDraft
  ) {
      isLoading = true
      loadingMessage = L10n.string("正在匯入...")

      Task {
          do {
              let draft = try await method(url)
              loadingMessage = L10n.string("正在儲存...")
              let book = Book(
                  title: draft.title,
                  author: draft.author,
                  coverImageData: draft.coverImageData,
                  fileName: draft.fileName,
                  format: draft.format
              )
              modelContext.insert(book)
              modelContext.safeSave()
              EPUBGuideTip().invalidate(reason: .actionPerformed)
              isLoading = false
              loadingMessage = ""
          } catch {
              isLoading = false
              loadingMessage = ""
              errorMessage = "\(error)"
              showError = true
          }
      }
  }
  ```

- [ ] **Step 5: 更新 `deleteBook`（L72）**

  ```swift
  fileManager.deleteBookFile(named: book.fileName)
  ```

- [ ] **Step 6: 編譯確認**
  ```bash
  ./ops/ios_build.sh
  ```
  Expected: Exit 0

- [ ] **Step 7: Commit**
  ```
  ios: extend BookshelfImporting + Coordinator for TXT/MD/PDF import
  ```

---

## Task 6: BookshelfView — fileImporter + routing + UI

**Files:**
- Modify: `ios/BooksBrowser/Views/Bookshelf/BookshelfView.swift`

- [ ] **Step 1: 更新 `fileImporter` UTTypes（L72-82）**

```swift
.fileImporter(
    isPresented: $coordinator.isImporting,
    allowedContentTypes: [
        UTType(filenameExtension: "epub") ?? .data,
        .plainText,
        UTType(filenameExtension: "md") ?? .data,
        .pdf,
    ],
    allowsMultipleSelection: false
) { result in
    coordinator.handleFileImport(result, modelContext: modelContext, importService: importService)
}
```

- [ ] **Step 2: 更新 `navigationDestination`（L188-190）**

```swift
.navigationDestination(for: Book.self) { book in
    switch book.format {
    case .epub, .txt, .md:
        ReaderView(book: book)
    case .pdf:
        PDFReaderView(book: book)
    }
}
```

- [ ] **Step 3: 在 `coverView` 佔位符加 format badge（L289-322）**

  在無封面時的 `VStack` 中加入：
  ```swift
  if book.format != .epub {
      Text(book.format.rawValue.uppercased())
          .font(.system(size: 11, weight: .bold, design: .monospaced))
          .padding(.horizontal, 6).padding(.vertical, 2)
          .background(Color.secondary.opacity(0.2))
          .cornerRadius(4)
  }
  ```

- [ ] **Step 4: 更新空狀態文案**

  搜尋 `AppEmptyStateContent` 中「EPUB 電子書」相關字串，改為「匯入 EPUB、TXT、MD 或 PDF 開始閱讀」。

- [ ] **Step 5: 編譯確認**
  ```bash
  ./ops/ios_build.sh
  ```
  Expected: Exit 0

- [ ] **Step 6: Commit**
  ```
  ios: expand fileImporter to TXT/MD/PDF, add format badge, update routing
  ```

---

## Task 7: 整合測試

- [ ] **Step 1: 手動測試清單**

  | 測試案例 | 預期結果 |
  |---------|---------|
  | 匯入 .txt | 書卡出現 "TXT" badge，Readium Reader 可開，可劃線加詞彙 |
  | 匯入 .md（含 h2 / bold / list）| MD 渲染正確 HTML，Readium 正常顯示 |
  | 匯入 .pdf | PDFKit 原生渲染，長按選字 → Edit Menu 含「翻譯 / 加詞彙」 |
  | 翻譯後 TranslationPanel 顯示 | PDF reader 底部出現翻譯結果 |
  | 關閉 PDF 再重開 | 恢復上次頁碼 |
  | 匯入 >20MB TXT | toast 大小限制錯誤 |
  | 非 UTF-8 TXT | Latin-1 fallback 成功，或 toast 提示編碼問題 |
  | 刪除 TXT/MD 書籍 | EPUB 檔 + Originals/ 原始檔均清除 |
  | 現有 EPUB 使用者升級後 | Book 資料完整，閱讀進度保留（SwiftData @Attribute migration） |
  | 現有 EPUB 開啟 | 行為不變 |

- [ ] **Step 2: Final commit（若無問題）**
  ```
  ios: multi-format import (TXT/MD/PDF) — complete
  ```
