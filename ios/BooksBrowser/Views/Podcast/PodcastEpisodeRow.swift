import SwiftUI

struct PodcastEpisodeRow: View {
    let episode: PodcastEpisode
    @Environment(\.vocabSkin) private var skin

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
            }
        }
        .padding(.vertical, skin.spacing.compactRowVerticalPadding)
    }

    private func formatDuration(_ sec: Double) -> String {
        let m = Int(sec) / 60, s = Int(sec) % 60
        return String(format: "%d:%02d", m, s)
    }
}
