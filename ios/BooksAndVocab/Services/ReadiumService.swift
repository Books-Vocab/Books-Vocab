#if os(iOS)
//
//  ReadiumService.swift
//  Books & Vocab
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

        // 開啟 Publication 以提取 metadata；壞檔／被取消時清掉已複製的 dest，避免留下無法開啟的孤檔。
        let publication: Publication
        do {
            publication = try await openPublication(at: destinationURL)
        } catch {
            try? FileManager.default.removeItem(at: destinationURL)
            throw error
        }
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

    /// 章節 HTML → 小寫單字集合（純函式，供 extractUniqueWords 與單測使用）。
    /// 剝標籤、解 HTML entity、NFKC 正規化（與前端擷取一致）後，以 `[\p{L}\p{M}\p{N}'-]+` 切 token
    /// （well-known、don't、café、covid-19），去頭尾 `'`／`-`，至少 2 個字元；
    /// 含 `'`／`-` 的 token 另把各片段（well、known、king）一併收入。
    nonisolated static func extractWords(fromHTML html: String) -> Set<String> {
        let textOnly = html.replacingOccurrences(of: "<[^>]+>", with: " ", options: .regularExpression)
        let normalized = decodeHTMLEntities(textOnly)
            .precomposedStringWithCompatibilityMapping
            .lowercased()
            .replacingOccurrences(of: "\u{2019}", with: "'")
            .replacingOccurrences(of: "\u{2018}", with: "'")
        guard let regex = try? NSRegularExpression(pattern: "[\\p{L}\\p{M}\\p{N}'\\-]+") else { return [] }
        let ns = normalized as NSString
        let edge = CharacterSet(charactersIn: "'-")
        var words = Set<String>()
        for match in regex.matches(in: normalized, range: NSRange(location: 0, length: ns.length)) {
            let token = ns.substring(with: match.range).trimmingCharacters(in: edge)
            if token.count >= 2 { words.insert(token) }
            guard token.contains("'") || token.contains("-") else { continue }
            for fragment in token.split(whereSeparator: { $0 == "'" || $0 == "-" }) where fragment.count >= 2 {
                words.insert(String(fragment))
            }
        }
        return words
    }

    private nonisolated static let namedEntities: [String: String] = [
        "amp": "&", "lt": "<", "gt": ">", "quot": "\"", "apos": "'", "nbsp": " ",
        "rsquo": "'", "lsquo": "'", "ldquo": " ", "rdquo": " ", "ndash": " ", "mdash": " ", "hellip": " ",
        "eacute": "\u{E9}", "egrave": "\u{E8}", "ecirc": "\u{EA}", "euml": "\u{EB}",
        "aacute": "\u{E1}", "agrave": "\u{E0}", "acirc": "\u{E2}", "auml": "\u{E4}", "aring": "\u{E5}",
        "iacute": "\u{ED}", "icirc": "\u{EE}", "iuml": "\u{EF}",
        "oacute": "\u{F3}", "ocirc": "\u{F4}", "ouml": "\u{F6}",
        "uacute": "\u{FA}", "ucirc": "\u{FB}", "uuml": "\u{FC}",
        "ccedil": "\u{E7}", "ntilde": "\u{F1}", "szlig": "\u{DF}",
        "Eacute": "\u{C9}", "Egrave": "\u{C8}", "Ecirc": "\u{CA}", "Euml": "\u{CB}",
        "Aacute": "\u{C1}", "Agrave": "\u{C0}", "Acirc": "\u{C2}", "Auml": "\u{C4}", "Aring": "\u{C5}",
        "Iacute": "\u{CD}", "Icirc": "\u{CE}", "Iuml": "\u{CF}",
        "Oacute": "\u{D3}", "Ocirc": "\u{D4}", "Ouml": "\u{D6}",
        "Uacute": "\u{DA}", "Ucirc": "\u{DB}", "Uuml": "\u{DC}",
        "Ccedil": "\u{C7}", "Ntilde": "\u{D1}",
    ]

    /// 單趟解碼（不二次解碼 `&amp;amp;`）；未知 entity 保留原樣。
    private nonisolated static func decodeHTMLEntities(_ text: String) -> String {
        guard text.contains("&"),
              let regex = try? NSRegularExpression(pattern: "&(#[0-9]+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]*);") else { return text }
        let ns = text as NSString
        var result = ""
        var cursor = 0
        for match in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            result += ns.substring(with: NSRange(location: cursor, length: match.range.location - cursor))
            let body = ns.substring(with: match.range(at: 1))
            var decoded: String?
            if body.hasPrefix("#x") || body.hasPrefix("#X") {
                decoded = UInt32(body.dropFirst(2), radix: 16).flatMap(Unicode.Scalar.init).map { String(Character($0)) }
            } else if body.hasPrefix("#") {
                decoded = UInt32(body.dropFirst(1)).flatMap(Unicode.Scalar.init).map { String(Character($0)) }
            } else {
                decoded = namedEntities[body]
            }
            result += decoded ?? ns.substring(with: match.range)
            cursor = match.range.location + match.range.length
        }
        result += ns.substring(from: cursor)
        return result
    }

    /// 從 Publication 的所有閱讀章節中提取出不重複的英文單字集合
    /// 此操作可能耗時，建議在背景 Task 中執行
    func extractUniqueWords(from publication: Publication) async -> Set<String> {
        // detached task 不繼承呼叫端取消；以 handler 轉送，關閉閱讀器後不再整本掃描
        // （取消時回傳空集合，呼叫端會丟棄結果）。
        let scan = Task.detached(priority: .background) { () async -> Set<String> in
            let perfSpan = PerfLog.reader.interval("extractUniqueWords")
            var uniqueWords = Set<String>()
            let readingOrder = publication.readingOrder

            for link in readingOrder {
                if Task.isCancelled { return [] }
                // 嘗試讀取章節資源
                guard let resource = publication.get(link) else { continue }
                do {
                    let data = try await resource.read().get()
                    if Task.isCancelled { return [] }
                    guard let htmlString = String(data: data, encoding: .utf8) else { continue }
                    
                    uniqueWords.formUnion(Self.extractWords(fromHTML: htmlString))
                } catch {
                    AppLog.readium.warning("extractUniqueWords: 無法讀取章節 \(String(describing: link.href)), error: \(error.localizedDescription)")
                }
            }
            
            AppLog.readium.info("extractUniqueWords 完成：共提取了 \(uniqueWords.count) 個不重複單字")
            perfSpan.end("\(uniqueWords.count) words")
            return uniqueWords
        }
        return await withTaskCancellationHandler {
            await scan.value
        } onCancel: {
            scan.cancel()
        }
    }
}
#endif
