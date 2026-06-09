//
//  Book.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import SwiftData

/// 書籍格式
enum BookFormat: String, Codable, CaseIterable {
    case epub
    case txt
    case md
    case pdf
}

/// 書籍資料模型 — 代表一本已匯入的書籍
@Model
final class Book {
    var id: UUID = UUID()
    var title: String = ""
    var author: String = ""
    var coverImageData: Data?
    var epubFileName: String = ""     // 檔案名稱（UUID.epub / UUID.txt / …），歷史命名保留以相容 CloudKit
    var lastReadLocatorJSON: String?  // Readium Locator 序列化 JSON
    var dateAdded: Date = Date()
    var dateLastRead: Date?
    var progression: Double?          // 閱讀進度 (0.0 ~ 1.0)
    var preferredNotebookId: String?   // 綁定的單字本 remoteId（nil = 跟隨全域設定）
    var formatRaw: String = BookFormat.epub.rawValue

    /// CloudKit 安全存取：舊記錄可能沒有 formatRaw，fallback 為 .epub
    var format: BookFormat {
        get { BookFormat(rawValue: formatRaw) ?? .epub }
        set { formatRaw = newValue.rawValue }
    }

    init(
        title: String,
        author: String,
        coverImageData: Data? = nil,
        fileName: String,
        format: BookFormat = BookFormat.epub
    ) {
        self.id = UUID()
        self.title = title
        self.author = author
        self.coverImageData = coverImageData
        self.epubFileName = fileName
        self.formatRaw = format.rawValue
        self.lastReadLocatorJSON = nil
        self.dateAdded = Date()
        self.dateLastRead = nil
        self.progression = nil
    }

    /// 書籍檔案的完整 URL — 自動解析 iCloud / 本機位置
    var fileURL: URL {
        Self.resolveFileURL(for: epubFileName)
    }

    // MARK: - 目錄管理

    /// iCloud Books 目錄快取（nil = 尚未取得或 iCloud 不可用）
    private static var _cachedICloudDir: URL?

    /// iCloud Books 目錄（nil 表示 iCloud 不可用，不快取 nil 以便下次重試）
    static var iCloudBooksDirectory: URL? {
        if let cached = _cachedICloudDir { return cached }
        guard let containerURL = FileManager.default.url(
            forUbiquityContainerIdentifier: nil
        ) else { return nil }
        let dir = containerURL.appendingPathComponent("Documents/Books")
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        } catch {
            AppLog.book.warning("Failed to create iCloud Books directory: \(error.localizedDescription)")
        }
        _cachedICloudDir = dir
        AppLog.book.info("Books directory: iCloud (\(dir.path))")
        return dir
    }

    /// 本機 Books 目錄
    private static var _cachedLocalDir: URL?

    static var localBooksDirectory: URL {
        if let cached = _cachedLocalDir { return cached }
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Books")
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        } catch {
            AppLog.book.warning("Failed to create local Books directory: \(error.localizedDescription)")
        }
        _cachedLocalDir = dir
        return dir
    }

    /// 新匯入使用的偏好目錄（優先 iCloud）
    static var booksDirectory: URL {
        iCloudBooksDirectory ?? localBooksDirectory
    }

    /// 解析書籍檔案的實際位置
    ///
    /// 檢查順序：iCloud（含 evicted placeholder）→ 本機 → fallback 到偏好目錄。
    /// 解決 iCloud 可用性在匯入與開啟之間改變的問題。
    static func resolveFileURL(for fileName: String) -> URL {
        let fm = FileManager.default

        // 1. iCloud 位置（含 evicted placeholder）
        if let iCloudDir = iCloudBooksDirectory {
            let url = iCloudDir.appendingPathComponent(fileName)
            if fm.fileExists(atPath: url.path) { return url }
            // iOS evict 時會建立 .filename.icloud placeholder
            let placeholder = iCloudDir.appendingPathComponent(".\(fileName).icloud")
            if fm.fileExists(atPath: placeholder.path) { return url }
        }

        // 2. 本機位置
        let localURL = localBooksDirectory.appendingPathComponent(fileName)
        if fm.fileExists(atPath: localURL.path) { return localURL }

        // 3. Legacy fallback — 舊版存在 Documents/EPUBs/ 的檔案
        let legacyDir = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("EPUBs")
        let legacyURL = legacyDir.appendingPathComponent(fileName)
        if fm.fileExists(atPath: legacyURL.path) { return legacyURL }
        if let iCloudContainer = fm.url(forUbiquityContainerIdentifier: nil) {
            let legacyICloud = iCloudContainer.appendingPathComponent("Documents/EPUBs/\(fileName)")
            if fm.fileExists(atPath: legacyICloud.path) { return legacyICloud }
            let legacyPlaceholder = iCloudContainer.appendingPathComponent("Documents/EPUBs/.\(fileName).icloud")
            if fm.fileExists(atPath: legacyPlaceholder.path) { return legacyICloud }
        }

        // 4. 都找不到 — 返回偏好目錄（供錯誤訊息使用）
        return booksDirectory.appendingPathComponent(fileName)
    }

    /// URL 是否位於 iCloud ubiquity container 內
    static func isInICloudContainer(_ url: URL) -> Bool {
        guard let iCloudDir = _cachedICloudDir else { return false }
        return url.path.hasPrefix(iCloudDir.path)
    }

    /// 書籍檔案是否已在本機可讀（用於書架顯示 iCloud 狀態）
    var isFileLocal: Bool {
        FileManager.default.isReadableFile(atPath: fileURL.path)
    }

    /// 是否需要從 iCloud 下載（metadata 已到、檔案未到）
    var needsICloudDownload: Bool {
        !isFileLocal
    }

    /// 此書的目標單字本 ID。**綁定即真相**：正常流程下書在開啟時即被
    /// `ensureBoundNotebook(seed:)` 固化綁定，故恆回 `preferredNotebookId`。
    /// `?? activeNotebookId` 僅為「未經 Reader 開啟流程就讀取」的防禦性 last-resort，
    /// 非主路徑 —— scope 不再隨全域 active 中途漂移（消除 highlight/cache scope 不一致）。
    ///
    /// 注意：不在此處驗證 notebook 是否已刪除，因為 @Model computed property
    /// 無法存取 ModelContext。已刪除 notebook 的防護由 ReaderNotebookPicker /
    /// ReaderView.sanitizeStaleBoundNotebook 在 UI 層處理。
    var resolvedNotebookId: String {
        if let bound = preferredNotebookId { return bound }
        return ActiveNotebookStore.shared.activeNotebookId
    }

    /// 強制綁定：每本書綁定恰好一本真實單字本。首次開啟（未綁定）時以 seed
    /// （最近使用的真實單字本，來自 `ActiveNotebookStore`）固化綁定並回傳；
    /// 已綁定則回既有值、不覆寫（idempotent）。固化後 `resolvedNotebookId` 不再
    /// runtime fallback，scope 穩定。caller 負責持久化（save + manifest）。
    @discardableResult
    func ensureBoundNotebook(seed: String) -> String {
        if let bound = preferredNotebookId { return bound }
        preferredNotebookId = seed
        return seed
    }
}
