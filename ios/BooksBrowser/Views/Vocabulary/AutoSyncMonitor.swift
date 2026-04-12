import SwiftUI
import SwiftData

struct AutoSyncMonitor: ViewModifier {
    @Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 })
    private var pendingEntries: [VocabularyEntry]

    @Environment(\.syncCoordinator) private var syncCoordinator
    @Environment(\.authManager) private var authManager
    @Environment(\.kgService) private var kgService
    @Environment(\.modelContext) private var modelContext
    @Environment(\.autoSyncSettingsStore) private var autoSyncStore
    @Environment(\.toastCoordinator) private var toastCoordinator

    @State private var debounceTask: Task<Void, Never>?

    func body(content: Content) -> some View {
        content
            .onChange(of: pendingEntries.count) { _, newCount in
                debounceTask?.cancel()
                debounceTask = Task { @MainActor in
                    try? await Task.sleep(for: .seconds(2))
                    guard !Task.isCancelled else { return }

                    let pending = pendingEntries.filter(\.shouldUploadOnNextSync)
                    guard Self.shouldTrigger(
                        pendingCount: pending.count,
                        isEnabled: autoSyncStore.isEnabled,
                        isRunning: syncCoordinator.phase == .running,
                        isLoggedIn: authManager.isLoggedIn,
                        isDemoMode: authManager.isDemoMode,
                        isConnected: NetworkMonitor.shared.isConnected
                    ) else { return }

                    let deletes = pending.filter { $0.syncAction == .delete }
                    let adds = pending.filter { $0.syncAction == .add }
                    syncCoordinator.buildSteps(deleteCount: deletes.count, addCount: adds.count)
                    syncCoordinator.startSync(
                        pendingEntries: pending,
                        modelContext: modelContext,
                        kgService: kgService
                    )
                    AppLog.kg.info("Auto-sync triggered with \(pending.count) pending entries")
                }
            }
    }

    /// Pure function for testability — all condition checks in one place.
    static func shouldTrigger(
        pendingCount: Int,
        isEnabled: Bool,
        isRunning: Bool,
        isLoggedIn: Bool,
        isDemoMode: Bool,
        isConnected: Bool
    ) -> Bool {
        isEnabled
            && pendingCount >= AutoSyncSettingsStore.threshold
            && !isRunning
            && isLoggedIn
            && !isDemoMode
            && isConnected
    }
}
