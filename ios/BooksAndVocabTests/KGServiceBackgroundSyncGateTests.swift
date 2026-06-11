import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Pins the backgroundSync ↔ logout-cleanup ordering invariant（000287 事故）。
///
/// `backgroundSync` 有四個觸發點（post-login / scenePhase→active / ⌘R /
/// Settings 手動同步）。gate 若只放在個別 call site，重登後立刻切前景或手動
/// 同步仍會落在 logout cleanup 窗口內、以未清的 boundary 跑 incremental sync。
/// 契約：gate 在 `backgroundSync` 入口單點生效 —— 任何 sync 工作（含 offline
/// 早退之前）都必須先 `await sessionInvalidator.waitForPendingLocalDataCleanup()`。
@MainActor
struct KGServiceBackgroundSyncGateTests {

    private final class RecordingInvalidator: SessionInvalidating {
        private(set) var events: [String] = []
        func logout(modelContainer: ModelContainer?, reason: String) {
            events.append("logout_\(reason)")
        }
        func waitForPendingLocalDataCleanup() async {
            events.append("wait_for_cleanup")
        }
    }

    private final class NilTokenSession: AuthSessionProviding {
        var isLoggedIn: Bool { true }
        var token: String? { nil }
    }

    /// 空 in-memory 容器：push payload 為空不打網路；pull 在 token 取得前就
    /// 因 nil token 走 unauthorized 早退 —— 全程無真網路呼叫。
    @MainActor
    private static func makeContainer() -> ModelContainer {
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try! ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            PodcastSeries.self, PodcastEpisode.self,
            configurations: config
        )
    }

    @Test func backgroundSyncAwaitsCleanupGateBeforeAnySyncWork() async {
        let invalidator = RecordingInvalidator()
        let service = KGService(
            authSession: NilTokenSession(),
            sessionInvalidator: invalidator
        )

        await service.backgroundSync(container: Self.makeContainer())

        #expect(invalidator.events.first == "wait_for_cleanup",
                "backgroundSync 必須在任何 sync 工作前先過 cleanup gate，實際事件：\(invalidator.events)")
    }
}
