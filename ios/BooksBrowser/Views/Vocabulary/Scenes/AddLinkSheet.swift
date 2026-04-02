import SwiftUI

struct AddLinkSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var vocabSkin

    let sourceEntry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    let onSelect: (VocabularyEntry) -> Void

    @State private var searchText = ""
    @State private var searchError: String?

    private var existingLinkedCardIds: Set<String> {
        Set(sourceEntry.graphLinksByKind.values.flatMap { $0 }.map(\.cardId))
    }

    private var filteredEntries: [VocabularyEntry] {
        let candidates = allEntries.filter { entry in
            entry.id != sourceEntry.id
                && entry.kgCardId != nil
                && !entry.isArchived
                && !(entry.kgCardId.map { existingLinkedCardIds.contains($0) } ?? false)
        }
        guard !searchText.isEmpty else { return [] }
        let query = searchText.lowercased()
        return Array(
            candidates
                .filter { $0.word.lowercased().contains(query) }
                .prefix(20)
        )
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let searchError {
                    AppBanner(
                        message: searchError,
                        systemImage: "exclamationmark.triangle",
                        onRetry: {
                            self.searchError = nil
                        },
                        onDismiss: { self.searchError = nil }
                    )
                }

                searchField
                    .padding(vocabSkin.metrics.cardBlockPadding)

                if searchText.isEmpty {
                    ContentUnavailableView(
                        "搜尋單字".localized,
                        systemImage: "magnifyingglass",
                        description: Text("輸入單字名稱來建立連結".localized)
                    )
                    .frame(maxHeight: .infinity)
                } else if filteredEntries.isEmpty {
                    ContentUnavailableView(
                        "沒有結果".localized,
                        systemImage: "magnifyingglass",
                        description: Text("找不到符合的單字".localized)
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    List(filteredEntries) { entry in
                        Button {
                            selectEntry(entry)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(entry.word)
                                    .font(vocabSkin.typography.rowWord)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                Text(entry.translation)
                                    .font(vocabSkin.typography.caption)
                                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                            }
                        }
                        .listRowBackground(Color.clear)
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .vocabCanvasBackground()
            .navigationTitle("新增連結".localized)
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                }
            }
        }
    }

    private func selectEntry(_ entry: VocabularyEntry) {
        guard entry.kgCardId != nil else {
            searchError = "此單字尚未同步，無法建立連結".localized
            return
        }
        onSelect(entry)
        dismiss()
    }

    private var searchField: some View {
        HStack(spacing: vocabSkin.metrics.cardBlockInnerGap) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(vocabSkin.palette.tertiaryText)
            TextField("搜尋單字…".localized, text: $searchText)
                .platformTextInputConfig()
        }
        .padding(vocabSkin.metrics.cardBlockInnerGap * 1.5)
        .background(vocabSkin.palette.cardBackground, in: RoundedRectangle(cornerRadius: 10))
    }
}
