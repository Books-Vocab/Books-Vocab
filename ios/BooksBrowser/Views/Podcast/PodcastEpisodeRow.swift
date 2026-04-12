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

    var body: some View {
        VStack(alignment: .leading, spacing: skin.spacing.rowContentSpacing) {
            Text(episode.displayTitle)
                .font(skin.typography.sectionTitle)
                .foregroundStyle(skin.palette.primaryText)
                .lineLimit(2)

            HStack(spacing: skin.spacing.metadataGap) {
                Text(formatDuration(episode.durationSec))
                    .font(skin.typography.monoLabel)
                    .foregroundStyle(skin.palette.tertiaryText)

                if episode.audioAvailable {
                    Image(systemName: "waveform.circle.fill")
                        .font(.caption)
                        .foregroundStyle(skin.palette.accent)
                }
                if episode.subtitleAvailable {
                    Image(systemName: "captions.bubble.fill")
                        .font(.caption)
                        .foregroundStyle(skin.palette.success)
                }

                Spacer()

                if let progress {
                    if progress.completed {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(skin.palette.success)
                    }
                }
            }

            if let progress, !progress.completed, episode.durationSec > 0, progress.lastPlayedTime > 0 {
                ProgressCapsule(
                    progress: progress.lastPlayedTime / episode.durationSec,
                    label: nil,
                    fillColor: skin.palette.accent,
                    trackColor: skin.palette.accent.opacity(0.15),
                    height: 4
                )
            }
        }
        .padding(.vertical, skin.spacing.compactRowVerticalPadding)
    }

    private func formatDuration(_ sec: Double) -> String {
        let m = Int(sec) / 60, s = Int(sec) % 60
        return String(format: "%d:%02d", m, s)
    }
}
