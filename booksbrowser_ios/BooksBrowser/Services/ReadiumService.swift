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
import ReadiumAdapterGCDWebServer

/// Readium 服務 — 封裝 EPUB 開啟與 Publication 管理
@MainActor
final class ReadiumService: ReadiumServing {
    static let shared = ReadiumService()

    private let httpClient: HTTPClient
    private let assetRetriever: AssetRetriever
    private let publicationOpener: PublicationOpener
    private(set) var httpServer: GCDHTTPServer

    private init() {
        httpClient = DefaultHTTPClient()
        assetRetriever = AssetRetriever(httpClient: httpClient)
        httpServer = GCDHTTPServer(assetRetriever: assetRetriever)
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
        print("📖 openPublication: \(url.path)")
        guard let absoluteURL = FileURL(url: url) else {
            print("❌ 無法轉換為 FileURL")
            throw NSError(
                domain: "ReadiumService",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: L10n.format("無法轉換檔案路徑: %@", url.path)]
            )
        }
        print("📖 retrieving asset...")
        let asset = try await assetRetriever.retrieve(url: absoluteURL).get()
        print("📖 asset retrieved: \(asset.format)")
        let publication = try await publicationOpener.open(
            asset: asset,
            allowUserInteraction: false
        ).get()
        print("📖 publication opened: \(publication.metadata.title ?? "no title")")
        return publication
    }

    // MARK: - 匯入 EPUB

    /// 匯入 EPUB 檔案到 App Documents
    /// - Returns: (儲存的檔名, Publication)
    func importEPUB(from sourceURL: URL) async throws -> (fileName: String, publication: Publication) {
        print("📦 importEPUB from: \(sourceURL.path)")
        let sourceAccess = sourceURL.startAccessingSecurityScopedResource()
        print("📦 security scoped access: \(sourceAccess)")
        defer {
            if sourceAccess {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }

        // 建立唯一檔名
        let fileName = UUID().uuidString + ".epub"
        let destinationURL = Book.epubsDirectory.appendingPathComponent(fileName)
        print("📦 destination: \(destinationURL.path)")

        // 複製到 App Documents
        try FileManager.default.copyItem(at: sourceURL, to: destinationURL)
        print("📦 file copied successfully")

        // 開啟 Publication 以提取 metadata
        let publication = try await openPublication(at: destinationURL)
        print("📦 publication ready")

        return (fileName, publication)
    }

    // MARK: - 提取 Metadata

    /// 從 Publication 提取書籍 metadata
    func extractMetadata(from publication: Publication) -> (title: String, author: String) {
        let title = publication.metadata.title ?? "Untitled"
        let authorNames = publication.metadata.authors.map(\.name)
        let author = authorNames.isEmpty ? "Unknown" : authorNames.joined(separator: ", ")
        print("📖 metadata: title=\(title), author=\(author)")
        return (title, author)
    }

    /// 從 Publication 提取封面圖片
    func extractCover(from publication: Publication) async -> Data? {
        do {
            guard let cover = try await publication.cover().get() else { return nil }
            return cover.pngData() ?? cover.jpegData(compressionQuality: 0.8)
        } catch {
            return nil
        }
    }

    // MARK: - 提取純文字與生字預過濾

    /// 從 Publication 的所有閱讀章節中提取出不重複的英文單字集合
    /// 此操作可能耗時，建議在背景 Task 中執行
    func extractUniqueWords(from publication: Publication) async -> Set<String> {
        return await Task.detached(priority: .background) {
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
                    print("⚠️ extractUniqueWords: 無法讀取章節 \(link.href), error: \(error)")
                }
            }
            
            print("📖 extractUniqueWords 完成：共提取了 \(uniqueWords.count) 個不重複單字")
            return uniqueWords
        }.value
    }

    // MARK: - 刪除

    /// 刪除 EPUB 檔案
    func deleteEPUB(fileName: String) {
        let url = Book.epubsDirectory.appendingPathComponent(fileName)
        try? FileManager.default.removeItem(at: url)
    }
}

// MARK: - URL Extension

fileprivate extension URL {
    /// 將 Foundation URL 轉為 Readium 的 AbsoluteURL
    var anyURL: ReadiumShared.AbsoluteURL {
        if let fileURL = FileURL(url: self) {
            return fileURL
        }
        // 回退：強制轉換
        return FileURL(url: self)!
    }
}
