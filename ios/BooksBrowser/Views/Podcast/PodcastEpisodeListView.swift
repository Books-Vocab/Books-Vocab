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
    case episode(episodeRemoteId: String)
}

private enum EpisodeSort: String, CaseIterable, Identifiable {
    case ascending, descending
    var id: String { rawValue }
    var label: String {
        switch self {
        case .ascending: return "集數由小到大"
        case .descending: return "集數由大到小"
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
    let seriesId: String
    @Environment(\.vocabSkin) private var skin
    @Environment(\.modelContext) private var modelContext

    @Query(sort: \PodcastEpisode.episodeNumber) private var allEpisodes: [PodcastEpisode]
    @Query private var allProgress: [PodcastProgress]
    @Query(filter: #Predicate<PodcastSeries> { !$0.isDeleted }) private var allSeries: [PodcastSeries]

    @State private var sort: EpisodeSort = .ascending

    private var series: PodcastSeries? {
        allSeries.first { $0.remoteId == seriesId }
    }

    private var rawEpisodes: [PodcastEpisode] {
        allEpisodes.filter { $0.series?.remoteId == seriesId }
    }

    private var episodes: [PodcastEpisode] {
        switch sort {
        case .ascending: return rawEpisodes
        case .descending: return Array(rawEpisodes.reversed())
        }
    }

    private var progressMap: [String: PodcastProgress] {
        let ids = Set(rawEpisodes.map(\.remoteId))
        return Dictionary(
            allProgress.lazy
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
        if rawEpisodes.isEmpty {
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
                    episodesSection
                }
                .padding(.horizontal, skin.spacing.cardPadding)
                .padding(.bottom, skin.spacing.sheetSectionSpacing)
            }
            .background(skin.palette.pageBackground.ignoresSafeArea())
        }
        .navigationTitle(series?.title ?? "")
        .navigationBarTitleDisplayMode(.inline)
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
            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusLarge, style: .continuous))
            .shadow(color: skin.palette.shadow, radius: 18, x: 0, y: 8)
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
                if unavailable { return "音訊暫不可用" }
                if allCompleted { return "重新播放" }
                if (progress?.lastPlayedTime ?? 0) > 0 && progress?.completed != true { return "繼續播放" }
                return "開始播放"
            }()
            let icon = unavailable ? "icloud.slash" : "play.fill"
            NavigationLink(value: PodcastNavRoute.episode(episodeRemoteId: target.remoteId)) {
                Label(label, systemImage: icon)
            }
            .buttonStyle(.appAction(.primary))
            .disabled(unavailable)
            .frame(maxWidth: 280)
        }
    }

    // MARK: - Episodes section

    private var episodesSection: some View {
        VStack(alignment: .leading, spacing: skin.spacing.inlineGap) {
            HStack {
                Text("集數")
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
                    .disabled(!episode.audioAvailable)

                    if index < episodes.count - 1 {
                        Divider()
                            .background(skin.palette.divider)
                            .padding(.leading, skin.spacing.cardPadding)
                    }
                }
            }
            .padding(.vertical, skin.spacing.microGap)
            .background(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusMedium, style: .continuous)
                    .fill(skin.palette.cardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusMedium, style: .continuous)
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
            .font(skin.typography.captionStrong)
            .foregroundStyle(skin.palette.accent)
        }
    }

    private func formatTotalDuration(_ sec: Double) -> String {
        guard sec.isFinite, sec > 0 else { return "" }
        let total = Int(sec)
        let h = total / 3600
        let m = (total % 3600) / 60
        if h > 0 {
            return "共 \(h) 小時 \(m) 分"
        }
        return "共 \(m) 分鐘"
    }
}
