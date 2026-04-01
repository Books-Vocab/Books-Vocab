# Multi-Format Import (TXT / MD / PDF) — Design Spec

## Problem

目前 iOS app 只支援 EPUB 匯入。使用者無法直接閱讀 TXT、Markdown、PDF 文件並在其中劃線捕捉詞彙。

---

## Scope

**含：**
- TXT 匯入 → on-device 轉 EPUB → Readium Reader（完整詞彙捕捉）
- MD 匯入 → on-device 轉 EPUB → Readium Reader（完整詞彙捕捉）
- PDF 匯入 → PDFKit 原生渲染 Reader（保留格式，詞彙捕捉橋接）
- `Book` model 加 `format` 欄位
- Bookshelf 支援三種格式圖標區分

**不含：**
- Image → MD（已推遲）
- PDF 全文搜尋
- PDF annotation 同步
- 雲端文件匯入（iCloud Drive 之外）

---

## Architecture

```
TXT ──→ EPUBConverter（on-device）──→ .epub 暫存 ──→ Readium Reader
MD  ──→ EPUBConverter（on-device）──/                  ↓ 詞彙捕捉
                                                  （零改動）

PDF ──→ 直接存為 .pdf ──→ PDFReaderView（新建）
                              ↓
                       PDFVocabBridge
                              ↓
                    現有 translate / VocabularyEntry flow
```

### 路由邏輯

```swift
// BookshelfCoordinator
func openBook(_ book: Book) {
    switch book.format {
    case .epub:   openReadiumReader(book)
    case .txt, .md: openReadiumReader(book)  // 已轉換為 epub，同路徑
    case .pdf:    openPDFReader(book)
    }
}
```

---

## Design

### 1. Book Model 擴充

```swift
enum BookFormat: String, Codable {
    case epub
    case txt
    case md
    case pdf
}

@Model class Book {
    // 現有欄位不變
    var format: BookFormat = .epub  // 新增
    // epubFileName → fileName（SwiftData lightweight migration）
    // 語意：轉換後的最終檔名，TXT/MD 為 .epub，PDF 為 .pdf
}
```

#### SwiftData Migration

`epubFileName` 重新命名為 `fileName`，使用 `VersionedSchema` + `MigrationPlan`：

```swift
// BookSchemaV2.swift
enum BookSchemaV2: VersionedSchema {
    static var models: [any PersistentModel.Type] = [Book.self]
    static var versionIdentifier = Schema.Version(2, 0, 0)
}

// 遷移：epubFileName → fileName（值不變，純重命名）
struct BookMigrationV1toV2: MigrationStage {
    static let migrateFromVersion = BookSchemaV1.self
    static let migrateToVersion = BookSchemaV2.self
}
```

所有 `book.epubFileName` 的呼叫站點（`epubFileURL`、`resolveEpubFileURL`、`iCloudDownloadManager`、`BookFileManaging`）統一改為 `book.fileName`。
檔案儲存目錄從 `Documents/EPUBs/` 統一改為 `Documents/Books/`（PDF 也放此處）。

---

### 2. Navigation 路由修正

現有 `BookshelfView` 用 `navigationDestination(for: Book.self)` 統一導向 `ReaderView`。需改為依 format dispatch：

```swift
// BookshelfView.swift
.navigationDestination(for: Book.self) { book in
    switch book.format {
    case .epub, .txt, .md:
        ReaderView(book: book)
    case .pdf:
        PDFReaderView(book: book)
    }
}
```

Coordinator 的 `openBook()` 仍保留，用於 programmatic navigation（push `Book` value 到 NavigationPath）。

---

### 2. EPUBConverter（TXT / MD → EPUB）

on-device 純 Swift，無外部依賴。

#### TXT → EPUB

```
純文字 → 段落切割（空行分段）→ HTML → EPUB3 zip 封裝
```

- 最大段落 1000 字，超過自動分頁（章節）
- 保留換行語意，不做任何格式推斷
- **大小限制：** TXT/MD > 20MB 拒絕匯入（轉換後 EPUB 可能膨脹 2-3x）

#### MD → EPUB

MD → HTML 使用 **[apple/swift-markdown](https://github.com/apple/swift-markdown)**（官方 SPM，輸出 AST，自行 walk 產生 HTML）。
支援範圍：h1-h3、粗體、斜體、list、code block、blockquote。複雜 HTML 元素降級為純文字。

```
.md 原文 → Document(parsing:) → AST walk → HTML → EPUB3 章節
```

EPUB3 封裝結構（最小可行）：

```
output.epub/
  mimetype            ← 第一個 entry，stored（no compression），EPUB3 規範要求
  META-INF/container.xml
  OEBPS/
    content.opf      ← metadata（title, author, language）
    toc.ncx
    chapter001.xhtml
    chapter002.xhtml
    ...
```

使用 **ZIPFoundation** SPM package，明確設定 `mimetype` entry 為 `.stored` compression method。

converter 為 **async** 操作，在 `Task.detached` 中執行，完成後回到 MainActor 做 SwiftData insert。

---

### 3. PDFReaderView

使用 `PDFKit.PDFView`，wrap 成 SwiftUI View。

#### 配置

```swift
pdfView.displayMode = .singlePageContinuous
pdfView.autoScales = true
pdfView.isUserInteractionEnabled = true  // 支援 pinch zoom
```

#### 詞彙捕捉橋接（PDFVocabBridge）

PDFKit 使用者長按 → 系統選字 → `UIMenuController` / `EditMenu`。

橋接策略（iOS 16+）：
1. 使用 `UIEditMenuInteraction` 在系統 Edit Menu 中注入「翻譯」選項（不另開 overlay，避免與系統 Menu 衝突）
2. 觸發時取 `PDFView.currentSelection?.string`
3. 傳入現有 `TranslationService` → 現有 `VocabularyEntry` 建立流程

```swift
// PDFReaderView 中
let editMenuInteraction = UIEditMenuInteraction(delegate: self)
pdfView.addInteraction(editMenuInteraction)

// UIEditMenuInteractionDelegate
func editMenuInteraction(_ interaction: UIEditMenuInteraction,
    menuFor configuration: UIEditMenuConfiguration,
    suggestedActions: [UIMenuElement]) -> UIMenu? {
    let translateAction = UIAction(title: "翻譯") { [weak self] _ in
        guard let text = self?.pdfView.currentSelection?.string else { return }
        self?.triggerVocabCapture(text)
    }
    return UIMenu(children: suggestedActions + [translateAction])
}
```

監聽 `.PDFViewSelectionChanged` 加 **300ms debounce**，僅用於更新 UI 狀態（非觸發 overlay）。

---

### 4. Bookshelf 顯示

- 書封無法從 TXT/MD 擷取 → 顯示格式 badge（`TXT` / `MD` / `PDF`）作為預設封面
- PDF 可用 `PDFPage.thumbnail()` 擷取第一頁作封面
- 格式 icon 統一在 `BookCoverView` 處理

---

### 5. FileImporter 擴充

```swift
// BookshelfView
.fileImporter(
    isPresented: $coordinator.isImporting,
    allowedContentTypes: [
        UTType(filenameExtension: "epub") ?? .data,
        .plainText,                              // txt
        UTType(filenameExtension: "md") ?? .data, // md
        .pdf,                                    // pdf
    ],
    allowsMultipleSelection: false
)
```

import handler 依副檔名 dispatch 到對應方法：

```swift
func handleImport(url: URL) {
    switch url.pathExtension.lowercased() {
    case "epub": importEPUB(url)
    case "txt":  importPlainText(url)
    case "md":   importMarkdown(url)
    case "pdf":  importPDF(url)
    default:     showUnsupportedFormatError()
    }
}
```

---

## Error Handling

| 情境 | 行為 |
|------|------|
| TXT/MD > 20MB | 拒絕匯入，toast 說明大小限制 |
| PDF > 100MB | import 前警告，使用者確認才繼續 |
| TXT/MD 轉換失敗 | toast 顯示錯誤，不建立 Book |
| PDF 無法開啟 | toast 顯示錯誤，不建立 Book |
| EPUB zip 封裝驗證失敗 | toast 顯示錯誤，刪除暫存 epub |
| 非 UTF-8 TXT 檔案 | 嘗試 Latin-1 fallback，仍失敗則 toast 提示編碼問題 |

---

## 其他設計決定

- **原始檔保留：** TXT/MD 原始檔存入 `Documents/Books/Originals/`，轉換產生的 EPUB 存於 `Documents/Books/`。保留原始檔確保未來可重新轉換（例如改善 MD parser 品質）。
- **PDF 進度保存：** `Book.lastReadLocatorJSON` 語意擴充為 `lastReadPositionJSON`，PDF 格式存 `{"pageIndex": N}`，EPUB 繼續存 Readium Locator JSON。
- **PDF 詞彙 context：** 含頁碼資訊，取 `PDFPage.label`（PDF 頁碼標示）+ `selection.string`。
- **最低 iOS 版本：** PDFKit `UIEditMenuInteraction` 需 iOS 16+，與現有 deployment target 一致（已降至 iOS 17）。
- **iCloud 同步：** PDF 預設同步（與 EPUB 行為一致），大型 PDF（> 50MB）在 bookshelf 顯示檔案大小提示。

---

## 成功標準

1. 使用者可從 Files app 選取 `.txt`、`.md`、`.pdf` 匯入
2. TXT/MD 在 Readium Reader 中可讀，劃線捕捉詞彙功能與 EPUB 相同
3. PDF 在 PDFKit Reader 中保留原始排版，長按選字可觸發詞彙捕捉
4. Bookshelf 正確顯示書封（PDF 用首頁縮圖，TXT/MD 用格式 badge）
5. 不影響現有 EPUB 匯入流程
