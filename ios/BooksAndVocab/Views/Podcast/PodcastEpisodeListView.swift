import SwiftUI
import SwiftData

/// Podcast push 路由 — value-based NavigationLink 目標。
///
/// 改成 value-based 的理由：PR #366/#368/#370/#373 追查一個 tap episode row →
/// 凍結（freeze，非 crash、無 log、無 crash report）。已確認 destination view
/// 本身空殼也凍結，根因鎖定在 navigation 機制而非 destination 內部。
/// closure-based `NavigationLink { destination }` 在 LazyVStack 中 SwiftUI 會
/// eager evaluate destination closure；結合父層 BookshelfView 同一
/// NavigationStack 已註冊 `navigationDestination(for: Book.self)` 的情境，
/// 2 層 push 時出現內部卡死。改成 value-based + 統一在 NavigationStack root
/// 註冊 destination，走正式 Apple 推薦路徑。
enum PodcastNavRoute: Hashable {
    case series(seriesRemoteId: String)
    case episode(episodeRemoteId: String)
}

private enum EpisodeSort: String, CaseIterable, Identifiable {
    case ascending, descending
    var id: String { rawValue }
    var label: String {
        switch self {
        case .ascending: return L10n.string("集數由小到大")
        case .descending: return L10n.string("集數由大到小")
        }
    }
    var systemImage: String {
        switch self {
        case .ascending: return "arrow.up"
        case .descending: return "arrow.down"
        }
    }
}

struct PodcastEpisodeListView: View {
    @ObserveInjection private var inject
    let seriesId: String
    @Environment(\.appSkin) private var skin
    @Environment(\.modelContext) private var modelContext
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.kgService) private var kgService
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.authManager) private var authManager

    /// Tiered-access UX mirror of the backend policy. A guest browses but taps
    /// route to the login sheet; a free user can open ep1 (preview) but ep2+
    /// rows are locked → paywall. Server stays the security boundary.
    private var tier: PodcastTier {
        PodcastAccess.tier(hasProAccess: subscriptionManager.hasProAccess, hasToken: authManager.token != nil)
    }
    @State private var monetizationGate = MonetizationGateState()

    // ⚠️ 5th bisect — 把所有 @Query 改成 @State + 一次性 fetch。
    // 過往 @Query 同 view 內 cross-store（PodcastSeries/Episode 在
    // LocalStore，PodcastProgress 在 CloudStore），且 progressMap /
    // continueEpisode 等 computed 在每次 body eval 都會重算 Dictionary
    // → SwiftData observation 任何一邊 update 即觸發整個 view 重評。
    // navigation push 動畫期間 parent view 仍 active，若此時 @Query
    // 在 transition 中觸發 SwiftData refetch + main thread Dictionary
    // rebuild，可能造成 UI freeze（使用者回報的「卡住、無錯誤」）。
    @State private var seriesEpisodes: [PodcastEpisode] = []
    @State private var progressArray: [PodcastProgress] = []
    @State private var currentSeries: PodcastSeries?
    @State private var sort: EpisodeSort = .ascending
    /// hasLoadedOnce 區分「首次未載入 (.loading)」與「載入後空集數 (.empty)」，
    /// 避免 0 集 series 在 task 啟動前閃 empty。
    @State private var hasLoadedOnce = false
    @State private var isLoading = false
    @State private var loadError: String?

    private var series: PodcastSeries? { currentSeries }

    private var rawEpisodes: [PodcastEpisode] { seriesEpisodes }

    private var episodes: [PodcastEpisode] {
        switch sort {
        case .ascending: return rawEpisodes
        case .descending: return Array(rawEpisodes.reversed())
        }
    }

    private var progressMap: [String: PodcastProgress] {
        let ids = Set(rawEpisodes.map(\.remoteId))
        return Dictionary(
            progressArray.lazy
                .filter { ids.contains($0.episodeRemoteId) }
                .map { ($0.episodeRemoteId, $0) },
            uniquingKeysWith: { lhs, rhs in lhs.updatedAt >= rhs.updatedAt ? lhs : rhs }
        )
    }

    private var continueEpisode: PodcastEpisode? {
        let inProgress = rawEpisodes
            .compactMap { ep -> (PodcastEpisode, PodcastProgress)? in
                guard let p = progressMap[ep.remoteId], !p.completed, p.lastPlayedTime > 0 else { return nil }
                return (ep, p)
            }
            .max { $0.1.updatedAt < $1.1.updatedAt }
            .map { $0.0 }
        if let inProgress { return inProgress }
        if let firstUnplayed = rawEpisodes.first(where: { progressMap[$0.remoteId]?.completed != true }) {
            return firstUnplayed
        }
        return rawEpisodes.first
    }

    private var allCompleted: Bool {
        !rawEpisodes.isEmpty && rawEpisodes.allSatisfy { progressMap[$0.remoteId]?.completed == true }
    }

    private var phase: VocabScenePhase {
        if isLoading && !hasLoadedOnce {
            return .loadingSkeleton()
        }
        if loadError != nil, rawEpisodes.isEmpty {
            return .error(
                title: L10n.string("無法載入集數"),
                systemImage: "exclamationmark.triangle",
                description: L10n.string("請確認網路連線後重試"),
                retryAction: {
                    Task { await reloadFromStore() }
                }
            )
        }
        if rawEpisodes.isEmpty && hasLoadedOnce {
            return .empty(
                title: L10n.string("尚無集數"),
                systemImage: "waveform.slash",
                description: L10n.string("此系列目前沒有可播放的集數"),
                action: nil
            )
        }
        return .content
    }

    var body: some View {
        VocabSceneShell(phase: phase) {
            ScrollView {
                LazyVStack(spacing: skin.spacing.sectionGap) {
                    heroHeader
                    staleDataBanner
                    episodesSection
                }
                .padding(.horizontal, skin.spacing.cardPadding)
                .padding(.bottom, skin.spacing.sheetSectionSpacing)
            }
            .background(skin.palette.pageBackground.ignoresSafeArea())
        }
        .navigationTitle(series?.title ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                followToggleButton
            }
        }
        .task(id: seriesId) {
            await reloadFromStore()
        }
        // Background sync (scenePhase active / ⌘R / login / parent
        // pull-to-refresh) upserts episodes/progress without changing seriesId,
        // so `.task(id:)` never re-fires and the frozen @State snapshot goes
        // stale. This is a *discrete* re-read on a one-shot Notification — it
        // does NOT reintroduce the continuous cross-store @Query observation
        // the freeze-fix removed (reloadFromStore uses explicit
        // modelContext.fetch, no @Query).
        //
        // We deliberately do NOT guard on "did this series change". syncAll
        // runs on `container.mainContext` (KGService+Sync.swift) — the very
        // same context backing this view's @Environment(\.modelContext) — so a
        // re-fetched series row is the *identical* live managed object as our
        // held `currentSeries`. upsertSeries mutates that object in place, so
        // any `current.updatedAt == latest.updatedAt` comparison is self==self
        // → always true → the reload would never fire. Catalog sync is a
        // discrete, low-frequency event, so an unconditional reload (3 cheap
        // fetches) is both correct and negligible.
        .onReceive(NotificationCenter.default.publisher(for: .podcastCatalogDidSync)) { _ in
            Task { await reloadFromStore() }
        }
        .monetizationGateSheets($monetizationGate)
        .enableInjection()
    }

    /// Tap on a locked episode (or hero CTA when locked). Guest → login sheet;
    /// free → Pro paywall (sourced as `.podcast`). Never navigates.
    @MainActor
    private func handleLockedTap() {
        switch tier {
        case .guest:
            monetizationGate.presentLogin()
        case .free:
            subscriptionManager.activePaywallSource = .podcast
            monetizationGate.presentPaywall()
        case .pro:
            break  // pro is never locked
        }
    }

    @MainActor
    private func reloadFromStore() async {
        let sid = seriesId
        isLoading = true
        defer {
            isLoading = false
            hasLoadedOnce = true
        }

        do {
            let seriesDescriptor = FetchDescriptor<PodcastSeries>(
                predicate: #Predicate { $0.remoteId == sid && !$0.isSoftDeleted }
            )
            currentSeries = try modelContext.fetch(seriesDescriptor).first

            let episodeDescriptor = FetchDescriptor<PodcastEpisode>(
                sortBy: [SortDescriptor(\.episodeNumber)]
            )
            let allEps = try modelContext.fetch(episodeDescriptor)
            seriesEpisodes = allEps.filter { $0.series?.remoteId == sid }

            let progressDescriptor = FetchDescriptor<PodcastProgress>()
            progressArray = try modelContext.fetch(progressDescriptor)

            loadError = nil
        } catch {
            AppLog.app.error("[Podcast] reloadFromStore failed: \(error.localizedDescription)")
            loadError = error.localizedDescription
        }
    }

    // MARK: - Follow toggle

    private var followToggleButton: some View {
        let isFollowed = currentSeries?.isFollowed == true
        return Button(action: toggleFollow) {
            AppToolbarGlyph(systemImage: isFollowed ? "star.fill" : "star")
        }
        .disabled(currentSeries == nil)
        .accessibilityLabel(L10n.string(isFollowed ? "podcast.followToggle.unfollow" : "podcast.followToggle.follow"))
        .accessibilityIdentifier("podcast.followToggle")
    }

    @MainActor
    private func toggleFollow() {
        guard let target = currentSeries else { return }
        // The flip is optimistic + animated. `PodcastFollowToggle.perform`
        // couples it to the save result: on a failed save it reverts the
        // model so the star never lies about a state that wasn't persisted.
        var outcome: PodcastFollowToggle.Outcome = .saved
        withAnimation(AppMotion.phaseChange) {
            outcome = PodcastFollowToggle.perform(series: target) {
                modelContext.safeSave()
            }
        }
        if outcome == .rolledBack {
            toastCoordinator.error(L10n.string("追蹤狀態儲存失敗"))
        }
    }

    // MARK: - Hero

    private var heroHeader: some View {
        VStack(spacing: skin.spacing.statusHeroGap) {
            if let series {
                PodcastSeriesHero(series: series)
            }
            heroContinue
                .padding(.top, skin.spacing.inlineGap)
        }
        .padding(.bottom, skin.spacing.sectionGap)
    }

    /// The "繼續收聽" centerpiece. Resolves the tier-aware hero action for the
    /// continue target, then wraps `PodcastContinueCard` exactly like
    /// `episodeRow`: a value-based `NavigationLink` when the action plays, a
    /// plain `Button` (→ login/paywall) when it gates — preserving the
    /// LazyVStack freeze contract (PR #366/#368/#370/#373).
    @ViewBuilder
    private var heroContinue: some View {
        if let target = continueEpisode {
            let progress = progressMap[target.remoteId]
            let hasProgress = (progress?.lastPlayedTime ?? 0) > 0 && progress?.completed != true
            let action = PodcastAccess.heroAction(
                tier: tier,
                episodeNumber: target.episodeNumber,
                previewAvailable: target.previewAvailable,
                audioAvailable: target.audioAvailable,
                hasProgress: hasProgress,
                allCompleted: allCompleted
            )
            let card = PodcastContinueCard(episode: target, progress: progress, action: action)

            if action.navigatesToPlayer {
                NavigationLink(value: PodcastNavRoute.episode(episodeRemoteId: target.remoteId)) {
                    card
                }
                .buttonStyle(.plain)
                .simultaneousGesture(
                    TapGesture().onEnded {
                        warmConnection(for: target)
                    }
                )
            } else {
                Button { handleLockedTap() } label: { card }
                    .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Stale data banner

    /// Reload from store failed but we still have cached episodes — surface
    /// the staleness inline with a retry CTA instead of silently letting the
    /// user think the cached list is fresh (state matrix L384, track-3).
    /// `.error` phase only fires when `rawEpisodes.isEmpty`, so this banner
    /// is the only signal users get when `loadError != nil` overlaps with
    /// cached content.
    @ViewBuilder
    private var staleDataBanner: some View {
        if loadError != nil && !rawEpisodes.isEmpty {
            AppBanner(
                message: L10n.string("podcast.episodeList.staleBanner.message"),
                systemImage: "exclamationmark.triangle",
                onRetry: {
                    Task { await reloadFromStore() }
                }
            )
            .accessibilityIdentifier("podcast.episodeList.staleBanner")
        }
    }

    // MARK: - Episodes section

    private var episodesSection: some View {
        VStack(alignment: .leading, spacing: skin.spacing.inlineGap) {
            HStack {
                Text(L10n.string("集數"))
                    .font(skin.typography.sectionTitle)
                    .foregroundStyle(skin.palette.primaryText)
                Spacer()
                sortMenu
            }
            .padding(.horizontal, skin.spacing.rowMicroGap)

            ListSectionCard {
                ForEach(Array(episodes.enumerated()), id: \.element.id) { index, episode in
                    episodeRow(episode)

                    if index < episodes.count - 1 {
                        Divider()
                            .background(skin.palette.divider)
                            .padding(.leading, skin.spacing.cardPadding)
                    }
                }
            }
        }
    }

    /// 集數 row → value-based NavigationLink push（所有 layout 一致，單欄）。
    /// 過去 regular 走右欄 inline player；雙欄已收斂成 push（見 PodcastDetailRouter
    /// 檔頭）。push 目標 `PodcastPlayerView` 由 BookshelfView root 的
    /// `navigationDestination(for: PodcastNavRoute.self)` 接住。value-based +
    /// root 統一註冊是 freeze-fix 契約（PR #366/#368/#370/#373，見檔頭註解）。
    @ViewBuilder
    private func episodeRow(_ episode: PodcastEpisode) -> some View {
        let locked = PodcastAccess.showsProLock(tier: tier, episodeNumber: episode.episodeNumber, previewAvailable: episode.previewAvailable)
        let row = PodcastEpisodeRow(
            episode: episode,
            progress: progressMap[episode.remoteId],
            locked: locked
        )
        .contentShape(Rectangle())

        if locked {
            // Plain Button (not a closure NavigationLink) so we don't reintroduce
            // the LazyVStack eager-destination freeze (PR #366/#368/#370/#373) and
            // never navigate into the player for a gated episode.
            Button { handleLockedTap() } label: { row }
                .buttonStyle(.plain)
                .accessibilityIdentifier("podcast.episode.\(episode.remoteId)")
        } else {
            NavigationLink(value: PodcastNavRoute.episode(episodeRemoteId: episode.remoteId)) {
                row
            }
            .buttonStyle(.plain)
            .disabled(!episode.audioAvailable)
            .accessibilityIdentifier("podcast.episode.\(episode.remoteId)")
            .simultaneousGesture(
                TapGesture().onEnded {
                    warmConnection(for: episode)
                }
            )
        }
    }

    private var sortMenu: some View {
        Menu {
            ForEach(EpisodeSort.allCases) { option in
                Button {
                    withAnimation(AppMotion.phaseChange) { sort = option }
                } label: {
                    Label(option.label, systemImage: option.systemImage)
                }
            }
        } label: {
            HStack(spacing: skin.spacing.tinyGap) {
                Text(sort.label)
                Image(systemName: "chevron.down")
            }
            .font(skin.typography.caption)
            .foregroundStyle(skin.palette.accent)
        }
    }

    /// Fires AVFoundation's DNS/TLS/first-Range while the navigation transition
    /// is still animating (~300ms). Token fetch races the transition — even if
    /// it finishes after the player view appears, the second auth'd Range
    /// inside the engine reuses the warmed connection.
    private func warmConnection(for episode: PodcastEpisode) {
        guard
            let urlStr = episode.audioURL,
            let url = URL(string: urlStr)
        else { return }
        Task { @MainActor in
            guard let headers = await Self.audioPreloadHeaders(kgService: kgService) else { return }
            PodcastAssetPreloader.shared.preload(url: url, headers: headers)
        }
    }

    static func audioPreloadHeaders(kgService: any KGServing) async -> [String: String]? {
        guard let token = await kgService.authTokenWithoutInvalidation() else { return nil }
        return ["Authorization": "Bearer \(token)"]
    }
}
