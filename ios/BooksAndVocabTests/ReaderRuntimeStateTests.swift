//
//  ReaderRuntimeStateTests.swift
//  BooksAndVocab Tests
//

import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct ReaderRuntimeStateTests {

    @Test func progressClassificationKeepsFiveRuntimeStatesDistinct() {
        #expect(ReaderProgressState.classify(progression: nil) == .unknown)
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
        #expect(state.runtimeStateAccessibilityValue.contains("progress=middle"))

        state.recordLocationProgression(0.73)

        #expect(state.progressState == .middle(0.73))
        #expect(state.totalProgression == 0.73)
        #expect(state.runtimeStateAccessibilityValue.contains("progress=middle"))
    }

    @Test func invalidRestoreIsProgressWarningAndDoesNotBecomeLoadFailure() {
        let state = ReaderRuntimeState(selection: ReaderRuntimeFixtureAdapter.selection(scenario: nil))

        state.markRestoreFailure()

        #expect(state.progressState == .restoreFailure)
        #expect(state.loadingState == .loading(.opening))
        #expect(state.errorMessage == nil)
        #expect(state.beginLoadAttempt() == .proceed)
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
