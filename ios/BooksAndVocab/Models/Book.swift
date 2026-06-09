//
//  Book.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import os
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

    // OSAllocatedUnfairLock 保護 iCloud 目錄快取，使 read/write 在任意 thread 都安全。
    // iCloudBooksDirectory 可從 nonisolated 的 LocalBookFileManager 讀取，
    // clearICloudDirectoryCache() 可從 nonisolated async（LocalDataCleanerService）寫入，
    // 若以裸 static var 實作則構成 data race。
    private static let _iCloudDirLock = OSAllocatedUnfairLock<URL?>(initialState: nil)

    /// iCloud Books 目錄（nil 表示 iCloud 不可用，不快取 nil 以便下次重試）
    static var iCloudBooksDirectory: URL? {
        // Fast path: cached value, no I/O.
        if let cached = _iCloudDirLock.withLock({ $0 }) { return cached }

        // Slow path: derive directory outside the lock (ubiquity container lookup + createDirectory
        // may block; OSAllocatedUnfairLock is a spinlock, unsuitable for blocking I/O).
        guard let containerURL = FileManager.default.url(
            forUbiquityContainerIdentifier: nil
        ) else { return nil }
        let dir = containerURL.appendingPathComponent("Documents/Books")
        do {
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        } catch {
            AppLog.book.warning("Failed to create iCloud Books directory: \(error.localizedDescription)")
        }
        AppLog.book.info("Books directory: iCloud (\(dir.path))")

        // Write-if-still-nil: two threads may both reach here; first writer wins,
        // second returns the already-cached value. createDirectory is idempotent.
        return _iCloudDirLock.withLock { cached in
            if let existing = cached { return existing }
            cached = dir
            return dir
        }
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

    /// 清除 iCloud 目錄快取，讓下次存取時以當前 Apple ID 重取容器路徑。
    /// 在 Apple ID 切換或 KG 帳號登出/切換時呼叫。
    static func clearICloudDirectoryCache() {
        _iCloudDirLock.withLock { $0 = nil }
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

    // 單字本綁定（resolvedNotebookId / ensureBoundNotebook / canSeedBinding）由
    // NotebookBindable 提供 —— 與 PodcastSeries 共用「每個容器綁定恰好一本真實單字本」
    // 不變式。已刪除 notebook 的防護由 ReaderNotebookPicker /
    // ReaderView.sanitizeStaleBoundNotebook 在 UI 層處理。
}

extension Book: NotebookBindable {}
