#if os(iOS)
import Foundation
import SwiftData

/// Bridges the existing fixture system into the live SwiftData container for UI tests.
/// Triggered by launch arguments when `-ui-testing` is active.
@MainActor
enum UITestFixtureSeed {
    /// Parse `-seedFixture:<domain>:<id>` arguments and inject matching fixtures.
    static func injectIfNeeded(into container: ModelContainer, arguments: [String]) {
        guard AppRuntimeOptions.isUITesting(arguments: arguments) else { return }

        // 資料安全防線（2026-06-10 事故）：fixture 會 wipe+seed VocabularyEntry。
        // 在真機上對真實 on-disk store 動手 = 清掉使用者整個本地單字庫，
        // 故只允許全 in-memory 容器（bootstrap 在 -ui-testing 下必須提供）。
        // !isEmpty：空配置容器 allSatisfy 恆真（fail-open），雖經查無實際
        // 產生路徑，仍以廉價保險封死。
        guard !container.configurations.isEmpty,
              container.configurations.allSatisfy(\.isStoredInMemoryOnly) else {
            AppLog.app.error("UITestFixtureSeed: refused — container has persistent store(s); fixtures may only seed the ephemeral UI-testing container")
            return
        }

        for arg in arguments {
            guard arg.hasPrefix("-seedFixture:") else { continue }
            let remainder = arg.dropFirst("-seedFixture:".count)
            let parts = remainder.split(separator: ":", maxSplits: 1).map(String.init)
            guard parts.count == 2 else { continue }
            let domain = parts[0]
            let id = parts[1]

            switch domain {
            case "bookshelf":
                seedBookshelf(id, into: container)
            case "podcast":
                seedPodcast(id, into: container)
            case "todayReview":
                seedTodayReview(id, into: container)
            case "auth":
                seedAuth(id, into: container)
            case "settings":
                seedSettings(id, into: container)
            case "shell":
                seedShell(id, into: container)
            case "search":
                seedSearch(id, into: container)
            case "reader":
                seedReader(id, into: container)
            case "notebook":
                seedNotebook(id, into: container)
            default:
                AppLog.app.warning("Unknown UI-test fixture domain: \(domain)")
            }
        }
    }

}
#endif
