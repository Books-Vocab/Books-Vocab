#if os(iOS)
import Foundation
import ReadiumShared
import Testing
@testable import BooksAndVocab

struct ReaderTOCNavigationTests {
    @Test func selectionFailureRetainsSheetAndRetryContext() {
        var state = ReaderTOCNavigationState()

        state.beginSelection(path: [0, 1], title: "Section 2")

        #expect(state.phase == .loading)
        #expect(state.selectedPath == [0, 1])
        #expect(!state.canDismissSheet)

        state.failSelection(message: "The chapter could not be opened.")

        #expect(state.phase == .failure)
        #expect(!state.canDismissSheet)
        #expect(state.canRetry)
        #expect(state.errorMessage == "The chapter could not be opened.")

        state.beginRetry()

        #expect(state.phase == .loading)
        #expect(state.selectedPath == [0, 1])
        #expect(state.canRetry == false)
        #expect(state.canDismissSheet == false)
    }

    @Test func missingDestinationIsRetryableAndSuccessClearsOutcome() {
        var state = ReaderTOCNavigationState()
        state.beginSelection(path: [2], title: "Missing chapter")
        state.markMissingDestination()

        #expect(state.phase == .missingDestination)
        #expect(state.canRetry)
        #expect(!state.canDismissSheet)

        state.beginRetry()
        state.succeed()

        #expect(state.phase == .success)
        #expect(state.selectedPath == [2])
        #expect(!state.canRetry)
        #expect(state.errorMessage == nil)
    }

    @Test func tocHierarchyKeepsStableNestedPaths() {
        let links = [
            Link(
                href: "chapter-1.xhtml",
                title: "Chapter 1",
                children: [
                    Link(href: "chapter-1.xhtml#section-1", title: "Section 1")
                ]
            ),
            Link(href: "chapter-2.xhtml", title: "Chapter 2")
        ]

        let items = ReaderTOCHierarchy.flatten(links)

        #expect(items.map(\.id) == ["0", "0.0", "1"])
        #expect(items.map(\.depth) == [0, 1, 0])
        #expect(items.map(\.title) == ["Chapter 1", "Section 1", "Chapter 2"])
    }

    @Test func evidencePartitionsUseRealWorldFixtureAndDisjointAssets() throws {
        let rootURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let worldURL = rootURL
            .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
        let data = try Data(contentsOf: worldURL)
        let root = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        #expect(root["schema"] as? String == "kg.fixture.dataset.v2")
        let reader = try #require(root["reader"] as? [String: Any])
        let bookshelf = try #require(root["bookshelf"] as? [String: Any])
        let required = try #require(reader["realBookLibrary"] as? [String: Any])
        let counterexample = try #require(bookshelf["book_card_complete"] as? [String: Any])
        let counterexampleBook = try #require((counterexample["books"] as? [[String: Any]])?.first)

        let requiredFixtureID = "reader.realBookLibrary"
        let counterexampleFixtureID = "bookshelf.book_card_complete"
        let requiredAssetID = try #require(required["bookAssetRef"] as? String)
        let counterexampleAssetID = try #require(counterexampleBook["bookAssetRef"] as? String)
        let requiredLabel = "reader-toc-required"
        let counterexampleLabels = [
            "reader-toc-counterexample-failure",
            "reader-toc-counterexample-missing"
        ]

        #expect(requiredFixtureID != counterexampleFixtureID)
        #expect(!counterexampleLabels.contains(requiredLabel))
        #expect(requiredAssetID == "books.reader_real_book_epub")
        #expect(counterexampleAssetID == "books.catalog_reader_epub")
        #expect(Set([requiredAssetID]).isDisjoint(with: [counterexampleAssetID]))
    }

    @Test func productionSelectorContractIsIdentifierBased() throws {
        let rootURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let tocSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocab/Views/Reader/TOCView.swift"
            ),
            encoding: .utf8
        )
        let headerSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocab/Views/Reader/ReaderViewPresenter+Headers.swift"
            ),
            encoding: .utf8
        )
        for identifier in [
            "reader.toc.chapterHierarchy",
            "reader.toc.selected",
            "reader.toc.loading",
            "reader.toc.navigation.loading",
            "reader.toc.result.success",
            "reader.toc.error",
            "reader.toc.retry",
            "reader.toc.missingDestination"
        ] {
            #expect(tocSource.contains(identifier))
        }
        #expect(headerSource.contains("reader.header.tocButton"))
    }
}
#endif
