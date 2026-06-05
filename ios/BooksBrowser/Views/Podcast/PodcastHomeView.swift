//
//  PodcastHomeView.swift
//  BooksBrowser
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
import Inject

/// 播客頂層 section 入口。自有 `NavigationStack(path:)`；series 卡片走 value-based
/// `NavigationLink(value: PodcastNavRoute.series(...))`，由本 stack root 的
/// `navigationDestination(for: PodcastNavRoute.self)` 接住（freeze 契約，
/// PR #366/#368/#370/#373）。
struct PodcastHomeView: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    @Query(filter: #Predicate<PodcastSeries> { !$0.isDeleted }, sort: \.sortOrder)
    private var podcastSeries: [PodcastSeries]

    @State private var navigationPath = NavigationPath()

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

    var body: some View {
        NavigationStack(path: $navigationPath) {
            ZStack {
                appTheme.palette.pageBackground
                    .ignoresSafeArea()

                if sortedPodcastSeries.isEmpty {
                    emptyState
                } else {
                    seriesGrid
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
            .task {
                if authManager.isLoggedIn {
                    let outcome = await PodcastSyncService(kgService: kgService).syncAll(context: modelContext)
                    if outcome == .listFetchFailed {
                        toastCoordinator.warning("同步失敗".localized)
                    }
                    await warmFollowedSeriesAudio()
                }
            }
        }
        .enableInjection()
    }

    // MARK: - Series 網格

    private var seriesGrid: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
                ForEach(sortedPodcastSeries) { series in
                    NavigationLink(value: PodcastNavRoute.series(seriesRemoteId: series.remoteId)) {
                        PodcastSeriesCard(series: series, coverHeight: coverHeight)
                    }
                    .buttonStyle(.bookshelfCard)
                    .accessibilityLabel("\(series.title), podcast")
                    .transition(.bookshelfCard)
                    .contextMenu {
                        Button {
                            toggleFollow(series)
                        } label: {
                            Label(
                                (series.isFollowed ? "取消追蹤" : "追蹤").localized,
                                systemImage: series.isFollowed ? "star.slash" : "star"
                            )
                        }
                    }
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppSpacing.s2)
            .animateContentFade(podcastSeries.count)
        }
        .refreshable {
            await refreshPodcastCatalog()
        }
    }

    // MARK: - 空狀態

    private var emptyState: some View {
        ScrollView {
            VStack(spacing: AppSpacing.s4) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: "尚無播客".localized,
                    systemImage: "waveform",
                    description: "追蹤喜歡的節目，從這裡開始收聽".localized,
                    guidanceText: "下拉重新整理以同步節目",
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

    /// Pull-to-refresh entry. A series-list fetch failure surfaces a warning
    /// toast；partial / auxiliary failures stay silent。
    @MainActor
    private func refreshPodcastCatalog() async {
        guard authManager.isLoggedIn else { return }
        let outcome = await PodcastSyncService(kgService: kgService).syncAll(context: modelContext)
        if outcome == .listFetchFailed {
            toastCoordinator.warning("同步失敗".localized)
        }
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
            toastCoordinator.error("追蹤狀態儲存失敗".localized)
        }
    }
}
