#if os(iOS)
import SwiftUI

/// Reader / Podcast 共用的生字標記色票選擇。選項本身使用 iOS 26
/// `Picker(.palette)`，讓系統負責選取語意、鍵盤與 Liquid Glass surface；
/// 色票仍讀同一份 `VocabHighlightColorPreset`，不另造一套色彩來源。
struct VocabHighlightColorPresetPicker: View {
    @ObserveInjection private var inject
    @Binding var selection: VocabHighlightColorPreset
    let title: String
    let accessibilityIdentifier: String?
    @Environment(\.appSkin) private var appSkin
    @Environment(\.colorScheme) private var colorScheme

    init(
        selection: Binding<VocabHighlightColorPreset>,
        title: String,
        accessibilityIdentifier: String? = nil
    ) {
        self._selection = selection
        self.title = title
        self.accessibilityIdentifier = accessibilityIdentifier
    }
    var body: some View {
        Menu {
            ForEach(VocabHighlightColorPreset.allCases) { preset in
                Button {
                    selection = preset
                } label: {
                    Text(L10n.string(preset.titleKey))
                }
                .modifier(
                    OptionalAccessibilityIdentifier(
                        id: accessibilityIdentifier.map { "\($0).\(preset.rawValue)" }
                    )
                )
            }
        } label: {
            HStack(spacing: AppSpacing.s2) {
                Text(title)
                Spacer(minLength: AppSpacing.s2)
                Circle()
                    .fill(selection.swiftUIColor(for: colorScheme))
                    .frame(width: 18, height: 18)
                    .overlay {
                        Circle()
                            .stroke(appSkin.palette.cardBorder, lineWidth: 1)
                    }
                Image(systemName: "chevron.up.chevron.down")
                    .font(appSkin.typography.iconSmall)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .accessibilityHidden(true)
            }
        }
        .buttonStyle(.borderless)
        .modifier(OptionalAccessibilityIdentifier(id: accessibilityIdentifier))
        .enableInjection()
    }
}

private struct OptionalAccessibilityIdentifier: ViewModifier {
    let id: String?

    func body(content: Content) -> some View {
        if let id {
            content.accessibilityIdentifier(id)
        } else {
            content
        }
    }
}
#endif
