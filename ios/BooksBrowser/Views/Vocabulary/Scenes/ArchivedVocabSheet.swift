import SwiftUI
import SwiftData

struct ArchivedVocabSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.vocabSkin) private var vocabSkin

    @Query private var allEntries: [VocabularyEntry]
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
                            description: "在知識庫中左滑卡片即可封存。".localized
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
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            }
        }
    }

    private var archivedEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.filteredArchivedEntries(
            in: allEntries,
            searchText: searchText
        )
    }

    private func handleUnarchive(_ entry: VocabularyEntry) {
        Task {
            do {
                try await kgService.archiveCard(word: entry.word, archived: false)
                entry.isArchived = false
                try? modelContext.save()
            } catch {
                print("⚠️ Unarchive failed: \(error.localizedDescription)")
            }
        }
    }
}
