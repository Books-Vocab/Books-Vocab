//
//  Book.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import SwiftData
import os

/// 書籍資料模型 — 代表一本已匯入的 EPUB 書籍
@Model
final class Book {
    var id: UUID = UUID()
    var title: String = ""
    var author: String = ""
    var coverImageData: Data?
    var epubFileName: String = ""     // .epub 檔案名稱（UUID.epub）
    var lastReadLocatorJSON: String?  // Readium Locator 序列化 JSON
    var dateAdded: Date = Date()
    var dateLastRead: Date?
    var progression: Double?          // 閱讀進度 (0.0 ~ 1.0)

    init(
        title: String,
        author: String,
        coverImageData: Data? = nil,
        epubFileName: String
    ) {
        self.id = UUID()
        self.title = title
        self.author = author
        self.coverImageData = coverImageData
        self.epubFileName = epubFileName
        self.lastReadLocatorJSON = nil
        self.dateAdded = Date()
        self.dateLastRead = nil
        self.progression = nil
    }

    /// EPUB 檔案的完整 URL — 自動解析 iCloud / 本機位置
    var epubFileURL: URL {
        Self.resolveEpubFileURL(for: epubFileName)
    }

    // MARK: - 目錄管理

    /// iCloud EPUBs 目錄快取（nil = 尚未取得或 iCloud 不可用）
    private static var _cachedICloudDir: URL?

    /// iCloud EPUBs 目錄（nil 表示 iCloud 不可用，不快取 nil 以便下次重試）
    static var iCloudEpubsDirectory: URL? {
        if let cached = _cachedICloudDir { return cached }
        guard let containerURL = FileManager.default.url(
            forUbiquityContainerIdentifier: nil
        ) else { return nil }
        let dir = containerURL.appendingPathComponent("Documents/EPUBs")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        _cachedICloudDir = dir
        AppLog.book.info("EPUBs directory: iCloud (\(dir.path))")
        return dir
    }

    /// 本機 EPUBs 目錄
    private static var _cachedLocalDir: URL?

    static var localEpubsDirectory: URL {
        if let cached = _cachedLocalDir { return cached }
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("EPUBs")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        _cachedLocalDir = dir
        return dir
    }

    /// 新匯入使用的偏好目錄（優先 iCloud）
    static var epubsDirectory: URL {
        iCloudEpubsDirectory ?? localEpubsDirectory
    }

    /// 解析 EPUB 檔案的實際位置
    ///
    /// 檢查順序：iCloud（含 evicted placeholder）→ 本機 → fallback 到偏好目錄。
    /// 解決 iCloud 可用性在匯入與開啟之間改變的問題。
    static func resolveEpubFileURL(for fileName: String) -> URL {
        let fm = FileManager.default

        // 1. iCloud 位置（含 evicted placeholder）
        if let iCloudDir = iCloudEpubsDirectory {
            let url = iCloudDir.appendingPathComponent(fileName)
            if fm.fileExists(atPath: url.path) { return url }
            // iOS evict 時會建立 .filename.epub.icloud placeholder
            let placeholder = iCloudDir.appendingPathComponent(".\(fileName).icloud")
            if fm.fileExists(atPath: placeholder.path) { return url }
        }

        // 2. 本機位置
        let localURL = localEpubsDirectory.appendingPathComponent(fileName)
        if fm.fileExists(atPath: localURL.path) { return localURL }

        // 3. 都找不到 — 返回偏好目錄（供錯誤訊息使用）
        return epubsDirectory.appendingPathComponent(fileName)
    }

    /// URL 是否位於 iCloud ubiquity container 內
    static func isInICloudContainer(_ url: URL) -> Bool {
        guard let iCloudDir = _cachedICloudDir else { return false }
        return url.path.hasPrefix(iCloudDir.path)
    }

    /// EPUB 檔案是否已在本機可讀（用於書架顯示 iCloud 狀態）
    var isEpubFileLocal: Bool {
        FileManager.default.isReadableFile(atPath: epubFileURL.path)
    }

    /// 是否需要從 iCloud 下載（metadata 已到、檔案未到）
    var needsICloudDownload: Bool {
        !isEpubFileLocal && Self.iCloudEpubsDirectory != nil
    }
}
