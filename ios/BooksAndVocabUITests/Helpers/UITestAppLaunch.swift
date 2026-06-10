import Foundation
import XCTest

private let uiTestAppArgumentsEnvKey = "KG_UI_TEST_APP_ARGS_JSON"
private let uiTestLaunchProfileEnvKey = "KG_UI_TEST_LAUNCH_PROFILE"
private let uiTestPerfLogEnvKey = "KG_PERF_LOG"

enum UITestFixture: Equatable {
    case raw(String)
    case bookshelf(String)
    case podcastPlayablePreview
    case authTieredCatalog
    case authSignedIn
    case settingsCleanPreferences

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
        case .settingsCleanPreferences:
            return "-seedFixture:settings:cleanPreferences"
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
