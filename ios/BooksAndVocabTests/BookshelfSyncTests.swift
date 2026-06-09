import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// Pins the explicit-sync feedback + eligibility policy shared by 書架 pull-to-refresh /
/// Mac toolbar 鈕 / ⌘R menu (`ExplicitSync.run`) plus the `BookshelfCoordinator.sync`
/// reentrancy guard.
///
/// Covered seams:
///  - eligibility gate: not-logged-in / demo mode → no-op (no sync, no toast), mirroring
///    the `BooksAndVocabApp` scenePhase/post-login `guard isLoggedIn, !isDemoMode`
///  - success → `.success` toast「同步完成」, `lastBackgroundSyncError` stays nil
///  - failure → `.warning` toast carrying the message, **read-then-clear** wipes the
///    shared field to nil (so a later consumer can't re-fire a stale failure toast)
///  - `sync` is reentrancy-guarded — an overlapping call no-ops instead of double-syncing
@MainActor
struct BookshelfSyncTests {

    /// Minimal in-memory container; `backgroundSync` is stubbed and never touches schema.
    private func makeContainer() throws -> ModelContainer {
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: Book.self, configurations: config)
    }

    /// Narrow `BackgroundSyncing` stub. `resultError` is what each `backgroundSync` run
    /// leaves in `lastBackgroundSyncError` (nil = success, mirroring the real service which
    /// resets to nil on success / sets a message on failure). `onSync` lets a test re-enter
    /// the coordinator mid-flight to exercise the reentrancy guard deterministically.
    private final class StubBackgroundSync: BackgroundSyncing, @unchecked Sendable {
        var lastBackgroundSyncError: String?
        var resultError: String?
        private(set) var callCount = 0
        var onSync: (@MainActor () async -> Void)?

        init(resultError: String? = nil) { self.resultError = resultError }

        func backgroundSync(container: ModelContainer) async {
            callCount += 1
            if let hook = onSync {
                onSync = nil
                await hook()
            }
            lastBackgroundSyncError = resultError
        }
    }

    // MARK: - Eligibility gate

    @Test func explicitSync_notLoggedIn_isNoOp() async throws {
        let stub = StubBackgroundSync(resultError: nil)
        let toast = AppToastCoordinator()
        await ExplicitSync.run(
            kgService: stub,
            isLoggedIn: false,
            isDemoMode: false,
            container: try makeContainer(),
            toastCoordinator: toast
        )

        // Never hits the network, never toasts — pull-to-refresh on the (logged-out) empty
        // shelf must not trip the unauthorized path into a spurious「登入已過期」.
        #expect(stub.callCount == 0)
        #expect(toast.current == nil)
    }

    @Test func explicitSync_demoMode_isNoOp() async throws {
        let stub = StubBackgroundSync(resultError: nil)
        let toast = AppToastCoordinator()
        await ExplicitSync.run(
            kgService: stub,
            isLoggedIn: true,
            isDemoMode: true,
            container: try makeContainer(),
            toastCoordinator: toast
        )

        #expect(stub.callCount == 0)
        #expect(toast.current == nil)
    }

    // MARK: - ExplicitSync feedback policy (eligible account)

    @Test func explicitSync_success_showsCompletedToast_andLeavesErrorNil() async throws {
        let stub = StubBackgroundSync(resultError: nil)
        let toast = AppToastCoordinator()
        await ExplicitSync.run(
            kgService: stub,
            isLoggedIn: true,
            isDemoMode: false,
            container: try makeContainer(),
            toastCoordinator: toast
        )

        #expect(stub.callCount == 1)
        #expect(toast.current?.style == .success)
        #expect(toast.current?.message == "同步完成".localized)
        #expect(stub.lastBackgroundSyncError == nil)
    }

    @Test func explicitSync_failure_showsWarningToast_andClearsSharedError() async throws {
        let message = "目前沒有網路連線，背景同步已跳過".localized
        let stub = StubBackgroundSync(resultError: message)
        let toast = AppToastCoordinator()
        await ExplicitSync.run(
            kgService: stub,
            isLoggedIn: true,
            isDemoMode: false,
            container: try makeContainer(),
            toastCoordinator: toast
        )

        #expect(toast.current?.style == .warning)
        #expect(toast.current?.message == message)
        // read-then-clear: the shared field must be wiped so the next consumer
        // (scenePhase / another explicit trigger) can't re-surface this failure.
        #expect(stub.lastBackgroundSyncError == nil)
    }

    // MARK: - Coordinator reentrancy guard

    @Test func coordinatorSync_isReentrancyGuarded() async throws {
        let coordinator = BookshelfCoordinator()
        let toast = AppToastCoordinator()
        let container = try makeContainer()
        let stub = StubBackgroundSync(resultError: nil)

        // While the first sync is mid-flight (isSyncing == true), re-enter. The guard
        // must short-circuit the second call so backgroundSync runs exactly once.
        stub.onSync = { [stub] in
            await coordinator.sync(
                container: container,
                kgService: stub,
                isLoggedIn: true,
                isDemoMode: false,
                toastCoordinator: toast
            )
        }

        await coordinator.sync(
            container: container,
            kgService: stub,
            isLoggedIn: true,
            isDemoMode: false,
            toastCoordinator: toast
        )

        #expect(stub.callCount == 1)
        // 被守衛擋掉的重入呼叫不得跑同步（callCount 已證），亦不得汙染首輪結果——
        // toast 仍是首輪那一次成功 toast，沒有來自「沒跑的那輪」的多餘 toast。
        #expect(toast.current?.style == .success)
    }
}
