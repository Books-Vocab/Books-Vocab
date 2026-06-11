import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Pins the logout-cleanup ↔ re-login race contract（2026-06-09 000287 事故根因）。
///
/// `logout()` 把 `clearLocalData`（清 SwiftData + sync boundary）排進 fire-and-forget
/// Task；使用者在 cleanup 完成前快速重登時，post-login sync 會搶用**尚未被清的**
/// sync boundary（incremental sync 跳過後端全部卡 → 本地空庫但自認最新），且
/// cleanup resume 後會把新 session 剛拉回的資料再清一遍。
///
/// 契約：`waitForPendingLocalDataCleanup()` 必須懸掛到 logout 排程的 cleanup
/// 完成為止 —— post-login sync（BooksAndVocabApp onChange(isLoggedIn)）以它為
/// 前置 gate，保證 full sync 讀到的是已清空的 boundary。
@MainActor
struct AuthManagerLogoutCleanupRaceTests {

    /// clearLocalData 進場後懸掛在閘門上，直到測試顯式放行 —— 模擬慢速 cleanup
    /// 與快速重登的競態窗口。事件順序記錄在 MainActor 上供確定性斷言。
    private final class GatedCleaner: LocalDataClearing, @unchecked Sendable {
        @MainActor private(set) var events: [String] = []
        @MainActor private var gateContinuation: CheckedContinuation<Void, Never>?
        @MainActor private var startedContinuation: CheckedContinuation<Void, Never>?
        @MainActor private var hasStarted = false

        func clearLocalData(container: ModelContainer, reason: String) async {
            await MainActor.run {
                events.append("cleanup_started")
                hasStarted = true
                startedContinuation?.resume()
                startedContinuation = nil
            }
            await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
                Task { @MainActor in
                    gateContinuation = continuation
                }
            }
            await MainActor.run { events.append("cleanup_finished") }
        }

        @MainActor
        func record(_ event: String) {
            events.append(event)
        }

        @MainActor
        func waitUntilStarted() async {
            if hasStarted { return }
            await withCheckedContinuation { startedContinuation = $0 }
        }

        @MainActor
        func release() async {
            // gateContinuation 由 clearLocalData 內的 Task hop 設置；輪詢到位後放行。
            while gateContinuation == nil { await Task.yield() }
            events.append("cleanup_released")
            gateContinuation?.resume()
            gateContinuation = nil
        }
    }

    private final class FixedSessionStore: AuthSessionStoring {
        let session: PersistedAuthSession
        init(userId: String?) {
            self.session = PersistedAuthSession(
                userId: userId,
                displayName: nil,
                userEmail: nil,
                avatarURL: nil,
                token: userId == nil ? nil : "tok.\(userId!)",
                keychainReadFailed: false
            )
        }
        func loadSession() -> PersistedAuthSession { session }
        func persistProfile(userId: String?, displayName: String?, userEmail: String?, avatarURL: URL?) {}
        func persistToken(_ token: String?) {}
        func clearSession() {}
    }

    private final class NoopVerifier: AuthVerifying {
        func verify(provider: String, token: String, email: String?) async throws -> AuthVerificationResult {
            throw CancellationError()
        }
    }

    @MainActor
    private static func makeContainer() -> ModelContainer {
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try! ModelContainer(for: Notebook.self, configurations: config)
    }

    private func makeManager(priorUserId: String?, cleaner: any LocalDataClearing) -> AuthManager {
        let manager = AuthManager(
            verifier: NoopVerifier(),
            localDataCleaner: cleaner,
            sessionStore: FixedSessionStore(userId: priorUserId)
        )
        manager.modelContainer = Self.makeContainer()
        return manager
    }

    /// 核心契約：cleanup 未完成前 wait 必懸掛；事件序必為
    /// started → released → finished → wait_finished（錯誤實作會讓
    /// wait_finished 搶在 released 之前 —— 確定性紅燈，無 timing flake）。
    @Test func waitSuspendsUntilLogoutCleanupFinishes() async {
        let cleaner = GatedCleaner()
        let manager = makeManager(priorUserId: "user-a", cleaner: cleaner)

        manager.logout(reason: "race_test")
        await cleaner.waitUntilStarted()

        // 模擬競態窗口中的快速重登 + post-login gate。
        manager.login(userId: "user-a", token: "fresh-token")
        let waiter = Task { @MainActor in
            await manager.waitForPendingLocalDataCleanup()
            cleaner.record("wait_finished")
        }

        await cleaner.release()
        await waiter.value

        #expect(cleaner.events == [
            "cleanup_started",
            "cleanup_released",
            "cleanup_finished",
            "wait_finished"
        ], "wait 必須排在 cleanup 完成之後，實際順序：\(cleaner.events)")
    }

    /// 無 pending cleanup（從未登出）時，gate 立即返回 —— 正常冷啟登入不被拖慢。
    @Test func waitReturnsImmediatelyWhenNoCleanupPending() async {
        let cleaner = GatedCleaner()
        let manager = makeManager(priorUserId: nil, cleaner: cleaner)

        await manager.waitForPendingLocalDataCleanup()

        #expect(cleaner.events.isEmpty)
    }

    /// 連續兩次 logout：wait 跟的是**最新**一次排程的 cleanup。
    @Test func waitTracksLatestLogoutCleanup() async {
        let cleaner = GatedCleaner()
        let manager = makeManager(priorUserId: "user-a", cleaner: cleaner)

        manager.logout(reason: "first")
        await cleaner.waitUntilStarted()
        await cleaner.release()
        await manager.waitForPendingLocalDataCleanup()

        let finishedBeforeSecond = cleaner.events.filter { $0 == "cleanup_finished" }.count
        #expect(finishedBeforeSecond == 1)
    }
}
