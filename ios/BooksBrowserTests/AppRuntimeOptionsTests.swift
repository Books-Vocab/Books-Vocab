import Testing
@testable import BooksBrowser

struct AppRuntimeOptionsTests {
    @Test func defaultsToStandardProfile() {
        #expect(AppRuntimeOptions.isUITesting(arguments: []) == false)
        #expect(AppRuntimeOptions.launchProfile(arguments: []) == .standard)
        #expect(AppRuntimeOptions.shouldSkipNonessentialStartupWork(arguments: []) == false)
    }

    @Test func uiTestingEnablesFastStartupPath() {
        let arguments = ["BooksBrowser", "-ui-testing", "-skipWelcome"]
        #expect(AppRuntimeOptions.isUITesting(arguments: arguments) == true)
        #expect(AppRuntimeOptions.launchProfile(arguments: arguments) == .standard)
        #expect(AppRuntimeOptions.shouldSkipNonessentialStartupWork(arguments: arguments) == false)
    }

    @Test func explicitLaunchProfileParsesFromArguments() {
        let arguments = ["BooksBrowser", "-ui-testing", "-appLaunchProfile", "ui-smoke"]
        #expect(AppRuntimeOptions.launchProfile(arguments: arguments) == .uiSmoke)
        #expect(AppRuntimeOptions.shouldSkipNonessentialStartupWork(arguments: arguments) == true)
    }
}
