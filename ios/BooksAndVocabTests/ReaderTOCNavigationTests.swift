#if os(iOS)
import Foundation
import ReadiumShared
import Testing
@testable import BooksAndVocab

struct ReaderTOCNavigationTests {
    @Test @MainActor
    func navigatorTrueIsTheFirstSuccessfulNavigationSignal() async throws {
        let requestID = UUID()
        let locator = try Self.locator(href: "OEBPS/chapter-b.xhtml")
        let navigator = FakeReaderNavigator(outcome: .accepted)
        let bridge = ReaderTOCNavigationBridge(
            navigator: navigator,
            timeoutNanoseconds: 50_000_000
        )

        let event = await bridge.navigate(requestID: requestID, locator: locator)

        #expect(event == .goAccepted(requestID: requestID, locatorHref: "OEBPS/chapter-b.xhtml"))
        #expect(navigator.requestedLocator?.href.string == "OEBPS/chapter-b.xhtml")
    }

    @Test @MainActor
    func navigatorFalseLeavesSelectionRetryable() async throws {
        let requestID = UUID()
        let locator = try Self.locator(href: "OEBPS/chapter-b.xhtml")
        let event = await ReaderTOCNavigationBridge(
            navigator: FakeReaderNavigator(outcome: .rejected),
            timeoutNanoseconds: 50_000_000
        ).navigate(requestID: requestID, locator: locator)

        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [1],
            title: "Chapter B",
            expectedHref: "OEBPS/chapter-b.xhtml",
            requestID: requestID
        )
        state.apply(event)

        #expect(event == .goRejected(requestID: requestID))
        #expect(state.phase == .failure)
        #expect(state.canRetry)
        #expect(!state.canDismissSheet)
    }

    @Test @MainActor
    func missingNavigatorIsNotASuccessSignal() async throws {
        let requestID = UUID()
        let locator = try Self.locator(href: "OEBPS/chapter-b.xhtml")
        let event = await ReaderTOCNavigationBridge(
            navigator: nil,
            timeoutNanoseconds: 50_000_000
        ).navigate(requestID: requestID, locator: locator)

        #expect(event == .navigatorUnavailable(requestID: requestID))
    }

    @Test @MainActor
    func matchingLocationCallbackOwnsSuccessForTheRequestToken() throws {
        let requestID = UUID()
        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [1],
            title: "Chapter B",
            expectedHref: "OEBPS/chapter-b.xhtml",
            requestID: requestID
        )

        state.apply(
            .locationDidChange(
                requestID: requestID,
                locatorHref: "OEBPS/chapter-b.xhtml"
            )
        )

        #expect(state.phase == .success)
        #expect(state.destinationHref == "OEBPS/chapter-b.xhtml")
        #expect(state.observedLocatorHref == "OEBPS/chapter-b.xhtml")
        #expect(state.canDismissSheet)
    }

    @Test @MainActor
    func timeoutAndCancellationRemainRetryable() throws {
        let requestID = UUID()
        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [1],
            title: "Chapter B",
            expectedHref: "OEBPS/chapter-b.xhtml",
            requestID: requestID
        )

        state.apply(.timedOut(requestID: requestID))
        #expect(state.phase == .failure)
        #expect(state.failureReason == .timedOut)
        #expect(state.canRetry)

        _ = state.beginRetry(requestID: requestID)
        state.apply(.cancelled(requestID: requestID))
        #expect(state.phase == .failure)
        #expect(state.failureReason == .cancelled)
        #expect(state.canRetry)
    }

    @Test @MainActor
    func locatorMismatchAndStaleCallbackCannotCloseSheet() throws {
        let requestID = UUID()
        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [1],
            title: "Chapter B",
            expectedHref: "OEBPS/chapter-b.xhtml",
            requestID: requestID
        )

        state.apply(
            .locationDidChange(
                requestID: requestID,
                locatorHref: "OEBPS/chapter-a.xhtml"
            )
        )
        #expect(state.phase == .failure)
        #expect(state.failureReason == .locatorMismatch)
        #expect(state.canRetry)

        _ = state.beginRetry(requestID: requestID)
        state.apply(
            .locationDidChange(
                requestID: UUID(),
                locatorHref: "OEBPS/chapter-b.xhtml"
            )
        )
        #expect(state.phase == .loading)
        #expect(!state.canDismissSheet)
    }

    @Test @MainActor
    func invalidPublicationDestinationIsMissingAndRetryable() throws {
        let requestID = UUID()
        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [2],
            title: "Missing Chapter",
            expectedHref: "OEBPS/does-not-exist.xhtml",
            requestID: requestID
        )

        state.apply(.missingDestination(requestID: requestID))

        #expect(state.phase == .missingDestination)
        #expect(state.failureReason == .missingDestination)
        #expect(state.canRetry)
        #expect(!state.canDismissSheet)
    }

    @Test @MainActor
    func evidenceContractRequiresCurrentRunnerAndArtifactProvenance() {
        let artifact = ReaderTOCEvidenceArtifact(
            schema: "kg.ui.perf.evidence.v2",
            run: ReaderTOCEvidenceRun(
                verdictPath: "",
                sourceCommit: "",
                sourceTreeDirty: true,
                datasetID: "",
                datasetSHA256: "",
                device: "",
                selector: "",
                runIdentity: "",
                logPath: "",
                xcresultPath: "",
                uiScreenshotDirectory: "",
                uiVisualReviewManifest: "",
                uiReviewRoot: "",
                uiVideo: ""
            ),
            entries: []
        )

        let errors = artifact.validationErrors

        #expect(errors.contains("run.sourceCommit"))
        #expect(errors.contains("run.sourceTreeDirty"))
        #expect(errors.contains("run.datasetSHA256"))
        #expect(errors.contains("run.device"))
        #expect(errors.contains("run.selector"))
        #expect(errors.contains("run.runIdentity"))
        #expect(errors.contains("run.artifacts"))
    }

    @Test
    func tocHierarchyKeepsStableNestedPaths() {
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
    }

    @Test
    func productionTOCInputDoesNotCreateSyntheticFragmentDestination() throws {
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
        let readerSource = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocab/Views/Reader/ReaderView.swift"
            ),
            encoding: .utf8
        )

        #expect(!tocSource.contains("href: \"#\""))
        #expect(!readerSource.contains("readerTOCInjectLocateFailureOnce"))
        #expect(!readerSource.contains("consumeTOCInjection"))
    }

    private static func locator(href: String) throws -> Locator {
        let mediaType = try #require(MediaType("application/xhtml+xml"))
        let url = try #require(AnyURL(path: href))
        return Locator(href: url, mediaType: mediaType)
    }
}

@MainActor
private final class FakeReaderNavigator: ReaderNavigatorDriving {
    enum Outcome {
        case accepted
        case rejected
        case hanging
    }

    let outcome: Outcome
    private(set) var requestedLocator: Locator?

    init(outcome: Outcome) {
        self.outcome = outcome
    }

    func go(to locator: Locator) async -> Bool? {
        requestedLocator = locator
        switch outcome {
        case .accepted:
            return true
        case .rejected:
            return false
        case .hanging:
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            return false
        }
    }
}
#endif
