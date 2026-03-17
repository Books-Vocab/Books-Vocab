import SwiftUI

struct ReaderSettingsPanelPresenter: View {
    @Environment(\.appTheme) private var appTheme

    struct State {
        let fontSizeText: String
        let canDecreaseFontSize: Bool
        let canIncreaseFontSize: Bool
    }

    struct Bindings {
        let lineHeight: Binding<Double>
        let font: Binding<ReaderFont>
        let theme: Binding<ReaderTheme>
        let underlineOpacity: Binding<Double>
        let showHitTestingDebug: Binding<Bool>
        let translationPanelMode: Binding<TranslationPanelMode>
    }

    private struct UnderlineOption: Identifiable {
        let label: String
        let value: Double

        var id: Double { value }
    }

    let state: State
    let bindings: Bindings
    let onDecreaseFontSize: () -> Void
    let onIncreaseFontSize: () -> Void
    let onSelectTheme: (ReaderTheme) -> Void
    let onSelectUnderlineOpacity: (Double) -> Void
    let onDismiss: () -> Void

    private let opacityOptions: [UnderlineOption] = [
        .init(label: "隱藏", value: 0.0),
        .init(label: "淡", value: 0.15),
        .init(label: "中", value: 0.35),
        .init(label: "深", value: 0.60)
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 0) {
                        ReaderStepControlButton(
                            label: "A",
                            font: ReaderGlassTypography.settingsStepSmall,
                            enabled: state.canDecreaseFontSize,
                            action: onDecreaseFontSize
                        )

                        Text(state.fontSizeText)
                            .font(ReaderGlassTypography.settingsValue)
                            .foregroundStyle(appTheme.palette.secondaryText)
                            .frame(width: ReaderPresentationMetrics.Settings.centeredValueWidth, alignment: .center)

                        ReaderStepControlButton(
                            label: "A",
                            font: ReaderGlassTypography.settingsStepLarge,
                            enabled: state.canIncreaseFontSize,
                            action: onIncreaseFontSize
                        )
                    }

                    HStack(spacing: ReaderPresentationMetrics.Settings.sliderSpacing) {
                        Image(systemName: "text.line.spacing")
                            .font(ReaderGlassTypography.settingsIcon)
                            .foregroundStyle(appTheme.palette.secondaryText)

                        Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                            .tint(appTheme.palette.tint)

                        Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                            .font(ReaderGlassTypography.settingsValue)
                            .foregroundStyle(appTheme.palette.secondaryText)
                            .frame(width: ReaderPresentationMetrics.Settings.sliderValueWidth, alignment: .trailing)
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
                } header: {
                    Text("排版".localized)
                }

                Section {
                    Picker("字體".localized, selection: bindings.font) {
                        ForEach(ReaderFont.allCases) { font in
                            Text(font.rawValue).tag(font)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack(spacing: ReaderPresentationMetrics.Settings.optionSpacing) {
                        ForEach(ReaderTheme.allCases) { theme in
                            themeTile(theme)
                        }
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
                } header: {
                    Text("外觀".localized)
                }

                Section {
                    HStack(spacing: ReaderPresentationMetrics.Settings.optionSpacing) {
                        ForEach(opacityOptions) { option in
                            underlineOptionButton(option)
                        }
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
                } header: {
                    Text("生字底線強度".localized)
                }

                Section {
                    Toggle("顯示點擊熱區".localized, isOn: bindings.showHitTestingDebug)
                        .tint(appTheme.palette.tint)
                } header: {
                    Text("開發者與除錯".localized)
                }

                Section {
                    Picker("閱讀介面風格".localized, selection: bindings.translationPanelMode) {
                        ForEach(TranslationPanelMode.allCases) { mode in
                            Label(mode.label, systemImage: mode.icon).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                } header: {
                    Text("閱讀介面風格".localized)
                }
            }
            .formStyle(.grouped)
            .navigationTitle("閱讀設定".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    closeToolbarButton
                }
            }
        }
    }

    private var closeToolbarButton: some View {
        Button(action: onDismiss) {
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(appTheme.palette.tertiaryText)
                .font(ReaderGlassTypography.settingsCloseIcon)
        }
    }

    private func themeTile(_ theme: ReaderTheme) -> some View {
        let isSelected = bindings.theme.wrappedValue == theme
        return Button { onSelectTheme(theme) } label: {
            ReaderSelectionTile(isSelected: isSelected) {
                HStack(spacing: ReaderPresentationMetrics.Settings.optionLabelSpacing) {
                    Image(systemName: theme.icon)
                        .font(ReaderGlassTypography.settingsValue)
                    Text(theme.rawValue)
                        .font(ReaderGlassTypography.body)
                        .fontWeight(isSelected ? .medium : .regular)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, ReaderPresentationMetrics.Settings.optionVerticalInset)
            }
        }
        .buttonStyle(.plain)
    }

    private func underlineOptionButton(_ option: UnderlineOption) -> some View {
        let isSelected = bindings.underlineOpacity.wrappedValue == option.value
        return Button { onSelectUnderlineOpacity(option.value) } label: {
            ReaderSelectionTile(isSelected: isSelected) {
                Text(option.label.localized)
                    .font(ReaderGlassTypography.body)
                    .fontWeight(isSelected ? .medium : .regular)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, ReaderPresentationMetrics.Settings.underlineVerticalInset)
            }
        }
        .buttonStyle(.plain)
    }
}

#Preview("ReaderSettingsPanel") {
    ReaderSettingsPanelPresenter(
        state: .init(
            fontSizeText: "17pt",
            canDecreaseFontSize: true,
            canIncreaseFontSize: true
        ),
        bindings: .init(
            lineHeight: .constant(1.4),
            font: .constant(.serif),
            theme: .constant(.light),
            underlineOpacity: .constant(0.35),
            showHitTestingDebug: .constant(false),
            translationPanelMode: .constant(.glass)
        ),
        onDecreaseFontSize: {},
        onIncreaseFontSize: {},
        onSelectTheme: { _ in },
        onSelectUnderlineOpacity: { _ in },
        onDismiss: {}
    )
}

#Preview("ReaderSettingsPanel / Disabled Bounds") {
    AppThemeContainer {
        ReaderSettingsPanelPresenter(
            state: .init(
                fontSizeText: "0.75x",
                canDecreaseFontSize: false,
                canIncreaseFontSize: true
            ),
            bindings: .init(
                lineHeight: .constant(2.5),
                font: .constant(.sans),
                theme: .constant(.dark),
                underlineOpacity: .constant(0.0),
                showHitTestingDebug: .constant(true),
                translationPanelMode: .constant(.vocab)
            ),
            onDecreaseFontSize: {},
            onIncreaseFontSize: {},
            onSelectTheme: { _ in },
            onSelectUnderlineOpacity: { _ in },
            onDismiss: {}
        )
    }
    .preferredColorScheme(.dark)
}
