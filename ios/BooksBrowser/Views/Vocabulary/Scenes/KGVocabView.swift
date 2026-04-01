//
//  KGVocabView.swift
//  BooksBrowser
//
//  Typography-driven knowledge base browser.
//  Clean white cards, generous spacing, ghost buttons, typography-driven hierarchy.
//

import SwiftUI
import SwiftData
import os

struct KGVocabView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Binding var searchText: String

    let notebookId: String

    @Query private var syncedEntries: [VocabularyEntry]
    @Environment(\.authManager) private var authManager

    @State private var coordinator = KGVocabCoordinator()
    @State private var selectedReviewStates: Set<VocabularyReviewState> = []
    @State private var sortOption: KGVocabSortOption = .default
    @State private var selectionState = SelectionModeState()
    @State private var showNotebookPicker = false
    @State private var showLoginSheet = false
    @Query private var pendingDeletes: [VocabularyEntry]

    init(searchText: Binding<String>, notebookId: String = "default") {
        self._searchText = searchText
        self.notebookId = notebookId
        let nbId = notebookId
        let syncedFilter = #Predicate<VocabularyEntry> {
            $0.syncStatus == 1 &&
            $0.actionType != "delete" &&
            $0.notebookId == nbId
        }
        self._syncedEntries = Query(filter: syncedFilter)
        let deleteFilter = #Predicate<VocabularyEntry> {
            $0.actionType == "delete" &&
            $0.notebookId == nbId
        }
        self._pendingDeletes = Query(filter: deleteFilter)
    }

    var body: some View {
        let n = Date()
        let c = VocabularyEntryPresentation.classifyKnowledgeEntries(in: syncedEntries, now: n)
        let filtered = VocabularyEntryPresentation.sortAndFilter(
            c.mergedBucket(for: selectedReviewStates),
            searchText: searchText,
            sortOption: sortOption,
            now: n
        )

        VocabSceneShell(phase: buildScenePhase(classified: c)) {
            contentView(classified: c, filteredEntries: filtered)
        }
        .animatePhaseChange(coordinator.isLoading)
        .animatePhaseChange(coordinator.errorMessage == nil)
        .toastSheet(item: $coordinator.selectedEntry) { entry in
            WordDetailSheet(entry: entry, allEntries: syncedEntries)
                .appSheet(.large)
        }
        .task {
            await coordinator.loadInitialData(
                authManager: authManager,
                kgService: kgService,
                modelContext: modelContext
            )
        }
    }

    private func contentView(
        classified c: VocabularyEntryPresentation.ClassifiedResult,
        filteredEntries: [VocabularyEntry]
    ) -> some View {
        let tabOptions = VocabularyReviewState.allCases.map { state in
            VocabTabOption(
                id: state,
                title: state.title,
                count: c.count(for: state)
            )
        }
        let state = KGVocabPresenter.State(
            banner: bannerState,
            reviewStateOptions: tabOptions,
            rows: filteredEntries.map {
                KGVocabPresenter.State.RowItem(id: $0.id, entry: $0)
            },
            emptyState: .init(
                title: emptyStateTitle,
                systemImage: emptyStateIcon,
                description: emptyStateDescription
            )
        )

        return KGVocabPresenter(
            state: state,
            selectedReviewStates: $selectedReviewStates,
            sortOption: $sortOption,
            onDismissBanner: coordinator.errorMessage == nil ? nil : { coordinator.dismissBanner() },
            onRetryBanner: pendingDeletes.isEmpty ? nil : {
                Task {
                    await coordinator.retryPendingDeletes(
                        pendingDeletes: pendingDeletes,
                        kgService: kgService,
                        modelContext: modelContext
                    )
                }
            },
            onRowTapped: { entryID in
                handleRowTap(entryID)
            },
            selectionState: selectionState,
            onLongPress: { id in selectionState.enter(with: id) },
            onRefresh: {
                await coordinator.forceRefresh(
                    kgService: kgService,
                    modelContext: modelContext
                )
            }
        )
        .overlay(alignment: .bottom) {
            if selectionState.isSelecting {
                SelectionToolbar(
                    selectionCount: selectionState.selectionCount,
                    onMove: { showNotebookPicker = true },
                    onArchive: { handleBatchArchive() },
                    onDelete: { handleBatchDelete() }
                )
                .transition(.readerPanelReveal)
            }
        }
        .animateSpring(selectionState.isSelecting)
        .onChange(of: selectedReviewStates) { _, _ in
            selectionState.exit()
        }
        .onChange(of: filteredEntries.count) { _, newCount in
            selectionState.updateVisibleCount(newCount)
        }
        .toolbar {
            if selectionState.isSelecting {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { selectionState.exit() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button(selectionState.isAllSelected ? "取消全選".localized : "全選".localized) {
                        if selectionState.isAllSelected {
                            selectionState.deselectAll()
                        } else {
                            selectionState.selectAll(filteredEntries.map(\.id))
                        }
                    }
                }
            }
            #if os(macOS)
            ToolbarItem(placement: .automatic) {
                Button {
                    Task {
                        await coordinator.forceRefresh(
                            kgService: kgService,
                            modelContext: modelContext
                        )
                    }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .keyboardShortcut("r", modifiers: .command)
                .help("重新整理".localized)
            }
            #endif
        }
        .toastSheet(isPresented: $showNotebookPicker) {
            NotebookPickerSheet(excludeNotebookId: notebookId) { notebook in
                handleBatchMove(to: notebook)
            }
            .appSheet(.medium)
        }
        .sheet(isPresented: $showLoginSheet) {
            LoginSheet()
        }
    }

    // MARK: - Computed

    private func buildScenePhase(
        classified c: VocabularyEntryPresentation.ClassifiedResult
    ) -> VocabScenePhase {
        if !authManager.isLoggedIn {
            return .empty(
                title: "尚未登入".localized,
                systemImage: "person.crop.circle.badge.exclamationmark",
                description: "登入後，您在閱讀時標記的生詞將會自動整理於此。".localized,
                action: .init(title: "登入帳號", systemImage: "person.crop.circle", handler: { showLoginSheet = true })
            )
        } else if coordinator.errorMessage != nil && syncedEntries.isEmpty {
            return .error(
                title: "無法載入單字".localized,
                systemImage: "exclamationmark.triangle",
                retryAction: {
                    Task {
                        await coordinator.loadInitialData(
                            authManager: authManager,
                            kgService: kgService,
                            modelContext: modelContext
                        )
                    }
                }
            )
        } else if coordinator.isLoading && syncedEntries.isEmpty {
            return .loading(
                title: "載入單字...".localized,
                systemImage: "arrow.clockwise"
            )
        } else {
            return .content
        }
    }

    private var bannerState: KGVocabPresenter.State.Banner? {
        if !pendingDeletes.isEmpty {
            return .init(
                message: L10n.format("%@ 個單字刪除待同步", "\(pendingDeletes.count)"),
                canDismiss: false,
                canRetry: true
            )
        }
        if let errorMessage = coordinator.errorMessage {
            return .init(
                message: L10n.format("離線模式，同步失敗：%@", errorMessage),
                canDismiss: true,
                canRetry: false
            )
        }
        return nil
    }


    private var emptyStateTitle: String {
        if syncedEntries.isEmpty { return "尚無已收錄單字".localized }
        if !searchText.isEmpty { return "沒有符合的單字".localized }
        if !selectedReviewStates.isEmpty { return "目前沒有符合篩選條件的單字".localized }
        return "尚無已收錄單字".localized
    }

    private var emptyStateDescription: String {
        if syncedEntries.isEmpty { return "同步完成後，這裡會顯示你的雲端單字。".localized }
        if !searchText.isEmpty { return "試試其他關鍵字，或取消部分篩選條件。".localized }
        if !selectedReviewStates.isEmpty { return "試試取消部分篩選條件，或切換排序方式。".localized }
        return "同步完成後，這裡會顯示你的雲端單字。".localized
    }

    private var emptyStateIcon: String {
        if selectedReviewStates.count == 1, let state = selectedReviewStates.first {
            switch state {
            case .unlearned: return "sparkles"
            case .due: return "checkmark.seal"
            case .reviewed: return "leaf"
            }
        }
        return "line.3.horizontal.decrease.circle"
    }

    // MARK: - Helpers

    private func handleRowTap(_ entryID: UUID) {
        coordinator.handleRowTap(entryID, syncedEntries: syncedEntries)
    }

    private func handleBatchDelete() {
        coordinator.handleBatchDelete(
            selectionState.selectedIDs,
            syncedEntries: syncedEntries,
            modelContext: modelContext,
            toastCoordinator: toastCoordinator
        )
        selectionState.exit()
    }

    private func handleBatchArchive() {
        let ids = selectionState.selectedIDs
        selectionState.exit()
        Task {
            await coordinator.handleBatchArchive(
                ids,
                syncedEntries: syncedEntries,
                kgService: kgService,
                modelContext: modelContext,
                toastCoordinator: toastCoordinator
            )
        }
    }

    private func handleBatchMove(to notebook: Notebook) {
        let ids = selectionState.selectedIDs
        selectionState.exit()
        Task {
            do {
                try await coordinator.handleBatchMove(
                    ids,
                    syncedEntries: syncedEntries,
                    toNotebook: notebook.remoteId,
                    fromNotebook: notebookId,
                    kgService: kgService,
                    modelContext: modelContext,
                    toastCoordinator: toastCoordinator
                )
            } catch {
                coordinator.errorMessage = error.localizedDescription
            }
        }
    }

}

// MARK: - Preview

#Preview("KGVocab / Default") {
    AppThemeContainer {
        NavigationStack {
            KGVocabView(searchText: .constant(""))
        }
        .modelContainer(for: [VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
    }
}
