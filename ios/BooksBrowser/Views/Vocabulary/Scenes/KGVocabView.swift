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

    @Query private var syncedEntries: [VocabularyEntry]
    @Environment(\.authManager) private var authManager

    @State private var coordinator = KGVocabCoordinator()
    @State private var selectedReviewState: VocabularyReviewState = .due
    @State private var sortOption: KGVocabSortOption = .default
    @State private var showArchiveList = false

    @Query(filter: #Predicate<VocabularyEntry> { $0.actionType == "delete" })
    private var pendingDeletes: [VocabularyEntry]

    init(searchText: Binding<String>) {
        self._searchText = searchText
        let filter = #Predicate<VocabularyEntry> {
            $0.syncStatus == 1 &&
            $0.actionType != "delete"
        }
        self._syncedEntries = Query(filter: filter)
    }

    var body: some View {
        Group {
            if !authManager.isLoggedIn {
                VStack {
                    Spacer()
                    VocabEmptyStateCard(
                        title: "尚未登入".localized,
                        systemImage: "person.crop.circle.badge.exclamationmark",
                        description: "登入後，您在閱讀時標記的生詞將會自動整理於此。".localized
                    )
                    Spacer()
                }
                .padding(vocabSkin.metrics.cardBlockPadding)
                .vocabCanvasBackground()
            } else if coordinator.errorMessage != nil && syncedEntries.isEmpty {
                VStack {
                    Spacer()
                    VocabStateMessageCard(
                        title: "無法載入知識庫".localized,
                        systemImage: "exclamationmark.triangle"
                    ) {
                        Button("重試".localized) {
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
                        .buttonStyle(.vocabAction())
                    }
                    Spacer()
                }
                .padding(vocabSkin.metrics.cardBlockPadding)
                .vocabCanvasBackground()
            } else if coordinator.isLoading && syncedEntries.isEmpty {
                VStack {
                    Spacer()
                    VocabStateMessageCard(
                        title: "載入知識庫...".localized,
                        systemImage: "arrow.clockwise"
                    ) {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Spacer()
                }
                .padding(vocabSkin.metrics.cardBlockPadding)
                .vocabCanvasBackground()
            } else {
                content
            }
        }
        .sheet(item: $coordinator.selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
                .presentationContentInteraction(.scrolls)
        }
        .sheet(isPresented: $showArchiveList) {
            ArchivedVocabSheet()
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
            onDeleteTapped: { entryID in
                handleDeleteTap(entryID)
            },
            onArchiveTapped: { entryID in
                handleArchiveTap(entryID)
            },
            onRefresh: {
                await coordinator.forceRefresh(
                    kgService: kgService,
                    modelContext: modelContext
                )
            }
        )
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
        if syncedEntries.isEmpty { return "知識庫目前是空的".localized }
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

    private func handleDeleteTap(_ entryID: UUID) {
        coordinator.handleDeleteTap(
            entryID,
            syncedEntries: syncedEntries,
            modelContext: modelContext
        )
    }

    private func handleArchiveTap(_ entryID: UUID) {
        guard let entry = syncedEntries.first(where: { $0.id == entryID }) else { return }
        Task {
            do {
                try await kgService.archiveCard(word: entry.word, archived: true)
                entry.isArchived = true
                modelContext.safeSave()
            } catch {
                AppLog.kg.error("Archive failed: \(error.localizedDescription)")
            }
        }
    }

    var archiveCount: Int {
        VocabularyEntryPresentation.archivedEntries(in: syncedEntries).count
    }
}
