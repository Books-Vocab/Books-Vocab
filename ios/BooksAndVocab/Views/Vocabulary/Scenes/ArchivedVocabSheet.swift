import SwiftUI
import SwiftData
import os

struct ArchivedVocabSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.appSkin) private var appSkin

    @Query(
        filter: #Predicate<VocabularyEntry> { $0.isArchived == true },
        sort: \VocabularyEntry.word
    )
    private var archivedAllEntries: [VocabularyEntry]
    @State private var searchText = ""
    @State private var selectedEntry: VocabularyEntry?
    @State private var errorMessage: String?

    var body: some View {
        let archivedEntries = self.archivedEntries
        NavigationStack {
            Group {
                if archivedEntries.isEmpty {
                    VStack {
                        Spacer()
                        VocabEmptyStateCard(
                            title: L10n.string("沒有封存的卡片"),
                            systemImage: "archivebox",
                            // 舊文案是「左滑卡片即可封存。」——那個手勢不存在：單字列在
                            // KGVocabPresenter 是 LazyVStack 而非 List，掛不了 swipeActions。
                            description: L10n.string("開啟單字詳情，點右上角的封存鈕即可收進這裡。")
                        )
                        Spacer()
                    }
                    .padding(appSkin.metrics.cardBlockPadding)
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
                                .tint(appSkin.palette.accent)
                            }
                            .listRowInsets(EdgeInsets(
                                top: 0, leading: appSkin.metrics.listRowHorizontalInset,
                                bottom: 0, trailing: appSkin.metrics.listRowHorizontalInset
                            ))
                        }
                    }
                    .listStyle(.plain)
                }
            }
            .animatePhaseChange(archivedEntries.isEmpty)
            .vocabCanvasBackground()
            .navigationTitle("封存".localized)
            .inlineNavigationBarTitle()
            .searchable(text: $searchText, prompt: "搜尋封存單字".localized)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("關閉".localized) { dismiss() }
                }
            }
            .toastSheet(item: $selectedEntry) { entry in
                WordDetailSheet(entry: entry)
                    .appSheet(.large)
            }
            .overlay(alignment: .top) {
                if let errorMessage {
                    AppBanner(
                        message: errorMessage,
                        systemImage: "exclamationmark.triangle",
                        onDismiss: { self.errorMessage = nil }
                    )
                }
            }
        }
        .enableInjection()
    }

    private var archivedEntries: [VocabularyEntry] {
        // archivedAllEntries is already Query-filtered to isArchived == true, so
        // this matches shouldAppearInArchiveList (isSynced && !delete && isArchived).
        let base = archivedAllEntries.filter(\.shouldAppearInArchiveList)
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
                if modelContext.safeSaveWithToast(toastCoordinator) {
                    toastCoordinator.success("已取消封存".localized)
                }
            } catch {
                AppLog.kg.error("Unarchive failed: \(error.localizedDescription)")
                await MainActor.run {
                    errorMessage = L10n.format("解除封存失敗：%@", error.localizedDescription)
                }
            }
        }
    }
}
