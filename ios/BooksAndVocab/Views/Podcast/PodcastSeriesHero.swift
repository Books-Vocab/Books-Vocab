import SwiftUI
import SwiftData

/// Streaming-style series header: an ambient blurred-artwork backdrop that melts
/// into the page, the cover floating on it, then the title + host/length meta.
/// Pure presentation — it owns no navigation, so it's safe to drop anywhere
/// (the play CTA lives in `PodcastContinueCard`, wrapped by the owning view to
/// preserve the value-based-push freeze contract).
struct PodcastSeriesHero: View {
    @ObserveInjection private var inject
    let series: PodcastSeries
    @Environment(\.appSkin) private var skin

    private var coverColor: Color { NotebookPalette.color(for: series.color) }
    private var pattern: NotebookCoverPattern? {
        series.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) }
    }

    private var backdropHeight: CGFloat { 196 }
    private var coverSize: CGFloat { 136 }

    var body: some View {
        VStack(spacing: skin.spacing.statusHeroGap) {
            backdrop
                .overlay {
                    NotebookCoverView(
                        color: coverColor,
                        pattern: pattern,
                        coverImagePath: series.coverImagePath,
                        name: series.title
                    )
                    .frame(width: coverSize, height: coverSize)
                    // 136pt 方形節目封面 —— 尺寸規則 >70pt 落 card（不是 icon，icon 保留
                    // 給小尺寸 app-icon 式方塊）。r 由 8 → 10.2，與書封同一手感。
                    .clipShape(AppRoundedRect(roundness: AppRoundness.card))
                    .appElevation(.z3)
                }

            Text(series.title)
                .font(skin.typography.displayTitle)
                .foregroundStyle(skin.palette.primaryText)
                .multilineTextAlignment(.center)
                .lineLimit(3)
                .truncationMode(.tail)

            if let meta = metaText {
                Text(meta)
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.tertiaryText)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
            }
        }
        .enableInjection()
    }

    /// Ambient band: a cover-colour wash (always predictable) with the real
    /// artwork blurred over it at low opacity, faded into `pageBackground` at the
    /// bottom so there's no hard edge — the streaming "glow behind the cover".
    private var backdrop: some View {
        ZStack {
            LinearGradient(
                colors: [coverColor.opacity(0.42), coverColor.opacity(0.12), .clear],
                startPoint: .top,
                endPoint: .bottom
            )

            if series.coverImagePath != nil {
                NotebookCoverView(
                    color: coverColor,
                    pattern: pattern,
                    coverImagePath: series.coverImagePath,
                    name: "", // i18n-allow: empty backdrop has no label
                    showsName: false
                )
                .frame(maxWidth: .infinity)
                .frame(height: backdropHeight)
                .clipped()
                .blur(radius: 32)
                .opacity(0.4)
                .allowsHitTesting(false)
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: backdropHeight)
        .overlay {
            LinearGradient(
                colors: [.clear, .clear, skin.palette.pageBackground],
                startPoint: .top,
                endPoint: .bottom
            )
        }
        .clipped()
        .accessibilityHidden(true)
    }

    private var metaText: String? {
        var parts: [String] = []
        if !series.hostNames.isEmpty {
            parts.append(series.hostNames.joined(separator: ", "))
        }
        if series.episodeCount > 0 {
            parts.append(L10n.format("%@ 集", String(series.episodeCount)))
        }
        if series.totalDurationSec > 0 {
            parts.append(formatTotalDuration(series.totalDurationSec))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
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
}

/// The series-hero primary CTA, rendered as a streaming "continue listening"
/// card: a play/lock disc + the action verb + the target episode + remaining
/// time. Pure content — the owning view wraps it in a value-based
/// `NavigationLink` (playable) or a plain `Button` (gate), mirroring the
/// per-row freeze contract. Never builds navigation itself.
struct PodcastContinueCard: View {
    @ObserveInjection private var inject
    let episode: PodcastEpisode
    let progress: PodcastProgress?
    let action: PodcastHeroAction
    @Environment(\.appSkin) private var skin

    private var isActionable: Bool { action != .unavailable }

    private var discIcon: String {
        switch action {
        case .signIn: return "person.crop.circle"
        case .upgrade: return "lock.fill"
        case .unavailable: return "icloud.slash"
        case .preview, .replay, .resume, .play: return "play.fill"
        }
    }

    private var eyebrow: String {
        switch action {
        case .signIn: return L10n.string("podcast.guest.cta.signInToListen")
        case .upgrade: return L10n.string("podcast.locked.cta.upgrade")
        case .unavailable: return L10n.string("音訊暫不可用")
        case .preview: return L10n.string("podcast.preview.cta.listenFree")
        case .replay: return L10n.string("重新播放")
        case .resume: return L10n.string("繼續播放")
        case .play: return L10n.string("開始播放")
        }
    }

    /// Remaining time only matters for an in-progress resume; everything else
    /// (fresh, replay, preview, gated) has no meaningful "time left".
    private var remainingText: String? {
        guard action == .resume,
              let p = progress,
              episode.durationSec > 0 else { return nil }
        let remaining = max(0, episode.durationSec - p.lastPlayedTime)
        return L10n.format("podcast.continue.remaining", PodcastClock.format(remaining))
    }

    private var progressFraction: Double {
        guard action == .resume, let p = progress, episode.durationSec > 0 else { return 0 }
        return min(1, max(0, p.lastPlayedTime / episode.durationSec))
    }

    var body: some View {
        HStack(spacing: skin.spacing.cardPadding) {
            ZStack {
                Circle()
                    .fill(isActionable ? skin.palette.brandHero : skin.palette.progressBarBackground)
                Image(systemName: discIcon)
                    .font(skin.typography.iconSmall)
                    .foregroundStyle(isActionable ? AppColors.onBrandHero : skin.palette.tertiaryText)
            }
            .frame(width: 46, height: 46)

            VStack(alignment: .leading, spacing: skin.spacing.tinyGap) {
                Text(eyebrow)
                    .font(skin.typography.caption)
                    .foregroundStyle(isActionable ? skin.palette.primaryText : skin.palette.tertiaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)

                Text(episode.displayTitle)
                    .font(skin.typography.sectionTitle)
                    .foregroundStyle(skin.palette.primaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)

                if progressFraction > 0 {
                    ProgressCapsule(
                        progress: progressFraction,
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
            .frame(maxWidth: .infinity, alignment: .leading)

            Spacer(minLength: skin.spacing.tinyGap)

            Image(systemName: action.navigatesToPlayer ? "chevron.right" : "lock.fill")
                .font(skin.typography.iconTiny)
                .foregroundStyle(skin.palette.quaternaryText)
                .opacity(isActionable ? 1 : 0.6)
        }
        .padding(skin.spacing.cardPadding)
        .background(
            AppRoundedRect(roundness: AppRoundness.card)
                .fill(skin.palette.cardBackground)
        )
        .appElevation(.z1)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .enableInjection()
    }
}

#if os(iOS)
#Preview("PodcastSeriesHero") {
    let series = PodcastSeries(
        remoteId: "s-1",
        title: "Atomic Habits Unpacked",
        hostNames: ["Ava Chen", "Leo Park"]
    )
    series.color = "#4A90D9" // token-allow: preview fixture notebook data color
    series.coverPattern = NotebookCoverPattern.waves.rawValue
    series.episodeCount = 7
    series.totalDurationSec = 7 * 932

    func ep(_ n: Int, _ title: String, audio: Bool = true, preview: Bool = false) -> PodcastEpisode {
        let e = PodcastEpisode(remoteId: "s-1_ep_\(n)", episodeNumber: n, title: title, durationSec: 932)
        e.audioAvailable = audio
        e.previewAvailable = preview
        return e
    }

    return AppThemeContainer {
        ScrollView {
            VStack(spacing: AppSpacing.s4) {
                PodcastSeriesHero(series: series)

                PodcastContinueCard(
                    episode: ep(2, "On Deep Work and Attention"),
                    progress: PodcastProgress(episodeRemoteId: "s-1_ep_2", lastPlayedTime: 410),
                    action: .resume
                )
                PodcastContinueCard(episode: ep(1, "The Comfort Crisis"), progress: nil, action: .play)
                PodcastContinueCard(episode: ep(1, "The Comfort Crisis", preview: true), progress: nil, action: .preview)
                PodcastContinueCard(episode: ep(1, "The Comfort Crisis"), progress: nil, action: .signIn)
                PodcastContinueCard(episode: ep(3, "Habits That Compound"), progress: nil, action: .upgrade)
                PodcastContinueCard(episode: ep(4, "Pending Upload", audio: false), progress: nil, action: .unavailable)
            }
            .padding(AppSpacing.s4)
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
