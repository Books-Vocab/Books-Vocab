//
//  KGVocabView.swift
//  BooksBrowser
//
//  Displays vocabulary cards fetched from the Knowledge Graph API server.
//

import SwiftUI
import SwiftData

// No longer needed: struct KGCard


/// 知識庫瀏覽 — 從 API server 拉取所有卡片
struct KGVocabView: View {
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Binding var searchText: String

    @Query private var syncedEntries: [VocabularyEntry]

    @Environment(\.authManager) private var authManager
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var selectedEntry: VocabularyEntry?
    
    @Query(filter: #Predicate<VocabularyEntry> { $0.actionType == "delete" })
    private var pendingDeletes: [VocabularyEntry]

    init(searchText: Binding<String>) {
        self._searchText = searchText

        // Dynamically initialize the query in the custom init
        let filter = #Predicate<VocabularyEntry> { $0.syncStatus == 1 && $0.actionType != "delete" }
        self._syncedEntries = Query(filter: filter)
    }

    var body: some View {
        Group {
            if !authManager.isLoggedIn {
                ContentUnavailableView(
                    "尚未登入",
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: Text("登入後，您在閱讀時標記的生詞將會自動整理於此。")
                )
            } else if !filteredEntries.isEmpty {
                // Offline-first: if we have local data, ALWAYS show the list.
                VStack(spacing: 0) {
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
                    
                    List {
                        ForEach(filteredEntries) { entry in
                            WordRow(
                                word: entry.word,
                                translation: entry.translation,
                                partOfSpeech: entry.partOfSpeech,
                                difficultyTier: entry.difficultyTier,
                                bookTitle: nil,
                                chapterTitle: nil,
                                nextReviewAt: entry.nextReviewAt,
                                syncStatus: nil
                            )
                            .contentShape(Rectangle())
                            .onTapGesture { selectedEntry = entry }
                        }
                        .onDelete(perform: deleteLocalEntries)
                    }
                    .listStyle(.insetGrouped)
                }
            } else if isLoading {
                ProgressView("載入知識庫...")
            } else if let error = errorMessage {
                ContentUnavailableView(
                    "無法連線",
                    systemImage: "wifi.slash",
                    description: Text(error)
                )
            } else {
                ContentUnavailableView(
                    "沒有符合的單字",
                    systemImage: "magnifyingglass",
                    description: Text("試試其他關鍵字")
                )
            }
        }
        .sheet(item: $selectedEntry) { entry in
            WordDetailSheet(entry: entry)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .task {
            guard authManager.isLoggedIn else { return }

            // Auto-sync missing cards from KG on appear
            isLoading = true
            do {
                try await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
                errorMessage = nil
            } catch {
                errorMessage = error.localizedDescription
            }
            isLoading = false
        }
    }

    // MARK: - Computed

    private var filteredEntries: [VocabularyEntry] {
        let sorted = syncedEntries.sorted {
            if $0.isReviewDue != $1.isReviewDue {
                return $0.isReviewDue && !$1.isReviewDue
            }
            let t0 = tierOrder($0.difficultyTier)
            let t1 = tierOrder($1.difficultyTier)
            if t0 != t1 { return t0 < t1 }
            if $0.nextReviewAt != $1.nextReviewAt {
                return $0.nextReviewAt < $1.nextReviewAt
            }
            return $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending
        }

        guard !searchText.isEmpty else { return sorted }
        return sorted.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
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

    // MARK: - Retry Pending Deletes

    private func retryPendingDeletes() async {
        for entry in pendingDeletes {
            do {
                try await kgService.deleteCard(word: entry.word)
                modelContext.delete(entry)
            } catch {
                // 保留，下次再試
            }
        }
        try? modelContext.save()
        await kgService.healthCheck()
    }

    // MARK: - Delete KG Cards (swipe)

    private func deleteLocalEntries(at offsets: IndexSet) {
        let targets = offsets.map { filteredEntries[$0] }
        for entry in targets {
            // Mark as delete so upload_delete can process it later
            entry.actionType = "delete"
            entry.syncStatus = 0
            // Since our @Query explicitly filters out actionType != "delete",
            // this item will instantly disappear from the list.
        }
        try? modelContext.save()
    }
}
