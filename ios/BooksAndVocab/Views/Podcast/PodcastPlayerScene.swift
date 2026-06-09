#if os(iOS)
import SwiftUI
import SwiftData

struct PodcastPlayerScene: View {
    @ObserveInjection private var inject
    let episodeId: String

    @Environment(\.appSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager
#if DEBUG
    @Environment(\.podcastPlayerCatalogPreview) private var catalogPreview
#endif

    @Query private var allVocabulary: [VocabularyEntry]
    @Query(filter: #Predicate<Notebook> { !$0.isSoftDeleted })
    private var liveNotebooks: [Notebook]

    @State private var viewModel: PodcastPlayerViewModel?
    @State private var translationHandler = ReaderTranslationHandler()
    @State private var autoPausedByTranslation: Bool = false
    @State private var showSettingsPopover: Bool = false
    @State private var showNotebookPicker: Bool = false
    @AppStorage("podcast.autoPauseOnLookup") private var autoPauseOnLookup: Bool = true
    @AppStorage("podcast.subtitleSize") private var subtitleSizeRaw: String = PodcastSubtitleSize.large.rawValue
    @State private var progressPersistence = PodcastProgressPersistenceController()
    @State private var monetizationGate = MonetizationGateState()
    @State private var loadTask: Task<Void, Never>?
    @State private var loadedEpisodeId: String?
    @State private var progressBootstrapCompleted = false
    @State private var overrideEpisodeId: String?

    private var accessState: PodcastPlayerAccessState {
        PodcastPlayerAccessState.resolve(
            hasProAccess: subscriptionManager.hasProAccess,
            hasToken: authManager.token != nil,
            episodeNumber: loadedEpisode?.episodeNumber,
            previewAvailable: loadedEpisode?.previewAvailable ?? false
        )
    }

    private var subtitleSize: PodcastSubtitleSize {
        PodcastSubtitleSize(rawValue: subtitleSizeRaw) ?? .large
    }

    private var subtitleSizeBinding: Binding<PodcastSubtitleSize> {
        Binding(
            get: { PodcastSubtitleSize(rawValue: subtitleSizeRaw) ?? .large },
            set: { subtitleSizeRaw = $0.rawValue }
        )
    }

    private var activeEpisodeId: String { overrideEpisodeId ?? episodeId }

    private var loadedEpisode: PodcastEpisode? {
        PodcastPlayerSupport.fetchEpisode(remoteId: activeEpisodeId, in: modelContext)
    }

    private var loadedSeries: PodcastSeries? {
        loadedEpisode?.series
    }

    private var bootstrapPhase: PodcastPlayerBootstrapPhase {
        PodcastPlayerBootstrapPhase.phase(
            hasViewModel: viewModel != nil,
            loadAttempted: loadedEpisodeId == activeEpisodeId,
            hasEpisode: loadedEpisode != nil,
            hasSeries: loadedSeries != nil
        )
    }

    private var vocabularyContext: PodcastVocabularyContext? {
        PodcastPlayerSupport.resolveVocabularyContext(
            episodeId: activeEpisodeId,
            modelContext: modelContext,
            // 系列綁定即真相：選詞 / cache 認綁定本，不再隨全域 active 漂移。
            rawNotebookId: loadedSeries?.resolvedNotebookId ?? ActiveNotebookStore.shared.activeNotebookId,
            toastCoordinator: toastCoordinator,
            vocabulary: allVocabulary
        )
    }

    /// 系列綁定 seed：未綁定時以最近使用的真實單字本固化（gate：seed 須為已 settle 的
    /// 真實 notebook，擋未同步 sentinel）。固化後底線 / 查詢 scope 認綁定本。
    private func seedSeriesBindingIfNeeded() {
        guard let series = loadedSeries, series.preferredNotebookId == nil else { return }
        let seed = ActiveNotebookStore.shared.activeNotebookId
        guard PodcastSeries.canSeedBinding(
            seed: seed,
            liveNotebookIds: Set(liveNotebooks.map(\.remoteId))
        ) else { return }
        series.ensureBoundNotebook(seed: seed)
        _ = modelContext.safeSave()
    }

    var body: some View {
        let _ = translationHandler.lookedUpWords.count
        return fullBody
            .monetizationGateSheets($monetizationGate)
            .enableInjection()
    }

    @ViewBuilder
    private var fullBody: some View {
        if loadedEpisode != nil && !accessState.playableForTier {
            PodcastPlayerLockedGateView(
                isGuest: accessState.gateDestination == .login,
                action: { presentUpgradeOrLogin() }
            )
        } else {
            playerCore
        }
    }

    @MainActor
    private func presentUpgradeOrLogin() {
        if accessState.gateDestination == .login {
            monetizationGate.presentLogin()
        } else {
            subscriptionManager.activePaywallSource = .podcast
            monetizationGate.presentPaywall()
        }
    }

    @ViewBuilder
    private var playerCore: some View {
        Group {
            if let vm = viewModel {
                playerContent(vm)
                    .background(
                        PodcastProgressTicker(viewModel: vm) { newTime in
                            saveProgressIfNeeded(time: newTime)
                        }
                    )
                    .onChange(of: vm.state) { _, newState in
                        if newState == .ready, !progressBootstrapCompleted {
                            progressBootstrapCompleted = true
                            return
                        }
                        if newState == .paused || newState == .ready {
                            saveProgress()
                        }
                    }
                    .sensoryFeedback(.success, trigger: vm.sleepTimerFiredTick)
                    .onChange(of: vm.sleepTimerFiredTick) { oldTick, newTick in
                        guard newTick != oldTick else { return }
                        toastCoordinator.info(L10n.string("podcast.sleepTimer.fired.toast"))
                    }
                    .onChange(of: vm.episodeFinishedTick) { oldTick, newTick in
                        guard newTick != oldTick else { return }
                        advanceToNextEpisode()
                    }
            } else {
                switch bootstrapPhase {
                case .loading, .ready:
                    podcastStateCard(
                        title: L10n.string("載入中…"),
                        systemImage: "waveform"
                    ) {
                        ProgressView()
                            .controlSize(.large)
                    }
                case .missingEpisode:
                    missingEpisodeView
                }
            }
        }
        .navigationBarTitleDisplayMode(.inline)
#if !targetEnvironment(macCatalyst)
        .toolbar(.hidden, for: .tabBar)
#endif
        .toolbar {
            if loadedSeries != nil {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showNotebookPicker = true
                    } label: {
                        Image(systemName: "books.vertical")
                    }
                    .accessibilityLabel(L10n.string("選擇單字本"))
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                PodcastPlayerSettingsButton(action: { showSettingsPopover = true })
            }
        }
        .sheet(isPresented: $showNotebookPicker) {
            if let series = loadedSeries {
                PodcastNotebookPicker(series: series)
            }
        }
        .sheet(isPresented: $showSettingsPopover) {
            NavigationStack {
                PodcastSettingsPopover(
                    subtitleSize: subtitleSizeBinding,
                    autoPauseOnLookup: Binding(
                        get: { autoPauseOnLookup },
                        set: { autoPauseOnLookup = $0 }
                    ),
                    sleepTimerMode: Binding(
                        get: { viewModel?.sleepTimerMode ?? .off },
                        set: { viewModel?.setSleepTimer($0) }
                    ),
                    sleepDeadline: viewModel?.sleepDeadline
                )
                .navigationTitle(L10n.string("podcast.player.subtitleSettings"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(L10n.string("完成")) { showSettingsPopover = false }
                    }
                }
            }
            .presentationDetents([.medium])
            .presentationDragIndicator(.visible)
        }
        .task(id: activeEpisodeId) {
            guard loadedEpisodeId != activeEpisodeId else { return }
            if let oldVm = viewModel, let oldId = loadedEpisodeId {
                saveProgress(vm: oldVm, episodeRemoteId: oldId, reason: .episodeSwitch)
            }
            loadTask?.cancel()
            loadTask = nil
            viewModel?.stop()
            viewModel = nil
            loadedEpisodeId = activeEpisodeId
            progressBootstrapCompleted = false
            progressPersistence.reset()
#if DEBUG
            if let preview = catalogPreview {
                loadCatalogPreview(preview)
                return
            }
#endif
            loadEpisode()
        }
        .onChange(of: allVocabulary.count) { _, _ in
            translationHandler.loadLookedUpWords(from: allVocabulary, notebookId: loadedSeries?.resolvedNotebookId)
        }
        .onAppear {
            translationHandler.loadLookedUpWords(from: allVocabulary, notebookId: loadedSeries?.resolvedNotebookId)
        }
        .onChange(of: loadedSeries?.remoteId) { _, _ in
            seedSeriesBindingIfNeeded()
            translationHandler.loadLookedUpWords(from: allVocabulary, notebookId: loadedSeries?.resolvedNotebookId)
        }
        .onChange(of: liveNotebooks.map(\.remoteId)) { _, _ in
            seedSeriesBindingIfNeeded()
        }
        .onDisappear {
            let pending = pendingProgressOnDisappear()
            loadTask?.cancel()
            loadTask = nil
            translationHandler.cancelCurrentTranslationTask()
            viewModel?.shutdown()
            viewModel = nil
            loadedEpisodeId = nil
            progressBootstrapCompleted = false
            if let pending {
                Task { @MainActor in
                    progressPersistence.saveSnapshot(
                        currentTime: pending.currentTime,
                        duration: pending.duration,
                        isCompleted: pending.isCompleted,
                        episodeRemoteId: pending.episodeRemoteId,
                        modelContext: modelContext,
                        kgService: kgService,
                        reason: .pause
                    )
                }
            }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { saveProgress() }
        }
    }

    private var missingEpisodeView: some View {
        podcastStateCard(
            title: L10n.string("podcast.player.missingEpisode.title"),
            systemImage: "waveform.badge.exclamationmark",
            description: L10n.string("podcast.player.missingEpisode.description")
        ) {
            Button(L10n.string("重試")) { reloadEpisode() }
                .buttonStyle(.appCompactAction(.primary))
        }
    }

    @ViewBuilder
    private func playerContent(_ vm: PodcastPlayerViewModel) -> some View {
        switch vm.state {
        case .idle, .loading:
            podcastStateCard(
                title: L10n.string("載入音訊…"),
                systemImage: "waveform"
            ) {
                ProgressView()
                    .controlSize(.large)
            }

        case .error(let msg):
            podcastStateCard(
                title: L10n.string("音訊載入失敗"),
                systemImage: "xmark.octagon",
                description: msg
            ) {
                Button(L10n.string("重試")) { reloadEpisode() }
                    .buttonStyle(.appCompactAction(.primary))
            }

        case .ready, .playing, .paused:
            VStack(spacing: 0) {
                PodcastSubtitleView(
                    viewModel: vm,
                    subtitleSize: subtitleSize,
                    initialScrollPositionResolved: vm.initialPositionResolved,
                    lookedUpWords: Set(translationHandler.lookedUpWords),
                    onRetrySubtitle: { retrySubtitle() }
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                if accessState.isPreviewPlayback {
                    PodcastPlayerPreviewBanner(action: { presentUpgradeOrLogin() })
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        .padding(.bottom, skin.spacing.inlineGap)
                }

                PodcastControlsView(viewModel: vm)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                    .padding(.bottom, PodcastPlayerMetrics.controlsBottomPadding)
            }
            .background(theme.palette.pageBackground)
            .overlay(alignment: .bottom) {
                if let selection = translationHandler.wordSelection {
                    let placement = ReaderOverlayPanelPlacement(layoutMode: LayoutMode(horizontalSizeClass: sizeClass))
                    TranslationPanel(
                        word: selection.word,
                        result: translationHandler.translationResult,
                        isLoading: translationHandler.isTranslating,
                        isSaved: translationHandler.isSaved,
                        isLoggedIn: translationHandler.authManager.isLoggedIn,
                        isExpanded: translationHandler.isExpanded,
                        explanation: translationHandler.explanationText,
                        isLoadingExplanation: translationHandler.isLoadingExplanation,
                        statusMessage: translationHandler.statusMessage,
                        isExplanationOnly: translationHandler.isExplanationOnly,
                        translationErrorMessage: translationHandler.translationErrorMessage,
                        explanationErrorMessage: translationHandler.explanationErrorMessage,
                        onExpand: { translationHandler.handleExpand() },
                        onDelete: {
                            if let ctx = vocabularyContext {
                                translationHandler.deleteFromVocabulary(selection.word, context: ctx)
                            }
                            vm.dismissWordSelection()
                        },
                        onShowDetail: nil,
                        onDismiss: {
                            translationHandler.dismiss()
                            vm.dismissWordSelection()
                        },
                        onRetryTranslation: (translationHandler.translationErrorMessage != nil
                            && translationHandler.lastLookup != nil)
                            ? { translationHandler.retryLastLookup(vocabularyContext: vocabularyContext) }
                            : nil,
                        onRetryExplanation: (translationHandler.explanationErrorMessage != nil
                            && translationHandler.lastLookup != nil)
                            ? { translationHandler.retryLastLookup(vocabularyContext: vocabularyContext) }
                            : nil,
                        isPanelLarge: translationHandler.isPanelLarge,
                        onToggleHeight: { translationHandler.togglePanelHeight() }
                    )
                    .frame(maxWidth: placement.maxWidth)
                    .frame(maxWidth: .infinity, alignment: placement.alignment)
                    .padding(.horizontal, placement.horizontalInset)
                    .padding(.bottom, placement.bottomInset)
                    .transition(.readerPanelReveal)
                }
            }
            .animation(AppMotion.panelState, value: translationHandler.wordSelection)
            .onChange(of: vm.wordTapTick) { _, _ in
                performWordTap()
            }
            .onChange(of: vm.phraseTapTick) { _, _ in
                performPhraseTap()
            }
            .onChange(of: vm.explainTapTick) { _, _ in
                performExplainTap()
            }
            .onChange(of: translationHandler.wordSelection?.word) { old, new in
                handlePanelVisibilityChange(from: old, to: new, vm: vm)
            }
        }
    }

    private func podcastStateCard<Accessory: View>(
        title: String,
        systemImage: String,
        description: String? = nil,
        @ViewBuilder accessory: () -> Accessory
    ) -> some View {
        AppStateMessageCard(
            title: title,
            systemImage: systemImage,
            description: description,
            style: .vocab(skin),
            accessory: accessory
        )
        .frame(maxWidth: 420)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(AppSpacing.s6)
        .background(theme.palette.pageBackground)
    }

    private func handlePanelVisibilityChange(
        from old: String?,
        to new: String?,
        vm: PodcastPlayerViewModel
    ) {
        switch PodcastTranslationPausePolicy.action(
            autoPauseEnabled: autoPauseOnLookup,
            wasPanelVisible: old != nil,
            isPanelVisible: new != nil,
            playerState: vm.state,
            autoPausedByTranslation: autoPausedByTranslation
        ) {
        case .none:
            return
        case .pauseAndMarkAutoPaused:
            vm.pause()
            autoPausedByTranslation = true
        case .resumeAndClearAutoPaused:
            autoPausedByTranslation = false
            vm.play()
        case .clearAutoPaused:
            autoPausedByTranslation = false
        }
    }

    private func performWordTap() {
        guard let vm = viewModel,
              let selection = vm.activeWordSelection,
              let ctx = vocabularyContext else { return }
        translationHandler.handleWordSelected(
            word: selection.word,
            context: selection.context,
            vocabularyContext: ctx
        )
    }

    private func performPhraseTap() {
        guard let vm = viewModel,
              let selection = vm.activePhraseSelection else { return }
        translationHandler.handlePhraseSelected(
            phrase: selection.phrase,
            context: selection.context,
            vocabularyContext: vocabularyContext
        )
    }

    private func performExplainTap() {
        guard let vm = viewModel,
              let selection = vm.activeExplainSelection else { return }
        translationHandler.handleExplainSelected(
            text: selection.text,
            context: selection.context
        )
    }

    private func reloadEpisode() {
        loadTask?.cancel()
        loadTask = nil
        viewModel?.stop()
        viewModel = nil
        progressBootstrapCompleted = false
        progressPersistence.reset()
        loadEpisode()
    }

    @MainActor
    private func advanceToNextEpisode() {
        guard let current = loadedEpisode, let series = loadedSeries else { return }
        guard let next = PodcastQueue.nextPlayable(
            in: series.episodes, after: current, tier: accessState.tier
        ) else { return }
        overrideEpisodeId = next.remoteId
    }

#if DEBUG
    private func loadCatalogPreview(_ preview: PodcastPlayerCatalogPreview) {
        guard let series = loadedSeries else { return }
        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        vm.catalogReadyPreview(
            duration: preview.durationSec,
            currentTime: preview.currentSec,
            subtitleSRT: preview.subtitleSRT
        )
        viewModel = vm
    }
#endif

    private func loadEpisode() {
        guard let episode = loadedEpisode,
              let series = loadedSeries else { return }
        guard accessState.playableForTier else { return }

        loadTask?.cancel()
        loadTask = nil

        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        viewModel = vm
        let initialProgressTime = initialProgressTime(for: activeEpisodeId)

        loadTask = Task { [weak vm] in
            guard let vm else { return }
            guard let plan = PodcastPlayerLoadPlan.make(episode: episode) else {
                await MainActor.run { vm.reportError(L10n.string("無音訊 URL")) }
                return
            }

            await MainActor.run { vm.setLoading() }
            if Task.isCancelled { return }

            if case .remote = plan.subtitleSource {
                await MainActor.run { vm.setSubtitleLoading() }
            }
            let resolvedSubtitle = await PodcastPlayerLoader.resolveSubtitle(
                from: plan.subtitleSource,
                kgService: kgService
            )
            if Task.isCancelled { return }

            let audioHeaders: [String: String]
            do {
                audioHeaders = try await PodcastPlayerLoader.resolveAudioHeaders(
                    for: plan,
                    kgService: kgService
                )
            } catch is CancellationError {
                return
            } catch {
                await MainActor.run {
                    vm.reportError(L10n.format("無法取得認證 token：%@", error.localizedDescription))
                }
                return
            }
            if Task.isCancelled { return }

            await MainActor.run {
                guard !Task.isCancelled else { return }
                switch resolvedSubtitle {
                case .content:
                    break
                case .unavailable:
                    vm.markSubtitleUnavailable()
                case .failed:
                    vm.markSubtitleFailed()
                }
                vm.loadEpisode(
                    audioURL: plan.audioURL,
                    subtitleContent: {
                        if case .content(let subtitleContent) = resolvedSubtitle {
                            return subtitleContent
                        }
                        return nil
                    }(),
                    title: plan.title,
                    audioHTTPHeaders: audioHeaders,
                    prefetchedDurationSec: plan.durationSec,
                    initialProgressTime: initialProgressTime
                )
            }
        }
    }

    @MainActor
    private func retrySubtitle() {
        guard let vm = viewModel,
              let episode = loadedEpisode,
              let subtitleURLStr = episode.subtitleURL else { return }
        vm.setSubtitleLoading()
        Task { [weak vm] in
            guard let vm else { return }
            let content = await PodcastPlayerLoader.fetchSubtitle(
                urlString: subtitleURLStr, kgService: kgService
            )
            await MainActor.run {
                if let content {
                    vm.applySubtitle(content: content)
                } else {
                    vm.markSubtitleFailed()
                }
            }
        }
    }

    @MainActor
    private func initialProgressTime(for episodeRemoteId: String) -> TimeInterval? {
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)]
        )
        if let progress = try? modelContext.fetch(descriptor).first,
           progress.lastPlayedTime > 0,
           !progress.completed {
            return progress.lastPlayedTime
        }
        return nil
    }

    private func saveProgressIfNeeded(time: TimeInterval) {
        guard let vm = viewModel else { return }
        guard loadedEpisodeId == activeEpisodeId else { return }
        progressPersistence.saveIfNeeded(
            time: time,
            viewModel: vm,
            episodeRemoteId: activeEpisodeId,
            modelContext: modelContext,
            kgService: kgService
        )
    }

    private func saveProgress(reason: PodcastProgressPushState.Reason = .pause) {
        guard let vm = viewModel else { return }
        guard loadedEpisodeId == activeEpisodeId else { return }
        if !progressBootstrapCompleted && vm.currentTime == 0 { return }
        saveProgress(vm: vm, episodeRemoteId: activeEpisodeId, reason: reason)
    }

    private func pendingProgressOnDisappear()
        -> (currentTime: TimeInterval, duration: TimeInterval, isCompleted: Bool, episodeRemoteId: String)? {
#if DEBUG
        if catalogPreview != nil { return nil }
#endif
        guard let vm = viewModel, loadedEpisodeId == activeEpisodeId else { return nil }
        if !progressBootstrapCompleted && vm.currentTime == 0 { return nil }
        return (
            currentTime: vm.currentTime,
            duration: vm.duration,
            isCompleted: PodcastPlayerSupport.isCompleted(
                currentTime: vm.currentTime, duration: vm.duration, isReady: vm.state == .ready
            ),
            episodeRemoteId: activeEpisodeId
        )
    }

    private func saveProgress(
        vm: PodcastPlayerViewModel,
        episodeRemoteId: String,
        reason: PodcastProgressPushState.Reason = .pause
    ) {
        progressPersistence.save(
            viewModel: vm,
            episodeRemoteId: episodeRemoteId,
            modelContext: modelContext,
            kgService: kgService,
            reason: reason
        )
    }
}
#endif
