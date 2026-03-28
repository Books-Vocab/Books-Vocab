//
//  SyncView.swift
//  BooksBrowser
//
//  Thin sync scene container — environment/query wiring only.
//

import SwiftUI
import SwiftData

struct SyncView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 })
    private var pendingEntries: [VocabularyEntry]

    @Environment(\.syncCoordinator) private var coordinator
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            SyncPresenter(
                state: presenterState,
                onPrimaryAction: handlePrimaryAction,
                onCancel: coordinator.cancelSync,
                onShowSettings: { showSettings = true }
            )
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .task {
                refreshStepLayoutIfIdle()
            }
            .onChange(of: pendingEntries.count) { _, _ in
                refreshStepLayoutIfIdle()
            }
        }
    }

    private var presenterState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: authManager.isLoggedIn,
            isConnected: kgService.isConnected,
            phase: coordinator.phase,
            failureKind: coordinator.failureKind,
            pendingCount: pendingEntries.count,
            addCount: addActions.count,
            deleteCount: deleteActions.count,
            steps: coordinator.steps,
            summaryText: coordinator.summaryText
        )
    }

    private var deleteActions: [VocabularyEntry] {
        pendingEntries.filter { $0.syncAction == .delete && $0.shouldUploadOnNextSync }
    }

    private var addActions: [VocabularyEntry] {
        pendingEntries.filter { $0.syncAction == .add && $0.shouldUploadOnNextSync }
    }

    private func handlePrimaryAction() {
        switch coordinator.phase {
        case .ready:
            coordinator.startSync(
                pendingEntries: pendingEntries,
                modelContext: modelContext,
                kgService: kgService
            )
        case .failed:
            refreshStepLayout()
        case .completed, .running:
            break
        }
    }

    private func refreshStepLayout() {
        coordinator.resetForRetry(
            deleteCount: deleteActions.count,
            addCount: addActions.count
        )
    }

    private func refreshStepLayoutIfIdle() {
        guard coordinator.phase != .running else { return }
        refreshStepLayout()
    }
}

// MARK: - Preview

#Preview("SyncView / Ready") {
    AppThemeContainer {
        SyncView()
            .modelContainer(for: [VocabularyEntry.self, Notebook.self], inMemory: true)
    }
}
