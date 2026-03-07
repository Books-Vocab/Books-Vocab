//
//  KGVocabView.swift
//  BooksBrowser
//
//  Mochi-inspired knowledge base browser.
//  Clean white cards, generous spacing, ghost buttons, typography-driven hierarchy.
//

import SwiftUI
import SwiftData

struct KGVocabView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Binding var searchText: String

    @Query private var syncedEntries: [VocabularyEntry]
    @Environment(\.authManager) private var authManager

    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var selectedEntry: VocabularyEntry?
    @State private var selectedReviewState: VocabularyReviewState = .due

    @Query(filter: #Predicate<VocabularyEntry> { $0.actionType == "delete" })
    private var pendingDeletes: [VocabularyEntry]

    init(searchText: Binding<String>) {
        self._searchText = searchText
        let filter = #Predicate<VocabularyEntry> { $0.syncStatus == 1 && $0.actionType != "delete" }
        self._syncedEntries = Query(filter: filter)
    }

    var body: some View {
        Group {
            if !authManager.isLoggedIn {
                VStack {
                    Spacer()
                    VocabEmptyStateCard(
                        title: "尚未登入",
                        systemImage: "person.crop.circle.badge.exclamationmark",
                        description: "登入後，您在閱讀時標記的生詞將會自動整理於此。"
                    )
                    Spacer()
                }
                .padding(AppMetrics.spacingLarge)
                .vocabCanvasBackground()
            } else if isLoading && syncedEntries.isEmpty {
                ProgressView("載入知識庫...")
            } else {
                content
            }
        }
        .sheet(item: $selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationContentInteraction(.scrolls)
        }
        .task {
            guard authManager.isLoggedIn else { return }

            isLoading = true
            do {
                try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
                errorMessage = nil
                if dueEntries.isEmpty && !unlearnedEntries.isEmpty {
                    selectedReviewState = .unlearned
                }
            } catch {
                errorMessage = error.localizedDescription
            }
            isLoading = false
        }
    }

    private var content: some View {
        KGVocabPresenter(
            state: presenterState,
            selectedReviewState: $selectedReviewState,
            onDismissBanner: errorMessage == nil ? nil : { errorMessage = nil },
            onRetryBanner: pendingDeletes.isEmpty ? nil : { Task { await retryPendingDeletes() } },
            onRowTapped: handleRowTap,
            onDeleteTapped: handleDeleteTap
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
                        showsSourceContext: false
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
        if let errorMessage {
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
            searchText: searchText
        )
    }

    private var emptyStateTitle: String {
        if syncedEntries.isEmpty { return "知識庫目前是空的" }
        if !searchText.isEmpty { return "沒有符合的單字" }
        return selectedReviewState.title
    }

    private var emptyStateDescription: String {
        if syncedEntries.isEmpty { return "同步完成後，這裡會顯示你的雲端單字。" }
        if !searchText.isEmpty { return "試試其他關鍵字，或切換到別的狀態。" }
        switch selectedReviewState {
        case .unlearned: return "目前沒有尚未進入複習流程的卡片。"
        case .due: return "今天沒有到期卡片。"
        case .reviewed: return "目前沒有已複習中的卡片。"
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

    private func markForDeletion(_ entry: VocabularyEntry) {
        entry.actionType = "delete"
        entry.syncStatus = 0
        try? modelContext.save()
    }

    private func handleRowTap(_ entryID: UUID) {
        selectedEntry = syncedEntries.first { $0.id == entryID }
    }

    private func handleDeleteTap(_ entryID: UUID) {
        guard let entry = syncedEntries.first(where: { $0.id == entryID }) else { return }
        markForDeletion(entry)
    }

    private func retryPendingDeletes() async {
        for entry in pendingDeletes {
            do {
                try await kgService.deleteCard(word: entry.word)
                modelContext.delete(entry)
            } catch {
            }
        }
        try? modelContext.save()
        await kgService.healthCheck()
    }
}
