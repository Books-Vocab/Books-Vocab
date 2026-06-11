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

    /// 啟動即開 Settings sheet（probe rig：真機 devicectl launch 無法驅動 UI，
    /// 用 launch arg 重現「開設定頁」路徑）。沿 isolatedAuthSession 慣例綁
    /// -ui-testing，避免單獨旗標誤觸。
    static func shouldOpenSettingsOnLaunch(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        isUITesting(arguments: arguments) && arguments.contains("-openSettingsOnLaunch")
    }
}
