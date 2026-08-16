import Foundation
import BooksAndVocab
import XCTest

private let uiTestAppArgumentsEnvKey = "KG_UI_TEST_APP_ARGS_JSON"
private let uiTestLaunchProfileEnvKey = "KG_UI_TEST_LAUNCH_PROFILE"
private let uiTestPerfLogEnvKey = "KG_PERF_LOG"
private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
private let fixtureDatasetDeflateEnvKey = "KG_FIXTURE_DATASET_DEFLATE_B64"
private let fixtureAssetRootEnvKey = "KG_FIXTURE_ASSET_ROOT"
private let p9ProofRelativePathEnvKey = "KG_P9_INSTALLED_FIXTURE_PROOF_RELATIVE_PATH"
private let uiTestSourceCommitEnvKey = "KG_UI_TEST_SOURCE_COMMIT"
private let uiTestDatasetIDEnvKey = "KG_UI_TEST_DATASET_ID"
private let uiTestDatasetSHA256EnvKey = "KG_UI_TEST_DATASET_SHA256"
private let uiTestDeviceUDIDEnvKey = "KG_UI_TEST_DEVICE_UDID"

enum UITestReaderRuntimeScenario: String, CaseIterable, Equatable {
    case progressUnknown = "progress-unknown"
    case progressZero = "progress-zero"
    case progressMiddle = "progress-middle"
    case progressComplete = "progress-complete"
    case progressRestoreFailure = "progress-restore-failure"
    case loadingSlow = "loading-slow"
    case loadingMissing = "loading-missing"
    case loadingErrorRetry = "loading-error-retry"
    case loadingEmpty = "loading-empty"

}

/// Progress-only fixture scenarios. Loading/error scenarios intentionally live
/// in `UITestReaderRuntimeScenario` but are not accepted by progress selectors.
enum UITestReaderProgressScenario: String, CaseIterable, Equatable {
    case progressUnknown = "progress-unknown"
    case progressZero = "progress-zero"
    case progressMiddle = "progress-middle"
    case progressComplete = "progress-complete"
    case progressRestoreFailure = "progress-restore-failure"

    var runtimeScenario: UITestReaderRuntimeScenario {
        switch self {
        case .progressUnknown: return .progressUnknown
        case .progressZero: return .progressZero
        case .progressMiddle: return .progressMiddle
        case .progressComplete: return .progressComplete
        case .progressRestoreFailure: return .progressRestoreFailure
        }
    }

    /// The fixture scenario name and rendered badge name are intentionally
    /// different: the app exposes the normalized production progress state.
    var progressAccessibilitySuffix: String {
        switch self {
        case .progressUnknown: return "unknown"
        case .progressZero: return "zero"
        case .progressMiddle: return "middle"
        case .progressComplete: return "complete"
        case .progressRestoreFailure: return "restore-failure"
        }
    }
    /// Production Reader selectors use the normalized state suffix rather than
    /// the fixture's `progress-*` launch argument.
    var readerProgressAccessibilityIdentifier: String {
        "reader.progress.\(progressAccessibilitySuffix)"
    }
}

enum UITestFixture: Equatable {
    case raw(String)
    case bookshelf(String)
    case podcastPlayablePreview
    case authTieredCatalog
    case authSignedIn
    case entitlementsProAccess
    case settingsCleanPreferences
    case settingsSyncTerminalErrorRetrySuccess
    case settingsLongContent
    case settingsResetLifecycle
    case shellNavigation
    case reviewCalendarDense
    case searchVocabNotebook
    case vocabularyLibraryFilterRich
    case vocabularyLibraryP11ReviewMix
    case vocabularyLibraryP11MixedRoleCounterexample
    case readerRealBookLibrary
    case readerInvalidDestinationLibrary
    case readerRuntime(UITestReaderRuntimeScenario)
    case notebookReviewDeck
    case notebookReviewDeckVaried
    case dictionaryP1Rich
    case dictionaryP2Senses
    case explore(String)
    case vocabulary(String)
    case notebookReviewCardFullContent
    case notebookReviewCardFullInfo
    case notebookReviewCardCompactCounterexample

    var launchArgument: String {
        switch self {
        case .raw(let value):
            return value
        case .bookshelf(let id):
            return "-seedFixture:bookshelf:\(id)"
        case .podcastPlayablePreview:
            return "-seedFixture:podcast:playablePreview"
        case .authTieredCatalog:
            return "-seedFixture:auth:tieredCatalog"
        case .authSignedIn:
            return "-seedFixture:auth:signedIn"
        case .entitlementsProAccess:
            return "-seedFixture:entitlements:pro"
        case .settingsCleanPreferences:
            return "-seedFixture:settings:cleanPreferences"
        case .settingsSyncTerminalErrorRetrySuccess:
            return "-seedFixture:settings:sync_terminal_error_retry_success"
        case .settingsLongContent:
            return "-seedFixture:settings:long_content_counterexample"
        case .settingsResetLifecycle:
            return "-seedFixture:settings:reset_counterexample"
        case .shellNavigation:
            return "-seedFixture:shell:navigation"
        case .reviewCalendarDense:
            return "-seedFixture:vocabulary:reviewCalendarDense"
        case .searchVocabNotebook:
            return "-seedFixture:search:vocabNotebook"
        case .vocabularyLibraryFilterRich:
            return UITestFixtureLaunchContract.vocabularyLibraryFilterRich
        case .vocabularyLibraryP11ReviewMix:
            return UITestFixtureLaunchContract.vocabularyLibraryP11ReviewMix
        case .vocabularyLibraryP11MixedRoleCounterexample:
            return UITestFixtureLaunchContract.vocabularyLibraryP11MixedRoleCounterexample
        case .readerRealBookLibrary:
            return "-seedFixture:reader:realBookLibrary"
        case .readerInvalidDestinationLibrary:
            return "-seedFixture:reader:invalidDestinationLibrary"
        case .readerRuntime(let scenario):
            return "-readerRuntimeScenario:\(scenario.rawValue)"
        case .notebookReviewDeck:
            return "-seedFixture:notebook:reviewDeck"
        case .notebookReviewDeckVaried:
            return "-seedFixture:notebook:reviewDeckVaried"
        case .dictionaryP1Rich:
            return "-seedFixture:dictionary:ui-p1-dictionary-rich"
        case .dictionaryP2Senses:
            return "-seedFixture:dictionary:ui-p2-dictionary-senses"
        case .explore(let id):
            return "-seedFixture:explore:\(id)"
        case .vocabulary(let id):
            return "-seedFixture:vocabulary:\(id)"
        case .notebookReviewCardFullContent:
            return "-seedFixture:notebook:reviewCardFullContent"
        case .notebookReviewCardFullInfo:
            return "-seedFixture:notebook:review.card-full-info"
        case .notebookReviewCardCompactCounterexample:
            return "-seedFixture:notebook:review.card-compact-counterexample"
        }
    }
}

enum UITestLaunchProfile: String {
    case standard

    var launchArguments: [String] {
        switch self {
        case .standard:
            return []
        }
    }
}

struct UITestLaunchConfiguration {
    var profile: UITestLaunchProfile = .standard
    var extraArgs: [String] = []
    var extraEnvironment: [String: String] = [:]
    var perfLog: String?

    var launchArguments: [String] {
        ["-ui-testing", "-skipWelcome"]
            + profile.launchArguments
            + inheritedLaunchArguments()
            + extraArgs
    }

    var launchEnvironment: [String: String] {
        var environment = extraEnvironment
        environment[uiTestLaunchProfileEnvKey] = profile.rawValue
        if let perfLog, !perfLog.isEmpty {
            environment[uiTestPerfLogEnvKey] = perfLog
        }

        // ios_test.sh --dataset exports the dataset onto the runner process;
        // forward it into the app. An explicit per-test value wins.
        for key in [fixtureDatasetDeflateEnvKey, fixtureDatasetEnvKey, fixtureAssetRootEnvKey] {
            if environment[key] == nil,
               let value = ProcessInfo.processInfo.environment[key],
               !value.isEmpty {
                environment[key] = value
            }
        }

        // Evidence provenance and the app-written proof destination are
        // explicit launch inputs; no host-side fixture copy is allowed.
        for key in [
            p9ProofRelativePathEnvKey,
            uiTestSourceCommitEnvKey,
            uiTestDatasetIDEnvKey,
            uiTestDatasetSHA256EnvKey,
            uiTestDeviceUDIDEnvKey,
        ] {
            if environment[key] == nil,
               let value = ProcessInfo.processInfo.environment[key],
               !value.isEmpty {
                environment[key] = value
            }
        }
        return environment
    }

    static func decodeInheritedLaunchArguments(from raw: String?) throws -> [String] {
        try UITestLaunchArguments.decodeInheritedLaunchArguments(from: raw)
    }

    private func inheritedLaunchArguments() -> [String] {
        do {
            return try Self.decodeInheritedLaunchArguments(
                from: ProcessInfo.processInfo.environment[uiTestAppArgumentsEnvKey]
            )
        } catch {
            preconditionFailure("Invalid KG_UI_TEST_APP_ARGS_JSON: \(error)")
        }
    }
}

func makeConfiguredApp(
    profile: UITestLaunchProfile = .standard,
    extraArgs: [String] = [],
    fixtures: [UITestFixture] = [],
    extraEnvironment: [String: String] = [:],
    perfLog: String? = nil
) -> XCUIApplication {
    let app = XCUIApplication()
    let configuration = UITestLaunchConfiguration(
        profile: profile,
        extraArgs: extraArgs + fixtures.map(\.launchArgument),
        extraEnvironment: extraEnvironment,
        perfLog: perfLog
    )
    app.launchArguments += configuration.launchArguments
    app.launchEnvironment.merge(configuration.launchEnvironment) { _, new in new }
    return app
}
