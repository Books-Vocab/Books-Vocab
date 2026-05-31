#if os(iOS)
import SwiftUI
import SwiftData
import Inject

struct PodcastPlayerView: View {
    @ObserveInjection private var inject
    let episodeId: String
    @Environment(\.appSkin) private var skin
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
    @State private var pushState = PodcastProgressPushState()

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

    private static let activeNotebookIdKey = "activeNotebookId"

    private var vocabularyContext: PodcastVocabularyContext? {
        Self.resolveVocabularyContext(
            episodeId: episodeId,
            modelContext: modelContext,
            rawNotebookId: UserDefaults.standard.string(forKey: Self.activeNotebookIdKey) ?? "default",
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
        .enableInjection()
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
                    .sensoryFeedback(.success, trigger: vm.sleepTimerFiredTick)
                    .onChange(of: vm.sleepTimerFiredTick) { oldTick, newTick in
                        guard newTick != oldTick else { return }
                        toastCoordinator.info(L10n.string("podcast.sleepTimer.fired.toast"))
                    }
            } else {
                ProgressView(L10n.string("載入中…"))
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
                .accessibilityLabel(L10n.string("podcast.player.subtitleSettings"))
            }
        }
        // 字幕設定改用 sheet。Mac Catalyst 上「從 toolbar 按鈕掛 .popover」會在 present
        // 過場走 UIKit keyboard-scene pin 路徑觸發內部 trap(EXC_BREAKPOINT,backtrace 全在
        // UIKitCore 無 app frame);sheet 走不同 presentation controller,徹底避開此 framework
        // bug(亦含 popover resize 時的 willReposition recursion crash)。
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
        .task(id: episodeId) {
            guard loadedEpisodeId != episodeId else { return }
            if let oldVm = viewModel, let oldId = loadedEpisodeId {
                saveProgress(vm: oldVm, episodeRemoteId: oldId, reason: .episodeSwitch)
            }
            loadTask?.cancel()
            loadTask = nil
            viewModel?.stop()
            viewModel = nil
            loadedEpisodeId = episodeId
            progressRestored = false
            lastSavedTime = 0
            pushState = PodcastProgressPushState()
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
                Text(L10n.string("載入音訊…"))
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .error(let msg):
            VStack(spacing: skin.spacing.sectionGap) {
                Image(systemName: "xmark.octagon")
                    .font(skin.typography.symbolHero)
                    .foregroundStyle(skin.palette.destructive)
                Text(L10n.string("音訊載入失敗"))
                    .font(skin.typography.sectionTitle)
                Text(msg)
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                Button(L10n.string("重試")) { reloadEpisode() }
                    .buttonStyle(.appCompactAction(.primary))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .ready, .playing, .paused:
            VStack(spacing: 0) {
                PodcastSubtitleView(
                    viewModel: vm,
                    subtitleSize: subtitleSize,
                    onRetrySubtitle: { retrySubtitle() }
                )
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
        pushState = PodcastProgressPushState()
        loadEpisode()
    }

    private func loadEpisode() {
        // `loadedEpisode` / `loadedSeries` / `vocabularyContext` are now
        // synchronous computed properties (via `resolveVocabularyContext`)
        // driven by `episodeId` + SwiftData + UserDefaults, so the context is
        // non-nil as soon as the row exists — no `.task` hydration race. This
        // function only owns the audio/subtitle async load + viewModel lifecycle.
        guard let episode = loadedEpisode,
              let series = loadedSeries else { return }

        loadTask?.cancel()
        loadTask = nil

        let vm = PodcastPlayerViewModel(hostNames: series.hostNames)
        viewModel = vm

        loadTask = Task { [weak vm] in
            guard let vm else { return }
            // Local-first: if the episode was downloaded, stream from disk.
            // file:// URLs need no auth header and AVPlayer skips network
            // entirely → instant ready, zero buffer concerns.
            let localURL: URL? = {
                guard let path = episode.localAudioPath,
                      FileManager.default.fileExists(atPath: path) else { return nil }
                return URL(fileURLWithPath: path)
            }()
            guard let audioURL = localURL
                ?? episode.audioURL.flatMap(URL.init(string:)) else {
                await MainActor.run { vm.reportError(L10n.string("無音訊 URL")) }
                return
            }
            let isLocal = localURL != nil

            await MainActor.run { vm.setLoading() }
            if Task.isCancelled { return }

            // Subtitle load is tracked on the VM separately from audio: a
            // failed fetch surfaces an inline retry instead of being silently
            // swallowed (the player still plays audio meanwhile).
            //
            // Fast path: when metadata.json already carried the SRT inline
            // (ops/podcast_upload.sh embeds it), skip the auth'd subtitle
            // fetch entirely — saves one round-trip and removes a failure
            // mode the user has to recover from.
            var subtitleContent: String?
            if let inline = episode.inlineSubtitle, !inline.isEmpty {
                subtitleContent = inline
            } else if let subtitleURLStr = episode.subtitleURL {
                await MainActor.run { vm.setSubtitleLoading() }
                subtitleContent = await Self.fetchSubtitle(
                    urlString: subtitleURLStr, kgService: kgService
                )
                if Task.isCancelled { return }
                if subtitleContent == nil {
                    await MainActor.run { vm.markSubtitleFailed() }
                }
            } else {
                await MainActor.run { vm.markSubtitleUnavailable() }
            }
            if Task.isCancelled { return }

            // Fetch the auth token AFTER subtitle so token refresh latency
            // doesn't block subtitle load, and so the token reflects the
            // latest state right before AVPlayer issues its first Range request.
            // Skip entirely for local file:// URLs — no network round-trip
            // means no auth needed, and we avoid blocking on a token fetch
            // that could fail offline.
            let audioHeaders: [String: String]
            if isLocal {
                audioHeaders = [:]
            } else {
                do {
                    let token = try await kgService.currentAuthToken()
                    audioHeaders = ["Authorization": "Bearer \(token)"]
                } catch is CancellationError {
                    return
                } catch {
                    await MainActor.run {
                        vm.reportError(L10n.format("無法取得認證 token：%@", error.localizedDescription))
                    }
                    return
                }
            }
            if Task.isCancelled { return }

            let episodeTitle = episode.displayTitle
            let prefetchedDuration = episode.durationSec
            await MainActor.run {
                guard !Task.isCancelled else { return }
                vm.loadEpisode(
                    audioURL: audioURL,
                    subtitleContent: subtitleContent,
                    title: episodeTitle,
                    audioHTTPHeaders: audioHeaders,
                    prefetchedDurationSec: prefetchedDuration
                )
            }
        }
    }

    /// Fetches + decodes the SRT for an episode. Returns nil on any
    /// network/decode failure so the caller can drive the inline retry state.
    static func fetchSubtitle(urlString: String, kgService: any KGServing) async -> String? {
        guard let data = try? await PodcastSyncService.authedData(
            from: urlString, kgService: kgService
        ) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Re-runs ONLY the subtitle load branch — used by the inline
    /// "字幕載入失敗 ⟳" retry. Audio playback is untouched.
    @MainActor
    private func retrySubtitle() {
        guard let vm = viewModel,
              let episode = loadedEpisode,
              let subtitleURLStr = episode.subtitleURL else { return }
        vm.setSubtitleLoading()
        Task { [weak vm] in
            guard let vm else { return }
            let content = await Self.fetchSubtitle(
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
        saveProgress(reason: .tick)
    }

    private func saveProgress(reason: PodcastProgressPushState.Reason = .pause) {
        guard let vm = viewModel else { return }
        guard loadedEpisodeId == episodeId else { return }
        if !progressRestored && vm.currentTime == 0 { return }
        saveProgress(vm: vm, episodeRemoteId: episodeId, reason: reason)
    }

    private func saveProgress(
        vm: PodcastPlayerViewModel,
        episodeRemoteId: String,
        reason: PodcastProgressPushState.Reason = .pause
    ) {
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
        let now = Date()
        progress.lastPlayedTime = vm.currentTime
        progress.completed = (
            vm.state == .ready
            && vm.duration > 0
            && vm.currentTime >= vm.duration - 1
        )
        progress.updatedAt = now
        do {
            try modelContext.save()
        } catch {
            AppLog.app.error("PodcastProgress save failed: \(error.localizedDescription)")
        }

        // Mirror the same write to the backend under the throttle policy.
        // Throttle lives in PodcastProgressPushState (unit-tested). Capture
        // values on the main actor; the detached Task uses the snapshot only.
        let shouldPush = pushState.shouldPush(
            position: vm.currentTime,
            duration: vm.duration,
            now: now,
            reason: reason
        )
        guard shouldPush,
              let parsed = PodcastSyncService.parseEpisodeRemoteId(episodeRemoteId) else { return }
        let captured = (
            seriesId: parsed.seriesId,
            episodeNumber: parsed.episodeNumber,
            positionSec: vm.currentTime,
            durationSec: vm.duration,
            updatedAt: now
        )
        let service = PodcastSyncService(kgService: kgService)
        Task.detached(priority: .utility) {
            do {
                try await service.pushProgress(
                    seriesId: captured.seriesId,
                    episodeNumber: captured.episodeNumber,
                    positionSec: captured.positionSec,
                    durationSec: captured.durationSec,
                    updatedAt: captured.updatedAt
                )
            } catch {
                AppLog.kg.warning("[PodcastSync] progress push failed: \(error.localizedDescription)")
            }
        }
    }
}
#endif
