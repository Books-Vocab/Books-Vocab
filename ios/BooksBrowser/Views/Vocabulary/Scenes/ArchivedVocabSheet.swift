import SwiftUI
import SwiftData
import os

struct ArchivedVocabSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.vocabSkin) private var vocabSkin

    @Query(
        filter: #Predicate<VocabularyEntry> { $0.isArchived == true },
        sort: \VocabularyEntry.word
    )
    private var archivedAllEntries: [VocabularyEntry]
    @State private var searchText = ""
    @State private var selectedEntry: VocabularyEntry?

    var body: some View {
        NavigationStack {
            Group {
                if archivedEntries.isEmpty {
                    VStack {
                        Spacer()
                        VocabEmptyStateCard(
                            title: "沒有封存的卡片".localized,
                            systemImage: "archivebox",
                            description: "左滑卡片即可封存。".localized
                        )
                        Spacer()
                    }
                    .padding(vocabSkin.metrics.cardBlockPadding)
                } else {
                    List {
                        ForEach(archivedEntries) { entry in
                            WordRow(viewData: entry.wordRowViewData(
                                showsReviewState: false,
                                showsSourceContext: false,
                                showsDifficultyTier: false,
                                showsArchiveStyle: true
                            ))
                            .contentShape(Rectangle())
                            .onTapGesture { selectedEntry = entry }
                            .swipeActions(edge: .trailing) {
                                Button {
                                    handleUnarchive(entry)
                                } label: {
                                    Label("解除封存".localized, systemImage: "arrow.uturn.backward")
                                }
                                .tint(vocabSkin.palette.accent)
                            }
                            .listRowInsets(EdgeInsets(
                                top: 0, leading: vocabSkin.metrics.listRowHorizontalInset,
                                bottom: 0, trailing: vocabSkin.metrics.listRowHorizontalInset
                            ))
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .animatePhaseChange(archivedEntries.isEmpty)
            .vocabCanvasBackground()
            .navigationTitle("封存".localized)
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $searchText, prompt: "搜尋封存單字".localized)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("關閉".localized) { dismiss() }
                }
            }
            .sheet(item: $selectedEntry) { entry in
                WordDetailSheet(entry: entry)
                    .appSheet(.large)
            }
        }
    }

    private var archivedEntries: [VocabularyEntry] {
        let base = archivedAllEntries.filter { $0.syncStatus == 1 && $0.actionType != "delete" }
        guard !searchText.isEmpty else { return base }
        return base.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    private func handleUnarchive(_ entry: VocabularyEntry) {
        Task {
            do {
                try await kgService.archiveCard(word: entry.word, archived: false, notebookId: entry.notebookId)
                entry.isArchived = false
                modelContext.safeSave()
            } catch {
                AppLog.kg.error("Unarchive failed: \(error.localizedDescription)")
            }
        }
    }
}
