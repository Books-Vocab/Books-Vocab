import Foundation
import Testing
@testable import BooksAndVocab

/// Coverage for `EPUBConverter` — the TXT/MD → EPUB3 converter behind the
/// multi-format bookshelf importer. There is no public seam exposing the
/// intermediate XHTML, so these tests drive the real `convertTXT` /
/// `convertMD` entry points and then parse the produced `.epub` back.
///
/// `EPUBConverter` builds archives with `MinimalZIP` using the **stored**
/// (no-compression) method, so every entry's bytes appear verbatim in the
/// payload. `StoredZipReader` below walks the local file headers to recover
/// each entry without needing zlib inflate — this is the only practical
/// seam for asserting chapter splitting / encoding / format detection.
struct EPUBConverterTests {

    // MARK: - Stored-ZIP reader (test-only helper)

    /// Minimal reader for archives written by `EPUBConverter.MinimalZIP`.
    /// Only supports the stored method (0) which is all the converter emits.
    private struct StoredZipReader {
        let entries: [String: Data]

        init?(_ data: Data) {
            var entries: [String: Data] = [:]
            var offset = 0
            let bytes = [UInt8](data)

            func u16(_ at: Int) -> Int { Int(bytes[at]) | (Int(bytes[at + 1]) << 8) }
            func u32(_ at: Int) -> Int {
                Int(bytes[at]) | (Int(bytes[at + 1]) << 8)
                    | (Int(bytes[at + 2]) << 16) | (Int(bytes[at + 3]) << 24)
            }

            while offset + 4 <= bytes.count {
                let sig = u32(offset)
                guard sig == 0x04034b50 else { break } // central directory → stop
                guard offset + 30 <= bytes.count else { return nil }
                let method = u16(offset + 8)
                let compSize = u32(offset + 18)
                let nameLen = u16(offset + 26)
                let extraLen = u16(offset + 28)
                let nameStart = offset + 30
                let dataStart = nameStart + nameLen + extraLen
                guard method == 0,
                      dataStart + compSize <= bytes.count,
                      let name = String(bytes: bytes[nameStart..<nameStart + nameLen], encoding: .utf8)
                else { return nil }
                entries[name] = Data(bytes[dataStart..<dataStart + compSize])
                offset = dataStart + compSize
            }
            guard !entries.isEmpty else { return nil }
            self.entries = entries
        }

        func text(_ name: String) -> String? {
            entries[name].flatMap { String(data: $0, encoding: .utf8) }
        }

        /// Names of `OEBPS/chNNN.xhtml` chapter documents, sorted.
        var chapterNames: [String] {
            entries.keys
                .filter { $0.hasPrefix("OEBPS/ch") && $0.hasSuffix(".xhtml") }
                .sorted()
        }
    }

    // MARK: - Temp-file fixtures

    /// Writes `data` to a uniquely-named temp file with `ext`, returns its URL.
    /// Caller is responsible for nothing — temp dir is volatile.
    private func writeTempFile(_ data: Data, ext: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("epubconv-test-\(UUID().uuidString)")
            .appendingPathExtension(ext)
        try data.write(to: url)
        return url
    }

    private func writeTempText(_ string: String, ext: String) throws -> URL {
        try writeTempFile(Data(string.utf8), ext: ext)
    }

    /// Convert via TXT path and parse the resulting EPUB.
    private func convertTXTAndParse(_ text: String, title: String = "Book") throws -> StoredZipReader {
        let src = try writeTempText(text, ext: "txt")
        let out = try EPUBConverter().convertTXT(at: src, title: title)
        let data = try Data(contentsOf: out)
        let reader = try #require(StoredZipReader(data), "produced EPUB must be a parseable stored-ZIP")
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
        return reader
    }

    private func convertMDAndParse(_ markdown: String, title: String = "Book") throws -> StoredZipReader {
        let src = try writeTempText(markdown, ext: "md")
        let out = try EPUBConverter().convertMD(at: src, title: title)
        let data = try Data(contentsOf: out)
        let reader = try #require(StoredZipReader(data), "produced EPUB must be a parseable stored-ZIP")
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
        return reader
    }

    // MARK: - EPUB structural invariants

    @Test func epub_contains_required_skeleton_files() throws {
        let reader = try convertTXTAndParse("Hello world.")
        // EPUB3 OCF: mimetype + container + package + nav are mandatory.
        #expect(reader.entries["mimetype"] != nil)
        #expect(reader.entries["META-INF/container.xml"] != nil)
        #expect(reader.entries["OEBPS/content.opf"] != nil)
        #expect(reader.entries["OEBPS/nav.xhtml"] != nil)
    }

    @Test func mimetype_entry_is_exact_epub_string() throws {
        let reader = try convertTXTAndParse("body")
        // Spec: mimetype must contain exactly `application/epub+zip`, no whitespace.
        #expect(reader.text("mimetype") == "application/epub+zip")
    }

    @Test func container_xml_points_at_content_opf() throws {
        let reader = try convertTXTAndParse("body")
        let container = try #require(reader.text("META-INF/container.xml"))
        #expect(container.contains("full-path=\"OEBPS/content.opf\""))
    }

    @Test func content_opf_declares_epub3_package() throws {
        let reader = try convertTXTAndParse("body")
        let opf = try #require(reader.text("OEBPS/content.opf"))
        #expect(opf.contains("version=\"3.0\""))
        #expect(opf.contains("<dc:identifier id=\"uid\">urn:uuid:"))
        #expect(opf.contains("<dc:language>en</dc:language>"))
        #expect(opf.contains("properties=\"nav\""))
    }

    // MARK: - Chapter extraction (TXT)

    @Test func short_txt_produces_single_chapter() throws {
        let reader = try convertTXTAndParse("One short paragraph.")
        #expect(reader.chapterNames == ["OEBPS/ch001.xhtml"])
    }

    @Test func long_txt_splits_into_multiple_chapters() throws {
        // charsPerChapter == 5000. Each line ~120 chars; 200 lines ≈ 24k chars
        // ⇒ must yield several chapter documents at paragraph boundaries.
        let paragraph = String(repeating: "x", count: 120)
        let text = (0..<200).map { _ in paragraph }.joined(separator: "\n")
        let reader = try convertTXTAndParse(text)
        #expect(reader.chapterNames.count > 1,
                "≈24k chars must split past the 5000-char chapter budget")
        // Chapter ids are zero-padded ch001, ch002, … and contiguous.
        for (idx, name) in reader.chapterNames.enumerated() {
            #expect(name == String(format: "OEBPS/ch%03d.xhtml", idx + 1))
        }
    }

    @Test func txt_paragraphs_wrapped_in_p_tags() throws {
        let reader = try convertTXTAndParse("First line.\nSecond line.")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<p>First line.</p>"))
        #expect(ch.contains("<p>Second line.</p>"))
    }

    @Test func txt_blank_lines_are_skipped_not_emitted_as_empty_paragraphs() throws {
        let reader = try convertTXTAndParse("Alpha\n\n\n   \nBeta")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<p>Alpha</p>"))
        #expect(ch.contains("<p>Beta</p>"))
        #expect(!ch.contains("<p></p>"), "blank / whitespace-only lines must not create empty <p>")
    }

    @Test func empty_txt_still_produces_one_placeholder_chapter() throws {
        // splitTXTIntoChapters guarantees ≥1 chapter so the EPUB stays valid.
        let reader = try convertTXTAndParse("")
        #expect(reader.chapterNames == ["OEBPS/ch001.xhtml"])
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<p></p>"), "empty input must fall back to a placeholder paragraph")
    }

    @Test func whitespace_only_txt_produces_placeholder_chapter() throws {
        let reader = try convertTXTAndParse("   \n\t\n   \n")
        #expect(reader.chapterNames == ["OEBPS/ch001.xhtml"])
        #expect(try #require(reader.text("OEBPS/ch001.xhtml")).contains("<p></p>"))
    }

    // MARK: - HTML escaping / encoding (TXT)

    @Test func txt_html_metacharacters_are_escaped() throws {
        let reader = try convertTXTAndParse("a < b && c > d")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("a &lt; b &amp;&amp; c &gt; d"))
        #expect(!ch.contains("a < b"), "raw '<' must never leak into XHTML body")
    }

    @Test func txt_title_is_escaped_in_opf_and_chapter() throws {
        let reader = try convertTXTAndParse("body", title: "Tom & Jerry <best>")
        let opf = try #require(reader.text("OEBPS/content.opf"))
        #expect(opf.contains("<dc:title>Tom &amp; Jerry &lt;best&gt;</dc:title>"))
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("&amp;") && ch.contains("&lt;best&gt;"))
    }

    @Test func txt_utf8_multibyte_content_round_trips() throws {
        let reader = try convertTXTAndParse("中文段落與 emoji 😀")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("中文段落與 emoji 😀"))
    }

    @Test func txt_latin1_only_bytes_decode_via_fallback() throws {
        // 0xE9 is `é` in Latin-1 but invalid as standalone UTF-8 — decodeText()
        // must fall back to isoLatin1 rather than throwing encodingFailed.
        var raw = Data("caf".utf8)
        raw.append(0xE9) // é (Latin-1)
        let src = try writeTempFile(raw, ext: "txt")
        let out = try EPUBConverter().convertTXT(at: src, title: "Café")
        let reader = try #require(StoredZipReader(try Data(contentsOf: out)))
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("café"), "Latin-1 byte 0xE9 must decode to 'é' via the fallback path")
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
    }

    // MARK: - Markdown conversion (MD)

    @Test func md_headings_convert_to_h_tags() throws {
        let reader = try convertMDAndParse("# Title\n\n## Subtitle\n\n###### Deep")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<h1>Title</h1>"))
        #expect(ch.contains("<h2>Subtitle</h2>"))
        #expect(ch.contains("<h6>Deep</h6>"))
    }

    @Test func md_bold_and_italic_inline_formatting() throws {
        let reader = try convertMDAndParse("This is **bold** and *italic* text.")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<strong>bold</strong>"))
        #expect(ch.contains("<em>italic</em>"))
    }

    @Test func md_unordered_list_converts_to_ul() throws {
        let reader = try convertMDAndParse("- apple\n- banana\n- cherry")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<ul>"))
        #expect(ch.contains("<li>apple</li>"))
        #expect(ch.contains("<li>cherry</li>"))
    }

    @Test func md_ordered_list_converts_to_ol() throws {
        let reader = try convertMDAndParse("1. first\n2. second\n3. third")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<ol>"))
        #expect(ch.contains("<li>first</li>"))
        #expect(ch.contains("<li>third</li>"))
    }

    @Test func md_fenced_code_block_escapes_and_wraps_in_pre_code() throws {
        let reader = try convertMDAndParse("```\nif a < b { x }\n```")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<pre><code>"))
        #expect(ch.contains("if a &lt; b { x }"), "code-block content must be HTML-escaped")
    }

    @Test func md_inline_code_converts_to_code_tag() throws {
        let reader = try convertMDAndParse("Run `swift build` now.")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<code>swift build</code>"))
    }

    @Test func md_blockquote_converts_to_blockquote_tag() throws {
        let reader = try convertMDAndParse("> quoted line one\n> quoted line two")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<blockquote>"))
        #expect(ch.contains("quoted line one"))
    }

    @Test func md_plain_paragraph_wrapped_in_p() throws {
        let reader = try convertMDAndParse("Just a normal paragraph of prose.")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<p>Just a normal paragraph of prose.</p>"))
    }

    @Test func md_metacharacters_in_paragraph_are_escaped() throws {
        let reader = try convertMDAndParse("compare a & b with x < y")
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("a &amp; b with x &lt; y"))
    }

    @Test func md_always_produces_exactly_one_chapter() throws {
        // convertMD never splits — the whole document is one chapter regardless of size.
        let big = (0..<500).map { "Paragraph number \($0) with some filler text here." }
            .joined(separator: "\n\n")
        let reader = try convertMDAndParse(big)
        #expect(reader.chapterNames == ["OEBPS/ch001.xhtml"])
    }

    @Test func empty_md_produces_one_chapter_with_empty_body() throws {
        let reader = try convertMDAndParse("")
        #expect(reader.chapterNames == ["OEBPS/ch001.xhtml"])
        // SimpleMarkdownToHTML("") yields "" — chapter is structurally valid but bodyless.
        let ch = try #require(reader.text("OEBPS/ch001.xhtml"))
        #expect(ch.contains("<body>"))
    }

    @Test func md_invalid_utf8_throws_encoding_failed() throws {
        // convertMD requires strict UTF-8 (no Latin-1 fallback, unlike TXT).
        var raw = Data("text".utf8)
        raw.append(0xFF) // invalid UTF-8 byte
        let src = try writeTempFile(raw, ext: "md")
        #expect(throws: EPUBConverterError.self) {
            _ = try EPUBConverter().convertMD(at: src, title: "Bad")
        }
        try? FileManager.default.removeItem(at: src)
    }

    // MARK: - Validation / error paths

    @Test func missing_source_file_throws() throws {
        let ghost = FileManager.default.temporaryDirectory
            .appendingPathComponent("does-not-exist-\(UUID().uuidString).txt")
        // attributesOfItem on a non-existent path throws before any conversion.
        #expect(throws: (any Error).self) {
            _ = try EPUBConverter().convertTXT(at: ghost, title: "Ghost")
        }
    }

    @Test func max_bytes_constant_is_twenty_megabytes() {
        // Pin the limit — importer surfaces this exact value in its error mapping.
        #expect(EPUBConverter.maxBytes == 20 * 1024 * 1024)
    }

    @Test func progress_chunk_constant_is_half_a_megabyte() {
        #expect(EPUBConverter.progressChunkBytes == 512 * 1024)
    }

    @Test func file_too_large_error_describes_byte_count() {
        let err = EPUBConverterError.fileTooLarge(21_000_000)
        let desc = try? #require(err.errorDescription)
        #expect(desc?.contains("21000000") == true)
        #expect(desc?.contains("too large") == true)
    }

    @Test func encoding_failed_error_has_description() {
        #expect(EPUBConverterError.encodingFailed.errorDescription?.isEmpty == false)
    }

    @Test func archive_failed_error_has_description() {
        #expect(EPUBConverterError.archiveFailed.errorDescription?.isEmpty == false)
    }

    // MARK: - Progress reporting

    @Test func convertTXT_reports_terminal_progress_value() throws {
        let src = try writeTempText("Some content for the conversion.", ext: "txt")
        var samples: [Double] = []
        let lock = NSLock()
        let out = try EPUBConverter().convertTXT(at: src, title: "P") { p in
            lock.lock(); samples.append(p); lock.unlock()
        }
        #expect(samples.last == 1.0, "progress callback must finish at 1.0")
        #expect(samples.allSatisfy { $0 >= 0.0 && $0 <= 1.0 }, "progress stays within 0…1")
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
    }

    @Test func convertTXT_progress_is_monotonic_non_decreasing() throws {
        // Build a file large enough to span several 512 KB read chunks.
        let big = String(repeating: "lorem ipsum dolor sit amet\n", count: 60_000)
        let src = try writeTempText(big, ext: "txt")
        var samples: [Double] = []
        let lock = NSLock()
        let out = try EPUBConverter().convertTXT(at: src, title: "Big") { p in
            lock.lock(); samples.append(p); lock.unlock()
        }
        #expect(samples.count > 1, "multi-chunk read must emit more than one progress sample")
        for i in 1..<samples.count {
            #expect(samples[i] >= samples[i - 1], "progress must never go backwards")
        }
        #expect(samples.last == 1.0)
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
    }

    @Test func convertTXT_succeeds_with_nil_progress_callback() throws {
        // The progress argument is optional — the default importer call passes nil.
        let src = try writeTempText("no progress observer here", ext: "txt")
        let out = try EPUBConverter().convertTXT(at: src, title: "NoProgress")
        #expect(FileManager.default.fileExists(atPath: out.path))
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
    }

    // MARK: - Output file contract

    @Test func output_url_has_epub_extension_and_exists() throws {
        let src = try writeTempText("content", ext: "txt")
        let out = try EPUBConverter().convertTXT(at: src, title: "Ext")
        #expect(out.pathExtension == "epub")
        #expect(FileManager.default.fileExists(atPath: out.path))
        try? FileManager.default.removeItem(at: out)
        try? FileManager.default.removeItem(at: src)
    }

    @Test func consecutive_conversions_produce_distinct_output_files() throws {
        let src = try writeTempText("same input", ext: "txt")
        let conv = EPUBConverter()
        let a = try conv.convertTXT(at: src, title: "T")
        let b = try conv.convertTXT(at: src, title: "T")
        #expect(a != b, "each conversion must write a uniquely-named temp EPUB")
        try? FileManager.default.removeItem(at: a)
        try? FileManager.default.removeItem(at: b)
        try? FileManager.default.removeItem(at: src)
    }

    // MARK: - Nav document ↔ chapter consistency

    @Test func nav_document_lists_every_chapter() throws {
        let paragraph = String(repeating: "y", count: 120)
        let text = (0..<200).map { _ in paragraph }.joined(separator: "\n")
        let reader = try convertTXTAndParse(text)
        let nav = try #require(reader.text("OEBPS/nav.xhtml"))
        for (idx, _) in reader.chapterNames.enumerated() {
            let id = String(format: "ch%03d", idx + 1)
            #expect(nav.contains("href=\"\(id).xhtml\""),
                    "nav.xhtml must reference every chapter document")
        }
    }

    @Test func content_opf_spine_references_all_manifest_chapters() throws {
        let reader = try convertTXTAndParse("solo chapter")
        let opf = try #require(reader.text("OEBPS/content.opf"))
        #expect(opf.contains("<item id=\"ch001\" href=\"ch001.xhtml\""))
        #expect(opf.contains("<itemref idref=\"ch001\"/>"))
    }
}
