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
    /// 多單字本入口才傳：候選只限來源同一本，sheet 要明講搜尋範圍（#2040）。
    var notebookScopeName: String? = nil
    var onLinked: () -> Void = {}

    @State private var searchText = ""
    @State private var coordinator = AddLinkCoordinator()
    // Made by the hub, which keeps a running creation alive after this sheet closes.
    @State private var creationCoordinator: AddLinkCreationCoordinator
    @State private var creationAttempt = 0
    @State private var didCompleteCreation = false
    @State private var recoveredProviderErrors: Set<UUID> = []
    @FocusState private var isSearchFocused: Bool

    init(
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        creationHub: AddLinkCreationHub = .shared,
        notebookScopeName: String? = nil,
        onLinked: @escaping () -> Void = {}
    ) {
        self.sourceEntry = sourceEntry
        self.allEntries = allEntries
        self.notebookScopeName = notebookScopeName
        self.onLinked = onLinked
        _creationCoordinator = State(initialValue: creationHub.makeCoordinator())
    }

    private func lookupState(_ snapshot: AddLinkSearchSnapshot) -> AddLinkLookupState {
        AddLinkCoordinator.lookupState(
            query: searchText,
            candidateCount: snapshot.candidates.count,
            creationPhase: creationCoordinator.phase,
            creationAttempt: creationAttempt
        )
    }

    private var showsCreationProgress: Bool {
        creationCoordinator.phase == .running
            || creationCoordinator.phase == .failed
            || creationCoordinator.phase == .succeededWithWarnings
    }

    var body: some View {
        // One candidate computation per render; every reader below gets this value.
        let snapshot = AddLinkSearchSnapshot.make(
            query: searchText,
            sourceEntry: sourceEntry,
            allEntries: allEntries
        )
        let lookup = lookupState(snapshot)
        NavigationStack {
            VStack(spacing: 0) {
                Text(lookup.accessibilityValue)
                    .font(.caption2)
                    .foregroundStyle(.clear)
                    .frame(width: 1, height: 1)
                    .accessibilityIdentifier("addLink.lookup.state")
                    .accessibilityValue(lookup.accessibilityValue)

                Text(L10n.format("addLink.sourceWord", sourceEntry.word))
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, appSkin.metrics.cardBlockPadding)
                    .accessibilityIdentifier("addLink.sourceWord")

                if let notebookScopeName {
                    Text(L10n.format("addLink.notebookScope", notebookScopeName))
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                        .lineLimit(2)
                        .truncationMode(.tail)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, appSkin.metrics.cardBlockPadding)
                        .accessibilityIdentifier("addLink.notebookScope")
                }

                if coordinator.actionPhase == .failed, !showsCreationProgress {
                    let actionError = coordinator.actionError ?? .existingLinkFailed
                    AppBanner(
                        message: actionError.message,
                        systemImage: "exclamationmark.triangle",
                        onRetry: coordinator.canRetryLastAction ? { coordinator.retryLastAction() } : nil
                    )
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("addLink.error.reason")
                    .accessibilityValue(actionError.reason)
                }

                if showsCreationProgress {
                    AddLinkCreationProgressView(
                        coordinator: creationCoordinator,
                        onRetry: retryCreation,
                        attempt: creationAttempt,
                        onDone: finishWithWarnings,
                        onBackToSearch: { creationCoordinator.acknowledge() }
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
                        localSection(snapshot)
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
            // Only a full success closes on its own. A warning keeps the sheet
            // open (retry / done) so a partial result is never swallowed.
            guard phase == .succeeded, !didCompleteCreation else { return }
            didCompleteCreation = true
            onLinked()
            dismiss()
        }
        .onDisappear {
            coordinator.cancel()
            // A running creation is deliberately NOT cancelled: the hub owns it,
            // finishes the local projection, and the source card shows it as a
            // pending link meanwhile.
        }
        .enableInjection()
    }

    private func localSection(_ snapshot: AddLinkSearchSnapshot) -> some View {
        Section(L10n.string("addLink.localSection")) {
            if snapshot.isEmptyQuery {
                Text(L10n.string("輸入單字名稱來建立連結"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .accessibilityIdentifier("addLink.local.empty")
            } else {
                ForEach(snapshot.candidates) { entry in
                    let projection = AddLinkCoordinator.dictionaryDetailProjection(
                        for: entry,
                        recoveringProviderError: recoveredProviderErrors.contains(entry.id)
                    )
                    let isLinkingRow = entry.kgCardId != nil
                        && coordinator.linkingTargetCardID == entry.kgCardId
                    VStack(alignment: .leading, spacing: appSkin.metrics.cardBlockInnerGap) {
                        Button { selectEntry(entry, in: snapshot) } label: {
                            HStack(spacing: appSkin.spacing.inlineGap) {
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
                                if isLinkingRow {
                                    Spacer(minLength: AppSpacing.s2)
                                    ProgressView()
                                        .controlSize(.mini)
                                        .accessibilityIdentifier("addLink.row.linking.\(entry.kgCardId ?? "")")
                                }
                            }
                        }
                        // One link at a time: every row is locked while one is in flight.
                        .disabled(coordinator.linkingTargetCardID != nil)
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
                // Create stays reachable next to partial matches (`run` while
                // `running` is listed); otherwise it explains the exact match.
                if let targetState = snapshot.exactTargetState {
                    missingTargetSection(targetState, hasCandidates: !snapshot.candidates.isEmpty)
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
    private func missingTargetSection(
        _ targetState: AddLinkLocalTargetState,
        hasCandidates: Bool
    ) -> some View {
        switch targetState {
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
                .disabled(coordinator.linkingTargetCardID != nil)
                .listRowBackground(Color.clear)
            } else if !hasCandidates {
                Text(L10n.string("沒有結果"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        case .pending, .failed:
            Text(L10n.string("此單字尚未同步，無法建立連結"))
                .foregroundStyle(appSkin.palette.tertiaryText)
        case .archived:
            Text(AddLinkCreationFailure(reason: "target_archived").message)
                .foregroundStyle(appSkin.palette.tertiaryText)
        case .active:
            // The exact match is a candidate row above; only explain when the
            // list could not show it.
            if !hasCandidates {
                Text(L10n.string("addLink.target.linkable"))
                    .foregroundStyle(appSkin.palette.tertiaryText)
            }
        case .linked:
            Text(L10n.string("addLink.target.alreadyLinked"))
                .foregroundStyle(appSkin.palette.tertiaryText)
                .accessibilityIdentifier("addLink.target.linked")
        case .source:
            Text(AddLinkCreationFailure(reason: "target_is_source").message)
                .foregroundStyle(appSkin.palette.tertiaryText)
        }
    }

    private func selectEntry(_ entry: VocabularyEntry, in snapshot: AddLinkSearchSnapshot) {
        guard snapshot.containsCandidate(entry) else { return }
        coordinator.startLinkExisting(
            target: entry,
            sourceEntry: sourceEntry,
            using: kgService
        )
    }

    /// A warning retry re-runs only the unfinished parts (the link exists); a
    /// failure retry starts a new attempt under the key policy.
    private func retryCreation() {
        if creationCoordinator.phase == .succeededWithWarnings {
            creationCoordinator.retryWarnings()
        } else {
            startCreation()
        }
    }

    /// The user accepts a partial result: retire the job and close.
    private func finishWithWarnings() {
        guard !didCompleteCreation else { return }
        didCompleteCreation = true
        creationCoordinator.acknowledge()
        onLinked()
        dismiss()
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
                .focused($isSearchFocused)
                // Opening the sheet is the intent to search: no extra tap.
                .onAppear { isSearchFocused = true }
                .accessibilityIdentifier("addLink.searchField")
        }
        .padding(appSkin.metrics.cardBlockInnerGap * 1.5)
        .background(
            appSkin.palette.cardBackground,
            in: AppRoundedRect(roundness: AppRoundness.control)
        )
    }
}
