#if os(iOS)
//
//  ReadiumService.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import UIKit
import ReadiumShared
import ReadiumStreamer
import ReadiumNavigator

/// Readium 服務 — 封裝 EPUB 開啟與 Publication 管理
@MainActor
final class ReadiumService: ReadiumServing {
    static let shared = ReadiumService()

    private let httpClient: HTTPClient
    private let assetRetriever: AssetRetriever
    private let publicationOpener: PublicationOpener

    private init() {
        httpClient = DefaultHTTPClient()
        assetRetriever = AssetRetriever(httpClient: httpClient)
        publicationOpener = PublicationOpener(
            parser: DefaultPublicationParser(
                httpClient: httpClient,
                assetRetriever: assetRetriever,
                pdfFactory: DefaultPDFDocumentFactory()
            )
        )
    }

    // MARK: - 開啟 Publication

    /// 從 EPUB 檔案 URL 開啟 Publication
    func openPublication(at url: URL) async throws -> Publication {
        let perfSpan = PerfLog.reader.interval("openPublication")
        defer { perfSpan.end(url.lastPathComponent) }
        let fm = FileManager.default
        AppLog.readium.info("openPublication: \(url.path) | exists=\(fm.fileExists(atPath: url.path)) readable=\(fm.isReadableFile(atPath: url.path))")
        guard let absoluteURL = FileURL(url: url) else {
            AppLog.readium.error("無法轉換為 FileURL — file exists=\(fm.fileExists(atPath: url.path))")
            throw NSError(
                domain: "ReadiumService",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: L10n.format("無法轉換檔案路徑: %@", url.path)]
            )
        }
        AppLog.readium.info("Retrieving asset...")
        let asset = try await assetRetriever.retrieve(url: absoluteURL).get()
        AppLog.readium.info("Asset retrieved: \(String(describing: asset.format))")
        let publication = try await publicationOpener.open(
            asset: asset,
            allowUserInteraction: false
        ).get()
        AppLog.readium.info("Publication opened: \(publication.metadata.title ?? "no title")")
        return publication
    }

    // MARK: - 匯入 EPUB

    /// 匯入 EPUB 檔案到 App Documents
    /// - Returns: (儲存的檔名, Publication)
    func importEPUB(from sourceURL: URL, progress: (@Sendable (Double) -> Void)? = nil) async throws -> (fileName: String, publication: Publication) {
        AppLog.readium.info("importEPUB from: \(sourceURL.path)")
        let sourceAccess = sourceURL.startAccessingSecurityScopedResource()
        AppLog.readium.info("Security scoped access: \(sourceAccess)")
        defer {
            if sourceAccess {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }

        // 建立唯一檔名
        let fileName = UUID().uuidString + ".epub"
        let destinationURL = Book.booksDirectory.appendingPathComponent(fileName)
        AppLog.readium.info("Destination: \(destinationURL.path)")

        // 以分塊複製避免大檔卡住主執行緒；回報進度
        try await BookshelfImportService.copyFileChunked(from: sourceURL, to: destinationURL, progress: progress)
        AppLog.readium.info("File copied successfully")

        // 開啟 Publication 以提取 metadata
        let publication = try await openPublication(at: destinationURL)
        AppLog.readium.info("Publication ready")

        return (fileName, publication)
    }

    // MARK: - 提取 Metadata

    /// 從 Publication 提取書籍 metadata
    func extractMetadata(from publication: Publication) -> (title: String, author: String) {
        let title = publication.metadata.title ?? "Untitled"
        let authorNames = publication.metadata.authors.map(\.name)
        let author = authorNames.isEmpty ? "Unknown" : authorNames.joined(separator: ", ")
        AppLog.readium.info("Metadata: title=\(title), author=\(author)")
        return (title, author)
    }

    /// 從 Publication 提取封面圖片
    func extractCover(from publication: Publication) async -> Data? {
        do {
            guard let cover = try await publication.cover().get() else { return nil }
            // Downsample to a bookshelf-thumbnail bound before persisting; the
            // raw EPUB cover is full-resolution PNG and bloats SwiftData. Fall
            // back to the original encoding if downsampling/encoding fails so a
            // cover is never silently dropped. (PDF path: BookshelfImporting.)
            if let thumbnail = CoverImageDownsampler.downsampledJPEG(from: cover) {
                return thumbnail
            }
            return cover.pngData() ?? cover.jpegData(compressionQuality: 0.8)
        } catch {
            AppCrashReporting.record(error, context: "readium.cover.extract")
            return nil
        }
    }

    // MARK: - 提取純文字與生字預過濾

    /// 從 Publication 的所有閱讀章節中提取出不重複的英文單字集合
    /// 此操作可能耗時，建議在背景 Task 中執行
    func extractUniqueWords(from publication: Publication) async -> Set<String> {
        return await Task.detached(priority: .background) {
            let perfSpan = PerfLog.reader.interval("extractUniqueWords")
            var uniqueWords = Set<String>()
            let readingOrder = publication.readingOrder

            for link in readingOrder {
                // 嘗試讀取章節資源
                guard let resource = publication.get(link) else { continue }
                do {
                    let data = try await resource.read().get()
                    guard let htmlString = String(data: data, encoding: .utf8) else { continue }
                    
                    // 1. 簡易剝離 HTML 標籤
                    // 將 <...> 替換為空白，避免標籤屬性（如 class="text"）和內文黏連
                    let textOnly = htmlString.replacingOccurrences(
                        of: "<[^>]+>",
                        with: " ",
                        options: .regularExpression,
                        range: nil
                    )

                    // 2. 轉小寫
                    let lowercased = textOnly.lowercased()

                    // 3. 提取所有純英文字母組成的單字（至少 2 個字母）
                    let regex = try NSRegularExpression(pattern: "\\b[a-z]{2,}\\b", options: [])
                    let nsString = lowercased as NSString
                    let results = regex.matches(in: lowercased, options: [], range: NSRange(location: 0, length: nsString.length))

                    for match in results {
                        let word = nsString.substring(with: match.range)
                        uniqueWords.insert(word)
                    }
                } catch {
                    AppLog.readium.warning("extractUniqueWords: 無法讀取章節 \(String(describing: link.href)), error: \(error.localizedDescription)")
                }
            }
            
            AppLog.readium.info("extractUniqueWords 完成：共提取了 \(uniqueWords.count) 個不重複單字")
            perfSpan.end("\(uniqueWords.count) words")
            return uniqueWords
        }.value
    }

    // MARK: - 刪除

    /// 刪除 EPUB 檔案（同時清理 iCloud 和本機）
    func deleteEPUB(fileName: String) {
        let fm = FileManager.default
        if let iCloudDir = Book.iCloudBooksDirectory {
            try? fm.removeItem(at: iCloudDir.appendingPathComponent(fileName))
        }
        try? fm.removeItem(at: Book.localBooksDirectory.appendingPathComponent(fileName))
    }
}
#endif
