import SwiftUI
import SwiftData

/// 串流首頁的泛用水平 shelf：section 標題 + 橫向滑動卡片列（YT Music / App Store
/// 那種 carousel）。codebase 首個泛用橫排容器。卡片由 caller 以 value-based
/// `NavigationLink` 包裹（freeze 契約），shelf 本身不持有 navigation。
struct PodcastShelf<Content: View>: View {
    @ObserveInjection private var inject
    let title: String
    @ViewBuilder var content: () -> Content
    @Environment(\.appSkin) private var skin

    var body: some View {
        VStack(alignment: .leading, spacing: skin.spacing.statusHeroGap) {
            Text(title)
                .font(skin.typography.sectionTitle)
                .foregroundStyle(skin.palette.primaryText)
                .lineLimit(1)
                .truncationMode(.tail)
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

            ScrollView(.horizontal, showsIndicators: false) {
                LazyHStack(spacing: AppSpacing.s3) {
                    content()
                }
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            }
        }
        .enableInjection()
    }
}

/// 「繼續收聽」橫排卡：直式封面縮圖（右下角 play disc）+ series 名 + 目標單集 +
/// 進度條 + 還剩時間。跨 series 顯示，固定寬。純展示——owner 用 value-based
/// `NavigationLink(value: .episode(...))` 包裹（freeze 契約）。
struct PodcastContinueRailCard: View {
    @ObserveInjection private var inject
    let episode: PodcastEpisode
    let series: PodcastSeries
    let progress: PodcastProgress?
    @Environment(\.appSkin) private var skin

    private let cardWidth: CGFloat = 150

    private var coverColor: Color { NotebookPalette.color(for: series.color) }
    private var pattern: NotebookCoverPattern? {
        series.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) }
    }

    private var fraction: Double {
        guard episode.durationSec > 0, let p = progress else { return 0 }
        return min(1, max(0, p.lastPlayedTime / episode.durationSec))
    }

    private var remainingText: String? {
        guard let p = progress, episode.durationSec > 0 else { return nil }
        let remaining = max(0, episode.durationSec - p.lastPlayedTime)
        return L10n.format("podcast.continue.remaining", PodcastClock.format(remaining))
    }

    /// VoiceOver 合併朗讀：series + 單集 + （有進度時）還剩，與視覺卡資訊對齊。
    private var accessibilityText: String {
        if let remainingText {
            return "\(series.title), \(episode.displayTitle), \(remainingText)"
        }
        return "\(series.title), \(episode.displayTitle)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            NotebookCoverView(
                color: coverColor,
                pattern: pattern,
                coverImagePath: series.coverImagePath,
                name: series.title
            )
            .frame(width: cardWidth, height: cardWidth)
            .clipShape(RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous))
            .overlay(alignment: .bottomTrailing) { playDisc }
            .appElevation(.z1)

            VStack(alignment: .leading, spacing: skin.spacing.tinyGap) {
                Text(series.title)
                    .font(AppFonts.caption(weight: .medium))
                    .foregroundStyle(skin.palette.primaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)

                Text(episode.displayTitle)
                    .font(AppFonts.caption2())
                    .foregroundStyle(skin.palette.tertiaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)

                if fraction > 0 {
                    ProgressCapsule(
                        progress: fraction,
                        label: nil,
                        fillColor: skin.palette.accent,
                        trackColor: skin.palette.progressBarBackground,
                        height: 3
                    )
                    .padding(.top, skin.spacing.tinyGap)
                }

                if let remainingText {
                    Text(remainingText)
                        .font(skin.typography.monoLabel)
                        .foregroundStyle(skin.palette.tertiaryText)
                        .monospacedDigit()
                }
            }
            .frame(width: cardWidth, alignment: .leading)
        }
        .frame(width: cardWidth)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityText)
        .enableInjection()
    }

    private var playDisc: some View {
        ZStack {
            Circle().fill(skin.palette.brandHero)
            Image(systemName: "play.fill")
                .font(skin.typography.iconTiny)
                .foregroundStyle(AppColors.onBrandHero)
        }
        .frame(width: 30, height: 30)
        .appElevation(.z1)
        .padding(AppSpacing.s2)
    }
}

#if os(iOS)
#Preview("PodcastShelf") {
    let series = PodcastSeries(remoteId: "s-1", title: "Atomic Habits Unpacked", hostNames: ["Ava Chen"])
    series.color = "#4A90D9" // token-allow: preview fixture notebook data color
    series.coverPattern = NotebookCoverPattern.waves.rawValue

    func ep(_ n: Int, _ title: String) -> PodcastEpisode {
        PodcastEpisode(remoteId: "s-1_ep_\(n)", episodeNumber: n, title: title, durationSec: 1832)
    }

    return AppThemeContainer {
        ScrollView {
            PodcastShelf(title: "繼續收聽".localized) {
                PodcastContinueRailCard(
                    episode: ep(2, "On Deep Work"),
                    series: series,
                    progress: PodcastProgress(episodeRemoteId: "s-1_ep_2", lastPlayedTime: 612)
                )
                PodcastContinueRailCard(
                    episode: ep(5, "A Very Long Episode Title That Should Truncate Cleanly"),
                    series: series,
                    progress: PodcastProgress(episodeRemoteId: "s-1_ep_5", lastPlayedTime: 1700)
                )
                PodcastContinueRailCard(episode: ep(1, "The Comfort Crisis"), series: series, progress: nil)
            }
            .padding(.vertical, AppSpacing.s4)
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
