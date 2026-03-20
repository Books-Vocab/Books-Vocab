import SwiftUI

// MARK: - Glass Layout

extension ReaderSettingsPresenter {
    var glassLayout: some View {
        NavigationStack {
            Form {
                glassTypographySection
                glassAppearanceSection
                glassHighlightSection
                glassDebugSection
                glassModeSection
            }
            .formStyle(.grouped)
            .navigationTitle("閱讀設定".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: onDismiss) {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundStyle(appTheme.palette.tertiaryText)
                            .font(ReaderGlassTypography.settingsCloseIcon)
                    }
                }
            }
        }
    }
}

// MARK: - Glass Sections

extension ReaderSettingsPresenter {
    var glassTypographySection: some View {
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
    }

    var glassAppearanceSection: some View {
        Section {
            Picker("字體".localized, selection: bindings.font) {
                ForEach(ReaderFont.allCases) { font in
                    Text(font.rawValue).tag(font)
                }
            }
            .pickerStyle(.menu)

            HStack(spacing: ReaderPresentationMetrics.Settings.optionSpacing) {
                ForEach(ReaderTheme.allCases) { theme in
                    glassThemeTile(theme)
                }
            }
            .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
        } header: {
            Text("外觀".localized)
        }
    }

    var glassHighlightSection: some View {
        Section {
            HStack(spacing: ReaderPresentationMetrics.Settings.optionSpacing) {
                ForEach(opacityOptions, id: \.label) { option in
                    let isSelected = bindings.underlineOpacity.wrappedValue == option.value
                    Button { onSelectUnderlineOpacity(option.value) } label: {
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
            .padding(.vertical, ReaderPresentationMetrics.Settings.sectionVerticalInset)
        } header: {
            Text("生字底線強度".localized)
        }
    }

    var glassDebugSection: some View {
        Section {
            Toggle("顯示點擊熱區".localized, isOn: bindings.showHitTestingDebug)
                .tint(appTheme.palette.tint)
        } header: {
            Text("開發者與除錯".localized)
        }
    }

    var glassModeSection: some View {
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

    func glassThemeTile(_ theme: ReaderTheme) -> some View {
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
}
