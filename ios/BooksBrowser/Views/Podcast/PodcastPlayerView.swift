#if os(iOS)
import SwiftUI
import SwiftData

struct PodcastPlayerView: View {
    let episodeId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.appTheme) private var theme
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.toastCoordinator) private var toastCoordinator

    @Query private var allVocabulary: [VocabularyEntry]

    @State private var viewModel: PodcastPlayerViewModel?
    @State private var translationHandler = ReaderTranslationHandler()
    @State private var autoPausedByTranslation: Bool = false
    @State private var showSettingsPopover: Bool = false
    @AppStorage("podcast.autoPauseOnLookup") private var autoPauseOnLookup: Bool = true
    @AppStorage("podcast.subtitleSize") private var subtitleSizeRaw: String = PodcastSubtitleSize.large.rawValue
    @State private var lastSavedTime: TimeInterval = 0

    private var subtitleSize: PodcastSubtitleSize {
        PodcastSubtitleSize(rawValue: subtitleSizeRaw) ?? .large
    }

    private var subtitleSizeBinding: Binding<PodcastSubtitleSize> {
        Binding(
            get: { PodcastSubtitleSize(rawValue: subtitleSizeRaw) ?? .large },
            set: { subtitleSizeRaw = $0.rawValue }
        )
    }
    @State private var loadTask: Task<Void, Never>?
    @State private var loadedEpisodeId: String?
    @State private var progressRestored = false

    /// Same-frame SwiftData fetch for the episode keyed by `episodeId`. Returns
    /// nil only when the row isn't hydrated yet (cold start mid-sync). Cheap —
    /// `fetch` with an indexed predicate is O(log n) and stays on the main
    /// context.
    private var loadedEpisode: PodcastEpisode? {
        Self.fetchEpisode(remoteId: episodeId, in: modelContext)
    }

    private var loadedSeries: PodcastSeries? {
        loadedEpisode?.series
    }

    /// Notebook id derived synchronously from UserDefaults + SwiftData lookup,
    /// so `vocabularyContext` becomes non-nil the instant the SwiftData row is
    /// hydrated — no dependency on `.task` having completed.
    private var resolvedNotebookId: String? {
        let raw = UserDefaults.standard.string(forKey: "activeNotebookId") ?? "default"
        return VocabularyEntry.resolveNotebookId(raw, in: modelContext)
    }

    private var vocabularyContext: PodcastVocabularyContext? {
        Self.resolveVocabularyContext(
            episodeId: episodeId,
            modelContext: modelContext,
            rawNotebookId: UserDefaults.standard.string(forKey: "activeNotebookId") ?? "default",
            toastCoordinator: toastCoordinator,
            vocabulary: allVocabulary
        )
    }

    /// Same logic as `vocabularyContext`, hoisted to a pure static so it is
    /// directly testable without SwiftUI runtime. The race that PR #400 fixed
    /// lives entirely inside this resolver: as long as the SwiftData episode
    /// row exists, this returns non-nil — no `.task` hydration required.
    static func fetchEpisode(remoteId: String, in context: ModelContext) -> PodcastEpisode? {
        let target = remoteId
        let descriptor = FetchDescriptor<PodcastEpisode>(
            predicate: #Predicate { $0.remoteId == target }
        )
        return try? context.fetch(descriptor).first
    }

    static func resolveVocabularyContext(
        episodeId: String,
        modelContext: ModelContext,
        rawNotebookId: String,
        toastCoordinator: AppToastCoordinator,
        vocabulary: [VocabularyEntry]
    ) -> PodcastVocabularyContext? {
        guard let episode = fetchEpisode(remoteId: episodeId, in: modelContext),
              let series = episode.series else { return nil }
        let nbId = VocabularyEntry.resolveNotebookId(rawNotebookId, in: modelContext)
        return PodcastVocabularyContext(
            vocabulary: vocabulary,
            modelContext: modelContext,
            series: series,
            episode: episode,
            notebookId: nbId,
            toastCoordinator: toastCoordinator
        )
    }

    var body: some View {
        fullBody
    }

    @ViewBuilder
    private var fullBody: some View {
        Group {
            if let vm = viewModel {
                playerContent(vm)
                    .onChange(of: vm.currentTime) { _, newTime in
                        guard vm.state == .playing else { return }
                        saveProgressIfNeeded(time: newTime)
                    }
                    .onChange(of: vm.state) { _, newState in
                        if newState == .ready, !progressRestored {
                            progressRestored = true
                            restoreProgress(vm: vm, episodeRemoteId: episodeId)
                            return
                        }
                        if newState == .paused || newState == .ready {
                            saveProgress()
                        }
                    }
            } else {
                ProgressView("載入中…")
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.hidden, for: .tabBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    showSettingsPopover = true
                } label: {
                    Image(systemName: "textformat.size")
                }
                .popover(isPresented: $showSettingsPopover, arrowEdge: .top) {
                    PodcastSettingsPopover(
                        subtitleSize: subtitleSizeBinding,
                        autoPauseOnLookup: Binding(
                            get: { autoPauseOnLookup },
                            set: { autoPauseOnLookup = $0 }
                        )
                    )
                    .presentationCompactAdaptation(.popover)
                }
            }
        }
        .task(id: episodeId) {
            guard loadedEpisodeId != episodeId else { return }
            if let oldVm = viewModel, let oldId = loadedEpisodeId {
                saveProgress(vm: oldVm, episodeRemoteId: oldId)
            }
            loadTask?.cancel()
            loadTask = nil
            viewModel?.stop()
            viewModel = nil
            loadedEpisodeId = episodeId
            progressRestored = false
            lastSavedTime = 0
            loadEpisode()
        }
        .onChange(of: allVocabulary) { _, newValue in
            translationHandler.loadLookedUpWords(from: newValue)
        }
        .onAppear {
            translationHandler.loadLookedUpWords(from: allVocabulary)
        }
        .onDisappear {
            saveProgress()
            loadTask?.cancel()
            loadTask = nil
            viewModel?.shutdown()
            viewModel = nil
            loadedEpisodeId = nil
            progressRestored = false
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { saveProgress() }
        }
    }

    @ViewBuilder
    private func playerContent(_ vm: PodcastPlayerViewModel) -> some View {
        switch vm.state {
        case .idle, .loading:
            VStack(spacing: skin.spacing.sectionGap) {
                ProgressView()
                Text("載入音訊…")
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .error(let msg):
            VStack(spacing: skin.spacing.sectionGap) {
                Image(systemName: "xmark.octagon")
                    .font(skin.typography.symbolHero)
                    .foregroundStyle(skin.palette.destructive)
                Text("音訊載入失敗")
                    .font(skin.typography.sectionTitle)
                Text(msg)
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                Button("重試") { reloadEpisode() }
                    .buttonStyle(.borderedProminent)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .ready, .playing, .paused:
            VStack(spacing: 0) {
                PodcastSubtitleView(viewModel: vm, subtitleSize: subtitleSize)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                PodcastControlsView(viewModel: vm)
                    .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                    .padding(.bottom, PodcastPlayerMetrics.controlsBottomPadding)
            }
            .background(theme.palette.pageBackground)
            .overlay(alignment: .bottom) {
                if let selection = translationHandler.wordSelection {
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
                        }
                    )
                    .transition(.readerPanelReveal)
                }
            }
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

    private func handlePanelVisibilityChange(
        from old: String?,
        to new: String?,
        vm: PodcastPlayerViewModel
    ) {
        guard autoPauseOnLookup else { return }
        if old == nil, new != nil {
            if vm.state == .playing {
                vm.pause()
                autoPausedByTranslation = true
            }
        } else if new == nil, autoPausedByTranslation {
            autoPausedByTranslation = false
            if vm.state == .paused { vm.play() }
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
        progressRestored = false
        lastSavedTime = 0
        loadEpisode()
    }

    private func loadEpisode() {
        // `loadedEpisode` / `loadedSeries` / `resolvedNotebookId` are now
        // synchronous computed properties driven by `episodeId` + SwiftData +
        // UserDefaults, so `vocabularyContext` is non-nil as soon as the row
        // exists — no `.task` hydration race. This function only owns the
        // audio/subtitle async load + viewModel lifecycle.
        guard let episode = loadedEpisode,
              let series = loadedSeries else { return }

        loadTask?.cancel()
        loadTask = nil

        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        viewModel = vm

        loadTask = Task { [weak vm] in
            guard let vm else { return }
            do {
                guard let audioURLStr = episode.audioURL,
                      let audioURL = URL(string: audioURLStr) else {
                    await MainActor.run { vm.reportError("無音訊 URL") }
                    return
                }

                await MainActor.run { vm.setLoading() }
                if Task.isCancelled { return }

                var subtitleContent: String?
                if let subtitleURLStr = episode.subtitleURL {
                    if let data = try? await PodcastSyncService.authedData(from: subtitleURLStr, kgService: kgService) {
                        subtitleContent = String(data: data, encoding: .utf8)
                    }
                }
                if Task.isCancelled { return }

                let episodeTitle = episode.displayTitle
                await MainActor.run {
                    guard !Task.isCancelled else { return }
                    vm.loadEpisode(
                        audioURL: audioURL,
                        subtitleContent: subtitleContent,
                        title: episodeTitle
                    )
                }
            } catch is CancellationError {
                return
            } catch {
                await MainActor.run {
                    vm.reportError("載入失敗：\(error.localizedDescription)")
                }
            }
        }
    }

    @MainActor
    private func restoreProgress(vm: PodcastPlayerViewModel, episodeRemoteId: String) {
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)]
        )
        if let progress = try? modelContext.fetch(descriptor).first,
           progress.lastPlayedTime > 0,
           !progress.completed {
            vm.seek(to: progress.lastPlayedTime)
        }
    }

    private func saveProgressIfNeeded(time: TimeInterval) {
        guard abs(time - lastSavedTime) > 10 else { return }
        lastSavedTime = time
        saveProgress()
    }

    private func saveProgress() {
        guard let vm = viewModel else { return }
        guard loadedEpisodeId == episodeId else { return }
        if !progressRestored && vm.currentTime == 0 { return }
        saveProgress(vm: vm, episodeRemoteId: episodeId)
    }

    private func saveProgress(vm: PodcastPlayerViewModel, episodeRemoteId: String) {
        if vm.currentTime == 0 { return }
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)]
        )
        let existing = (try? modelContext.fetch(descriptor)) ?? []
        for stale in existing.dropFirst() {
            modelContext.delete(stale)
        }
        let progress: PodcastProgress
        if let newest = existing.first {
            progress = newest
        } else {
            progress = PodcastProgress(episodeRemoteId: episodeRemoteId)
            modelContext.insert(progress)
        }
        progress.lastPlayedTime = vm.currentTime
        progress.completed = (
            vm.state == .ready
            && vm.duration > 0
            && vm.currentTime >= vm.duration - 1
        )
        progress.updatedAt = Date()
        do {
            try modelContext.save()
        } catch {
            AppLog.app.error("PodcastProgress save failed: \(error.localizedDescription)")
        }
    }
}
#endif
