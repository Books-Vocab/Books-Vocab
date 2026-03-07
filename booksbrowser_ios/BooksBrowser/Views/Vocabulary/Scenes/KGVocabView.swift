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
    @Environment(\.vocabSkin) private var vocabSkin
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
        ScrollView {
            VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                if !pendingDeletes.isEmpty {
                    ErrorBannerView(
                        message: "\(pendingDeletes.count) 個單字刪除待同步",
                        onDismiss: nil,
                        onRetry: { Task { await retryPendingDeletes() } }
                    )
                } else if let error = errorMessage {
                    ErrorBannerView(message: "離線模式，同步失敗：\(error)", onDismiss: {
                        errorMessage = nil
                    })
                }

                if !syncedEntries.isEmpty {
                    browserSection
                } else {
                    emptyState
                }
            }
            .padding(AppMetrics.spacingLarge)
            .padding(.bottom, 120)
        }
        .vocabCanvasBackground()
    }

    // MARK: - Browser Section

    private var browserSection: some View {
        VocabCard(padding: 0) {
            VStack(alignment: .leading, spacing: 0) {
                VStack(alignment: .leading, spacing: 10) {
                    VocabTabSelector(options: reviewStateOptions, selection: $selectedReviewState)
                }
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 12)

                Divider()
                    .padding(.horizontal, 16)

                if filteredEntries.isEmpty {
                    emptyState
                        .padding(16)
                } else {
                    LazyVStack(spacing: 0) {
                        ForEach(Array(filteredEntries.enumerated()), id: \.element.id) { index, entry in
                            WordRow(
                                word: entry.word,
                                translation: entry.translation,
                                partOfSpeech: entry.partOfSpeech,
                                difficultyTier: entry.difficultyTier,
                                bookTitle: nil,
                                chapterTitle: nil,
                                nextReviewAt: entry.nextReviewAt,
                                reviewState: entry.reviewState,
                                syncStatus: nil,
                                showsReviewState: false
                            )
                            .contentShape(Rectangle())
                            .onTapGesture { selectedEntry = entry }
                            .contextMenu {
                                Button(role: .destructive) {
                                    markForDeletion(entry)
                                } label: {
                                    Label("刪除卡片", systemImage: "trash")
                                }
                            }
                            .padding(.horizontal, 16)

                            if index < filteredEntries.count - 1 {
                                Divider()
                                    .padding(.leading, 16)
                            }
                        }
                    }
                }
            }
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

    // MARK: - Components

    // MARK: - Computed

    private var dueEntries: [VocabularyEntry] {
        sortedEntries.filter { $0.reviewState == .due }
    }

    private var unlearnedEntries: [VocabularyEntry] {
        sortedEntries.filter { $0.reviewState == .unlearned }
    }

    private var reviewedEntries: [VocabularyEntry] {
        sortedEntries.filter { $0.reviewState == .reviewed }
    }

    private var filteredEntries: [VocabularyEntry] {
        let stateFiltered = sortedEntries.filter { $0.reviewState == selectedReviewState }
        guard !searchText.isEmpty else { return stateFiltered }
        return stateFiltered.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var sortedEntries: [VocabularyEntry] {
        syncedEntries.sorted {
            if reviewOrder($0.reviewState) != reviewOrder($1.reviewState) {
                return reviewOrder($0.reviewState) < reviewOrder($1.reviewState)
            }
            if $0.reviewState != .reviewed && $0.nextReviewAt != $1.nextReviewAt {
                return $0.nextReviewAt < $1.nextReviewAt
            }
            let t0 = tierOrder($0.difficultyTier)
            let t1 = tierOrder($1.difficultyTier)
            if t0 != t1 { return t0 < t1 }
            return $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending
        }
    }

    private var emptyState: some View {
        VocabEmptyStateContent(
            title: emptyStateTitle,
            systemImage: emptyStateIcon,
            description: emptyStateDescription
        )
        .padding(.vertical, 16)
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
        syncedEntries.filter { $0.reviewState == state }.count
    }

    private func reviewOrder(_ state: VocabularyReviewState) -> Int {
        switch state {
        case .due: return 0
        case .unlearned: return 1
        case .reviewed: return 2
        }
    }

    private func tierOrder(_ tier: String?) -> Int {
        switch tier {
        case "core": return 0
        case "intermediate": return 1
        case "advanced": return 2
        case "rare": return 3
        default: return 4
        }
    }

    private func markForDeletion(_ entry: VocabularyEntry) {
        entry.actionType = "delete"
        entry.syncStatus = 0
        try? modelContext.save()
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
