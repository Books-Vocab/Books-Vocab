import Foundation
import XCTest

private let uiTestAppArgumentsEnvKey = "KG_UI_TEST_APP_ARGS_JSON"
private let uiTestLaunchProfileEnvKey = "KG_UI_TEST_LAUNCH_PROFILE"
private let uiTestPerfLogEnvKey = "KG_PERF_LOG"
private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
private let fixtureDatasetDeflateEnvKey = "KG_FIXTURE_DATASET_DEFLATE_B64"
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
enum UITestLaunchArgumentsError: Error, CustomStringConvertible {
    case missingUTF8
    case invalidJSON(underlying: Error)

    var description: String {
        switch self {
        case .missingUTF8:
            return "KG_UI_TEST_APP_ARGS_JSON is not valid UTF-8"
        case .invalidJSON(let underlying):
            return "KG_UI_TEST_APP_ARGS_JSON must be a JSON array of strings: \(underlying)"
        }
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
        case .shellNavigation:
            return "-seedFixture:shell:navigation"
        case .reviewCalendarDense:
            return "-seedFixture:vocabulary:reviewCalendarDense"
        case .searchVocabNotebook:
            return "-seedFixture:search:vocabNotebook"
        case .vocabularyLibraryFilterRich:
            return "-seedFixture:vocabulary:vocabListFilterRich"
        case .vocabularyLibraryP11ReviewMix:
            return "-seedFixture:vocabulary:p11.644.reviewMix"
        case .vocabularyLibraryP11MixedRoleCounterexample:
            return "-seedFixture:vocabulary:role.mixed"
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
        // ios_test.sh --dataset exports the dataset onto the runner process
        // (deflate+base64 by default; plaintext base64 kept for compatibility);
        // forward it into the app so the seeders' renderModel chain picks it
        // up. An explicit per-test value always wins over the runner-wide one.
        for key in [fixtureDatasetDeflateEnvKey, fixtureDatasetEnvKey] {
            if environment[key] == nil,
               let dataset = ProcessInfo.processInfo.environment[key],
               !dataset.isEmpty {
                environment[key] = dataset
            }
        }
        // P9 evidence provenance and the app-written proof destination are
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
        guard let raw else {
            return []
        }
        guard let data = raw.data(using: .utf8) else {
            throw UITestLaunchArgumentsError.missingUTF8
        }
        do {
            return try JSONDecoder().decode([String].self, from: data)
        } catch {
            throw UITestLaunchArgumentsError.invalidJSON(underlying: error)
        }
    }

    private func inheritedLaunchArguments() -> [String] {
        do {
            return try Self.decodeInheritedLaunchArguments(
                from: ProcessInfo.processInfo.environment[uiTestAppArgumentsEnvKey]
            )
        } catch {
            preconditionFailure("\(error)")
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
