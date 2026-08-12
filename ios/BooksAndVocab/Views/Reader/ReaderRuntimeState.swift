#if os(iOS)
import Foundation
import Observation

/// Reader progress is deliberately not represented by a nullable percentage.
/// The distinction is observable by the UI World and therefore part of the
/// Reader runtime contract.
enum ReaderProgressState: Equatable, Sendable {
    case unknown
    case zero
    case middle(Double)
    case complete
    case restoreFailure

    static func classify(progression: Double?, restoreFailed: Bool = false) -> Self {
        guard !restoreFailed else { return .restoreFailure }
        guard let progression, progression.isFinite else { return .unknown }
        if progression <= 0 { return .zero }
        if progression >= 1 { return .complete }
        return .middle(progression)
    }

    var accessibilityIdentifier: String {
        switch self {
        case .unknown: return "unknown"
        case .zero: return "zero"
        case .middle: return "middle"
        case .complete: return "complete"
        case .restoreFailure: return "restore-failure"
        }
    }

    var progression: Double? {
        switch self {
        case .unknown, .restoreFailure: return nil
        case .zero: return 0
        case let .middle(value): return value
        case .complete: return 1
        }
    }
}

enum ReaderRuntimeScenario: String, CaseIterable, Equatable, Sendable {
    case progressUnknown = "progress-unknown"
    case progressZero = "progress-zero"
    case progressMiddle = "progress-middle"
    case progressComplete = "progress-complete"
    case progressRestoreFailure = "progress-restore-failure"
    case loadingSlow = "loading-slow"
    case loadingMissing = "loading-missing"
    case loadingErrorRetry = "loading-error-retry"

    var progressState: ReaderProgressState {
        switch self {
        case .progressUnknown, .loadingSlow, .loadingMissing, .loadingErrorRetry:
            return .unknown
        case .progressZero: return .zero
        case .progressMiddle: return .middle(0.42)
        case .progressComplete: return .complete
        case .progressRestoreFailure: return .restoreFailure
        }
    }

    var loadMode: ReaderLoadMode {
        switch self {
        case .loadingSlow: return .slow
        case .loadingMissing: return .missing
        case .loadingErrorRetry: return .errorRetry
        default: return .normal
        }
    }

    var isProgressOverride: Bool {
        switch self {
        case .progressUnknown, .progressZero, .progressMiddle, .progressComplete, .progressRestoreFailure:
            return true
        case .loadingSlow, .loadingMissing, .loadingErrorRetry:
            return false
        }
    }
}

enum ReaderLoadMode: Equatable, Sendable {
    case normal
    case slow
    case missing
    case errorRetry
}

enum ReaderLoadingPhase: String, Equatable, Sendable {
    case opening
    case slow
}

enum ReaderLoadingFailure: Equatable, Sendable {
    case missing
    case retryable
    case openFailed
    case restoreFailure
}

enum ReaderLoadingState: Equatable, Sendable {
    case loading(ReaderLoadingPhase)
    case ready
    case failed(ReaderLoadingFailure)

    var isLoading: Bool {
        if case .loading = self { return true }
        return false
    }

    var isFailed: Bool {
        if case .failed = self { return true }
        return false
    }

    var accessibilityIdentifier: String {
        switch self {
        case let .loading(phase): return phase.rawValue
        case .ready: return "ready"
        case let .failed(failure):
            switch failure {
            case .missing: return "missing"
            case .retryable: return "retryable"
            case .openFailed: return "open-failed"
            case .restoreFailure: return "restore-failure"
            }
        }
    }
}

enum ReaderLoadAttempt: Equatable, Sendable {
    case proceed
    case holdSlow
    case failed(ReaderLoadingFailure)
}

struct ReaderFixtureDatasetProvenance: Equatable, Sendable {
    let datasetID: String
    let source: String

    var accessibilityValue: String {
        "dataset=\(datasetID);source=\(source)"
    }
}

struct ReaderRuntimeClock {
    let now: @MainActor () -> Date

    static let live = ReaderRuntimeClock(now: Date.init)
}

struct ReaderRuntimeProvenance: Equatable, Sendable {
    let datasetID: String
    let source: String
    let scenario: String

    init(dataset: ReaderFixtureDatasetProvenance, scenario: ReaderRuntimeScenario?) {
        datasetID = dataset.datasetID
        source = dataset.source
        self.scenario = scenario?.rawValue ?? "production"
    }

    var accessibilityValue: String {
        "dataset=\(datasetID);source=\(source);scenario=\(scenario)"
    }
}

struct ReaderRuntimeSelection: Equatable, Sendable {
    let scenario: ReaderRuntimeScenario?
    let progressState: ReaderProgressState
    let loadMode: ReaderLoadMode
    let provenance: ReaderRuntimeProvenance?

    var locksProgress: Bool {
        scenario?.isProgressOverride == true
    }

    var accessibilityValue: String {
        let scenarioValue = scenario?.rawValue ?? "production"
        let provenanceValue = provenance?.accessibilityValue ?? "dataset=none;source=production"
        return "scenario=\(scenarioValue);progress=\(progressState.accessibilityIdentifier);loading=\(loadMode.accessibilityIdentifier);\(provenanceValue)"
    }
}

private extension ReaderLoadMode {
    var accessibilityIdentifier: String {
        switch self {
        case .normal: return "normal"
        case .slow: return "slow"
        case .missing: return "missing"
        case .errorRetry: return "error-retry"
        }
    }
}

enum ReaderRuntimeFixtureAdapter {
    private static let argumentPrefix = "-readerRuntimeScenario:"

    static func selection(
        arguments: [String],
        dataset: ReaderFixtureDatasetProvenance? = nil
    ) -> ReaderRuntimeSelection? {
        guard let argument = arguments.first(where: { $0.hasPrefix(argumentPrefix) }) else {
            return selection(scenario: nil, dataset: dataset)
        }
        let rawValue = String(argument.dropFirst(argumentPrefix.count))
        guard let scenario = ReaderRuntimeScenario(rawValue: rawValue) else { return nil }
        return selection(scenario: scenario, dataset: dataset)
    }

    static func selection(
        scenario: ReaderRuntimeScenario?,
        dataset: ReaderFixtureDatasetProvenance? = nil
    ) -> ReaderRuntimeSelection {
        ReaderRuntimeSelection(
            scenario: scenario,
            progressState: scenario?.progressState ?? .unknown,
            loadMode: scenario?.loadMode ?? .normal,
            provenance: dataset.map { ReaderRuntimeProvenance(dataset: $0, scenario: scenario) }
        )
    }
}

@MainActor
@Observable
final class ReaderRuntimeState {
    let selection: ReaderRuntimeSelection

    private(set) var progressState: ReaderProgressState
    private(set) var loadingState: ReaderLoadingState = .loading(.opening)

    private var loadAttemptCount = 0
    private var slowLoadingReleased = false
    private var failureMessage: String?

    init(selection: ReaderRuntimeSelection = ReaderRuntimeFixtureAdapter.selection(scenario: nil)) {
        self.selection = selection
        progressState = selection.progressState
    }

    var isLoading: Bool { loadingState.isLoading }
    var errorMessage: String? { failureMessage }
    var totalProgression: Double { progressState.progression ?? 0 }

    var runtimeStateAccessibilityValue: String {
        "\(selection.accessibilityValue);state=\(loadingState.accessibilityIdentifier)"
    }

    var loadingPhase: String {
        switch loadingState {
        case .loading(.slow): return L10n.string("等待載入…")
        case .loading(.opening): return L10n.string("開啟書本…")
        case .ready: return L10n.string("載入完成")
        case .failed: return L10n.string("載入失敗")
        }
    }

    func beginLoadAttempt() -> ReaderLoadAttempt {
        loadAttemptCount += 1
        failureMessage = nil

        switch selection.loadMode {
        case .slow where !slowLoadingReleased:
            loadingState = .loading(.slow)
            return .holdSlow
        case .missing where loadAttemptCount == 1:
            fail(.missing)
            return .failed(.missing)
        case .errorRetry where loadAttemptCount == 1:
            fail(.retryable)
            return .failed(.retryable)
        default:
            loadingState = .loading(.opening)
            return .proceed
        }
    }

    @discardableResult
    func releaseSlowLoading() -> Bool {
        guard selection.loadMode == .slow, loadingState == .loading(.slow) else { return false }
        slowLoadingReleased = true
        loadingState = .loading(.opening)
        return true
    }

    @discardableResult
    func retry() -> Bool {
        guard loadingState.isFailed else { return false }
        failureMessage = nil
        loadingState = .loading(.opening)
        return true
    }

    func markReady() {
        failureMessage = nil
        loadingState = .ready
    }

    func fail(_ failure: ReaderLoadingFailure, message: String? = nil) {
        failureMessage = message ?? defaultFailureMessage(for: failure)
        loadingState = .failed(failure)
    }

    func markRestoreFailure() {
        progressState = .restoreFailure
        fail(.restoreFailure)
    }

    func recordLocationProgression(_ progression: Double?) {
        guard !selection.locksProgress else { return }
        progressState = ReaderProgressState.classify(progression: progression)
    }

    private func defaultFailureMessage(for failure: ReaderLoadingFailure) -> String {
        switch failure {
        case .missing: return L10n.string("找不到書本檔案")
        case .retryable: return L10n.string("模擬載入失敗，請重試")
        case .openFailed: return L10n.string("無法開啟書本")
        case .restoreFailure: return L10n.string("閱讀進度無法還原")
        }
    }
}
#endif
