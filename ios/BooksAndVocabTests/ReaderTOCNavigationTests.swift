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
        let uiTestSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocabUITests/ReaderFlowUITests.swift"
            ),
            encoding: .utf8
        )
        let requiredBlock = try #require(
            Self.sourceBlock(
                containing: "fixtures: [.authSignedIn, .readerRealBookLibrary]",
                in: uiTestSource
            )
        )
        let counterexampleBlocks = Self.sourceBlocks(
            containing: ".bookshelf(\"book_card_complete\")",
            in: uiTestSource
        )
        let requiredLabels = Self.perfLogLabels(in: requiredBlock).filter {
            $0.hasPrefix("reader-toc-")
        }
        let counterexampleLabels = counterexampleBlocks
            .flatMap(Self.perfLogLabels(in:))
            .filter { $0.hasPrefix("reader-toc-") }
        let requiredLabel = try #require(requiredLabels.first)

        #expect(requiredFixtureID != counterexampleFixtureID)
        #expect(requiredLabels.count == 1)
        #expect(counterexampleLabels.count == 2)
        #expect(counterexampleLabels.allSatisfy { $0.contains("-counterexample-") })
        #expect(requiredLabel.hasSuffix("-required"))
        #expect(Set([requiredLabel]).isDisjoint(with: Set(counterexampleLabels)))
        #expect(requiredAssetID == "books.reader_real_book_epub")
        #expect(counterexampleAssetID == "books.catalog_reader_epub")
        #expect(Set([requiredAssetID]).isDisjoint(with: [counterexampleAssetID]))
    }

    @Test func counterexampleUITestsAssertDoneControlIsDisabled() throws {
        let rootURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let pageSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocabUITests/Pages/ReaderPage.swift"
            ),
            encoding: .utf8
        )
        let flowSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocabUITests/ReaderFlowUITests.swift"
            ),
            encoding: .utf8
        )

        #expect(pageSource.contains("var tocDone: XCUIElement"))
        #expect(Self.occurrences(of: "XCTAssertTrue(reader.tocDone.waitUntilExists", in: flowSource) == 2)
        #expect(Self.occurrences(of: "XCTAssertFalse(reader.tocDone.isEnabled)", in: flowSource) == 2)
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
        #expect(tocSource.contains("reader.toc.done"))
    }

    private static func perfLogLabels(in source: String) -> [String] {
        source.split(whereSeparator: \.isNewline).compactMap { line in
            guard let marker = line.range(of: "perfLog: \"") else { return nil }
            let valueStart = marker.upperBound
            guard let valueEnd = line[valueStart...].firstIndex(of: "\"") else { return nil }
            return String(line[valueStart..<valueEnd])
        }
    }

    private static func sourceBlock(containing marker: String, in source: String) -> String? {
        sourceBlocks(containing: marker, in: source).first
    }

    private static func sourceBlocks(containing marker: String, in source: String) -> [String] {
        let lines = source.split(omittingEmptySubsequences: false, whereSeparator: \.isNewline)
            .map(String.init)
        var blocks: [String] = []

        for markerIndex in lines.indices where lines[markerIndex].contains(marker) {
            guard let start = lines[...markerIndex].lastIndex(where: {
                $0.hasPrefix("    func ")
            }) else { continue }
            let end = lines[(markerIndex + 1)...].firstIndex(where: {
                $0.hasPrefix("    @MainActor")
            }) ?? lines.endIndex
            blocks.append(lines[start..<end].joined(separator: "\n"))
        }
        return blocks
    }

    private static func occurrences(of needle: String, in source: String) -> Int {
        source.components(separatedBy: needle).count - 1
    }
}
#endif
