#if os(iOS)
import SwiftUI
import SwiftData
import Inject

struct PodcastPlayerView: View {
    @ObserveInjection private var inject
    let episodeId: String
    /// episode player 一律經 push detail 進入（#672 收斂掉 regular 的 inline
    /// 右欄），故 chrome 不再依 sizeClass / layoutMode 分支：tab bar 恆隱藏、
    /// 設定鍵恆走 ambient push nav bar 的 toolbar。亦**不**自帶內層
    /// NavigationStack —— 過去 inline 傳 `wrapInNavigation:true` 自帶
    /// `NavigationStack` host 設定鍵，但該內層 stack 嵌在 BookshelfView 外層
    /// NavigationStack subtree 內，會**持久破壞外層 value-based push**（NAVDBG
    /// 坐實：顯示過 inline player 後 reader 永久無法 push，Catalyst SwiftUI 缺陷）。
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

    @State private var viewModel: PodcastPlayerViewModel?
    @State private var translationHandler = ReaderTranslationHandler()
    @State private var autoPausedByTranslation: Bool = false
    @State private var showSettingsPopover: Bool = false
    @AppStorage("podcast.autoPauseOnLookup") private var autoPauseOnLookup: Bool = true
    @AppStorage("podcast.subtitleSize") private var subtitleSizeRaw: String = PodcastSubtitleSize.large.rawValue
    @State private var progressPersistence = PodcastProgressPersistenceController()
    @State private var showLoginSheet = false
    @State private var showPaywall = false

    /// Tiered-access UX mirror (server is the security boundary). Centralizes
    /// player gate + preview state so policy predicates do not drift inside the
    /// large SwiftUI view.
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
    @State private var loadTask: Task<Void, Never>?
    @State private var loadedEpisodeId: String?
    @State private var progressBootstrapCompleted = false
    /// 連續播放換集 override（auto-advance）：nil → 用 push 進來的 `episodeId`；
    /// 設成下一集 remoteId 後，`.task(id: activeEpisodeId)` 偵測變化即 teardown 舊集
    /// + load 新集（複用既有換集路徑，nav stack 不堆疊——對齊串流連續播放）。
    @State private var overrideEpisodeId: String?

    /// 目前實際播放的 episode remoteId：override（auto-advance 後）優先於 push 進來者。
    private var activeEpisodeId: String { overrideEpisodeId ?? episodeId }

    /// Same-frame SwiftData fetch for the episode keyed by `activeEpisodeId`.
    /// Returns nil only when the row isn't hydrated yet (cold start mid-sync).
    /// Cheap — `fetch` with an indexed predicate is O(log n) on the main context.
    private var loadedEpisode: PodcastEpisode? {
        Self.fetchEpisode(remoteId: activeEpisodeId, in: modelContext)
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
        Self.resolveVocabularyContext(
            episodeId: activeEpisodeId,
            modelContext: modelContext,
            rawNotebookId: ActiveNotebookStore.shared.activeNotebookId,
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
        // 在 TOP-LEVEL body 註冊 `lookedUpWords` 依賴：mid-episode 查一個新詞 →
        // `appendLookedUpWordIfNeeded` 樂觀 append → 此讀取使 body 失效重評 → 字幕子樹
        // 拿到新 `lookedUpWords` 即時長出螢光筆。否則唯一讀取點埋在帶參數的
        // `playerContent(_:)` @ViewBuilder func 內（再經 `Set(...)` 包裝），`@Observable`
        // 失效不及於 body，highlight 只在跳出再重進該集（`.onAppear → loadLookedUpWords`
        // 重建整棵字幕樹）後才出現。鏡射 ReaderView 在其 body 層直讀 `handler.lookedUpWords`
        // 的 proven pattern（亦同本 app `AppThemeContainer` 的 `let _ = fontTracker...` 慣例）。
        let _ = translationHandler.lookedUpWords.count
        return fullBody
        .monetizationGateSheets(login: $showLoginSheet, paywall: $showPaywall)
        .enableInjection()
    }

    @ViewBuilder
    private var fullBody: some View {
        if loadedEpisode != nil && !accessState.playableForTier {
            lockedGateView
        } else {
            playerCore
        }
    }

    /// Defense-in-depth gate shown when a non-playable episode is reached
    /// directly (deep link / continue-playing). Guest → sign-in CTA; free on a
    /// Pro-only episode → upgrade CTA. Audio is never loaded for this episode.
    private var lockedGateView: some View {
        let isGuest = accessState.gateDestination == .login
        return VStack(spacing: skin.spacing.sectionGap) {
            Image(systemName: "lock.fill")
                .font(skin.typography.symbolHero)
                .foregroundStyle(skin.palette.accent)
            Text(isGuest
                 ? L10n.string("podcast.guest.locked.title")
                 : L10n.string("podcast.locked.title"))
                .font(skin.typography.sectionTitle)
                .foregroundStyle(skin.palette.primaryText)
            Text(isGuest
                 ? L10n.string("podcast.guest.locked.body")
                 : L10n.string("podcast.locked.body"))
                .font(skin.typography.caption)
                .foregroundStyle(skin.palette.secondaryText)
                .multilineTextAlignment(.center)
            Button {
                presentUpgradeOrLogin()
            } label: {
                Label(isGuest
                      ? L10n.string("podcast.guest.cta.signInToListen")
                      : L10n.string("podcast.locked.cta.upgrade"),
                      systemImage: isGuest ? "person.crop.circle" : "sparkles")
            }
            .buttonStyle(.appAction(.primary))
            .frame(maxWidth: 280)
        }
        .padding(AppShellMetrics.pageHorizontalPadding)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(theme.palette.pageBackground.ignoresSafeArea())
        .navigationBarTitleDisplayMode(.inline)
    }

    /// Brand banner shown throughout a free-tier preview: signals "this is the
    /// free 3-min preview" + an inline upgrade CTA. The preview asset itself is
    /// physically ~3 min, so playback ends naturally — no media-time cap needed.
    private var previewUpgradeBanner: some View {
        HStack(spacing: skin.spacing.inlineGap) {
            Image(systemName: "lock.circle.fill")
                .font(skin.typography.iconSmall)
                .foregroundStyle(AppColors.onBrandHero)
            Text(L10n.string("podcast.preview.banner.message"))
                .font(skin.typography.caption)
                .foregroundStyle(AppColors.onBrandHero)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                presentUpgradeOrLogin()
            } label: {
                Text(L10n.string("podcast.locked.cta.upgrade"))
                    .font(skin.typography.caption.weight(.semibold))
            }
            .buttonStyle(.appCompactAction(.primary))
        }
        .padding(.horizontal, skin.spacing.cardPadding)
        .padding(.vertical, skin.spacing.inlineGap)
        .background(skin.palette.brandHero, in: RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("podcast.preview.banner")
    }

    /// Route the upgrade/login CTA: guest → login sheet; free → Pro paywall.
    @MainActor
    private func presentUpgradeOrLogin() {
        if accessState.gateDestination == .login {
            showLoginSheet = true
        } else {
            subscriptionManager.activePaywallSource = .podcast
            showPaywall = true
        }
    }

    /// 字幕設定鍵，恆掛 push detail 的 `.topBarTrailing` toolbar。
    private var settingsButton: some View {
        Button {
            showSettingsPopover = true
        } label: {
            AppToolbarGlyph(systemImage: "textformat.size")
        }
        .accessibilityLabel(L10n.string("podcast.player.subtitleSettings"))
        .accessibilityIdentifier("podcast.player.settingsButton")
    }

    @ViewBuilder
    private var playerCore: some View {
        Group {
            if let vm = viewModel {
                playerContent(vm)
                    // 進度持久化的 currentTime 訂閱必須【隔離】到葉子 view,不可直接
                    // .onChange(of: vm.currentTime) 掛在 playerCore 上。currentTime 是
                    // 15Hz tick(handleTimeUpdate);.onChange 的 of: 參數在 body 求值時
                    // 被讀取,會讓【整個 PodcastPlayerView.body】訂閱 currentTime → 每
                    // tick 重求值 → playerContent(@ViewBuilder func,無 diff 邊界)連鎖
                    // 重建 PodcastSubtitleView/PodcastSentenceLevelView 子樹(每次帶新
                    // closure → 非 Equatable → body 重求值),其外層 follow TimelineView
                    // 被每秒 tear-down/rebuild 15 次 → 主線飽和(卡頓)+ follow schedule
                    // 永遠無法穩定推進(自動捲動死)。token 樹的 .equatable() 只擋最內層
                    // PodcastTranscriptColumn,擋不住這條【父層】invalidation——這正是
                    // f6e077a8 把優化包在父層失效之下、徒勞無功的原因。
                    // @Observable 依賴是 per-view 的:把 currentTime 的讀取關進只渲染
                    // Color.clear 的 PodcastProgressTicker,只有該葉子每 tick 重求值
                    // (O(1)、無子樹),父 body 與整條字幕子樹徹底解放。
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
                    // 連續播放：本集自然播畢 → 自動續播下一可播集（gate 在 PodcastQueue）。
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
        // episode player 一律 push detail（compact iPhone push、regular iPad/
        // Catalyst 亦走 BookshelfView root 的 value-based push，見 #672 收斂；
        // regular 右欄 inline player 已絕跡）→ 永遠隱藏 tab bar 取得全屏。
        // Catalyst 無 tab bar 故整段略過。
        #if !targetEnvironment(macCatalyst)
        .toolbar(.hidden, for: .tabBar)
        #endif
        // 設定鍵恆走 push detail 的 ambient nav bar toolbar（與 compact 對齊）。
        // 過去 regular inline 右欄無專屬 nav bar 才改 content overlay；inline
        // 絕跡後浮角多餘（且可能與字幕/內容衝突），統一回 toolbar。
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                settingsButton
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
        // id = activeEpisodeId：push 進入跑一次；auto-advance 改 overrideEpisodeId 時
        // id 變 → 同一套 teardown（save 舊集進度 → stop vm → reset）+ loadEpisode 新集，
        // nav stack 不堆疊（對齊串流連續播放）。
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
        // Trigger on `.count` (新增/刪除 entry) rather than the whole array,
        // matching ReaderView.swift's deliberate choice (see its
        // `.onChange(of: allVocabulary.count)`). The lookedUp set is derived
        // purely from word identity (word + inflections + rootForm of entries
        // passing `shouldAppearInReader`), so a background-sync LWW write that
        // only bumps an existing entry's `updatedAt` must NOT force a full
        // `loadLookedUpWords` recompute. Keying on the entire `[VocabularyEntry]`
        // re-ran it on every field mutation — pure waste during sync.
        .onChange(of: allVocabulary.count) { _, _ in
            translationHandler.loadLookedUpWords(from: allVocabulary)
        }
        .onAppear {
            translationHandler.loadLookedUpWords(from: allVocabulary)
        }
        .onDisappear {
            // Snapshot the final position SYNCHRONOUSLY — before `shutdown()` flips
            // the vm state to `.idle` — then persist OFF this runloop turn. A
            // synchronous `modelContext.save()` here executes inside
            // `ViewGraphHost.tearDown` (deferred onDisappear at `_UIHostingView`
            // deinit); its SwiftData change notification is observed by
            // `_SwiftData_SwiftUI` against the deallocating `@Query` →
            // EXC_BREAKPOINT (confirmed via crash report). Deferring runs the save
            // after teardown completes, when no `@Query` is mid-dealloc. App-kill
            // is covered by the `scenePhase` save below (runs outside teardown).
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
                    persistProgress(
                        currentTime: pending.currentTime,
                        duration: pending.duration,
                        isCompleted: pending.isCompleted,
                        episodeRemoteId: pending.episodeRemoteId,
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
                    previewUpgradeBanner
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
            // Drive the panel's `.readerPanelReveal` transition on BOTH insert and
            // remove. Reader gets its entry animation from an `.animation(panelState,
            // value: chrome.overlay)` on the overlay container (ReaderViewPresenter+
            // Overlays.swift:52); without an equivalent here, only `handler.dismiss()`'s
            // own `withAnimation` animated the panel — so it slid out but popped in.
            // `WordSelection` is Equatable (==, ignoring position), so nil↔non-nil
            // drives the up-slide/fade. Same spring as dismiss →退場 stays single-feel.
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

    /// 連續播放：本集自然播畢（`episodeFinishedTick`）時，取同 series 下一個可播集
    /// （`PodcastQueue` 含 entitlement gate）設為 `overrideEpisodeId` → `.task(id:)`
    /// 接手 teardown + load。無下一集或被 gate 擋（free 播完 ep1、guest）則維持本集尾
    /// `.ready`、不前進。換集走 override 而非 nav push，故 nav stack 不堆疊。
    @MainActor
    private func advanceToNextEpisode() {
        guard let current = loadedEpisode, let series = loadedSeries else { return }
        guard let next = PodcastQueue.nextPlayable(
            in: series.episodes, after: current, tier: accessState.tier
        ) else { return }
        overrideEpisodeId = next.remoteId
    }

#if DEBUG
    /// Catalog-only counterpart to `loadEpisode()`: builds a synchronous, AVPlayer-
    /// free `.ready` viewModel so the Playbook catalog renders the real player
    /// chrome (transcript + scrubber + transport) deterministically.
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
        // `loadedEpisode` / `loadedSeries` / `vocabularyContext` are now
        // synchronous computed properties (via `resolveVocabularyContext`)
        // driven by `episodeId` + SwiftData + UserDefaults, so the context is
        // non-nil as soon as the row exists — no `.task` hydration race. This
        // function only owns the audio/subtitle async load + viewModel lifecycle.
        guard let episode = loadedEpisode,
              let series = loadedSeries else { return }
        // Tier gate (defense in depth): never load audio for an episode the
        // caller can't play — the body shows `lockedGateView` instead.
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

            // Subtitle load is tracked on the VM separately from audio: a
            // failed fetch surfaces an inline retry instead of being silently
            // swallowed (the player still plays audio meanwhile).
            //
            // Fast path: when metadata.json already carried the SRT inline
            // (ops/podcast_upload.sh embeds it), skip the auth'd subtitle
            // fetch entirely — saves one round-trip and removes a failure
            // mode the user has to recover from.
            var subtitleContent: String?
            switch plan.subtitleSource {
            case .inline(let inline):
                subtitleContent = inline
            case .remote(let subtitleURLStr):
                await MainActor.run { vm.setSubtitleLoading() }
                subtitleContent = await Self.fetchSubtitle(
                    urlString: subtitleURLStr, kgService: kgService
                )
                if Task.isCancelled { return }
                if subtitleContent == nil {
                    await MainActor.run { vm.markSubtitleFailed() }
                }
            case .unavailable:
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
            if plan.usesLocalAudio {
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

            await MainActor.run {
                guard !Task.isCancelled else { return }
                vm.loadEpisode(
                    audioURL: plan.audioURL,
                    subtitleContent: subtitleContent,
                    title: plan.title,
                    audioHTTPHeaders: audioHeaders,
                    prefetchedDurationSec: plan.durationSec,
                    initialProgressTime: initialProgressTime
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

    /// Progress snapshot to persist when the player disappears — same guards as
    /// `saveProgress(reason:)` but returns captured scalars (not the live vm) so
    /// the write can be deferred past view teardown. Returns nil when there is
    /// nothing meaningful to persist. The catalog preview never persists (it is a
    /// static fixture), so it returns nil here too — no pointless deferred Task.
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
            isCompleted: Self.isCompleted(
                currentTime: vm.currentTime, duration: vm.duration, isReady: vm.state == .ready
            ),
            episodeRemoteId: activeEpisodeId
        )
    }

    /// Decides whether a `position == 0` write is meaningful.
    ///
    /// A `.tick` at position 0 is pure noise (audio not advanced yet) and must
    /// be dropped. But an explicit `.pause` / `.episodeSwitch` at position 0 is
    /// a real user-visible transition that must persist — notably when a
    /// *completed* episode is reopened: `restoreProgress` skips the seek for
    /// completed rows (see L541-545), so `currentTime` stays 0; if the user
    /// then pauses immediately, the only way to record that (and let the row
    /// drop out of "completed") is to honour the position-0 pause write.
    static func shouldPersist(
        currentTime: TimeInterval,
        reason: PodcastProgressPushState.Reason
    ) -> Bool {
        PodcastProgressPersistenceController.shouldPersist(
            currentTime: currentTime,
            reason: reason
        )
    }

    /// Whether a position counts as "episode completed". Hoisted to a pure
    /// function so `onDisappear`'s synchronous snapshot and the live-vm save path
    /// compute it identically — and so it stays unit-testable. `isReady` must
    /// reflect the vm state CAPTURED BEFORE `shutdown()`, which flips it to `.idle`.
    static func isCompleted(currentTime: TimeInterval, duration: TimeInterval, isReady: Bool) -> Bool {
        isReady && duration > 0 && currentTime >= duration - 1
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

/// 把 15Hz `currentTime` 的 `@Observable` 訂閱關進一個只渲染 `Color.clear` 的葉子
/// view,使父層 `PodcastPlayerView.body` 不再訂閱 currentTime。
///
/// 背景:`@Observable` 的失效粒度是 per-view-body——某個 view 的 body 在求值時讀了
/// 哪些 property,就只訂閱那些。先前進度持久化的 `.onChange(of: vm.currentTime)` 直接
/// 掛在 `playerCore`,等於讓整個 player body 訂閱 15Hz 的 currentTime,每 tick 連鎖
/// 重建非 Equatable 的字幕子樹 + 每秒重建 follow `TimelineView` 15 次 → 捲動卡頓 +
/// 自動捲動失效。把讀取隔離到這個無子樹的葉子後,每 tick 只重求值一個 `Color.clear`
/// (O(1)),父 body 與字幕子樹不再被 currentTime 牽連。
///
/// `onTick` 僅在 `state == .playing` 時呼叫,保留原 `.onChange` 的語意(節流/持久化
/// gating 仍由呼叫端 `saveProgressIfNeeded` 的 `lastSavedTime` 判斷負責)。
struct PodcastProgressTicker: View {
    let viewModel: PodcastPlayerViewModel
    let onTick: (TimeInterval) -> Void

    var body: some View {
        Color.clear
            .onChange(of: viewModel.currentTime) { _, newTime in
                guard viewModel.state == .playing else { return }
                onTick(newTime)
            }
    }
}
#endif
