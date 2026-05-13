import SwiftUI

struct PodcastBadge: View {
    @Environment(\.vocabSkin) private var skin

    var body: some View {
        Image(systemName: "waveform")
            .font(AppFonts.caption2(weight: .bold))
            .foregroundStyle(skin.palette.primaryTextMuted)
            .padding(.horizontal, skin.spacing.chipHorizontalPadding)
            .padding(.vertical, skin.spacing.chipVerticalPadding)
            .background(
                Capsule()
                    .fill(skin.palette.mutedFill.opacity(0.85))
            )
            .padding(skin.spacing.cardPadding / 2)
    }
}
