import Foundation
import XCTest

private let uiTestAppArgumentsEnvKey = "KG_UI_TEST_APP_ARGS_JSON"

func makeConfiguredApp() -> XCUIApplication {
    let app = XCUIApplication()
    app.launchArguments += ["-ui-testing", "-skipWelcome"]
    app.launchArguments += extraUITestLaunchArguments()
    return app
}

private func extraUITestLaunchArguments() -> [String] {
    guard let raw = ProcessInfo.processInfo.environment[uiTestAppArgumentsEnvKey],
          let data = raw.data(using: .utf8),
          let decoded = try? JSONDecoder().decode([String].self, from: data)
    else {
        return []
    }
    return decoded
}
