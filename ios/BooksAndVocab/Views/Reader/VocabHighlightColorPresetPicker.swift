#if os(iOS)
import SwiftUI

/// Reader / Podcast 共用的生字標記色票選擇。預設色票保留原生 Menu；
/// 自訂色則交給系統 `ColorPicker`，只回寫同一份 sRGB 偏好資料，且不把
/// opacity 混進色彩值。
struct VocabHighlightColorPresetPicker: View {
    @ObserveInjection private var inject
    @Binding var selection: VocabHighlightColorPreset
    @Binding var customSRGB: VocabHighlightSRGB
    let title: String
    let accessibilityIdentifier: String?
    @Environment(\.appSkin) private var appSkin
    @Environment(\.colorScheme) private var colorScheme

    init(
        selection: Binding<VocabHighlightColorPreset>,
        customSRGB: Binding<VocabHighlightSRGB> = .constant(.default),
        title: String,
        accessibilityIdentifier: String? = nil
    ) {
        self._selection = selection
        self._customSRGB = customSRGB
        self.title = title
        self.accessibilityIdentifier = accessibilityIdentifier
    }
    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            Menu {
                ForEach(VocabHighlightColorPreset.presetCases) { preset in
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
                        .fill(selection.swiftUIColor(for: colorScheme, customSRGB: customSRGB))
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

            ColorPicker(
                L10n.string("自訂"),
                selection: customColorBinding,
                supportsOpacity: false
            )
            .modifier(
                OptionalAccessibilityIdentifier(
                    id: accessibilityIdentifier.map { "\($0).custom" }
                )
            )
        }
        .enableInjection()
    }

    private var customColorBinding: Binding<Color> {
        Binding(
            get: { customSRGB.color },
            set: {
                customSRGB = VocabHighlightSRGB(color: $0)
                selection = .custom
            }
        )
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
