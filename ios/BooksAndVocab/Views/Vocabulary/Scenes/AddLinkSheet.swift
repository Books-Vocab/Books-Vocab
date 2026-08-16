import SwiftUI

struct AddLinkSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appSkin) private var appSkin
    @Environment(\.kgService) private var kgService

    let sourceEntry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    var onLinked: () -> Void = {}

    @State private var searchText = ""
    @State private var coordinator = AddLinkCoordinator()

    init(
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        onLinked: @escaping () -> Void = {}
    ) {
        self.sourceEntry = sourceEntry
        self.allEntries = allEntries
        self.onLinked = onLinked
    }

    private var filteredEntries: [VocabularyEntry] {
        AddLinkCoordinator.localCandidates(
            query: searchText,
            sourceEntry: sourceEntry,
            allEntries: allEntries
        )
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if coordinator.actionPhase == .failed {
                    AppBanner(
                        message: L10n.string("addLink.error.linkFailed"),
                        systemImage: "exclamationmark.triangle"
                    )
                }

                searchField
                    .padding(appSkin.metrics.cardBlockPadding)

                List {
                    localSection
                }
                .listStyle(.insetGrouped)
                .scrollContentBackground(.hidden)
            }
            .vocabCanvasBackground()
            .navigationTitle(L10n.string("新增連結"))
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.string("取消")) { dismiss() }
                        .accessibilityIdentifier("addLink.cancel")
                }
            }
        }
        .onChange(of: coordinator.actionPhase) { _, phase in
            if phase == .succeeded {
                onLinked()
                dismiss()
            }
        }
        .onDisappear { coordinator.cancel() }
        .enableInjection()
    }

    private var localSection: some View {
        Section(L10n.string("addLink.localSection")) {
            if searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(L10n.string("輸入單字名稱來建立連結"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .accessibilityIdentifier("addLink.local.empty")
            } else if filteredEntries.isEmpty {
                Text(L10n.string("沒有結果"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
            } else {
                ForEach(filteredEntries) { entry in
                    Button { selectEntry(entry) } label: {
                        VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                            Text(entry.word)
                                .font(appSkin.typography.rowWord)
                                .foregroundStyle(appSkin.palette.primaryText)
                                .lineLimit(1)
                                .truncationMode(.tail)
                            Text(entry.translation)
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.tertiaryText)
                                .lineLimit(2)
                                .truncationMode(.tail)
                        }
                    }
                    .listRowBackground(Color.clear)
                }
            }
        }
    }

    private func selectEntry(_ entry: VocabularyEntry) {
        coordinator.startLinkExisting(
            target: entry,
            sourceEntry: sourceEntry,
            using: kgService
        )
    }

    private var searchField: some View {
        HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(appSkin.palette.tertiaryText)
            TextField(L10n.string("搜尋單字…"), text: $searchText)
                .platformTextInputConfig()
                .submitLabel(.done)
                .accessibilityIdentifier("addLink.searchField")
        }
        .padding(appSkin.metrics.cardBlockInnerGap * 1.5)
        .background(
            appSkin.palette.cardBackground,
            in: AppRoundedRect(roundness: AppRoundness.control)
        )
    }
}
