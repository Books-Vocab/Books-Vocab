import SwiftUI
import SwiftData

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
    @State private var coordinator = AddLinkCoordinator()
    @State private var creationCoordinator = AddLinkCreationCoordinator()
    @State private var creationAttempt = 0
    @State private var recoveredProviderErrors: Set<UUID> = []

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

    private var lookupState: AddLinkLookupState {
        AddLinkCoordinator.lookupState(
            query: searchText,
            candidateCount: filteredEntries.count,
            creationPhase: creationCoordinator.phase,
            creationAttempt: creationAttempt
        )
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Text(lookupState.accessibilityValue)
                    .font(.caption2)
                    .foregroundStyle(.clear)
                    .frame(width: 1, height: 1)
                    .accessibilityIdentifier("addLink.lookup.state")
                    .accessibilityValue(lookupState.accessibilityValue)

                if coordinator.actionPhase == .failed {
                    AppBanner(
                        message: L10n.string("addLink.error.linkFailed"),
                        systemImage: "exclamationmark.triangle"
                    )
                }

                if creationCoordinator.phase == .running || creationCoordinator.phase == .failed {
                    AddLinkCreationProgressView(
                        coordinator: creationCoordinator,
                        onRetry: startCreation,
                        attempt: creationAttempt
                    )
                        .padding(.horizontal, appSkin.metrics.cardBlockPadding)
                        .frame(maxHeight: .infinity, alignment: .top)
                } else {
                    if creationCoordinator.phase == .blocked,
                       let message = creationCoordinator.message {
                        AppBanner(message: message, systemImage: "exclamationmark.triangle")
                    }

                    searchField
                        .padding(appSkin.metrics.cardBlockPadding)

                    List {
                        localSection
                    }
                    .listStyle(.insetGrouped)
                    .scrollContentBackground(.hidden)
                }
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
        .onChange(of: creationCoordinator.phase) { _, phase in
            guard phase == .succeeded || phase == .succeededWithWarnings else { return }
            onLinked()
            dismiss()
        }
        .onDisappear {
            coordinator.cancel()
            // Cancelling the client poll does not cancel the durable operation.
            creationCoordinator.cancel()
        }
        .enableInjection()
    }

    private var localSection: some View {
        Section(L10n.string("addLink.localSection")) {
            if searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(L10n.string("輸入單字名稱來建立連結"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .accessibilityIdentifier("addLink.local.empty")
            } else if filteredEntries.isEmpty {
                missingTargetSection
            } else {
                ForEach(filteredEntries) { entry in
                    let projection = AddLinkCoordinator.dictionaryDetailProjection(
                        for: entry,
                        recoveringProviderError: recoveredProviderErrors.contains(entry.id)
                    )
                    VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
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
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        .accessibilityIdentifier(AddLinkCoordinator.detailIdentifier(for: entry))
                        .accessibilityValue(
                            AddLinkCoordinator.lookupEvidence(
                                for: entry,
                                recoveringProviderError: recoveredProviderErrors.contains(entry.id)
                            )
                        )

                        dictionaryDetail(projection, for: entry)
                    }
                    .listRowBackground(Color.clear)
                }
            }
        }
    }

    @ViewBuilder
    private func dictionaryDetail(
        _ projection: AddLinkDetailProjection,
        for entry: VocabularyEntry
    ) -> some View {
        let detailID = AddLinkCoordinator.detailIdentifier(for: entry)
        Color.clear
            .frame(width: 1, height: 1)
            .accessibilityElement()
            .accessibilityIdentifier(AddLinkCoordinator.detailStateIdentifier(for: entry))
            .accessibilityValue(
                "\(projection.state.accessibilityValue)|senses=\(projection.senses.count)"
            )

        switch projection.state {
        case .providerDecodeError:
            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                Text(L10n.string("sync.failure.reason.decoding"))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("\(detailID).provider.error")
                Button(L10n.string("重試")) {
                    recoveredProviderErrors.insert(entry.id)
                }
                .buttonStyle(.appCompactAction(.neutral))
                .accessibilityIdentifier(AddLinkCoordinator.detailRetryIdentifier(for: entry))
            }
        case .ready, .missingExample, .recovered:
            ForEach(Array(projection.senses.enumerated()), id: \.offset) { senseIndex, sense in
                VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                    if let partOfSpeech = sense.partOfSpeech {
                        Text(L10n.string("reviewCardLayout.field.partOfSpeech") + ": " + partOfSpeech)
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.tertiaryText)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier(
                                "\(AddLinkCoordinator.detailSenseIdentifier(for: entry, index: senseIndex)).partOfSpeech"
                            )
                    }
                    Text(sense.definition)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier(
                            AddLinkCoordinator.detailSenseIdentifier(for: entry, index: senseIndex)
                        )
                    if let translation = sense.translation,
                       translation != projection.translation {
                        Text(translation)
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.tertiaryText)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier(
                                "\(AddLinkCoordinator.detailSenseIdentifier(for: entry, index: senseIndex)).translation"
                            )
                    }
                    if sense.examples.isEmpty {
                        Color.clear
                            .frame(width: 1, height: 1)
                            .accessibilityElement()
                            .accessibilityIdentifier(
                                AddLinkCoordinator.detailMissingExampleIdentifier(
                                    for: entry,
                                    senseIndex: senseIndex
                                )
                            )
                            .accessibilityValue("missing")
                    } else {
                        ForEach(Array(sense.examples.enumerated()), id: \.offset) { exampleIndex, example in
                            Text(L10n.string("reviewCardLayout.field.example") + ": " + example)
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.tertiaryText)
                                .fixedSize(horizontal: false, vertical: true)
                                .accessibilityIdentifier(
                                    AddLinkCoordinator.detailExampleIdentifier(
                                        for: entry,
                                        senseIndex: senseIndex,
                                        exampleIndex: exampleIndex
                                    )
                                )
                        }
                    }
                }
                .accessibilityElement(children: .contain)
            }

            if !projection.forms.isEmpty {
                Text(L10n.string("變化形") + ": " + projection.forms.joined(separator: ", "))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier(AddLinkCoordinator.detailFormsIdentifier(for: entry))
            }

            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                Text(L10n.string("來源") + ": " + projection.provenance.source)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("\(detailID).provenance.source")
                if let chapter = projection.provenance.chapter {
                    Text(chapter)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("\(detailID).provenance.chapter")
                }
                Text(projection.provenance.context)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("\(detailID).provenance.context")
            }
            .font(appSkin.typography.caption)
            .foregroundStyle(appSkin.palette.tertiaryText)
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier(AddLinkCoordinator.detailProvenanceIdentifier(for: entry))
        }
    }

    @ViewBuilder
    private var missingTargetSection: some View {
        switch AddLinkCreationCoordinator.localTargetState(
            query: searchText,
            sourceEntry: sourceEntry,
            allEntries: allEntries
        ) {
        case .missing:
            if kgService is any AddLinkOperationServing {
                Button(action: startCreation) {
                    HStack(spacing: appSkin.spacing.inlineGap) {
                        Image(systemName: "plus.circle.fill")
                            .foregroundStyle(appSkin.palette.accent)
                        VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                            Text(L10n.string("建立"))
                                .foregroundStyle(appSkin.palette.primaryText)
                            Text(searchText.trimmingCharacters(in: .whitespacesAndNewlines))
                                .font(appSkin.typography.caption)
                                .foregroundStyle(appSkin.palette.secondaryText)
                                .lineLimit(1)
                        }
                        Spacer(minLength: 0)
                    }
                }
                .accessibilityIdentifier("addLink.create")
                .listRowBackground(Color.clear)
            } else {
                Text(L10n.string("沒有結果"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        case .pending, .failed:
            Text(L10n.string("此單字尚未同步，無法建立連結"))
                .foregroundStyle(appSkin.palette.tertiaryText)
        case .archived:
            Text(L10n.string("封存"))
                .foregroundStyle(appSkin.palette.tertiaryText)
        case .active:
            Text(L10n.string("已建立"))
                .foregroundStyle(appSkin.palette.tertiaryText)
        case .source:
            Text(L10n.string("新增連結失敗"))
                .foregroundStyle(appSkin.palette.tertiaryText)
        }
    }

    private func selectEntry(_ entry: VocabularyEntry) {
        guard filteredEntries.contains(where: { $0.id == entry.id }) else { return }
        coordinator.startLinkExisting(
            target: entry,
            sourceEntry: sourceEntry,
            using: kgService
        )
    }

    private func startCreation() {
        guard let operationService = kgService as? any AddLinkOperationServing else { return }
        creationAttempt += 1
        creationCoordinator.start(
            word: searchText,
            sourceEntry: sourceEntry,
            allEntries: allEntries,
            operationService: operationService,
            syncService: kgService,
            container: modelContext.container
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
