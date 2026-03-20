import SwiftUI

// MARK: - Vocab Layout & Sections

extension ReaderSettingsPresenter {

    // MARK: Layout

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

    // MARK: Header

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

    // MARK: Typography

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
                Divider().overlay(vocabSkin.palette.divider)
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

    // MARK: Appearance

    var vocabAppearanceSection: some View {
        vocabSettingsSection(title: "外觀".localized) {
            VStack(alignment: .leading, spacing: 16) {
                Menu {
                    ForEach(ReaderFont.allCases) { font in
                        Button(font.rawValue) { bindings.font.wrappedValue = font }
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
                    ForEach(ReaderTheme.allCases) { theme in vocabThemeTile(theme) }
                }
            }
        }
    }

    // MARK: Highlight

    var vocabHighlightSection: some View {
        vocabSettingsSection(title: "生字標記".localized) {
            HStack(spacing: 8) {
                ForEach(opacityOptions, id: \.label) { option in
                    let isSelected = bindings.underlineOpacity.wrappedValue == option.value
                    Button { onSelectUnderlineOpacity(option.value) } label: {
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

    // MARK: Debug

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

    // MARK: Helpers

    func vocabSettingsSection<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        AppSectionBlock(title: title) { content() }
    }

    func vocabLabelChip(title: String, systemImage: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage).font(vocabSkin.typography.iconTiny)
            Text(title).font(vocabSkin.typography.captionStrong)
        }
        .foregroundStyle(vocabSkin.palette.secondaryText)
        .padding(.horizontal, vocabSkin.spacing.chipHorizontalPadding)
        .padding(.vertical, vocabSkin.spacing.chipVerticalPaddingLoose)
        .background(Capsule(style: .continuous).fill(vocabSkin.palette.mutedFill))
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
        return Button { onSelectTheme(theme) } label: {
            ReaderSelectionTile(isSelected: isSelected) {
                VStack(alignment: .leading, spacing: 12) {
                    Image(systemName: theme.icon).font(vocabSkin.typography.iconToolbar)
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
}
