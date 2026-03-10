import SwiftUI

struct ReaderSettingsVocabPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: ReaderSettingsPanelPresenter.State
    let bindings: ReaderSettingsPanelPresenter.Bindings
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

                headerBlock

                ScrollView {
                    VStack(alignment: .leading, spacing: vocabSkin.metrics.readerSettingsSectionSpacing) {
                        typographySection
                        appearanceSection
                        highlightSection
                        modeSection
                        debugSection
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

    private var headerBlock: some View {
        HStack(alignment: .top, spacing: vocabSkin.metrics.readerSettingsHeaderSpacing) {
            VStack(alignment: .leading, spacing: 6) {
                Text("reader")
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .tracking(1.2)

                Text("閱讀設定")
                    .font(vocabSkin.typography.sectionTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)
            }

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", action: onDismiss)
        }
        .padding(.horizontal, vocabSkin.metrics.readerSettingsHorizontalInset)
        .padding(.bottom, vocabSkin.metrics.readerSettingsHeaderBottomInset)
    }

    private var typographySection: some View {
        settingsSection(
            title: "排版",
            eyebrow: "Typography"
        ) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .center, spacing: 0) {
                    Button(action: onDecreaseFontSize) {
                        Text("A")
                            .font(vocabSkin.typography.settingsAdjustSmall)
                            .foregroundStyle(state.canDecreaseFontSize ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
                            .frame(width: 52, height: 52)
                            .background(
                                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                    .fill(vocabSkin.palette.pageBackground)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)
                    .disabled(!state.canDecreaseFontSize)

                    Text(state.fontSizeText)
                        .font(vocabSkin.typography.settingsFontSizeDisplay)
                        .foregroundStyle(vocabSkin.palette.primaryText)
                        .frame(maxWidth: .infinity)

                    Button(action: onIncreaseFontSize) {
                        Text("A")
                            .font(vocabSkin.typography.settingsAdjustLarge)
                            .foregroundStyle(state.canIncreaseFontSize ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
                            .frame(width: 52, height: 52)
                            .background(
                                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                    .fill(vocabSkin.palette.pageBackground)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)
                    .disabled(!state.canIncreaseFontSize)
                }

                Divider()
                    .overlay(vocabSkin.palette.divider)

                HStack(alignment: .center, spacing: 12) {
                    labelChip(title: "行距", systemImage: "text.line.spacing")

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

    private var appearanceSection: some View {
        settingsSection(
            title: "外觀",
            eyebrow: "Atmosphere"
        ) {
            VStack(alignment: .leading, spacing: 16) {
                Menu {
                    ForEach(ReaderFont.allCases) { font in
                        Button(font.rawValue) {
                            bindings.font.wrappedValue = font
                        }
                    }
                } label: {
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
                    .padding(.horizontal, vocabSkin.metrics.readerSettingsControlHorizontalPadding)
                    .padding(.vertical, vocabSkin.metrics.readerSettingsControlVerticalPadding)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                            .fill(vocabSkin.palette.pageBackground)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                HStack(spacing: 10) {
                    ForEach(ReaderTheme.allCases) { theme in
                        themeTile(theme)
                    }
                }
            }
        }
    }

    private var highlightSection: some View {
        settingsSection(
            title: "生字標記",
            eyebrow: "Highlights"
        ) {
            HStack(spacing: 8) {
                ForEach(opacityOptions, id: \.label) { option in
                    let isSelected = bindings.underlineOpacity.wrappedValue == option.value
                    Button {
                        onSelectUnderlineOpacity(option.value)
                    } label: {
                        Text(option.label.localized)
                            .font(vocabSkin.typography.captionStrong)
                            .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .background(
                                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                    .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                    .stroke(isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(vocabSkin.metrics.readerSettingsDividerOpacity), lineWidth: 1)
                            )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var modeSection: some View {
        settingsSection(
            title: "閱讀介面",
            eyebrow: "Render Mode"
        ) {
            HStack(spacing: 10) {
                ForEach(TranslationPanelMode.allCases) { mode in
                    let isSelected = bindings.translationPanelMode.wrappedValue == mode
                    let icon = mode == .glass ? "sparkles.rectangle.stack" : "character.book.closed"
                    Button {
                        bindings.translationPanelMode.wrappedValue = mode
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: icon)
                                .font(vocabSkin.typography.iconToolbar)
                            Text(mode.label)
                                .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, vocabSkin.metrics.readerSettingsControlVerticalPadding)
                        .background(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                                .stroke(isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(vocabSkin.metrics.readerSettingsDividerOpacity), lineWidth: 1)
                        )
                        .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var debugSection: some View {
        settingsSection(
            title: "開發者與除錯",
            eyebrow: "Debug"
        ) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("顯示點擊熱區")
                        .font(vocabSkin.typography.body.weight(.medium))
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Text("用於校正 reader hit-testing。")
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

    private func settingsSection<Content: View>(
        title: String,
        eyebrow: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        AppSectionBlock(title: title, eyebrow: eyebrow) {
            content()
        }
    }

    private func labelChip(title: String, systemImage: String) -> some View {
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

    private func themeTile(_ theme: ReaderTheme) -> some View {
        let isSelected = bindings.theme.wrappedValue == theme
        return Button {
            onSelectTheme(theme)
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: theme.icon)
                    .font(vocabSkin.typography.iconToolbar)
                Text(theme.rawValue)
                    .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                Rectangle()
                    .fill(themeSwatchColor(theme))
                    .frame(height: 8)
                    .clipShape(Capsule(style: .continuous))
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, vocabSkin.metrics.readerSettingsControlHorizontalPadding)
            .padding(.vertical, vocabSkin.metrics.readerSettingsControlVerticalPadding)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(
                        isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(vocabSkin.metrics.readerSettingsDividerOpacity),
                        lineWidth: 1
                    )
            )
            .foregroundStyle(
                isSelected
                    ? vocabSkin.palette.primaryText
                    : vocabSkin.palette.secondaryText
            )
        }
        .buttonStyle(.plain)
    }

    private var fontToneLabel: String {
        switch bindings.font.wrappedValue {
        case .serif:
            return "classic"
        case .athelas:
            return "reader"
        case .sans:
            return "clean"
        case .mono:
            return "coded"
        }
    }

    private func themeSwatchColor(_ theme: ReaderTheme) -> Color {
        vocabSkin.readerThemeSwatchColor(theme)
    }

}
