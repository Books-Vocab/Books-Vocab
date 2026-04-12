import SwiftUI

struct SpeakerAccentBar: View {
    let speaker: String
    let hostNames: [String]
    @Environment(\.vocabSkin) private var skin

    private var barColor: Color {
        guard let index = hostNames.firstIndex(of: speaker) else {
            return skin.palette.primaryTextMuted
        }
        return index == 0 ? skin.palette.accent : skin.palette.success
    }

    var body: some View {
        RoundedRectangle(cornerRadius: skin.radii.tiny)
            .fill(barColor)
            .frame(width: 3)
    }
}

struct SpeakerChip: View {
    let speaker: String
    let hostNames: [String]
    @Environment(\.vocabSkin) private var skin

    private var chipColor: Color {
        guard let index = hostNames.firstIndex(of: speaker) else {
            return skin.palette.primaryTextMuted
        }
        return index == 0 ? skin.palette.accent : skin.palette.success
    }

    var body: some View {
        Text(speaker)
            .font(skin.typography.monoLabel)
            .foregroundStyle(chipColor)
            .padding(.horizontal, skin.spacing.chipHorizontalPadding)
            .padding(.vertical, skin.spacing.chipVerticalPadding / 2)
            .background(chipColor.opacity(0.12), in: Capsule())
    }
}
