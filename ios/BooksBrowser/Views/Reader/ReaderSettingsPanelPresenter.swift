import SwiftUI

struct ReaderSettingsPanelPresenter: View {
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

    let state: State
    let bindings: Bindings
    let onDecreaseFontSize: () -> Void
    let onIncreaseFontSize: () -> Void
    let onSelectTheme: (ReaderTheme) -> Void
    let onSelectUnderlineOpacity: (Double) -> Void
    let onDismiss: () -> Void

    private let opacityOptions: [(label: String, value: Double)] = [
        ("隱藏", 0.0),
        ("淡", 0.15),
        ("中", 0.35),
        ("深", 0.60)
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack(spacing: 0) {
                        Button(action: onDecreaseFontSize) {
                            Text("A")
                                .font(ReaderGlassTypography.settingsStepSmall)
                                .frame(maxWidth: .infinity)
                                .frame(height: ReaderPresentationMetrics.Settings.controlHeight)
                                .contentShape(Rectangle())
                        }
                        .disabled(!state.canDecreaseFontSize)
                        .buttonStyle(.plain)

                        Text(state.fontSizeText)
                            .font(ReaderGlassTypography.settingsValue)
                            .foregroundStyle(.secondary)
                            .frame(width: ReaderPresentationMetrics.Settings.centeredValueWidth, alignment: .center)

                        Button(action: onIncreaseFontSize) {
                            Text("A")
                                .font(ReaderGlassTypography.settingsStepLarge)
                                .frame(maxWidth: .infinity)
                                .frame(height: ReaderPresentationMetrics.Settings.controlHeight)
                                .contentShape(Rectangle())
                        }
                        .disabled(!state.canIncreaseFontSize)
                        .buttonStyle(.plain)
                    }
                    .foregroundStyle(.primary)

                    HStack(spacing: ReaderPresentationMetrics.Settings.sliderSpacing) {
                        Image(systemName: "text.line.spacing")
                            .font(ReaderGlassTypography.settingsIcon)
                            .foregroundStyle(.secondary)

                        Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                            .tint(.primary)

                        Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                            .font(ReaderGlassTypography.settingsValue)
                            .foregroundStyle(.secondary)
                            .frame(width: ReaderPresentationMetrics.Settings.sliderValueWidth, alignment: .trailing)
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
                } header: {
                    Text("排版")
                }

                Section {
                    Picker("字體", selection: bindings.font) {
                        ForEach(ReaderFont.allCases) { font in
                            Text(font.rawValue).tag(font)
                        }
                    }
                    .pickerStyle(.menu)

                    HStack(spacing: ReaderPresentationMetrics.Settings.optionSpacing) {
                        ForEach(ReaderTheme.allCases) { theme in
                            Button {
                                onSelectTheme(theme)
                            } label: {
                                HStack(spacing: 6) {
                                    Image(systemName: theme.icon)
                                        .font(ReaderGlassTypography.settingsValue)
                                    Text(theme.rawValue)
                                        .font(ReaderGlassTypography.body)
                                        .fontWeight(bindings.theme.wrappedValue == theme ? .medium : .regular)
                                }
                                .padding(.vertical, ReaderPresentationMetrics.Settings.optionVerticalInset)
                                .frame(maxWidth: .infinity)
                                .background(
                                    RoundedRectangle(
                                        cornerRadius: ReaderPresentationMetrics.Settings.optionCornerRadius,
                                        style: .continuous
                                    )
                                    .fill(
                                        bindings.theme.wrappedValue == theme
                                        ? Color.primary.opacity(ReaderPresentationMetrics.Settings.selectedFillOpacity)
                                        : Color.clear
                                    )
                                )
                                .overlay(
                                    RoundedRectangle(
                                        cornerRadius: ReaderPresentationMetrics.Settings.optionCornerRadius,
                                        style: .continuous
                                    )
                                    .stroke(
                                        Color.primary.opacity(ReaderPresentationMetrics.Settings.selectedStrokeOpacity),
                                        lineWidth: bindings.theme.wrappedValue == theme ? 1 : 0
                                    )
                                )
                                .foregroundStyle(bindings.theme.wrappedValue == theme ? .primary : .secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
                } header: {
                    Text("外觀")
                }

                Section {
                    HStack(spacing: ReaderPresentationMetrics.Settings.optionSpacing) {
                        ForEach(opacityOptions, id: \.label) { option in
                            Button {
                                onSelectUnderlineOpacity(option.value)
                            } label: {
                                Text(option.label.localized)
                                    .font(ReaderGlassTypography.body)
                                    .fontWeight(bindings.underlineOpacity.wrappedValue == option.value ? .medium : .regular)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, ReaderPresentationMetrics.Settings.underlineVerticalInset)
                                    .background(
                                        RoundedRectangle(
                                            cornerRadius: ReaderPresentationMetrics.Settings.underlineCornerRadius,
                                            style: .continuous
                                        )
                                        .fill(
                                            bindings.underlineOpacity.wrappedValue == option.value
                                            ? Color.primary.opacity(ReaderPresentationMetrics.Settings.selectedFillOpacity)
                                            : Color.clear
                                        )
                                    )
                                    .overlay(
                                        RoundedRectangle(
                                            cornerRadius: ReaderPresentationMetrics.Settings.underlineCornerRadius,
                                            style: .continuous
                                        )
                                        .stroke(
                                            Color.primary.opacity(ReaderPresentationMetrics.Settings.selectedStrokeOpacity),
                                            lineWidth: bindings.underlineOpacity.wrappedValue == option.value ? 1 : 0
                                        )
                                    )
                                    .foregroundStyle(bindings.underlineOpacity.wrappedValue == option.value ? .primary : .secondary)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
                } header: {
                    Text("生字底線強度")
                }

                Section {
                    Toggle("顯示點擊熱區", isOn: bindings.showHitTestingDebug)
                        .tint(.primary)
                } header: {
                    Text("開發者與除錯")
                }

                Section {
                    Picker("閱讀介面風格", selection: bindings.translationPanelMode) {
                        ForEach(TranslationPanelMode.allCases) { mode in
                            Label(mode.label, systemImage: mode.icon).tag(mode)
                        }
                    }
                    .pickerStyle(.segmented)
                } header: {
                    Text("閱讀介面風格")
                }
            }
            .formStyle(.grouped)
            .navigationTitle("閱讀設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: onDismiss) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(.tertiary)
                            .font(.system(size: ReaderPresentationMetrics.Settings.closeIconSize))
                    }
                }
            }
        }
    }
}
