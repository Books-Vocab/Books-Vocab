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
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != VocabularySyncState.synced.rawValue })
    private var pendingEntries: [VocabularyEntry]

    @StateObject private var coordinator = SyncCoordinator()
    @State private var showSettings = false
    @State private var showPaywall = false

    var body: some View {
        NavigationStack {
            SyncPresenter(
                state: presenterState,
                onPrimaryAction: handlePrimaryAction,
                onCancel: coordinator.cancelSync,
                onShowSettings: { showSettings = true },
                onShowPaywall: {
                    subscriptionManager.activePaywallSource = .sync
                    showPaywall = true
                }
            )
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .sheet(isPresented: $showPaywall) {
                SubscriptionPaywallSheet()
            }
            .task {
                refreshStepLayout()
            }
            .onChange(of: pendingEntries.count) { _, _ in
                refreshStepLayoutIfIdle()
            }
        }
    }

    private var presenterState: SyncPresenterState {
        SyncPresenterState(
            isLoggedIn: authManager.isLoggedIn,
            hasProAccess: subscriptionManager.hasProAccess,
            isConnected: kgService.isConnected,
            phase: coordinator.phase,
            pendingCount: pendingEntries.count,
            addCount: addActions.count,
            deleteCount: deleteActions.count,
            steps: coordinator.steps,
            summaryText: coordinator.summaryText
        )
    }

    private var deleteActions: [VocabularyEntry] {
        pendingEntries.filter { $0.syncAction == .delete }
    }

    private var addActions: [VocabularyEntry] {
        pendingEntries.filter { $0.syncAction == .add }
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
