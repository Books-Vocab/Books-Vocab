import SwiftUI

// MARK: - Variant

enum ReaderSettingsVariant {
    case glass, vocab
}

// MARK: - Presenter

struct ReaderSettingsPresenter: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.vocabSkin) private var vocabSkin

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

    let variant: ReaderSettingsVariant
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
        switch variant {
        case .glass:
            glassLayout
        case .vocab:
            vocabLayout
        }
    }
}

// MARK: - Glass Layout

private extension ReaderSettingsPresenter {
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

// MARK: - Vocab Layout

private extension ReaderSettingsPresenter {
    var vocabLayout: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                Capsule(style: .continuous)
                    .fill(vocabSkin.palette.quaternaryText.opacity(vocabSkin.metrics.panelHandleOpacity))
                    .frame(
                        width: vocabSkin.metrics.readerSettingsHandleWidth,
                        height: vocabSkin.metrics.readerSettingsHandleHeight
                    )
                    .padding(.top, vocabSkin.metrics.readerSettingsHandleTopInset)
                    .padding(.bottom, vocabSkin.metrics.readerSettingsHandleBottomInset)

                vocabHeaderBlock

                ScrollView {
                    VStack(alignment: .leading, spacing: vocabSkin.metrics.readerSettingsSectionSpacing) {
                        vocabTypographySection
                        vocabAppearanceSection
                        vocabHighlightSection
                        vocabModeSection
                        vocabDebugSection
                    }
                    .padding(.horizontal, vocabSkin.metrics.readerSettingsHorizontalInset)
                    .padding(.bottom, vocabSkin.metrics.readerSettingsBottomInset)
                }
            }
        }
        .shadow(
            color: vocabSkin.palette.shadow.opacity(vocabSkin.metrics.readerPanelShadowOpacity),
            radius: vocabSkin.metrics.readerPanelShadowRadius,
            y: vocabSkin.metrics.readerPanelShadowY
        )
    }

    var vocabHeaderBlock: some View {
        HStack(alignment: .top, spacing: vocabSkin.metrics.readerSettingsHeaderSpacing) {
            Text("閱讀設定")
                .font(vocabSkin.typography.sectionTitle)
                .foregroundStyle(vocabSkin.palette.primaryText)

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", action: onDismiss)
        }
        .padding(.horizontal, vocabSkin.metrics.readerSettingsHorizontalInset)
        .padding(.bottom, vocabSkin.metrics.readerSettingsHeaderBottomInset)
    }

    var vocabTypographySection: some View {
        vocabSettingsSection(title: "排版".localized) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .center, spacing: 0) {
                    ReaderStepControlButton(
                        label: "A",
                        font: vocabSkin.typography.settingsAdjustSmall,
                        enabled: state.canDecreaseFontSize,
                        action: onDecreaseFontSize
                    )

                    Text(state.fontSizeText)
                        .font(vocabSkin.typography.settingsFontSizeDisplay)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .frame(maxWidth: .infinity)

                    ReaderStepControlButton(
                        label: "A",
                        font: vocabSkin.typography.settingsAdjustLarge,
                        enabled: state.canIncreaseFontSize,
                        action: onIncreaseFontSize
                    )
                }

                Divider()
                    .overlay(vocabSkin.palette.divider)

                HStack(alignment: .center, spacing: 12) {
                    vocabLabelChip(title: "行距", systemImage: "text.line.spacing")

                    Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                        .tint(vocabSkin.palette.primaryText)

                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                        .font(vocabSkin.typography.monoBodyStrong)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .frame(width: 34, alignment: .trailing)
                }
            }
        }
    }

    var vocabAppearanceSection: some View {
        vocabSettingsSection(title: "外觀".localized) {
            VStack(alignment: .leading, spacing: 16) {
                Menu {
                    ForEach(ReaderFont.allCases) { font in
                        Button(font.rawValue) {
                            bindings.font.wrappedValue = font
                        }
                    }
                } label: {
                    vocabControlSurface {
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("字體")
                                    .font(vocabSkin.typography.captionStrong)
                                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                                Text(bindings.font.wrappedValue.rawValue)
                                    .font(vocabSkin.typography.translationTitle)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                            }

                            Spacer()

                            HStack(spacing: 6) {
                                Text(fontToneLabel)
                                    .font(vocabSkin.typography.monoLabel)
                                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                                Image(systemName: "chevron.down")
                                    .font(vocabSkin.typography.iconTiny.weight(.bold))
                                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                            }
                        }
                    }
                }
                .buttonStyle(.plain)

                HStack(spacing: 10) {
                    ForEach(ReaderTheme.allCases) { theme in
                        vocabThemeTile(theme)
                    }
                }
            }
        }
    }

    var vocabHighlightSection: some View {
        vocabSettingsSection(title: "生字標記".localized) {
            HStack(spacing: 8) {
                ForEach(opacityOptions, id: \.label) { option in
                    let isSelected = bindings.underlineOpacity.wrappedValue == option.value
                    Button {
                        onSelectUnderlineOpacity(option.value)
                    } label: {
                        ReaderSelectionTile(isSelected: isSelected) {
                            Text(option.label.localized)
                                .font(vocabSkin.typography.captionStrong)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 10)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    var vocabModeSection: some View {
        vocabSettingsSection(title: "閱讀介面".localized) {
            HStack(spacing: 10) {
                ForEach(TranslationPanelMode.allCases) { mode in
                    let isSelected = bindings.translationPanelMode.wrappedValue == mode
                    let icon = mode == .glass ? "sparkles.rectangle.stack" : "character.book.closed"
                    Button {
                        bindings.translationPanelMode.wrappedValue = mode
                    } label: {
                        ReaderSelectionTile(isSelected: isSelected) {
                            HStack(spacing: 10) {
                                Image(systemName: icon)
                                    .font(vocabSkin.typography.iconToolbar)
                                Text(mode.label)
                                    .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, vocabSkin.metrics.readerSettingsControlVerticalPadding)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    var vocabDebugSection: some View {
        vocabSettingsSection(title: "開發者與除錯".localized) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("顯示點擊熱區")
                        .font(vocabSkin.typography.body.weight(.medium))
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Text("用於校正閱讀器點擊熱區。")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }

                Spacer()

                Toggle("", isOn: bindings.showHitTestingDebug)
                    .labelsHidden()
                    .tint(vocabSkin.palette.primaryText)
            }
        }
    }
}

// MARK: - Vocab Helpers

private extension ReaderSettingsPresenter {
    func vocabSettingsSection<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        AppSectionBlock(title: title) {
            content()
        }
    }

    func vocabLabelChip(title: String, systemImage: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconTiny)
            Text(title)
                .font(vocabSkin.typography.captionStrong)
        }
        .foregroundStyle(vocabSkin.palette.secondaryText)
        .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
        .padding(.vertical, vocabSkin.spacing.chipVerticalPaddingLoose)
        .background(
            Capsule(style: .continuous)
                .fill(vocabSkin.palette.mutedFill)
        )
    }

    func vocabControlSurface<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VocabChromeSurface(
            fill: vocabSkin.palette.pageBackground,
            border: vocabSkin.palette.cardBorder
        ) {
            content()
                .padding(.horizontal, vocabSkin.metrics.readerSettingsControlHorizontalPadding)
                .padding(.vertical, vocabSkin.metrics.readerSettingsControlVerticalPadding)
                .contentShape(Rectangle())
        }
    }

    func vocabThemeTile(_ theme: ReaderTheme) -> some View {
        let isSelected = bindings.theme.wrappedValue == theme
        return Button {
            onSelectTheme(theme)
        } label: {
            ReaderSelectionTile(isSelected: isSelected) {
                VStack(alignment: .leading, spacing: 12) {
                    Image(systemName: theme.icon)
                        .font(vocabSkin.typography.iconToolbar)
                    Text(theme.rawValue)
                        .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                    Rectangle()
                        .fill(vocabSkin.readerThemeSwatchColor(theme))
                        .frame(height: 8)
                        .clipShape(Capsule(style: .continuous))
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal, vocabSkin.metrics.readerSettingsControlHorizontalPadding)
                .padding(.vertical, vocabSkin.metrics.readerSettingsControlVerticalPadding)
            }
        }
        .buttonStyle(.plain)
    }

    var fontToneLabel: String {
        switch bindings.font.wrappedValue {
        case .serif:
            return "classic"
        case .athelas:
            return "reader"
        case .sans:
            return "clean"
        case .mono:
            return "coded"
        @unknown default:
            return bindings.font.wrappedValue.rawValue
        }
    }
}

// MARK: - Previews

#Preview("ReaderSettings / Glass") {
    ReaderSettingsPresenter(
        variant: .glass,
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

#Preview("ReaderSettings / Vocab") {
    AppThemeContainer {
        ReaderSettingsPresenter(
            variant: .vocab,
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
                translationPanelMode: .constant(.vocab)
            ),
            onDecreaseFontSize: {},
            onIncreaseFontSize: {},
            onSelectTheme: { _ in },
            onSelectUnderlineOpacity: { _ in },
            onDismiss: {}
        )
        .padding()
    }
}

#Preview("ReaderSettings / Glass Bounds") {
    AppThemeContainer {
        ReaderSettingsPresenter(
            variant: .glass,
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
