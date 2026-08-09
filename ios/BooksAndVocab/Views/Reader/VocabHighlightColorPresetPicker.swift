#if os(iOS)
import SwiftUI

/// 生字標記色票選擇。刻意仍是自繪的色票格（第一刀原生化明文排除它 ——
/// 它同時服務 podcast 設定 popover，另立票），但選擇塊本身已改用兩個設定面
/// 共用的 `SettingsSelectionTile`，不再有 reader 專屬的第二份實作。
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
                        SettingsSelectionTile(isSelected: isSelected, density: .compact) {
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
