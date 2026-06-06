import Foundation

// MARK: - Errors

enum EPUBConverterError: Error, LocalizedError {
    case fileTooLarge(Int)
    case encodingFailed
    case archiveFailed

    var errorDescription: String? {
        switch self {
        case .fileTooLarge(let bytes):
            return "File too large: \(bytes) bytes (max 20 MB)"
        case .encodingFailed:
            return "Failed to decode file text"
        case .archiveFailed:
            return "Failed to create EPUB archive"
        }
    }
}

// MARK: - EPUBConverter
//
// File composition (post-split, lineage of PRs #604/#594/#590):
// - `EPUBConverter.swift`           — TXT/MD → EPUB3 orchestration (this file)
// - `EPUBConverter+MinimalZIP.swift` — pure-Swift ZIP writer (stored method) + zlib CRC-32
// - `EPUBConverter+Markdown.swift`   — `SimpleMarkdownToHTML` converter

struct EPUBConverter {
    static let maxBytes = 20 * 1024 * 1024 // 20 MB
    /// 每讀 ~500 KB 觸發一次 progress callback。
    static let progressChunkBytes = 512 * 1024

    /// Convert a plain-text file to EPUB3.
    func convertTXT(at url: URL, title: String, progress: (@Sendable (Double) -> Void)? = nil) throws -> URL {
        let data = try loadAndValidate(url, progress: progress)
        let text = try decodeTextAllowingLatin1Fallback(data)
        let chapters = splitTXTIntoChapters(text, charsPerChapter: 5000)
        let htmlChapters = chapters.enumerated().map { idx, body in
            wrapXHTML(title: "\(title) — Chapter \(idx + 1)", body: body)
        }
        return try buildEPUB(title: title, chapters: htmlChapters)
    }

    /// Convert a Markdown file to EPUB3.
    func convertMD(at url: URL, title: String, progress: (@Sendable (Double) -> Void)? = nil) throws -> URL {
        let data = try loadAndValidate(url, progress: progress)
        let text = try decodeStrictUTF8(data)
        let htmlBody = SimpleMarkdownToHTML().convert(text)
        let chapter = wrapXHTML(title: title, body: htmlBody)
        return try buildEPUB(title: title, chapters: [chapter])
    }

    // MARK: - Private

    /// 以 ~512 KB 區塊讀取檔案，每塊回報一次進度（0.0–1.0）。
    /// 避免 `Data(contentsOf:)` 一次性吃掉大檔造成主執行緒（或單一 task）長時間無回應。
    private func loadAndValidate(_ url: URL, progress: (@Sendable (Double) -> Void)? = nil) throws -> Data {
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        let totalBytes = (attrs[.size] as? NSNumber)?.intValue ?? 0
        if totalBytes > Self.maxBytes {
            throw EPUBConverterError.fileTooLarge(totalBytes)
        }

        // totalBytes == 0 時直接走原路徑（保留行為）；否則 chunked read
        guard totalBytes > 0 else {
            let data = try Data(contentsOf: url)
            progress?(1.0)
            return data
        }

        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }

        var buffer = Data()
        buffer.reserveCapacity(totalBytes)
        var readSoFar = 0
        progress?(0.0)

        while true {
            let chunk = try handle.read(upToCount: Self.progressChunkBytes) ?? Data()
            if chunk.isEmpty { break }
            buffer.append(chunk)
            readSoFar += chunk.count
            if readSoFar > Self.maxBytes {
                throw EPUBConverterError.fileTooLarge(readSoFar)
            }
            let ratio = min(1.0, Double(readSoFar) / Double(totalBytes))
            progress?(ratio)
        }
        progress?(1.0)
        return buffer
    }

    private func decodeStrictUTF8(_ data: Data) throws -> String {
        guard let utf8 = String(data: data, encoding: .utf8) else {
            throw EPUBConverterError.encodingFailed
        }
        return utf8
    }

    private func decodeTextAllowingLatin1Fallback(_ data: Data) throws -> String {
        if let utf8 = String(data: data, encoding: .utf8) { return utf8 }
        if let latin1 = String(data: data, encoding: .isoLatin1) { return latin1 }
        throw EPUBConverterError.encodingFailed
    }

    private func escapeHTML(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    /// Split plain text into chapters of approximately `charsPerChapter` characters,
    /// breaking at paragraph boundaries.
    private func splitTXTIntoChapters(_ text: String, charsPerChapter: Int) -> [String] {
        let lines = text.components(separatedBy: "\n")
        var chapters: [String] = []
        var current = ""

        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let escaped = escapeHTML(trimmed)

            if current.count + escaped.count > charsPerChapter, !current.isEmpty {
                chapters.append(current)
                current = ""
            }
            if !current.isEmpty { current += "\n" }
            current += "<p>\(escaped)</p>"
        }
        if !current.isEmpty { chapters.append(current) }
        if chapters.isEmpty { chapters.append("<p></p>") }
        return chapters
    }

    private func wrapXHTML(title: String, body: String) -> String {
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
        <head><meta charset="UTF-8"/><title>\(escapeHTML(title))</title>
        <style>body{margin:1em;font-family:Georgia,serif;line-height:1.6}h1,h2,h3{margin-top:1.2em}pre{background:#f4f4f4;padding:.8em;overflow-x:auto}code{font-family:Menlo,monospace;font-size:0.9em}blockquote{border-left:3px solid #ccc;margin-left:0;padding-left:1em;color:#555}</style>
        </head>
        <body>
        \(body)
        </body>
        </html>
        """
    }

    private func buildEPUB(title: String, chapters: [String]) throws -> URL {
        let bookUID = UUID().uuidString

        var zip = MinimalZIP()

        // 1. mimetype (must be first, uncompressed, no extra field)
        zip.addEntry(name: "mimetype", data: Data("application/epub+zip".utf8))

        // 2. META-INF/container.xml
        let containerXML = """
        <?xml version="1.0" encoding="UTF-8"?>
        <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
          <rootfiles>
            <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
          </rootfiles>
        </container>
        """
        zip.addEntry(name: "META-INF/container.xml", data: Data(containerXML.utf8))

        // 3. Chapter files
        var manifestItems = ""
        var spineItems = ""
        for (idx, chapterHTML) in chapters.enumerated() {
            let id = String(format: "ch%03d", idx + 1)
            let filename = "\(id).xhtml"
            zip.addEntry(name: "OEBPS/\(filename)", data: Data(chapterHTML.utf8))
            manifestItems += "    <item id=\"\(id)\" href=\"\(filename)\" media-type=\"application/xhtml+xml\"/>\n"
            spineItems += "    <itemref idref=\"\(id)\"/>\n"
        }

        // 4. content.opf
        let contentOPF = """
        <?xml version="1.0" encoding="UTF-8"?>
        <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:identifier id="uid">urn:uuid:\(bookUID)</dc:identifier>
            <dc:title>\(escapeHTML(title))</dc:title>
            <dc:language>en</dc:language>
            <meta property="dcterms:modified">\(iso8601Now())</meta>
          </metadata>
          <manifest>
        \(manifestItems)    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
          </manifest>
          <spine>
        \(spineItems)  </spine>
        </package>
        """
        zip.addEntry(name: "OEBPS/content.opf", data: Data(contentOPF.utf8))

        // 5. nav.xhtml (EPUB3 requires navigation document)
        var navList = ""
        for (idx, _) in chapters.enumerated() {
            let id = String(format: "ch%03d", idx + 1)
            navList += "      <li><a href=\"\(id).xhtml\">Chapter \(idx + 1)</a></li>\n"
        }
        let navXHTML = """
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE html>
        <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
        <head><meta charset="UTF-8"/><title>Navigation</title></head>
        <body>
        <nav epub:type="toc" id="toc">
          <h1>Table of Contents</h1>
          <ol>
        \(navList)  </ol>
        </nav>
        </body>
        </html>
        """
        zip.addEntry(name: "OEBPS/nav.xhtml", data: Data(navXHTML.utf8))

        // Finalize ZIP
        let epubData = zip.finalize()

        let outputURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("epub")

        do {
            try epubData.write(to: outputURL)
        } catch {
            throw EPUBConverterError.archiveFailed
        }

        return outputURL
    }

    private func iso8601Now() -> String {
        // EPUB3 requires format without fractional seconds — use shared
        // AppDateFormatters.iso8601Simple ([.withInternetDateTime]).
        return AppDateFormatters.iso8601Simple.string(from: Date())
    }
}
