import SwiftUI
import SwiftData

struct PodcastEpisodeRow: View {
    let episode: PodcastEpisode
    let progress: PodcastProgress?
    @Environment(\.appSkin) private var skin

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
        guard sec.isFinite, sec >= 0 else { return "--:--" }
        let total = Int(sec)
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    private func formatDate(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return L10n.string("今天") }
        if cal.isDateInYesterday(date) { return L10n.string("昨天") }
        let sameYear = cal.isDate(date, equalTo: Date(), toGranularity: .year)
        // template → ICU 給各 locale 最佳化:
        // sameYear: en="May 22" / ja="5月22日" / zh-Hant="5月22日" / ko="5월 22일"
        // crossYear: en="May 22, 2025" / ja="2025年5月22日" / zh-Hant="2025/5/22"
        let template = sameYear ? "Md" : "yMd"
        return LocaleAwareFormatter.shared.string(from: date, template: template)
    }
}
