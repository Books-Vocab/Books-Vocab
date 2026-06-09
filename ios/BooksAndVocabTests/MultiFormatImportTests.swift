#if os(iOS)
import Foundation
import PDFKit
import Testing
@testable import BooksAndVocab

/// Coverage for the non-EPUB import paths — focused on the seams that are
/// *not* already pinned by `EPUBConverterTests`.
///
/// Scope rationale:
/// - TXT / MD *conversion* (`EPUBConverter.convertTXT` / `convertMD` — paragraph
///   splitting, Markdown structure, escaping, encoding fallback, oversize) is
///   already exhaustively covered in `EPUBConverterTests.swift`; re-testing it
///   here would only duplicate. This file therefore does not re-pin conversion.
/// - PDF import has no converter (`importPDF` keeps the original file and uses
///   `PDFDocument` directly for cover + page handling). PDF text extraction is
///   pinned here at the `PDFDocument` API level — exactly the dependency
///   `importPDF` and the reader's `extractContext` consume.
/// - The cross-format failure contract — `BookshelfImportError` classification,
///   diagnosis labels and user-facing descriptions — covers the TXT / MD / PDF
///   error surfaces that `importTXT` / `importMD` / `importPDF` route through
///   `BookshelfImportError.classify`. The import methods themselves require
///   security-scoped URLs + `Book.booksDirectory` filesystem side effects +
///   `@MainActor` Readium wiring, so the classifier is the testable seam.
///
/// EPUB conversion is intentionally out of scope (owned by `EPUBConverterTests`).
struct MultiFormatImportTests {

    // MARK: - Fixture helpers

    /// A minimal single-page PDF synthesized in-memory containing `text`.
    /// Uses `UIGraphicsPDFRenderer` so no external file is required.
    private func makePDFData(text: String, pages: Int = 1) -> Data {
        let bounds = CGRect(x: 0, y: 0, width: 320, height: 480)
        let renderer = UIGraphicsPDFRenderer(bounds: bounds)
        return renderer.pdfData { ctx in
            for _ in 0..<max(1, pages) {
                ctx.beginPage()
                let attrs: [NSAttributedString.Key: Any] = [
                    .font: UIFont.systemFont(ofSize: 18)
                ]
                (text as NSString).draw(
                    in: bounds.insetBy(dx: 16, dy: 16),
                    withAttributes: attrs
                )
            }
        }
    }

    // MARK: - PDF text extraction

    @Test func pdf_extractsTextFromSinglePage() throws {
        // Mirrors importPDF's reliance on PDFDocument: a synthesized PDF must
        // round-trip its text via `page.string`.
        let pdf = makePDFData(text: "Vocabulary appears here.")
        let doc = try #require(PDFDocument(data: pdf))
        #expect(doc.pageCount == 1)
        let page = try #require(doc.page(at: 0))
        let extracted = page.string ?? ""
        #expect(extracted.contains("Vocabulary"))
    }

    @Test func pdf_multiPageDocumentReportsPageCount() throws {
        let pdf = makePDFData(text: "Page body.", pages: 3)
        let doc = try #require(PDFDocument(data: pdf))
        #expect(doc.pageCount == 3)
    }

    @Test func pdf_documentLevelStringConcatenatesPages() throws {
        // PDFDocument.string aggregates page text — the surface a future
        // full-text import would consume.
        let pdf = makePDFData(text: "Repeated body.", pages: 2)
        let doc = try #require(PDFDocument(data: pdf))
        let whole = doc.string ?? ""
        #expect(whole.contains("Repeated"))
    }

    @Test func pdf_firstPageThumbnailIsRenderable() throws {
        // importPDF derives the cover from `page(at: 0)?.thumbnail(...)`.
        // Confirm the thumbnail seam produces a non-zero-size image.
        let pdf = makePDFData(text: "Cover page.")
        let doc = try #require(PDFDocument(data: pdf))
        let page = try #require(doc.page(at: 0))
        let thumb = page.thumbnail(
            of: CGSize(width: 300, height: 400),
            for: .artBox
        )
        #expect(thumb.size.width > 0)
        #expect(thumb.size.height > 0)
    }

    @Test func pdf_thumbnailEncodesToJPEG() throws {
        // importPDF stores the cover as `thumbnail.jpegData(...)` — pin that
        // the encode step yields non-empty data.
        let pdf = makePDFData(text: "Cover.")
        let doc = try #require(PDFDocument(data: pdf))
        let page = try #require(doc.page(at: 0))
        let thumb = page.thumbnail(
            of: CGSize(width: 300, height: 400),
            for: .artBox
        )
        let jpeg = try #require(thumb.jpegData(compressionQuality: 0.8))
        #expect(!jpeg.isEmpty)
    }

    @Test func pdf_pageIndexBeyondBoundsReturnsNil() throws {
        // Boundary: out-of-range page access must be nil-safe, not a trap.
        let pdf = makePDFData(text: "Single.")
        let doc = try #require(PDFDocument(data: pdf))
        #expect(doc.page(at: 5) == nil)
    }

    @Test func pdf_corruptData_failsToOpen() {
        // Boundary: bytes that are not a PDF must yield a nil document so
        // importPDF surfaces no cover and the reader shows an error state.
        let garbage = Data("not a pdf at all".utf8)
        #expect(PDFDocument(data: garbage) == nil)
    }

    @Test func pdf_emptyData_failsToOpen() {
        // Boundary: a zero-byte file must not be mistaken for a valid PDF.
        #expect(PDFDocument(data: Data()) == nil)
    }

    @Test func pdf_truncatedHeader_failsToOpen() {
        // Only the "%PDF" magic with no body — a corrupt-header case.
        let truncated = Data("%PDF-1.4".utf8)
        #expect(PDFDocument(data: truncated) == nil)
    }

    // MARK: - Import error classification (TXT / MD / PDF failure contract)

    @Test func classify_passesThroughTypedError() {
        // A pre-typed BookshelfImportError must round-trip unchanged.
        let result = BookshelfImportError.classify(
            BookshelfImportError.encodingFailed
        )
        if case .encodingFailed = result {} else {
            Issue.record("expected .encodingFailed, got \(result)")
        }
    }

    @Test func classify_mapsConverterFileTooLarge() {
        // TXT/MD oversize: EPUBConverterError.fileTooLarge → typed fileTooLarge
        // carrying the converter's 20 MB cap as the reported limit.
        let result = BookshelfImportError.classify(
            EPUBConverterError.fileTooLarge(99_000_000)
        )
        if case let .fileTooLarge(bytes, limit) = result {
            #expect(bytes == 99_000_000)
            #expect(limit == EPUBConverter.maxBytes)
        } else {
            Issue.record("expected .fileTooLarge, got \(result)")
        }
    }

    @Test func classify_mapsConverterEncodingFailed() {
        // MD invalid-UTF-8 path surfaces as encodingFailed.
        let result = BookshelfImportError.classify(
            EPUBConverterError.encodingFailed
        )
        if case .encodingFailed = result {} else {
            Issue.record("expected .encodingFailed, got \(result)")
        }
    }

    @Test func classify_archiveFailedBecomesCorruptedHeaderWithTXTExt() {
        // Converter archive failure during a .txt import → corruptedHeader
        // labelled by the source extension.
        let result = BookshelfImportError.classify(
            EPUBConverterError.archiveFailed,
            sourceURL: URL(fileURLWithPath: "/tmp/x.txt")
        )
        if case let .corruptedHeader(format) = result {
            #expect(format == "TXT")
        } else {
            Issue.record("expected .corruptedHeader, got \(result)")
        }
    }

    @Test func classify_archiveFailedFallsBackToEPUBLabelWithoutURL() {
        // No source URL → default "EPUB" label.
        let result = BookshelfImportError.classify(
            EPUBConverterError.archiveFailed
        )
        if case let .corruptedHeader(format) = result {
            #expect(format == "EPUB")
        } else {
            Issue.record("expected .corruptedHeader, got \(result)")
        }
    }

    @Test func classify_cocoaCorruptFileErrorBecomesCorruptedHeader() {
        // Foundation read-corrupt error during a .md import.
        let cocoa = NSError(
            domain: NSCocoaErrorDomain,
            code: NSFileReadCorruptFileError
        )
        let result = BookshelfImportError.classify(
            cocoa,
            sourceURL: URL(fileURLWithPath: "/tmp/doc.md")
        )
        if case let .corruptedHeader(format) = result {
            #expect(format == "MD")
        } else {
            Issue.record("expected .corruptedHeader, got \(result)")
        }
    }

    @Test func classify_cocoaInapplicableEncodingBecomesCorruptedHeader() {
        // PDF (or any) read with an inapplicable string encoding.
        let cocoa = NSError(
            domain: NSCocoaErrorDomain,
            code: NSFileReadInapplicableStringEncodingError
        )
        let result = BookshelfImportError.classify(
            cocoa,
            sourceURL: URL(fileURLWithPath: "/tmp/scan.pdf")
        )
        if case let .corruptedHeader(format) = result {
            #expect(format == "PDF")
        } else {
            Issue.record("expected .corruptedHeader, got \(result)")
        }
    }

    @Test func classify_cocoaNoPermissionBecomesSecurityScopeFailure() {
        let cocoa = NSError(
            domain: NSCocoaErrorDomain,
            code: NSFileReadNoPermissionError
        )
        let result = BookshelfImportError.classify(cocoa)
        if case .securityScopeAccessFailed = result {} else {
            Issue.record("expected .securityScopeAccessFailed, got \(result)")
        }
    }

    @Test func classify_cocoaNoSuchFileBecomesSecurityScopeFailure() {
        let cocoa = NSError(
            domain: NSCocoaErrorDomain,
            code: NSFileReadNoSuchFileError
        )
        let result = BookshelfImportError.classify(cocoa)
        if case .securityScopeAccessFailed = result {} else {
            Issue.record("expected .securityScopeAccessFailed, got \(result)")
        }
    }

    @Test func classify_unrelatedCocoaErrorFallsThrough() {
        // A Cocoa-domain error with an unhandled code drops to .unknown.
        let cocoa = NSError(domain: NSCocoaErrorDomain, code: 99_999)
        let result = BookshelfImportError.classify(cocoa)
        if case .unknown = result {} else {
            Issue.record("expected .unknown, got \(result)")
        }
    }

    @Test func classify_unknownErrorFallsThrough() {
        struct Weird: Error {}
        let result = BookshelfImportError.classify(Weird())
        if case .unknown = result {} else {
            Issue.record("expected .unknown, got \(result)")
        }
    }

    // MARK: - Error presentation contract

    @Test func diagnosisLabels_areDistinctAndNonEmpty() {
        let cases: [BookshelfImportError] = [
            .securityScopeAccessFailed,
            .unsupportedExtension("xyz"),
            .fileTooLarge(bytes: 1, limit: 1),
            .encodingFailed,
            .corruptedHeader(format: "PDF"),
            .unknown(underlying: "boom")
        ]
        let labels = cases.map(\.diagnosisLabel)
        #expect(labels.allSatisfy { !$0.isEmpty })
        // Each failure category needs a distinct short label for the toast.
        #expect(Set(labels).count == labels.count)
    }

    @Test func errorDescription_isNonEmptyForEveryCase() {
        let cases: [BookshelfImportError] = [
            .securityScopeAccessFailed,
            .unsupportedExtension("rtf"),
            .fileTooLarge(bytes: 1, limit: 1),
            .encodingFailed,
            .corruptedHeader(format: "TXT"),
            .unknown(underlying: "boom")
        ]
        #expect(cases.allSatisfy { ($0.errorDescription ?? "").isEmpty == false })
    }

    @Test func errorDescription_fileTooLargeReportsMegabytes() {
        let err = BookshelfImportError.fileTooLarge(
            bytes: 25 * 1_048_576,
            limit: 20 * 1_048_576
        )
        let desc = err.errorDescription ?? ""
        #expect(desc.contains("25"))
        #expect(desc.contains("20"))
    }

    @Test func errorDescription_unsupportedExtensionIncludesExtension() {
        let err = BookshelfImportError.unsupportedExtension("rtf")
        #expect((err.errorDescription ?? "").contains("rtf"))
    }

    @Test func errorDescription_corruptedHeaderIncludesFormat() {
        let err = BookshelfImportError.corruptedHeader(format: "PDF")
        #expect((err.errorDescription ?? "").contains("PDF"))
    }

    @Test func errorDescription_unknownEchoesUnderlyingMessage() {
        let err = BookshelfImportError.unknown(underlying: "disk full")
        #expect(err.errorDescription == "disk full")
    }
}
#endif
