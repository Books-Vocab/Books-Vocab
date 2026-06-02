import SwiftUI
import Inject

struct SpeakerAccentBar: View {
    @ObserveInjection private var inject
    let speaker: String
    let hostNames: [String]
    @Environment(\.appSkin) private var skin

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
            .enableInjection()
    }
}

struct SpeakerChip: View {
    @ObserveInjection private var inject
    let speaker: String
    let hostNames: [String]
    @Environment(\.appSkin) private var skin

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
            .enableInjection()
    }
}

#Preview("SpeakerAccentBar + Chip") {
    let hosts = ["Maya", "Kai"]
    return AppThemeContainer {
        VStack(alignment: .leading, spacing: AppSpacing.s4) {
            ForEach(hosts + ["Guest"], id: \.self) { speaker in
                HStack(spacing: AppSpacing.s3) {
                    SpeakerAccentBar(speaker: speaker, hostNames: hosts)
                        .frame(height: 32)
                    SpeakerChip(speaker: speaker, hostNames: hosts)
                }
            }
        }
        .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}
