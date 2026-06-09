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
    @Environment(\.networkMonitor) private var networkMonitor

    @State private var debounceTask: Task<Void, Never>?
    @State private var lastTriggerAt: Date?

    /// 兩次自動同步最小間隔（秒）。避免 failed 後立即 retry 形成 hot loop。
    static let minTriggerInterval: TimeInterval = 60

    func body(content: Content) -> some View {
        content
            .onChange(of: pendingEntries.count) { _, _ in
                scheduleEvaluation(debounceSeconds: 2)
            }
            .onChange(of: autoSyncStore.isEnabled) { _, isOn in
                // off→on：使用者剛打開開關，需重新評估累積的 pending（count 不變，
                // 無法由 pendingEntries.count onChange 觸發）
                guard isOn else {
                    debounceTask?.cancel()
                    return
                }
                scheduleEvaluation(debounceSeconds: 0.5)
            }
            .onChange(of: networkMonitor.isConnected) { wasConnected, isConnected in
                guard Self.shouldScheduleOnConnectivityChange(
                    wasConnected: wasConnected,
                    isConnected: isConnected
                ) else { return }
                scheduleEvaluation(debounceSeconds: 0.5)
            }
    }

    private func scheduleEvaluation(debounceSeconds: Double) {
        debounceTask?.cancel()
        debounceTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(debounceSeconds))
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

            // Cooldown 保護：距上次觸發 < 60s 不重跑，避免 failed 狀態下的 hot loop
            if let last = lastTriggerAt,
               Date().timeIntervalSince(last) < Self.minTriggerInterval {
                return
            }

            let deletes = pending.filter { $0.syncAction == .delete }
            let adds = pending.filter { $0.syncAction == .add }
            syncCoordinator.buildSteps(deleteCount: deletes.count, addCount: adds.count)
            syncCoordinator.startSync(
                pendingEntries: pending,
                modelContext: modelContext,
                kgService: kgService
            )
            lastTriggerAt = Date()
            AppLog.kg.info("Auto-sync triggered with \(pending.count) pending entries")
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

    static func shouldScheduleOnConnectivityChange(wasConnected: Bool, isConnected: Bool) -> Bool {
        !wasConnected && isConnected
    }
}
