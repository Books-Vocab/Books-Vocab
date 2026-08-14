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
        Picker(title, selection: $selection) {
            ForEach(VocabHighlightColorPreset.allCases) { preset in
                Label {
                    Text(L10n.string(preset.titleKey))
                } icon: {
                    Circle()
                        .fill(preset.swiftUIColor(for: colorScheme))
                        .frame(width: 18, height: 18)
                        .overlay {
                            Circle()
                                .stroke(appSkin.palette.cardBorder, lineWidth: 1)
                        }
                }
                .modifier(
                    OptionalAccessibilityIdentifier(
                        id: accessibilityIdentifier.map { "\($0).\(preset.rawValue)" }
                    )
                )
                .tag(preset)
            }
        }
        .pickerStyle(.palette)
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
