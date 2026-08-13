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
    func acceptedNavigationRemainsPendingUntilMatchingLocationCallback() throws {
        let requestID = UUID()
        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [1],
            title: "Chapter B",
            expectedHref: "OEBPS/chapter-b.xhtml",
            requestID: requestID
        )

        state.apply(
            .goAccepted(
                requestID: requestID,
                locatorHref: "OEBPS/chapter-b.xhtml"
            )
        )

        #expect(state.phase == .loading)
        #expect(state.destinationHref == nil)
        #expect(!state.canDismissSheet)

        state.apply(
            .locationDidChange(
                requestID: requestID,
                locatorHref: "OEBPS/chapter-b.xhtml"
            )
        )

        #expect(state.phase == .success)
        #expect(state.destinationHref == "OEBPS/chapter-b.xhtml")
    }

    @Test @MainActor
    func acceptedWrongLocatorAndMissingCallbackCannotCloseSheet() throws {
        let requestID = UUID()
        var state = ReaderTOCNavigationState()
        _ = state.beginSelection(
            path: [1],
            title: "Chapter B",
            expectedHref: "OEBPS/chapter-b.xhtml",
            requestID: requestID
        )

        state.apply(
            .goAccepted(
                requestID: requestID,
                locatorHref: "OEBPS/chapter-a.xhtml"
            )
        )
        #expect(state.phase == .loading)
        #expect(state.destinationHref == nil)
        #expect(!state.canDismissSheet)

        state.apply(
            .locationDidChange(
                requestID: requestID,
                locatorHref: "OEBPS/chapter-a.xhtml"
            )
        )
        #expect(state.phase == .failure)
        #expect(state.failureReason == .locatorMismatch)
        #expect(state.canRetry)
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
    func hangingNavigatorIsActuallyInvokedAndHardTimeoutDoesNotWaitForIt() async throws {
        let requestID = UUID()
        let locator = try Self.locator(href: "OEBPS/chapter-b.xhtml")
        let navigator = FakeReaderNavigator(outcome: .hanging)
        let bridge = ReaderTOCNavigationBridge(
            navigator: navigator,
            timeoutNanoseconds: 50_000_000
        )
        let start = ContinuousClock.now

        let event = await bridge.navigate(requestID: requestID, locator: locator)
        let elapsed = start.duration(to: .now)

        #expect(event == .timedOut(requestID: requestID))
        #expect(navigator.requestedLocator?.href.string == "OEBPS/chapter-b.xhtml")
        #expect(elapsed < .milliseconds(500))
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
                invocation: ReaderTOCEvidenceInvocation(
                    ts: 0,
                    pid: 0,
                    verdictFile: ""
                ),
                status: "pending",
                result: "fail",
                exit: "1",
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
                screenshotPath: "",
                uiVisualReviewManifest: "",
                uiReviewRoot: "",
                uiVideo: ""
            ),
            entries: []
        )

        let errors = artifact.validationErrors

        #expect(errors.contains("run.invocation.verdictFile"))
        #expect(errors.contains("run.status"))
        #expect(errors.contains("run.result"))
        #expect(errors.contains("run.exit"))
        #expect(errors.contains("run.sourceCommit"))
        #expect(errors.contains("run.sourceTreeDirty"))
        #expect(errors.contains("run.datasetSHA256"))
        #expect(errors.contains("run.device"))
        #expect(errors.contains("run.selector"))
        #expect(errors.contains("run.runIdentity"))
        #expect(errors.contains("run.artifacts"))
    }

    @Test
    func evidenceContractRejectsUnverifiedEntryAssetIntegrity() {
        let artifact = ReaderTOCEvidenceArtifact(
            schema: "kg.ui.perf.evidence.v2",
            run: ReaderTOCEvidenceRun(
                invocation: ReaderTOCEvidenceInvocation(
                    ts: 1,
                    pid: 2,
                    verdictFile: "/tmp/verdict"
                ),
                status: "ok",
                result: "ok",
                exit: "0",
                sourceCommit: "abc123",
                sourceTreeDirty: false,
                datasetID: "marketing_demo",
                datasetSHA256: String(repeating: "a", count: 64),
                device: "simulator",
                selector: "ReaderFlow/test",
                runIdentity: "1-2-ReaderFlow/test",
                logPath: "/tmp/run.log",
                xcresultPath: "/tmp/run.xcresult",
                uiScreenshotDirectory: "/tmp/screenshots",
                screenshotPath: "/tmp/screenshots/step.png",
                uiVisualReviewManifest: "/tmp/visual.json",
                uiReviewRoot: "/tmp/review",
                uiVideo: "/tmp/run.mp4"
            ),
            entries: [
                ReaderTOCEvidenceEntry(
                    label: "reader-toc-required",
                    partition: "required",
                    fixtureID: "reader.realBookLibrary",
                    asset: ReaderTOCEvidenceAsset(
                        assetID: "not-books.reader",
                        installedPath: "relative/reader.epub",
                        expectedSHA256: String(repeating: "a", count: 64),
                        expectedByteSize: 0,
                        actualSHA256: String(repeating: "b", count: 64),
                        actualByteSize: 1
                    ),
                    path: [-1],
                    selectedRow: ReaderTOCEvidenceSelectedRow(
                        path: [0],
                        href: "",
                        title: ""
                    ),
                    observation: ReaderTOCEvidenceObservation(
                        requestedHref: "",
                        observedLocatorHref: nil,
                        observedContent: nil,
                        contentSelector: nil
                    )
                )
            ]
        )

        let errors = artifact.validationErrors

        #expect(errors.contains("entries[0].asset.assetID"))
        #expect(errors.contains("entries[0].asset.installedPath"))
        #expect(errors.contains("entries[0].asset.expectedByteSize"))
        #expect(errors.contains("entries[0].asset.sha256Mismatch"))
        #expect(errors.contains("entries[0].path"))
        #expect(errors.contains("entries[0].observation.requestedHref"))
    }

    @Test
    func evidenceContractBindsSelectedRowHrefContentAndLocator() {
        let entry = Self.evidenceEntry(
            label: "reader-toc-required",
            partition: "required",
            path: [1],
            rowPath: [0],
            href: "OEBPS/chapter2.xhtml",
            observedLocator: "OEBPS/chapter2.xhtml",
            content: "Chapter Two",
            contentSelector: "Chapter Two"
        )

        let errors = ReaderTOCEvidenceEntry.validationErrors(for: [entry])

        #expect(errors.contains("entries[0].selectedRow.pathMismatch"))
    }

    @Test
    func evidenceAssemblyFailsClosedForStaleVerdictAndRequiresCompletePartitions() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-reader-evidence-\(UUID().uuidString)", isDirectory: true)
        let screenshotPath = directory.appendingPathComponent("toc.png")
        let verdictBase = directory.appendingPathComponent("verdict").path
        let verdictJSON = URL(fileURLWithPath: "\(verdictBase).json")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try Data("png".utf8).write(to: screenshotPath)
        try Data("{}".utf8).write(to: verdictJSON)
        defer { try? FileManager.default.removeItem(at: directory) }

        let required = Self.evidenceEntry(
            label: "reader-toc-required",
            partition: "required",
            path: [1],
            rowPath: [1],
            href: "OEBPS/chapter2.xhtml",
            observedLocator: "OEBPS/chapter2.xhtml",
            content: "Chapter Two",
            contentSelector: "Chapter Two"
        )
        let counterexample = Self.evidenceEntry(
            label: "reader-toc-counterexample-failure",
            partition: "counterexample",
            path: [1],
            rowPath: [1],
            href: "OEBPS/does-not-exist.xhtml",
            observedLocator: "OEBPS/chapter1.xhtml",
            content: nil,
            contentSelector: nil
        )
        let retry = Self.evidenceEntry(
            label: "reader-toc-counterexample-retry",
            partition: "counterexample",
            path: [1],
            rowPath: [1],
            href: "OEBPS/does-not-exist.xhtml",
            observedLocator: "OEBPS/chapter1.xhtml",
            content: nil,
            contentSelector: nil
        )
        let context = ReaderTOCEvidenceContext(
            schema: ReaderTOCEvidenceContext.schema,
            invocation: ReaderTOCEvidenceContext.Invocation(verdictFile: verdictBase),
            selectors: ["ReaderFlow/testRequired", "ReaderFlow/testInvalid"],
            screenshotDirectory: directory.path,
            screenshotPath: screenshotPath.path,
            entries: [required, counterexample, retry]
        )
        let verdict = Self.runnerVerdict(
            verdictBase: verdictBase,
            screenshotDirectory: directory.path
        )

        let assembled = try ReaderTOCEvidenceAssembler.assemble(
            context: context,
            verdict: verdict,
            verdictJSONPath: verdictJSON.path
        )
        #expect(assembled.validationErrors.isEmpty)

        let incompleteContext = ReaderTOCEvidenceContext(
            schema: context.schema,
            invocation: context.invocation,
            selectors: context.selectors,
            screenshotDirectory: context.screenshotDirectory,
            screenshotPath: context.screenshotPath,
            entries: [required, counterexample]
        )
        #expect(throws: ReaderTOCEvidenceAssemblyError.self) {
            try ReaderTOCEvidenceAssembler.assemble(
                context: incompleteContext,
                verdict: verdict,
                verdictJSONPath: verdictJSON.path
            )
        }

        let staleVerdict = Self.runnerVerdict(
            verdictBase: directory.appendingPathComponent("stale-verdict").path,
            screenshotDirectory: directory.path
        )
        #expect(throws: ReaderTOCEvidenceAssemblyError.self) {
            try ReaderTOCEvidenceAssembler.assemble(
                context: context,
                verdict: staleVerdict,
                verdictJSONPath: verdictJSON.path
            )
        }
    }

    @Test
    func evidenceWriterUsesPreRunContextAndPostRunAssemblyOnly() throws {
        let rootURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(
            contentsOf: rootURL.appendingPathComponent(
                "ios/BooksAndVocabUITests/Helpers/ReaderTOCEvidence.swift"
            ),
            encoding: .utf8
        )
        let body = try #require(
            source.split(separator: "func writeReaderTOCEvidence(", maxSplits: 1).last
        )
        #expect(!body.contains("currentIOSRunVerdict"))
        #expect(body.contains("ReaderTOCEvidenceContext"))
        #expect(source.contains("assembleReaderTOCEvidencePostRun"))
        #expect(source.contains("verdictURL"))
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

    private static func evidenceEntry(
        label: String,
        partition: String,
        path: [Int],
        rowPath: [Int],
        href: String,
        observedLocator: String?,
        content: String?,
        contentSelector: String?
    ) -> ReaderTOCEvidenceEntry {
        ReaderTOCEvidenceEntry(
            label: label,
            partition: partition,
            fixtureID: partition == "required"
                ? "reader.realBookLibrary"
                : "reader.invalidDestinationLibrary",
            asset: ReaderTOCEvidenceAsset(
                assetID: partition == "required"
                    ? "books.reader_real_book_epub"
                    : "books.reader_invalid_destination_epub",
                installedPath: "/tmp/\(label).epub",
                expectedSHA256: String(repeating: "a", count: 64),
                expectedByteSize: 10,
                actualSHA256: String(repeating: "a", count: 64),
                actualByteSize: 10
            ),
            path: path,
            selectedRow: ReaderTOCEvidenceSelectedRow(
                path: rowPath,
                href: href,
                title: partition == "required" ? "Chapter Two" : "Missing Destination"
            ),
            observation: ReaderTOCEvidenceObservation(
                requestedHref: href,
                observedLocatorHref: observedLocator,
                observedContent: content,
                contentSelector: contentSelector
            )
        )
    }

    private static func runnerVerdict(
        verdictBase: String,
        screenshotDirectory: String
    ) -> ReaderTOCEvidenceRunnerVerdict {
        ReaderTOCEvidenceRunnerVerdict(
            status: "ok",
            result: "ok",
            exit: "0",
            options: ReaderTOCEvidenceRunnerVerdict.Options(
                sourceCommit: "abc123",
                sourceTreeDirty: false,
                datasetID: "marketing_demo",
                datasetSHA256: String(repeating: "b", count: 64),
                device: "platform=iOS Simulator,id=SIM"
            ),
            invocation: ReaderTOCEvidenceRunnerVerdict.Invocation(
                ts: 100,
                pid: 200,
                verdictFile: verdictBase
            ),
            device: "SIM",
            artifacts: ReaderTOCEvidenceRunnerVerdict.Artifacts(
                log: "/tmp/run.log",
                xcresult: "/tmp/run.xcresult",
                uiScreenshotDir: screenshotDirectory,
                uiVisualReviewManifest: "/tmp/visual.json",
                uiReviewRoot: "/tmp/review",
                uiVideo: "/tmp/run.mp4"
            )
        )
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
            // Deliberately never resume or honor cancellation: this fake
            // proves the bridge has a hard deadline independent of navigator
            // cooperation.
            return await withUnsafeContinuation { (_: UnsafeContinuation<Bool?, Never>) in }
        }
    }
}
#endif
