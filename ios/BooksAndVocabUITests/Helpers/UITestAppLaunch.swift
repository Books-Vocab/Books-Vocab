import Foundation
import XCTest

private let uiTestAppArgumentsEnvKey = "KG_UI_TEST_APP_ARGS_JSON"
private let uiTestLaunchProfileEnvKey = "KG_UI_TEST_LAUNCH_PROFILE"
private let uiTestPerfLogEnvKey = "KG_PERF_LOG"
private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
private let fixtureDatasetDeflateEnvKey = "KG_FIXTURE_DATASET_DEFLATE_B64"

enum UITestFixture: Equatable {
    case raw(String)
    case bookshelf(String)
    case podcastPlayablePreview
    case authTieredCatalog
    case authSignedIn
    case entitlementsProAccess
    case settingsCleanPreferences
    case shellNavigation
    case searchVocabNotebook
    case readerRealBookLibrary
    case notebookReviewDeck

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
        case .searchVocabNotebook:
            return "-seedFixture:search:vocabNotebook"
        case .readerRealBookLibrary:
            return "-seedFixture:reader:realBookLibrary"
        case .notebookReviewDeck:
            return "-seedFixture:notebook:reviewDeck"
        }
    }
}

enum UITestLaunchProfile: String {
    case standard
    case clean

    var launchArguments: [String] {
        switch self {
        case .standard:
            return []
        case .clean:
            return ["-resetContainer"]
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
        return environment
    }

    private func inheritedLaunchArguments() -> [String] {
        guard let raw = ProcessInfo.processInfo.environment[uiTestAppArgumentsEnvKey],
              let data = raw.data(using: .utf8),
              let decoded = try? JSONDecoder().decode([String].self, from: data)
        else {
            return []
        }
        return decoded
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
