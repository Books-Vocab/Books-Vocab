import SwiftData
import SwiftUI

struct AddLinkSheet: View {
    @ObserveInjection private var inject
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appSkin) private var appSkin
    @Environment(\.kgService) private var kgService
    @Environment(\.modelContext) private var modelContext

    let sourceEntry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    var onLinked: () -> Void = {}

    @State private var searchText = ""
    @State private var searchError: String?
    @State private var coordinator = AddLinkCoordinator()

    init(
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        initialQuery: String = "",
        initialSearchPhase: DictionarySearchPhase = .idle,
        onLinked: @escaping () -> Void = {}
    ) {
        self.sourceEntry = sourceEntry
        self.allEntries = allEntries
        self.onLinked = onLinked
        _searchText = State(initialValue: initialQuery)
        _coordinator = State(
            initialValue: AddLinkCoordinator(initialSearchPhase: initialSearchPhase)
        )
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
                if let searchError {
                    AppBanner(
                        message: searchError,
                        systemImage: "exclamationmark.triangle",
                        onDismiss: { self.searchError = nil }
                    )
                }
                if coordinator.materializePhase == .failed {
                    AppBanner(
                        message: L10n.string("addLink.error.linkFailed"),
                        systemImage: "exclamationmark.triangle"
                    )
                }

                searchField
                    .padding(appSkin.metrics.cardBlockPadding)

                List {
                    localSection
                    dictionarySection
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
            .vocabCanvasBackground()
            .navigationTitle(L10n.string("新增連結"))
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.string("取消")) { dismiss() }
                }
            }
        }
        .onChange(of: searchText) {
            coordinator.queryDidChange()
        }
        .onChange(of: coordinator.materializePhase) {
            if coordinator.materializePhase == .succeeded {
                onLinked()
                dismiss()
            }
        }
        .onDisappear { coordinator.cancelSearch() }
        .enableInjection()
    }

    private var localSection: some View {
        Section(L10n.string("addLink.localSection")) {
            if searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(L10n.string("輸入單字名稱來建立連結"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
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

    @ViewBuilder
    private var dictionarySection: some View {
        Section(L10n.string("addLink.dictionarySection")) {
            let trimmed = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty {
                Text(L10n.string("addLink.dictionaryPrompt"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
            } else {
                switch coordinator.searchPhase {
                case .idle:
                    Button {
                        coordinator.submitSearch(query: trimmed, using: kgService)
                    } label: {
                        Label(
                            L10n.format("addLink.searchDictionary", trimmed),
                            systemImage: "text.book.closed"
                        )
                    }
                    .lineLimit(1)
                    .truncationMode(.tail)

                case .loading:
                    HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
                        ProgressView()
                        Text(L10n.string("addLink.dictionaryLoading"))
                    }

                case .empty:
                    Text(L10n.string("addLink.dictionaryEmpty"))
                        .foregroundStyle(appSkin.palette.tertiaryText)

                case .failed(let failure):
                    VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
                        Text(failureMessage(failure))
                            .foregroundStyle(appSkin.palette.tertiaryText)
                        Button(L10n.string("重試")) {
                            coordinator.submitSearch(query: trimmed, using: kgService)
                        }
                    }

                case .result(let entry, let cacheStatus):
                    dictionaryResult(entry, cacheStatus: cacheStatus)
                }
            }
        }
    }

    @ViewBuilder
    private func dictionaryResult(_ entry: LexicalEntry, cacheStatus: String) -> some View {
        if let existing = AddLinkCoordinator.existingEntry(
            for: entry.word,
            notebookID: sourceEntry.notebookId,
            excluding: sourceEntry.id,
            allEntries: allEntries
        ) {
            VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
                Button {
                    selectEntry(existing)
                } label: {
                    Label(
                        existing.cardRole == .learning
                            ? L10n.string("addLink.alreadyLearning")
                            : L10n.string("addLink.alreadyDictionary"),
                        systemImage: existing.cardRole == .learning ? "checkmark.circle" : "text.book.closed"
                    )
                }
                if existing.cardRole == .dictionary, !existing.context.isEmpty {
                    Text(existing.context)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                        .lineLimit(3)
                        .truncationMode(.tail)
                }
            }
        } else {
            ForEach(entry.senses) { sense in
                VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
                    if let partOfSpeech = sense.partOfSpeech {
                        Text(partOfSpeech)
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.tertiaryText)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                    Text(sense.definition)
                        .font(appSkin.typography.body)
                        .lineLimit(3)
                        .truncationMode(.tail)
                    ForEach(sense.examples) { example in
                        Button {
                            coordinator.select(senseKey: sense.id, exampleKey: example.id)
                        } label: {
                            HStack(alignment: .top) {
                                Image(systemName: coordinator.selectedExampleKey == example.id
                                      ? "checkmark.circle.fill" : "circle")
                                Text(example.text)
                                    .multilineTextAlignment(.leading)
                                    .lineLimit(3)
                                    .truncationMode(.tail)
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityValue(
                            coordinator.selectedExampleKey == example.id
                                ? L10n.string("a11y.toggle.on")
                                : L10n.string("a11y.toggle.off")
                        )
                    }
                }
                .padding(.vertical, AppSpacing.microGap)
            }

            if coordinator.selectedExampleKey != nil {
                Button {
                    Task {
                        await coordinator.materializeSelectedExample(
                            sourceEntry: sourceEntry,
                            entry: entry,
                            using: kgService,
                            container: modelContext.container
                        )
                    }
                } label: {
                    if coordinator.materializePhase == .running {
                        ProgressView()
                    } else {
                        Text(coordinator.materializePhase == .failed
                             ? L10n.string("重試")
                             : L10n.string("addLink.addSelectedExample"))
                    }
                }
                .disabled(coordinator.materializePhase == .running)
            }
        }

        VStack(alignment: .leading, spacing: AppSpacing.microGap) {
            if cacheStatus == "stale" {
                Label(L10n.string("addLink.staleCache"), systemImage: "clock.arrow.circlepath")
            }
            Text(entry.attributionText)
                .lineLimit(2)
                .truncationMode(.tail)
            if let sourceURL = URL(string: entry.sourceUrl) {
                Link(L10n.string("addLink.openSource"), destination: sourceURL)
            }
            if let licenseURL = URL(string: entry.licenseUrl) {
                Link(entry.licenseName, destination: licenseURL)
                    .lineLimit(1)
                    .truncationMode(.tail)
            } else {
                Text(entry.licenseName)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
        .font(appSkin.typography.caption)
        .foregroundStyle(appSkin.palette.tertiaryText)
    }

    private func failureMessage(_ failure: DictionarySearchFailure) -> String {
        switch failure {
        case .offline: L10n.string("addLink.error.offline")
        case .rateLimited: L10n.string("addLink.error.rateLimited")
        case .timeout: L10n.string("addLink.error.timeout")
        case .malformed: L10n.string("addLink.error.malformed")
        case .unavailable: L10n.string("addLink.error.unavailable")
        }
    }

    private func selectEntry(_ entry: VocabularyEntry) {
        guard entry.kgCardId != nil else {
            searchError = L10n.string("此單字尚未同步，無法建立連結")
            return
        }
        Task {
            await coordinator.linkExisting(
                target: entry,
                sourceEntry: sourceEntry,
                using: kgService
            )
        }
    }

    private var searchField: some View {
        HStack(spacing: appSkin.metrics.cardBlockInnerGap) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(appSkin.palette.tertiaryText)
            TextField(L10n.string("搜尋單字…"), text: $searchText)
                .platformTextInputConfig()
                .submitLabel(.search)
                .onSubmit {
                    coordinator.submitSearch(query: searchText, using: kgService)
                }
        }
        .padding(appSkin.metrics.cardBlockInnerGap * 1.5)
        .background(appSkin.palette.cardBackground, in: AppRoundedRect(roundness: AppRoundness.control))
    }
}
