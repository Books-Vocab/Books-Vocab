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
    var epubFileName: String = ""     // .epub 檔案名稱（在 Documents/EPUBs/ 下）
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

    /// EPUB 檔案的完整 URL
    var epubFileURL: URL {
        Self.epubsDirectory.appendingPathComponent(epubFileName)
    }

    /// EPUBs 儲存目錄（優先使用 iCloud Documents）
    private static var _cachedEpubsDirectory: URL?

    static var epubsDirectory: URL {
        if let cached = _cachedEpubsDirectory { return cached }

        if let iCloudURL = FileManager.default.url(
            forUbiquityContainerIdentifier: nil
        )?.appendingPathComponent("Documents/EPUBs") {
            try? FileManager.default.createDirectory(at: iCloudURL, withIntermediateDirectories: true)
            AppLog.book.info("EPUBs directory: iCloud (\(iCloudURL.path))")
            _cachedEpubsDirectory = iCloudURL
            return iCloudURL
        }

        // Fallback to local when iCloud is not ready
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("EPUBs")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        AppLog.book.info("EPUBs directory: local fallback (\(dir.path))")
        // Don't cache local fallback — retry iCloud on next access
        return dir
    }
}
