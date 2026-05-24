import SwiftUI
import SwiftData
import Inject

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
    @State private var navigationLocked = false
    @State private var navigationUnlockTask: Task<Void, Never>?
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
                title: "無法載入集數",
                systemImage: "exclamationmark.triangle",
                retryAction: {
                    Task { await reloadFromStore() }
                }
            )
        }
        if rawEpisodes.isEmpty && hasLoadedOnce {
            return .empty(
                title: "尚無集數",
                systemImage: "waveform.slash",
                description: "此系列目前沒有可播放的集數",
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
        .onAppear {
            navigationUnlockTask?.cancel()
            navigationUnlockTask = nil
            navigationLocked = false
        }
        .onDisappear {
            navigationUnlockTask?.cancel()
            navigationUnlockTask = nil
        }
        .task(id: seriesId) {
            await reloadFromStore()
        }
        .enableInjection()
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
                predicate: #Predicate { $0.remoteId == sid && !$0.isDeleted }
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
        .accessibilityLabel(isFollowed ? "取消追蹤" : "追蹤")
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
            toastCoordinator.error("追蹤狀態儲存失敗")
        }
    }

    // MARK: - Hero

    private var heroHeader: some View {
        VStack(spacing: skin.spacing.statusHeroGap) {
            NotebookCoverView(
                color: NotebookPalette.color(for: series?.color),
                pattern: NotebookCoverPattern(rawValue: series?.coverPattern ?? "") ?? .waves,
                coverImagePath: series?.coverImagePath,
                name: series?.title ?? ""
            )
            .frame(width: 168, height: 168)
            .clipShape(RoundedRectangle(cornerRadius: AppRadius.lg, style: .continuous))
            .appElevation(.z3)
            .padding(.top, skin.spacing.sectionGap)

            Text(series?.title ?? "")
                .font(skin.typography.displayTitle)
                .foregroundStyle(skin.palette.primaryText)
                .multilineTextAlignment(.center)
                .lineLimit(3)

            if let meta = heroMetaText {
                Text(meta)
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.tertiaryText)
                    .multilineTextAlignment(.center)
            }

            heroActions
                .padding(.top, skin.spacing.inlineGap)
        }
        .padding(.bottom, skin.spacing.sectionGap)
    }

    private var heroMetaText: String? {
        guard let series else { return nil }
        var parts: [String] = []
        if !series.hostNames.isEmpty {
            parts.append(series.hostNames.joined(separator: ", "))
        }
        if series.episodeCount > 0 {
            parts.append("\(series.episodeCount) 集")
        }
        if series.totalDurationSec > 0 {
            parts.append(formatTotalDuration(series.totalDurationSec))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var heroActions: some View {
        if let target = continueEpisode {
            let progress = progressMap[target.remoteId]
            let unavailable = !target.audioAvailable
            let label: String = {
                if unavailable { return L10n.string("音訊暫不可用") }
                if allCompleted { return L10n.string("重新播放") }
                if (progress?.lastPlayedTime ?? 0) > 0 && progress?.completed != true { return L10n.string("繼續播放") }
                return L10n.string("開始播放")
            }()
            let icon = unavailable ? "icloud.slash" : "play.fill"
            NavigationLink(value: PodcastNavRoute.episode(episodeRemoteId: target.remoteId)) {
                Label(label, systemImage: icon)
            }
            .buttonStyle(.appAction(.primary))
            .disabled(unavailable || navigationLocked)
            .simultaneousGesture(
                TapGesture().onEnded {
                    beginNavigationLock()
                }
            )
            .frame(maxWidth: 280)
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
                message: "載入失敗，顯示快取資料",
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
            .padding(.horizontal, skin.spacing.microGap)

            VStack(spacing: 0) {
                ForEach(Array(episodes.enumerated()), id: \.element.id) { index, episode in
                    NavigationLink(value: PodcastNavRoute.episode(episodeRemoteId: episode.remoteId)) {
                        PodcastEpisodeRow(
                            episode: episode,
                            progress: progressMap[episode.remoteId]
                        )
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(!episode.audioAvailable || navigationLocked)
                    .simultaneousGesture(
                        TapGesture().onEnded {
                            beginNavigationLock()
                            warmConnection(for: episode)
                        }
                    )

                    if index < episodes.count - 1 {
                        Divider()
                            .background(skin.palette.divider)
                            .padding(.leading, skin.spacing.cardPadding)
                    }
                }
            }
            .padding(.vertical, skin.spacing.microGap)
            .background(
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .fill(skin.palette.cardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
                    .stroke(skin.palette.cardBorder, lineWidth: 0.5)
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

    private func formatTotalDuration(_ sec: Double) -> String {
        guard sec.isFinite, sec > 0 else { return "" }
        let total = Int(sec)
        let h = total / 3600
        let m = (total % 3600) / 60
        if h > 0 {
            return L10n.format("共 %@ 小時 %@ 分", String(h), String(m))
        }
        return L10n.format("共 %@ 分鐘", String(m))
    }

    @MainActor
    private func beginNavigationLock() {
        guard !navigationLocked else { return }
        navigationLocked = true
        navigationUnlockTask?.cancel()
        navigationUnlockTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(1))
            guard !Task.isCancelled else { return }
            navigationLocked = false
            navigationUnlockTask = nil
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
            var headers: [String: String] = [:]
            if let token = try? await kgService.currentAuthToken() {
                headers["Authorization"] = "Bearer \(token)"
            }
            PodcastAssetPreloader.shared.preload(url: url, headers: headers)
        }
    }
}
