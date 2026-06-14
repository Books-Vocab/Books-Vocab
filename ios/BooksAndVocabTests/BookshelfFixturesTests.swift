#if DEBUG
import Foundation
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
            "bookshelf.progress_card",
            "bookshelf.placeholder_card",
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

    @Test func repoAndGeneratedDatasetsDeclareEveryBookshelfFixture() throws {
        let expected = Set(BookshelfFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        #expect(Set(repoDocument.bookshelf.keys) == expected)
        #expect(Set(generatedDocument.bookshelf.keys) == expected)
        try Self.expectEveryBookAssetRefResolves(in: repoDocument, label: "marketing_demo")
        try Self.expectEveryBookAssetRefResolves(in: generatedDocument, label: "generated_demo")
    }

    @MainActor
    @Test func withBooksLibraryFixtureComesFromUIWorld() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedSeed = try #require(document.bookshelf[BookshelfFixtureID.withBooksLibrary.rawValue])
        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let model = BookshelfFixtures.renderModel(for: .withBooksLibrary)
            #expect(model.books.map(\.title) == expectedSeed.books.map(\.title))
            #expect(model.referenceDate == expectedSeed.referenceDate)
            #expect(model.container != nil)
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
}
#endif
