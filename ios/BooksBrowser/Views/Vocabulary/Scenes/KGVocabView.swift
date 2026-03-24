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
    @Binding var searchText: String

    let notebookId: String

    @Query private var syncedEntries: [VocabularyEntry]
    @Environment(\.authManager) private var authManager

    @State private var coordinator = KGVocabCoordinator()
    @State private var selectedReviewState: VocabularyReviewState = .due
    @State private var sortOption: KGVocabSortOption = .default
    @State private var selectionState = SelectionModeState()
    @State private var showNotebookPicker = false
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
        VocabSceneShell(phase: scenePhase) {
            content
        }
        .animatePhaseChange(coordinator.isLoading)
        .animatePhaseChange(coordinator.errorMessage == nil)
        .sheet(item: $coordinator.selectedEntry) { entry in
            WordDetailSheet(entry: entry, allEntries: syncedEntries)
                .appSheet(.large)
        }
        .task {
            await coordinator.loadInitialData(
                authManager: authManager,
                kgService: kgService,
                modelContext: modelContext,
                dueEntries: dueEntries,
                unlearnedEntries: unlearnedEntries,
                selectedReviewState: $selectedReviewState
            )
        }
    }

    private var content: some View {
        KGVocabPresenter(
            state: presenterState,
            selectedReviewState: $selectedReviewState,
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
        .onChange(of: selectedReviewState) { _, _ in
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
        }
        .sheet(isPresented: $showNotebookPicker) {
            NotebookPickerSheet(excludeNotebookId: notebookId) { notebook in
                handleBatchMove(to: notebook)
            }
            .appSheet(.medium)
        }
    }

    private var reviewStateOptions: [VocabTabOption<VocabularyReviewState>] {
        VocabularyReviewState.allCases.map { state in
            VocabTabOption(
                id: state,
                title: state.title,
                count: count(for: state)
            )
        }
    }

    // MARK: - Computed

    private var scenePhase: VocabScenePhase {
        if !authManager.isLoggedIn {
            return .empty(
                title: "尚未登入".localized,
                systemImage: "person.crop.circle.badge.exclamationmark",
                description: "登入後，您在閱讀時標記的生詞將會自動整理於此。".localized
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
                            modelContext: modelContext,
                            dueEntries: dueEntries,
                            unlearnedEntries: unlearnedEntries,
                            selectedReviewState: $selectedReviewState
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

    private var presenterState: KGVocabPresenter.State {
        KGVocabPresenter.State(
            banner: bannerState,
            reviewStateOptions: reviewStateOptions,
            rows: filteredEntries.map {
                KGVocabPresenter.State.RowItem(
                    id: $0.id,
                    row: $0.wordRowViewData(
                        showsReviewState: false,
                        showsSourceContext: false,
                        showsDifficultyTier: false,
                        showsReviewProgress: true
                    )
                )
            },
            emptyState: .init(
                title: emptyStateTitle,
                systemImage: emptyStateIcon,
                description: emptyStateDescription
            )
        )
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

    private var dueEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredKnowledgeEntries(
            in: syncedEntries,
            reviewState: .due,
            searchText: ""
        )
    }

    private var unlearnedEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredKnowledgeEntries(
            in: syncedEntries,
            reviewState: .unlearned,
            searchText: ""
        )
    }

    private var reviewedEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredKnowledgeEntries(
            in: syncedEntries,
            reviewState: .reviewed,
            searchText: ""
        )
    }

    private var filteredEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredKnowledgeEntries(
            in: syncedEntries,
            reviewState: selectedReviewState,
            searchText: searchText,
            sortOption: sortOption
        )
    }

    private var emptyStateTitle: String {
        if syncedEntries.isEmpty { return "尚無已收錄單字".localized }
        if !searchText.isEmpty { return "沒有符合的單字".localized }
        return selectedReviewState.title
    }

    private var emptyStateDescription: String {
        if syncedEntries.isEmpty { return "同步完成後，這裡會顯示你的雲端單字。".localized }
        if !searchText.isEmpty { return "試試其他關鍵字，或切換到別的狀態。".localized }
        switch selectedReviewState {
        case .unlearned: return "目前沒有尚未進入複習流程的卡片。".localized
        case .due: return "今天沒有到期卡片。".localized
        case .reviewed: return "目前沒有已複習中的卡片。".localized
        }
    }

    private var emptyStateIcon: String {
        switch selectedReviewState {
        case .unlearned: return "sparkles"
        case .due: return "checkmark.seal"
        case .reviewed: return "leaf"
        }
    }

    // MARK: - Helpers

    private func count(for state: VocabularyReviewState) -> Int {
        VocabularyEntryPresentation.countKnowledgeEntries(
            in: syncedEntries,
            reviewState: state
        )
    }

    private func handleRowTap(_ entryID: UUID) {
        coordinator.handleRowTap(entryID, syncedEntries: syncedEntries)
    }

    private func handleBatchDelete() {
        coordinator.handleBatchDelete(
            selectionState.selectedIDs,
            syncedEntries: syncedEntries,
            modelContext: modelContext
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
                modelContext: modelContext
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
                    modelContext: modelContext
                )
            } catch {
                coordinator.errorMessage = error.localizedDescription
            }
        }
    }

}
