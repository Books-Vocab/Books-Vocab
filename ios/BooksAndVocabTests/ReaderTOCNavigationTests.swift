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

    @Test func nilLocatorWithFragmentUsesMissingDestinationOnly() {
        #expect(
            ReaderTOCNavigationResolution.resolve(hasLocator: false, href: "#")
                == .missingDestination
        )
        #expect(
            ReaderTOCNavigationResolution.resolve(hasLocator: false, href: "chapter.xhtml")
                == .failure
        )
        #expect(
            ReaderTOCNavigationResolution.resolve(hasLocator: true, href: "#")
                == .success
        )
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
        #expect(items.map(\.path) == [[0], [0, 0], [1]])
        #expect(items.map(\.depth) == [0, 1, 0])
        #expect(items.map(\.title) == ["Chapter 1", "Section 1", "Chapter 2"])
        #expect(items.map(\.href) == [
            "chapter-1.xhtml",
            "chapter-1.xhtml#section-1",
            "chapter-2.xhtml"
        ])
        #expect(items.map { $0.link.url().string } == items.map(\.href))

        // Counterexample: a flattened item must not silently retain a sibling's
        // path or href when the hierarchy is nested.
        #expect(!items.contains { $0.path == [0, 1] && $0.href == "chapter-2.xhtml" })
        #expect(!items.contains { $0.path == [0, 0] && $0.href == "chapter-2.xhtml" })
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
        let artifactURL = ProcessInfo.processInfo.environment["KG_PERF_UI_EVIDENCE_ARTIFACT"]
            .map(URL.init(fileURLWithPath:))
            ?? rootURL.appendingPathComponent(
                "ios/BooksAndVocabTests/Fixtures/reader-toc-ui-evidence.json"
            )
        let artifactData = try Data(contentsOf: artifactURL)
        let artifact = try JSONDecoder().decode(
            ReaderTOCEvidenceArtifact.self,
            from: artifactData
        )
        #expect(artifact.schema == "kg.ui.perf.evidence.v1")
        #expect(artifact.datasetID == "marketing_demo")
        let requiredEntries = artifact.entries.filter { $0.partition == "required" }
        let counterexampleEntries = artifact.entries.filter { $0.partition == "counterexample" }
        let requiredLabels = requiredEntries.map(\.label)
        let counterexampleLabels = counterexampleEntries.map(\.label)
        let requiredLabel = try #require(requiredLabels.first)
        let requiredInodes = Set(requiredEntries.map(\.assetInode))
        let counterexampleInodes = Set(counterexampleEntries.map(\.assetInode))
        let manifestAssets = try #require(root["assets"] as? [String: Any])
        let manifestAssetIDs = Set(
            manifestAssets.flatMap { category, value -> [String] in
                guard let categoryAssets = value as? [String: Any] else { return [] }
                return categoryAssets.keys.map { "\(category).\($0)" }
            }
        )
        let artifactAssetIDs = Set(artifact.entries.map(\.assetID))

        #expect(requiredFixtureID != counterexampleFixtureID)
        #expect(requiredLabels.count == 1)
        #expect(counterexampleLabels.count == 2)
        #expect(counterexampleLabels.allSatisfy { $0.contains("-counterexample-") })
        #expect(requiredLabel.hasSuffix("-required"))
        #expect(Set([requiredLabel]).isDisjoint(with: Set(counterexampleLabels)))
        #expect(requiredInodes.isDisjoint(with: counterexampleInodes))
        #expect(artifactAssetIDs.isSubset(of: Set(manifestAssetIDs)))
        #expect(requiredAssetID == "books.reader_real_book_epub")
        #expect(counterexampleAssetID == "books.catalog_reader_epub")
        #expect(Set([requiredAssetID]).isDisjoint(with: Set(counterexampleEntries.map(\.assetID))))
        #expect(requiredEntries.first?.href == "OEBPS/chapter1.xhtml")
        #expect(requiredEntries.first?.locatorHref == "OEBPS/chapter1.xhtml")
        #expect(counterexampleEntries.contains { $0.href == "#" && $0.locatorHref == nil })
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
        #expect(Self.occurrences(of: "XCTAssertFalse(reader.tocDone.isEnabled)", in: flowSource) == 3)
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
        let readerSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocab/Views/Reader/ReaderView.swift"
            ),
            encoding: .utf8
        )
        let panelsSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocab/Views/Reader/ReaderView+Panels.swift"
            ),
            encoding: .utf8
        )
        let stateSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocab/Views/Reader/ReaderViewState.swift"
            ),
            encoding: .utf8
        )
        let flowSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocabUITests/ReaderFlowUITests.swift"
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
        #expect(panelsSource.contains("reader.toc.destination"))
        #expect(panelsSource.contains("reader.toc.result.success"))
        #expect(flowSource.contains("reader.tocSuccess.waitUntilExists"))
        #expect(flowSource.contains("reader.tocDestination.waitUntilExists"))
        #expect(flowSource.contains("reader.contentText(Self.seededWord)"))
        #expect(stateSource.contains("href == \"#\""))
        #expect(!flowSource.contains("-readerTOCInjectMissingDestinationOnce"))
    }

    private struct ReaderTOCEvidenceArtifact: Decodable {
        let schema: String
        let datasetID: String
        let entries: [ReaderTOCEvidenceEntry]
    }

    private struct ReaderTOCEvidenceEntry: Decodable {
        let label: String
        let partition: String
        let fixtureID: String
        let assetID: String
        let assetInode: String
        let path: [Int]
        let href: String
        let locatorHref: String?
    }

    private static func occurrences(of needle: String, in source: String) -> Int {
        source.components(separatedBy: needle).count - 1
    }
}
#endif
