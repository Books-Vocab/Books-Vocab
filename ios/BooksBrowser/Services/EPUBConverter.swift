import Foundation
import zlib

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
            return "Failed to decode file as UTF-8 or Latin-1"
        case .archiveFailed:
            return "Failed to create EPUB archive"
        }
    }
}

// MARK: - MinimalZIP

/// Pure-Swift ZIP archive builder using stored (no compression) method.
/// Uses system zlib only for CRC-32 calculation.
private struct MinimalZIP {
    private struct Entry {
        let name: String
        let data: Data
        let crc32: UInt32
        let offset: UInt32
    }

    private var entries: [Entry] = []
    private var payload = Data()

    mutating func addEntry(name: String, data: Data) {
        let crc = crc32Checksum(data)
        let offset = UInt32(payload.count)

        let nameData = Data(name.utf8)
        let nameLen = UInt16(nameData.count)
        let size = UInt32(data.count)

        // DOS date/time: 2025-01-01 00:00:00
        let modTime: UInt16 = 0
        let modDate: UInt16 = (45 << 9) | (1 << 5) | 1 // year=2025-1980=45

        // Local file header
        var header = Data()
        header.appendUInt32(0x04034b50) // signature
        header.appendUInt16(20)         // version needed
        header.appendUInt16(0)          // flags
        header.appendUInt16(0)          // method (stored)
        header.appendUInt16(modTime)
        header.appendUInt16(modDate)
        header.appendUInt32(crc)
        header.appendUInt32(size)       // compressed size
        header.appendUInt32(size)       // uncompressed size
        header.appendUInt16(nameLen)
        header.appendUInt16(0)          // extra length
        header.append(nameData)
        header.append(data)

        payload.append(header)
        entries.append(Entry(name: name, data: data, crc32: crc, offset: offset))
    }

    func finalize() -> Data {
        var result = payload

        let cdOffset = UInt32(result.count)
        var cdSize: UInt32 = 0

        // DOS date/time matching local headers
        let modTime: UInt16 = 0
        let modDate: UInt16 = (45 << 9) | (1 << 5) | 1

        for entry in entries {
            let nameData = Data(entry.name.utf8)
            let nameLen = UInt16(nameData.count)
            let size = UInt32(entry.data.count)

            var cd = Data()
            cd.appendUInt32(0x02014b50) // signature
            cd.appendUInt16(20)         // version made by
            cd.appendUInt16(20)         // version needed
            cd.appendUInt16(0)          // flags
            cd.appendUInt16(0)          // method
            cd.appendUInt16(modTime)
            cd.appendUInt16(modDate)
            cd.appendUInt32(entry.crc32)
            cd.appendUInt32(size)       // compressed
            cd.appendUInt32(size)       // uncompressed
            cd.appendUInt16(nameLen)
            cd.appendUInt16(0)          // extra length
            cd.appendUInt16(0)          // comment length
            cd.appendUInt16(0)          // disk number start
            cd.appendUInt16(0)          // internal attributes
            cd.appendUInt32(0)          // external attributes
            cd.appendUInt32(entry.offset)
            cd.append(nameData)

            result.append(cd)
            cdSize += UInt32(cd.count)
        }

        // End of central directory
        let count = UInt16(entries.count)
        var eocd = Data()
        eocd.appendUInt32(0x06054b50) // signature
        eocd.appendUInt16(0)          // disk number
        eocd.appendUInt16(0)          // disk with CD
        eocd.appendUInt16(count)      // entries on disk
        eocd.appendUInt16(count)      // total entries
        eocd.appendUInt32(cdSize)
        eocd.appendUInt32(cdOffset)
        eocd.appendUInt16(0)          // comment length

        result.append(eocd)
        return result
    }

    private func crc32Checksum(_ data: Data) -> UInt32 {
        data.withUnsafeBytes { buffer in
            let ptr = buffer.bindMemory(to: UInt8.self).baseAddress
            return UInt32(zlib.crc32(0, ptr, uInt(data.count)))
        }
    }
}

private extension Data {
    mutating func appendUInt16(_ value: UInt16) {
        var le = value.littleEndian
        append(Data(bytes: &le, count: 2))
    }

    mutating func appendUInt32(_ value: UInt32) {
        var le = value.littleEndian
        append(Data(bytes: &le, count: 4))
    }
}

// MARK: - SimpleMarkdownToHTML

/// Minimal Markdown → HTML converter. No external dependencies.
///
/// Supported syntax:
/// - Headings: `# H1` through `###### H6`
/// - Bold: `**text**`
/// - Italic: `*text*`
/// - Unordered list: `- item`
/// - Ordered list: `1. item`
/// - Inline code: `` `code` ``
/// - Fenced code blocks: ```` ``` ````
/// - Blockquote: `> text`
/// - Paragraphs (blank-line separated)
/// - HTML entity escaping (`<`, `>`, `&`)
private struct SimpleMarkdownToHTML {
    func convert(_ markdown: String) -> String {
        let lines = markdown.components(separatedBy: "\n")
        var html = ""
        var i = 0

        while i < lines.count {
            let line = lines[i]

            // Fenced code block
            if line.hasPrefix("```") {
                i += 1
                var codeLines: [String] = []
                while i < lines.count, !lines[i].hasPrefix("```") {
                    codeLines.append(escapeHTML(lines[i]))
                    i += 1
                }
                if i < lines.count { i += 1 } // skip closing ```
                html += "<pre><code>\(codeLines.joined(separator: "\n"))</code></pre>\n"
                continue
            }

            // Blank line — skip
            if line.trimmingCharacters(in: .whitespaces).isEmpty {
                i += 1
                continue
            }

            // Heading
            if let heading = parseHeading(line) {
                html += heading + "\n"
                i += 1
                continue
            }

            // Blockquote
            if line.hasPrefix("> ") || line == ">" {
                var quoteLines: [String] = []
                while i < lines.count, (lines[i].hasPrefix("> ") || lines[i] == ">") {
                    let content = lines[i].hasPrefix("> ") ? String(lines[i].dropFirst(2)) : ""
                    quoteLines.append(content)
                    i += 1
                }
                let inner = quoteLines.map { inlineFormat(escapeHTML($0)) }.joined(separator: "<br/>")
                html += "<blockquote>\(inner)</blockquote>\n"
                continue
            }

            // Unordered list
            if line.hasPrefix("- ") {
                var items: [String] = []
                while i < lines.count, lines[i].hasPrefix("- ") {
                    items.append(inlineFormat(escapeHTML(String(lines[i].dropFirst(2)))))
                    i += 1
                }
                html += "<ul>\n" + items.map { "<li>\($0)</li>" }.joined(separator: "\n") + "\n</ul>\n"
                continue
            }

            // Ordered list
            if isOrderedListItem(line) {
                var items: [String] = []
                while i < lines.count, isOrderedListItem(lines[i]) {
                    let text = stripOrderedPrefix(lines[i])
                    items.append(inlineFormat(escapeHTML(text)))
                    i += 1
                }
                html += "<ol>\n" + items.map { "<li>\($0)</li>" }.joined(separator: "\n") + "\n</ol>\n"
                continue
            }

            // Paragraph — collect consecutive non-blank, non-special lines
            var paraLines: [String] = []
            while i < lines.count {
                let l = lines[i]
                let trimmed = l.trimmingCharacters(in: .whitespaces)
                if trimmed.isEmpty || l.hasPrefix("```") || l.hasPrefix("# ") ||
                    l.hasPrefix("## ") || l.hasPrefix("### ") || l.hasPrefix("#### ") ||
                    l.hasPrefix("##### ") || l.hasPrefix("###### ") ||
                    l.hasPrefix("> ") || l == ">" || l.hasPrefix("- ") || isOrderedListItem(l) {
                    break
                }
                paraLines.append(inlineFormat(escapeHTML(l)))
                i += 1
            }
            if !paraLines.isEmpty {
                html += "<p>\(paraLines.joined(separator: "\n"))</p>\n"
            }
        }

        return html
    }

    // MARK: Helpers

    private func escapeHTML(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private func inlineFormat(_ text: String) -> String {
        var result = text

        // Inline code (must be before bold/italic to avoid conflicts)
        result = replacePattern(result, pattern: "`([^`]+)`", template: "<code>$1</code>")

        // Bold
        result = replacePattern(result, pattern: "\\*\\*(.+?)\\*\\*", template: "<strong>$1</strong>")

        // Italic (single *)
        result = replacePattern(result, pattern: "\\*(.+?)\\*", template: "<em>$1</em>")

        return result
    }

    private func replacePattern(_ text: String, pattern: String, template: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        let range = NSRange(text.startIndex..., in: text)
        return regex.stringByReplacingMatches(in: text, range: range, withTemplate: template)
    }

    private func parseHeading(_ line: String) -> String? {
        var level = 0
        for ch in line {
            if ch == "#" { level += 1 } else { break }
        }
        guard level >= 1, level <= 6, line.count > level, line[line.index(line.startIndex, offsetBy: level)] == " " else {
            return nil
        }
        let text = inlineFormat(escapeHTML(String(line.dropFirst(level + 1))))
        return "<h\(level)>\(text)</h\(level)>"
    }

    private func isOrderedListItem(_ line: String) -> Bool {
        guard let dotIdx = line.firstIndex(of: ".") else { return false }
        let prefix = line[line.startIndex..<dotIdx]
        guard !prefix.isEmpty, prefix.allSatisfy(\.isNumber) else { return false }
        let afterDot = line.index(after: dotIdx)
        return afterDot < line.endIndex && line[afterDot] == " "
    }

    private func stripOrderedPrefix(_ line: String) -> String {
        guard let dotIdx = line.firstIndex(of: ".") else { return line }
        let afterDot = line.index(after: dotIdx)
        guard afterDot < line.endIndex, line[afterDot] == " " else { return line }
        return String(line[line.index(after: afterDot)...])
    }
}

// MARK: - EPUBConverter

struct EPUBConverter {
    static let maxBytes = 20 * 1024 * 1024 // 20 MB

    /// Convert a plain-text file to EPUB3.
    func convertTXT(at url: URL, title: String) throws -> URL {
        let data = try loadAndValidate(url)
        let text = try decodeText(data)
        let chapters = splitTXTIntoChapters(text, charsPerChapter: 5000)
        let htmlChapters = chapters.enumerated().map { idx, body in
            wrapXHTML(title: "\(title) — Chapter \(idx + 1)", body: body)
        }
        return try buildEPUB(title: title, chapters: htmlChapters)
    }

    /// Convert a Markdown file to EPUB3.
    func convertMD(at url: URL, title: String) throws -> URL {
        let data = try loadAndValidate(url)
        guard let text = String(data: data, encoding: .utf8) else {
            throw EPUBConverterError.encodingFailed
        }
        let htmlBody = SimpleMarkdownToHTML().convert(text)
        let chapter = wrapXHTML(title: title, body: htmlBody)
        return try buildEPUB(title: title, chapters: [chapter])
    }

    // MARK: - Private

    private func loadAndValidate(_ url: URL) throws -> Data {
        let data = try Data(contentsOf: url)
        if data.count > Self.maxBytes {
            throw EPUBConverterError.fileTooLarge(data.count)
        }
        return data
    }

    private func decodeText(_ data: Data) throws -> String {
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
        let paragraphs = text.components(separatedBy: "\n\n")
        var chapters: [String] = []
        var current = ""

        for para in paragraphs {
            let escaped = escapeHTML(para.trimmingCharacters(in: .whitespacesAndNewlines))
            guard !escaped.isEmpty else { continue }

            if current.count + escaped.count > charsPerChapter, !current.isEmpty {
                chapters.append(current)
                current = ""
            }
            if !current.isEmpty { current += "\n" }
            current += "<p>\(escaped.replacingOccurrences(of: "\n", with: "<br/>"))</p>"
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
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        // EPUB3 requires format without fractional seconds
        return f.string(from: Date())
    }
}
