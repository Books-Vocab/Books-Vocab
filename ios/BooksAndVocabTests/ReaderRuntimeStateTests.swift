//
//  ReaderRuntimeStateTests.swift
//  BooksAndVocab Tests
//

import Foundation
import Testing
import ReadiumShared
@testable import BooksAndVocab

@MainActor
struct ReaderRuntimeStateTests {

    @Test func progressClassificationKeepsFiveRuntimeStatesDistinct() {
        #expect(ReaderProgressState.classify(progression: nil) == .unknown)
        #expect(ReaderProgressState.classify(progression: .nan) == .unknown)
        #expect(ReaderProgressState.classify(progression: .infinity) == .unknown)
        #expect(ReaderProgressState.classify(progression: -0.01) == .unknown)
        #expect(ReaderProgressState.classify(progression: 1.01) == .unknown)
        #expect(ReaderProgressState.classify(progression: 0) == .zero)
        #expect(ReaderProgressState.classify(progression: 0.42) == .middle(0.42))
        #expect(ReaderProgressState.classify(progression: 1) == .complete)
        #expect(ReaderProgressState.classify(progression: 0.42, restoreFailed: true) == .restoreFailure)
        #expect(ReaderProgressState.unknown.accessibilityIdentifier == "unknown")
        #expect(ReaderProgressState.zero.accessibilityIdentifier == "zero")
        #expect(ReaderProgressState.middle(0.42).accessibilityIdentifier == "middle")
        #expect(ReaderProgressState.complete.accessibilityIdentifier == "complete")
        #expect(ReaderProgressState.restoreFailure.accessibilityIdentifier == "restore-failure")
    }

    @Test func runtimeAdapterSelectsScenarioAndCarriesDatasetProvenance() throws {
        let dataset = ReaderFixtureDatasetProvenance(
            datasetID: "marketing_demo",
            source: "environment:KG_FIXTURE_DATASET_DEFLATE_B64"
        )

        let selection = try #require(
            ReaderRuntimeFixtureAdapter.selection(
                arguments: ["-readerRuntimeScenario:progress-middle"],
                dataset: dataset
            )
        )

        #expect(selection.scenario == .progressMiddle)
        #expect(selection.progressState == .middle(0.42))
        #expect(selection.provenance?.accessibilityValue == "dataset=marketing_demo;source=environment:KG_FIXTURE_DATASET_DEFLATE_B64;scenario=progress-middle")
    }

    @Test func runtimeAdapterRejectsDuplicateScenarioSelectors() {
        #expect(
            ReaderRuntimeFixtureAdapter.selection(
                arguments: [
                    "-readerRuntimeScenario:progress-middle",
                    "-readerRuntimeScenario:progress-complete"
                ]
            ) == nil
        )
    }

    @Test func productionRuntimeStartsFromPersistedProgressionBeforeFirstLocation() {
        let state = ReaderRuntimeState(
            selection: ReaderRuntimeFixtureAdapter.selection(scenario: nil),
            initialProgression: 0.568
        )

        #expect(state.progressState == .middle(0.568))
        #expect(state.totalProgression == 0.568)
        #expect(state.visibleProgressState == .unknown)
        #expect(state.visibleTotalProgression == nil)
        #expect(state.runtimeStateAccessibilityValue.contains("progress=unknown"))

        state.markReady()
        #expect(state.visibleProgressState == .middle(0.568))
        #expect(state.visibleTotalProgression == 0.568)

        state.recordLocationProgression(0.73)

        #expect(state.progressState == .middle(0.73))
        #expect(state.totalProgression == 0.73)
        #expect(state.runtimeStateAccessibilityValue.contains("progress=middle"))
    }

    @Test func loadingAndFailureHidePreviousProgressFromTheVisibleProjection() {
        let state = ReaderRuntimeState(
            selection: ReaderRuntimeFixtureAdapter.selection(scenario: nil),
            initialProgression: 0.42
        )

        #expect(state.visibleProgressState == .unknown)
        #expect(state.visibleTotalProgression == nil)

        state.markReady()
        #expect(state.visibleProgressState == .middle(0.42))
        #expect(state.visibleProgressState(hasPublication: false) == .unknown)
        #expect(state.visibleTotalProgression(hasPublication: false) == nil)
        #expect(state.runtimeStateAccessibilityValue(hasPublication: false).contains("progress=unknown"))

        state.fail(.openFailed)
        #expect(state.visibleProgressState == .unknown)
        #expect(state.visibleTotalProgression == nil)
        #expect(state.runtimeStateAccessibilityValue.contains("progress=unknown"))
    }

    @Test func invalidRestoreIsProgressWarningAndDoesNotBecomeLoadFailure() {
        let state = ReaderRuntimeState(selection: ReaderRuntimeFixtureAdapter.selection(scenario: nil))

        state.markRestoreFailure()

        #expect(state.progressState == .restoreFailure)
        #expect(state.loadingState == .loading(.opening))
        #expect(state.errorMessage == nil)
        #expect(state.beginLoadAttempt() == .proceed)
    }

    @Test func invalidSavedLocatorUsesProductionRestoreTransition() throws {
        let book = Book(title: "Reader", author: "Author", fileName: "reader.epub")
        book.progression = 0.37
        book.lastReadLocatorJSON = "not-a-locator"

        // Use the production ReaderView restore entry point, not a fixture
        // scenario. An invalid saved locator raises a warning while retaining
        // the persisted progression until Readium emits a valid location.
        var view = ReaderView(book: book)
        view.prepareRestoreState()
        #expect(view.readerState.progressState == .restoreFailure)
        #expect(book.progression == 0.37)

        view.readerState.runtime.recordLocationProgression(nil)
        view.readerState.runtime.recordLocationProgression(.nan)
        #expect(view.readerState.progressState == .restoreFailure)
        #expect(book.progression == 0.37)

        let validLocator = try #require(try? Locator(jsonString: """
        {"href":"chapter1.html","type":"text/html","locations":{"totalProgression":0.74}}
        """))
        view.handleLocationChange(validLocator)
        #expect(view.readerState.progressState == .middle(0.74))
        #expect(book.progression == 0.74)
    }

    @Test func restoreFailureDoesNotLockReadiumLocationEvents() {
        let selection = ReaderRuntimeFixtureAdapter.selection(scenario: .progressRestoreFailure)
        let state = ReaderRuntimeState(selection: selection)

        #expect(state.selection.locksProgress == false)
        state.recordLocationProgression(0.74)

        #expect(state.progressState == .middle(0.74))
    }

    @Test func unknownLocatorProgressionPreservesBookProgression() {
        let book = Book(title: "Reader", author: "Author", fileName: "reader.epub")
        book.progression = 0.37
        let clock = ReaderRuntimeClock(now: { Date(timeIntervalSince1970: 123) })
        let snapshot = ReaderProgressPersistenceSnapshot(
            progression: ReaderProgressState.validProgression(nil),
            clock: clock
        )

        snapshot.apply(to: book, locatorJSON: "valid-locator-json")

        #expect(book.lastReadLocatorJSON == "valid-locator-json")
        #expect(book.dateLastRead == Date(timeIntervalSince1970: 123))
        #expect(book.progression == 0.37)
    }

    @Test func invalidLocatorProgressionPreservesBookProgressionThroughHandler() throws {
        let book = Book(title: "Reader", author: "Author", fileName: "reader.epub")
        book.progression = 0.37
        var view = ReaderView(book: book)
        let invalidLocator = try #require(try? Locator(jsonString: """
        {"href":"chapter1.html","type":"text/html","locations":{"totalProgression":1.5}}
        """))

        view.handleLocationChange(invalidLocator)

        // An invalid Readium progression is ignored; it must not erase the
        // last known valid persisted progress from the runtime projection.
        #expect(view.readerState.progressState == .middle(0.37))
        #expect(book.progression == 0.37)
    }

    @Test func emptyRuntimeAttemptReachesProductionEmptyRoute() {
        let state = ReaderRuntimeState(
            selection: ReaderRuntimeFixtureAdapter.selection(scenario: .loadingEmpty)
        )

        #expect(state.beginLoadAttempt() == .empty)
        #expect(state.loadingState == .ready)
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: false,
                errorMessage: state.errorMessage,
                loadingState: state.loadingState
            ) == .empty
        )
    }

    @Test func mainContentStateExposesLoadingErrorContentAndEmptyBranches() {
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: false,
                errorMessage: nil,
                loadingState: .loading(.opening)
            ) == .loading
        )
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: false,
                errorMessage: "open failed",
                loadingState: .failed(.openFailed)
            ) == .error
        )
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: true,
                errorMessage: nil,
                loadingState: .ready
            ) == .content
        )
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: false,
                errorMessage: nil,
                loadingState: .ready
            ) == .empty
        )
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: true,
                errorMessage: nil,
                loadingState: .loading(.opening)
            ) == .loading
        )
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: true,
                errorMessage: "stale failure",
                loadingState: .failed(.openFailed)
            ) == .error
        )
        #expect(
            ReaderMainContentState.resolve(
                hasPublication: true,
                errorMessage: nil,
                loadingState: .failed(.openFailed)
            ) == .error
        )
    }

    @Test func slowLoadingCanBeReleasedWithoutWallClockWait() {
        let selection = ReaderRuntimeFixtureAdapter.selection(scenario: .loadingSlow)
        let state = ReaderRuntimeState(selection: selection)

        #expect(state.beginLoadAttempt() == .holdSlow)
        #expect(state.loadingState == .loading(.slow))
        #expect(state.releaseSlowLoading())
        #expect(state.beginLoadAttempt() == .proceed)
        #expect(state.loadingState == .loading(.opening))
    }

    @Test func missingAndRetryableLoadingFailOnceThenRetrySuccessfully() {
        for scenario in [ReaderRuntimeScenario.loadingMissing, .loadingErrorRetry] {
            let state = ReaderRuntimeState(selection: ReaderRuntimeFixtureAdapter.selection(scenario: scenario))
            let expectedFailure: ReaderLoadingFailure = scenario == .loadingMissing ? .missing : .retryable

            #expect(state.beginLoadAttempt() == .failed(expectedFailure))
            #expect(state.loadingState.isFailed)
            #expect(state.retry())
            #expect(state.beginLoadAttempt() == .proceed)
            #expect(state.loadingState == .loading(.opening))
            state.markReady()
            #expect(state.loadingState == .ready)
        }
    }

    @Test func progressOverrideSurvivesReadiumLocationEventsUntilRuntimeScenarioEnds() {
        let selection = ReaderRuntimeFixtureAdapter.selection(scenario: .progressComplete)
        let state = ReaderRuntimeState(selection: selection)

        state.recordLocationProgression(0.42)

        #expect(state.progressState == .complete)
        #expect(state.totalProgression == 1)
    }

    @Test func progressSaverUsesInjectedDebouncerInsteadOfWallClock() {
        let debouncer = ManualReaderProgressDebouncer()
        let saves = Counter()
        let sut = ReaderProgressSaver(flushDelay: 1, debouncer: debouncer)

        sut.recordChange(apply: {}, save: { saves.increment() })
        #expect(saves.value == 0)

        debouncer.fire()

        #expect(saves.value == 1)
    }

    @Test func progressPersistenceSnapshotUsesInjectedClockForTimestampOnly() {
        let expected = Date(timeIntervalSince1970: 123)
        let clock = ReaderRuntimeClock(now: { expected })
        let snapshot = ReaderProgressPersistenceSnapshot(progression: 0.42, clock: clock)

        #expect(snapshot.dateLastRead == expected)
        #expect(snapshot.progression == 0.42)
    }
}

@MainActor
private final class ManualReaderProgressDebouncer: ReaderProgressDebouncing {
    private var pendingAction: (@MainActor () -> Void)?

    func schedule(after _: TimeInterval, action: @escaping @MainActor () -> Void) {
        pendingAction = action
    }

    func cancel() {
        pendingAction = nil
    }

    func fire() {
        let action = pendingAction
        pendingAction = nil
        action?()
    }
}

private final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    var value: Int {
        lock.lock()
        defer { lock.unlock() }
        return count
    }

    func increment() {
        lock.lock()
        count += 1
        lock.unlock()
    }
}
