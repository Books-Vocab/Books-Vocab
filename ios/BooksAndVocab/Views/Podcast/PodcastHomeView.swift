//
//  PodcastHomeView.swift
//  Books & Vocab
//
//  播客首頁 — 獨立頂層 section（軸 B Phase 3）。
//
//  podcast 過去無頂層入口、寄生 BookshelfView 的 NavigationStack，逼出一整套
//  Catalyst overlay-pane workaround（regular 用 `selectedSeriesRemoteId` 疊加層、
//  root content 不可 swap）。抽成獨立 section 後，series→episode→player push
//  全在**本 view 自己的** `NavigationStack(path:)` 裡完成，不再干擾書架 root，
//  Catalyst overlay-pane 那套 workaround 一併消滅，series 啟動全平台統一 value-based
//  push（鏡射已驗證穩定的 `NotebookListView` path-bound root 模式）。
//

import SwiftUI
import SwiftData

enum PodcastHomePhase: Equatable {
    case loading
    case error
    case empty
    case content

    static func resolve(
        isLoggedIn: Bool,
        isSyncing: Bool,
        syncFailed: Bool,
        seriesCount: Int
    ) -> PodcastHomePhase {
        if seriesCount > 0 { return .content }
        if isSyncing { return .loading }
        if syncFailed { return .error }
        return .empty
    }
}

/// 播客頂層 section 入口。自有 `NavigationStack(path:)`；series 卡片走 value-based
/// `NavigationLink(value: PodcastNavRoute.series(...))`，由本 stack root 的
/// `navigationDestination(for: PodcastNavRoute.self)` 接住（freeze 契約，
/// PR #366/#368/#370/#373）。
struct PodcastHomeView: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.appSkin) private var skin
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.catalogTaskPolicy) private var catalogTaskPolicy

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    @Query(filter: #Predicate<PodcastSeries> { !$0.isSoftDeleted }, sort: \.sortOrder)
    private var podcastSeries: [PodcastSeries]

    /// 跨 series 的播放進度（CloudStore）。home 是輕量列表頁、無高頻 tick，故可
    /// 直接 `@Query` 觀察（不同於 `PodcastPlayerView`/`PodcastEpisodeListView` 因
    /// 15Hz tick 而改用一次性 fetch）。最近更新者排前 → 繼續收聽 shelf 順序。
    @Query(sort: \PodcastProgress.updatedAt, order: .reverse)
    private var allProgress: [PodcastProgress]

    @State private var navigationPath = NavigationPath()
    @State private var isSyncingCatalog = false
    @State private var syncFailed = false

    private var phase: PodcastHomePhase {
        PodcastHomePhase.resolve(
            isLoggedIn: authManager.isLoggedIn,
            isSyncing: isSyncingCatalog,
            syncFailed: syncFailed,
            seriesCount: sortedPodcastSeries.count
        )
    }

    /// 已追蹤的浮上來；同組內維持 server `sortOrder`。`@Query` macro 不支援多重
    /// SortDescriptor，這裡 in-memory 穩定排序（O(n log n)，series 數 << 100）。
    /// 與 `BookshelfView` 舊邏輯逐字一致。
    private var sortedPodcastSeries: [PodcastSeries] {
        podcastSeries.enumerated()
            .sorted { lhs, rhs in
                if lhs.element.isFollowed != rhs.element.isFollowed {
                    return lhs.element.isFollowed && !rhs.element.isFollowed
                }
                return lhs.offset < rhs.offset
            }
            .map(\.element)
    }

    private var columns: [GridItem] { [layoutMode.bookshelfGridItem] }
    private var coverHeight: CGFloat { layoutMode.bookshelfCoverHeight }

    /// 「繼續收聽」資料：把每筆有效進度（曾播放、未完成）對應回其 episode/series。
    /// 以 `podcastSeries.episodes` 在記憶體建 remoteId→(episode,series) map，避免
    /// 跨 store fetch。tap 進 player 後仍由 player 防禦式 gate 把關 entitlement。
    private var continueItems: [PodcastContinueItem] {
        var epMap: [String: (PodcastEpisode, PodcastSeries)] = [:]
        for s in podcastSeries {
            for e in s.episodes { epMap[e.remoteId] = (e, s) }
        }
        return allProgress.compactMap { p in
            guard p.lastPlayedTime > 0, !p.completed,
                  let (episode, series) = epMap[p.episodeRemoteId] else { return nil }
            return PodcastContinueItem(episode: episode, series: series, progress: p)
        }
    }

    var body: some View {
        NavigationStack(path: $navigationPath) {
            ZStack {
                appTheme.palette.pageBackground
                    .ignoresSafeArea()

                switch phase {
                case .loading:
                    loadingState
                case .error:
                    syncErrorState
                case .empty:
                    emptyState
                case .content:
                    content
                }
            }
            .navigationTitle(L10n.string("app.section.podcasts"))
            .largeNavigationBarTitle()
            // 統一在 NavigationStack root 註冊 destination（避免 nested-modifier
            // 競爭）；series / episode 全平台單欄 push。
            .navigationDestination(for: PodcastNavRoute.self) { route in
                switch route {
                case .series(let seriesRemoteId):
                    PodcastEpisodeListView(seriesId: seriesRemoteId)
                case .episode(let episodeRemoteId):
                    PodcastPlayerView(episodeId: episodeRemoteId)
                }
            }
            // `.task(id:)` 對齊 NotebookListView：login 狀態翻轉才重跑，避免
            // Catalyst sidebar 切回 podcast section（remount）以外的無謂重同步。
            .task(id: authManager.isLoggedIn) {
                guard catalogTaskPolicy.runsTasks else { return }
                await syncPodcastCatalog(showToastOnFailure: true, warmAudioAfterSync: true)
            }
        }
        .enableInjection()
    }

    // MARK: - 內容（continue shelf 堆疊 + 所有節目 grid）

    private var content: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AppSpacing.s5) {
                if !continueItems.isEmpty {
                    continueShelf
                        .padding(.top, AppSpacing.s2)
                }
                seriesGridSection
            }
            .animateContentFade(podcastSeries.count)
        }
        .refreshable {
            await refreshPodcastCatalog()
        }
    }

    /// 繼續收聽 — 跨 series 最近播放未完成；空則整段不顯示。LazyHStack 內走
    /// value-based `NavigationLink`（freeze 契約，等同 LazyVStack）。
    private var continueShelf: some View {
        PodcastShelf(title: L10n.string("繼續收聽")) {
            ForEach(continueItems) { item in
                NavigationLink(value: PodcastNavRoute.episode(episodeRemoteId: item.episode.remoteId)) {
                    PodcastContinueRailCard(episode: item.episode, series: item.series, progress: item.progress)
                }
                .buttonStyle(.bookshelfCard)
            }
        }
    }

    /// 所有節目 — followed 排前 + star badge。有 continue shelf 時冠標題與上段區隔。
    @ViewBuilder
    private var seriesGridSection: some View {
        if !continueItems.isEmpty {
            Text(L10n.string("所有節目"))
                .font(skin.typography.sectionTitle)
                .foregroundStyle(skin.palette.primaryText)
                .lineLimit(1)
                .truncationMode(.tail)
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
            ForEach(sortedPodcastSeries) { series in
                NavigationLink(value: PodcastNavRoute.series(seriesRemoteId: series.remoteId)) {
                    PodcastSeriesCard(series: series, coverHeight: coverHeight)
                }
                .buttonStyle(.bookshelfCard)
                .accessibilityIdentifier("podcast.series.\(series.remoteId)")
                .accessibilityLabel("\(series.title), podcast")
                .transition(.bookshelfCard)
                .contextMenu {
                    Button {
                        toggleFollow(series)
                    } label: {
                        Label(
                            L10n.string(series.isFollowed ? "取消追蹤" : "追蹤"),
                            systemImage: series.isFollowed ? "star.slash" : "star"
                        )
                    }
                }
            }
        }
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        .padding(.top, continueItems.isEmpty ? AppSpacing.s2 : 0)
    }

    // MARK: - 空狀態

    private var emptyState: some View {
        ScrollView {
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: L10n.string("尚無播客"),
                    systemImage: "waveform",
                    description: L10n.string("追蹤喜歡的節目，從這裡開始收聽"),
                    guidanceText: L10n.string("下拉重新整理以同步節目"),
                    style: .bookshelf(appTheme)
                )

                Spacer(minLength: 120)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        .refreshable {
            await refreshPodcastCatalog()
        }
    }

    private var loadingState: some View {
        VStack {
            Spacer()
            AppStateMessageCard(
                title: L10n.string("正在同步播客"),
                systemImage: "arrow.triangle.2.circlepath",
                description: L10n.string("正在向伺服器拉取最新節目清單")
            ) {
                ProgressView()
                    .controlSize(.small)
            }
            .frame(maxWidth: 420)
            Spacer()
        }
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
    }

    private var syncErrorState: some View {
        ScrollView {
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: L10n.string("同步失敗"),
                    systemImage: "exclamationmark.triangle",
                    description: L10n.string("目前無法取得播客節目清單"),
                    guidanceText: L10n.string("請確認網路連線後重試"),
                    action: AppEmptyStateAction(
                        title: L10n.string("重試"),
                        systemImage: "arrow.clockwise",
                        handler: {
                            Task { await refreshPodcastCatalog() }
                        }
                    ),
                    style: .bookshelf(appTheme)
                )

                Spacer(minLength: 120)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        .refreshable {
            await refreshPodcastCatalog()
        }
    }

    // MARK: - 同步 / 預熱 / 追蹤（自 BookshelfView re-home，行為逐字保留）

    @MainActor
    private func syncPodcastCatalog(showToastOnFailure: Bool, warmAudioAfterSync: Bool) async {
        isSyncingCatalog = true
        defer { isSyncingCatalog = false }

        let outcome = await PodcastSyncService(kgService: kgService).syncAll(context: modelContext)
        syncFailed = outcome == .listFetchFailed
        if syncFailed && showToastOnFailure {
            toastCoordinator.warning(L10n.string("同步失敗"))
        }
        if warmAudioAfterSync && authManager.isLoggedIn {
            await warmFollowedSeriesAudio()
        }
    }

    /// Pull-to-refresh entry. A series-list fetch failure surfaces a warning
    /// toast；partial / auxiliary failures stay silent。
    @MainActor
    private func refreshPodcastCatalog() async {
        await syncPodcastCatalog(showToastOnFailure: true, warmAudioAfterSync: false)
    }

    /// Predictive prefetch：暖機已追蹤 series 首集的 AVFoundation 連線，使從
    /// shelf 點進幾乎瞬間 `.ready`。受 preloader 自身 LRU(5) 上限。
    @MainActor
    private func warmFollowedSeriesAudio() async {
        let token: String
        do {
            token = try await kgService.currentAuthToken()
        } catch {
            return  // No auth → preload would 401; skip silently.
        }
        let headers = ["Authorization": "Bearer \(token)"]
        for series in podcastSeries where series.isFollowed {
            guard
                let first = series.episodes
                    .filter({ $0.audioAvailable })
                    .min(by: { $0.episodeNumber < $1.episodeNumber }),
                let urlStr = first.audioURL,
                let url = URL(string: urlStr)
            else { continue }
            PodcastAssetPreloader.shared.preload(url: url, headers: headers)
        }
    }

    /// Series context-menu 追蹤切換。樂觀翻轉 + 失敗回滾，與
    /// `PodcastEpisodeListView.toggleFollow` 共用 `PodcastFollowToggle` 契約。
    @MainActor
    private func toggleFollow(_ series: PodcastSeries) {
        var outcome: PodcastFollowToggle.Outcome = .saved
        withAnimation(AppMotion.phaseChange) {
            outcome = PodcastFollowToggle.perform(series: series) {
                modelContext.safeSave()
            }
        }
        if outcome == .rolledBack {
            toastCoordinator.error(L10n.string("追蹤狀態儲存失敗"))
        }
    }
}

/// 繼續收聽 shelf 的一筆：episode + 其 series + 進度。`Identifiable`（id=episode
/// remoteId）供 `ForEach`，episode 在 catalog 內唯一。
private struct PodcastContinueItem: Identifiable {
    let episode: PodcastEpisode
    let series: PodcastSeries
    let progress: PodcastProgress
    var id: String { episode.remoteId }
}
