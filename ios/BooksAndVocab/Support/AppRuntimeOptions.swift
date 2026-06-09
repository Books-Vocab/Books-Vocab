import Foundation

enum AppLaunchProfile: String, Equatable {
    case standard
    case uiSmoke = "ui-smoke"

    static func resolve(arguments: [String]) -> AppLaunchProfile {
        guard let index = arguments.firstIndex(of: "-appLaunchProfile"),
              arguments.indices.contains(index + 1)
        else {
            return .standard
        }
        return AppLaunchProfile(rawValue: arguments[index + 1]) ?? .standard
    }
}

enum AppRuntimeOptions {
    static func isUITesting(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        arguments.contains("-ui-testing")
    }

    static func launchProfile(arguments: [String] = ProcessInfo.processInfo.arguments) -> AppLaunchProfile {
        AppLaunchProfile.resolve(arguments: arguments)
    }

    static func shouldSkipNonessentialStartupWork(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        launchProfile(arguments: arguments) == .uiSmoke
    }

    static func shouldUseIsolatedAuthSession(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        isUITesting(arguments: arguments) && arguments.contains("-isolatedAuthSession")
    }
}
