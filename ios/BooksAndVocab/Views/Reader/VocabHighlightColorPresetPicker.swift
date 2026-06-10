#if os(iOS)
import SwiftUI

struct VocabHighlightColorPresetPicker: View {
    @ObserveInjection private var inject
    @Binding var selection: VocabHighlightColorPreset
    let title: String
    @Environment(\.appSkin) private var appSkin
    @Environment(\.colorScheme) private var colorScheme

    private let swatchSize: CGFloat = 18

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            Text(title)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.secondaryText)

            HStack(spacing: AppSpacing.s2) {
                ForEach(VocabHighlightColorPreset.allCases) { preset in
                    let isSelected = selection == preset
                    Button {
                        withAnimation(AppMotion.panelState) {
                            selection = preset
                        }
                    } label: {
                        ReaderSelectionTile(isSelected: isSelected) {
                            VStack(spacing: AppSpacing.s2) {
                                Circle()
                                    .fill(preset.swiftUIColor(for: colorScheme))
                                    .frame(width: swatchSize, height: swatchSize)
                                    .overlay {
                                        Circle()
                                            .stroke(appSkin.palette.cardBorder, lineWidth: 1)
                                    }
                                Text(L10n.string(preset.titleKey))
                                    .font(appSkin.typography.caption)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.75)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, ReaderMetrics.vocabOptionVerticalPadding)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(L10n.string(preset.titleKey))
                    .accessibilityAddTraits(isSelected ? .isSelected : [])
                }
            }
        }
        .enableInjection()
    }
}
#endif
