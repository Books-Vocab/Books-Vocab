import SwiftUI
import SwiftData

struct PodcastEpisodeRow: View {
    let episode: PodcastEpisode
    let progress: PodcastProgress?
    @Environment(\.vocabSkin) private var skin

    init(episode: PodcastEpisode, progress: PodcastProgress? = nil) {
        self.episode = episode
        self.progress = progress
    }

    private var isCompleted: Bool { progress?.completed == true }
    private var hasProgress: Bool {
        guard let p = progress else { return false }
        return !p.completed && p.lastPlayedTime > 0 && episode.durationSec > 0
    }
    private var progressFraction: Double {
        guard hasProgress, let p = progress else { return 0 }
        return min(1, p.lastPlayedTime / episode.durationSec)
    }

    var body: some View {
        HStack(alignment: .top, spacing: skin.spacing.rowContentSpacing) {
            VStack(alignment: .leading, spacing: skin.spacing.tinyGap) {
                Text(episode.title)
                    .font(skin.typography.sectionTitle)
                    .foregroundStyle(episode.audioAvailable ? skin.palette.primaryText : skin.palette.tertiaryText)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)

                metadataLine

                if hasProgress {
                    ProgressCapsule(
                        progress: progressFraction,
                        label: nil,
                        fillColor: skin.palette.accent,
                        trackColor: skin.palette.progressBarBackground,
                        height: 3
                    )
                    .padding(.top, skin.spacing.tinyGap)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            trailingAccessory
                .padding(.top, skin.spacing.compactRowAccessoryTopInset)
        }
        .padding(.vertical, skin.spacing.compactRowVerticalPadding)
        .padding(.horizontal, skin.spacing.cardPadding)
        .contentShape(Rectangle())
    }

    private var metadataLine: some View {
        HStack(spacing: skin.spacing.metadataGap) {
            Text("Ep \(episode.episodeNumber)")
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.secondaryText)

            Text("·")
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.quaternaryText)

            Text(formatDate(episode.createdAt))
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.tertiaryText)

            Text("·")
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.quaternaryText)

            Text(formatDuration(episode.durationSec))
                .font(skin.typography.monoLabel)
                .foregroundStyle(skin.palette.tertiaryText)

            if episode.subtitleAvailable {
                Image(systemName: "captions.bubble.fill")
                    .font(skin.typography.iconTiny)
                    .foregroundStyle(skin.palette.success)
            }
        }
    }

    @ViewBuilder
    private var trailingAccessory: some View {
        if isCompleted {
            Image(systemName: "checkmark.circle.fill")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.success)
        } else if !episode.audioAvailable {
            Image(systemName: "icloud.slash")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.quaternaryText)
        } else {
            Image(systemName: "play.circle.fill")
                .font(skin.typography.iconSmall)
                .foregroundStyle(skin.palette.accent)
        }
    }

    private func formatDuration(_ sec: Double) -> String {
        let total = Int(sec)
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }

    private func formatDate(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return "今天" }
        if cal.isDateInYesterday(date) { return "昨天" }
        let sameYear = cal.isDate(date, equalTo: Date(), toGranularity: .year)
        return (sameYear ? Self.sameYearFormatter : Self.crossYearFormatter).string(from: date)
    }

    private static let sameYearFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_TW")
        f.dateFormat = "M月d日"
        return f
    }()

    private static let crossYearFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_TW")
        f.dateFormat = "yyyy/M/d"
        return f
    }()
}
