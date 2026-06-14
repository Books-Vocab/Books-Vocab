#if DEBUG
import Foundation
import PDFKit
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite(.serialized) struct BookshelfFixturesTests {
    private static var marketingDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
            return try Data(contentsOf: url)
        }
    }

    private static var generatedDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/demo/generated/ios_fixture_dataset.json")
            return try Data(contentsOf: url)
        }
    }

    @Test func bookshelfFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = BookshelfFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = BookshelfFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "bookshelf.book_card_complete",
            "bookshelf.book_card_long_title",
            "bookshelf.book_card_mid_progress",
            "bookshelf.book_card_pdf_format",
            "bookshelf.book_card_placeholder_epub",
            "bookshelf.progress_card",
            "bookshelf.placeholder_card",
            "bookshelf.reader_notebook_bound",
            "bookshelf.reader_notebook_empty",
            "bookshelf.reader_notebook_long_bound",
            "bookshelf.reader_notebook_unbound",
            "bookshelf.empty_library",
            "bookshelf.with_books_library",
            "bookshelf.loading_overlay",
        ])

        #expect(catalogKeys == previewKeys)
    }

    @Test func bookshelfFixtureRegistryIsManifestOnly() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support/Fixtures/Bookshelf/BookshelfFixtures.swift")
        let source = try String(contentsOf: url, encoding: .utf8)
        let registryStart = try #require(source.range(of: "private static let registry"))
        let registryEnd = try #require(source.range(of: "private static func tags", range: registryStart.upperBound..<source.endIndex))
        let registrySource = String(source[registryStart.lowerBound..<registryEnd.lowerBound])

        #expect(registrySource.contains("BookshelfFixtureID.allCases.map"))
        #expect(registrySource.contains("FixtureDatasetStore.requireBookshelfSeed(for: fixtureID)"))
        #expect(!registrySource.contains(".init("), "Bookshelf fixture registry must not construct local seed data")
    }

    @Test func bookshelfFixtureMaterializationIsFailFast() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support/Fixtures/Bookshelf/BookshelfFixtures.swift")
        let fixtureSource = try String(contentsOf: fixtureURL, encoding: .utf8)

        #expect(fixtureSource.contains("let container: ModelContainer"))
        #expect(!fixtureSource.contains("ModelContainer?"), "Bookshelf fixtures must not expose nil as a materialization fallback")
        #expect(!fixtureSource.contains("try? context.save()"), "Bookshelf fixture SwiftData save must fail fast")
        #expect(!fixtureSource.contains("return nil"), "Bookshelf fixtures must not fall back to nil containers")
        #expect(!fixtureSource.contains("BookshelfFixtures container failed"), "Bookshelf fixtures must not log-and-continue after materialization failure")
        #expect(fixtureSource.contains("preconditionFailure(\"Failed to materialize UI World bookshelf seed"))

        let previewURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Views/Bookshelf/BookshelfPreviews.swift")
        let previewSource = try String(contentsOf: previewURL, encoding: .utf8)
        #expect(!previewSource.contains("if let container = renderModel.container"), "Bookshelf preview must not hide fixture materialization failure")
        #expect(!previewSource.contains("EmptyView()"), "Bookshelf preview must not render an empty fallback when UI World materialization fails")
    }

    @Test func repoAndGeneratedDatasetsDeclareEveryBookshelfFixture() throws {
        let expected = Set(BookshelfFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        #expect(Set(repoDocument.bookshelf.keys) == expected)
        #expect(Set(generatedDocument.bookshelf.keys) == expected)
        try Self.expectEveryBookAssetRefResolves(in: repoDocument, label: "marketing_demo")
        try Self.expectEveryBookAssetRefResolves(in: generatedDocument, label: "generated_demo")
    }

    @Test func withBooksLibraryDeclaresManifestPDFBook() throws {
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        try Self.expectManifestPDFBook(in: repoDocument, label: "marketing_demo")
        try Self.expectManifestPDFBook(in: generatedDocument, label: "generated_demo")
    }

    @Test func withBooksLibraryDeclaresManifestEPUBBook() throws {
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        try Self.expectManifestEPUBBook(in: repoDocument, label: "marketing_demo")
        try Self.expectManifestEPUBBook(in: generatedDocument, label: "generated_demo")
    }

    @MainActor
    @Test func withBooksLibraryFixtureComesFromUIWorld() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedSeed = try #require(document.bookshelf[BookshelfFixtureID.withBooksLibrary.rawValue])
        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let model = BookshelfFixtures.renderModel(for: .withBooksLibrary)
            #expect(model.books.map(\.title) == expectedSeed.books.map(\.title))
            #expect(model.referenceDate == expectedSeed.referenceDate)
            let rows = try model.container.mainContext.fetch(FetchDescriptor<Book>())
            #expect(rows.map(\.title).sorted() == expectedSeed.books.map(\.title).sorted())
        }
    }

    private static func expectEveryBookAssetRefResolves(in document: FixtureDatasetDocument, label: String) throws {
        for (fixtureKey, seed) in document.bookshelf {
            for book in seed.books {
                let ref = try #require(
                    book.bookAssetRef?.trimmingCharacters(in: .whitespacesAndNewlines),
                    "\(label): bookshelf.\(fixtureKey).\(book.title) must declare bookAssetRef"
                )
                #expect(ref.hasPrefix("books."), "\(label): bookshelf.\(fixtureKey).\(book.title) must use books.* asset ref")
                #expect(document.assets.asset(for: ref) != nil, "\(label): bookshelf.\(fixtureKey).\(book.title) asset \(ref) must resolve")
            }
        }
    }

    private static func expectManifestPDFBook(in document: FixtureDatasetDocument, label: String) throws {
        let seed = try #require(document.bookshelf[BookshelfFixtureID.withBooksLibrary.rawValue])
        let pdfBook = try #require(
            seed.books.first(where: { $0.format == .pdf }),
            "\(label): bookshelf.with_books_library must include a PDF book for PDFReaderViewScenarios"
        )
        let ref = try #require(
            pdfBook.bookAssetRef?.trimmingCharacters(in: .whitespacesAndNewlines),
            "\(label): PDF book must declare bookAssetRef"
        )
        #expect(ref == "books.catalog_reader_pdf")
        let asset = try #require(document.assets.asset(for: ref), "\(label): \(ref) must resolve")
        #expect(asset.installAs == "Books/\(pdfBook.fileName)")
        #expect(asset.byteSize > 0)
        #expect(asset.sha256.count == 64)
        let pdfDocument = try #require(
            PDFDocument(url: URL(fileURLWithPath: asset.sourcePath)),
            "\(label): \(ref) must be readable by PDFKit"
        )
        #expect(pdfDocument.pageCount > 0, "\(label): \(ref) must contain at least one PDF page")
    }

    private static func expectManifestEPUBBook(in document: FixtureDatasetDocument, label: String) throws {
        let seed = try #require(document.bookshelf[BookshelfFixtureID.withBooksLibrary.rawValue])
        let epubBook = try #require(
            seed.books.first(where: { $0.format == .epub }),
            "\(label): bookshelf.with_books_library must include an EPUB book for full book-state restoration"
        )
        let ref = try #require(
            epubBook.bookAssetRef?.trimmingCharacters(in: .whitespacesAndNewlines),
            "\(label): EPUB book must declare bookAssetRef"
        )
        #expect(ref == "books.catalog_reader_epub")
        let asset = try #require(document.assets.asset(for: ref), "\(label): \(ref) must resolve")
        #expect(asset.contentType == "application/epub+zip", "\(label): \(ref) must declare EPUB contentType")
        #expect(URL(fileURLWithPath: asset.sourcePath).pathExtension == "epub", "\(label): \(ref) source must be .epub")
        #expect(asset.installAs == "Books/\(epubBook.fileName)", "\(label): \(ref) must install as the book fileName")
        #expect(FileManager.default.fileExists(atPath: asset.sourcePath), "\(label): \(ref) source file must exist")
        let data = try Data(contentsOf: URL(fileURLWithPath: asset.sourcePath))
        #expect(data.starts(with: Data("PK".utf8)), "\(label): \(ref) must be a ZIP-backed EPUB package")
    }
}
#endif
