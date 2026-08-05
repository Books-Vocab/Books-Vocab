import SwiftUI

struct AddLinkSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appSkin) private var appSkin

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
                && entry.notebookId == sourceEntry.notebookId  // notebook isolation: backend rejects cross-notebook links (404)
                && entry.kgCardId != nil
                && !entry.isArchived
                && !(entry.kgCardId.map { existingLinkedCardIds.contains($0) } ?? false)
        }
        guard !searchText.isEmpty else { return [] }
        let query = searchText.lowercased()
        return Array(
            candidates
                .filter {
                    $0.word.lowercased().contains(query)
                        || $0.translation.lowercased().contains(query)
                }
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
                    .padding(appSkin.metrics.cardBlockPadding)

                if searchText.isEmpty {
                    AppEmptyStateContent(
                        title: "搜尋單字",
                        systemImage: "magnifyingglass",
                        description: "輸入單字名稱來建立連結"
                    )
                    .frame(maxHeight: .infinity)
                } else if filteredEntries.isEmpty {
                    AppEmptyStateContent(
                        title: "沒有結果",
                        systemImage: "magnifyingglass",
                        description: "找不到符合的單字"
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    List(filteredEntries) { entry in
                        Button {
                            selectEntry(entry)
                        } label: {
                            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                                Text(entry.word)
                                    .font(appSkin.typography.rowWord)
                                    .foregroundStyle(appSkin.palette.primaryText)
                                Text(entry.translation)
                                    .font(appSkin.typography.caption)
                                    .foregroundStyle(appSkin.palette.tertiaryText)
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
        .enableInjection()
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
        HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(appSkin.palette.tertiaryText)
            TextField("搜尋單字…".localized, text: $searchText)
                .platformTextInputConfig()
        }
        .padding(appSkin.metrics.cardBlockInnerGap * 1.5)
        .background(appSkin.palette.cardBackground, in: AppRoundedRect(roundness: AppRoundness.control))
    }
}
