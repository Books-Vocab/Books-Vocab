#if os(iOS)
import SwiftUI

// MARK: - Vocab Layout & Sections

extension ReaderSettingsPresenter {

    // MARK: Layout

    var vocabLayout: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                Capsule(style: .continuous)
                    .fill(appSkin.palette.quaternaryText.opacity(appSkin.metrics.panelHandleOpacity))
                    .frame(
                        width: appSkin.metrics.readerSettingsHandleWidth,
                        height: appSkin.metrics.readerSettingsHandleHeight
                    )
                    .padding(.top, appSkin.metrics.readerSettingsHandleTopInset)
                    .padding(.bottom, appSkin.metrics.readerSettingsHandleBottomInset)
                vocabHeaderBlock
                ScrollView {
                    VStack(alignment: .leading, spacing: appSkin.metrics.readerSettingsSectionSpacing) {
                        vocabTypographySection
                        vocabAppearanceSection
                        vocabHighlightSection
                        vocabDebugSection
                    }
                    .padding(.horizontal, appSkin.metrics.readerSettingsHorizontalInset)
                    .padding(.bottom, appSkin.metrics.readerSettingsBottomInset)
                }
            }
        }
        .appElevation(.z3, direction: .up)
    }

    // MARK: Header

    var vocabHeaderBlock: some View {
        HStack(alignment: .top, spacing: appSkin.metrics.readerSettingsHeaderSpacing) {
            Text("閱讀設定".localized)
                .font(appSkin.typography.sectionTitle)
                .foregroundStyle(appSkin.palette.primaryText)
            Spacer()
            VocabChromeIconButton(systemImage: "xmark", action: onDismiss)
        }
        .padding(.horizontal, appSkin.metrics.readerSettingsHorizontalInset)
        .padding(.bottom, appSkin.metrics.readerSettingsHeaderBottomInset)
    }

    // MARK: Typography

    var vocabTypographySection: some View {
        vocabSettingsSection(title: "排版".localized) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .center, spacing: 0) {
                    ReaderStepControlButton(
                        label: "A",
                        font: appSkin.typography.settingsAdjustSmall,
                        enabled: state.canDecreaseFontSize,
                        action: onDecreaseFontSize
                    )
                    Text(state.fontSizeText)
                        .font(appSkin.typography.settingsFontSizeDisplay)
                        .foregroundStyle(appSkin.palette.primaryText)
                        .frame(maxWidth: .infinity)
                    ReaderStepControlButton(
                        label: "A",
                        font: appSkin.typography.settingsAdjustLarge,
                        enabled: state.canIncreaseFontSize,
                        action: onIncreaseFontSize
                    )
                }
                Divider().overlay(appSkin.palette.divider)
                HStack(alignment: .center, spacing: 12) {
                    vocabLabelChip(title: "行距", systemImage: "text.line.spacing")
                    Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                        .tint(appSkin.palette.primaryText)
                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                        .font(appSkin.typography.monoBodyStrong)
                        .foregroundStyle(appSkin.palette.secondaryText)
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
                                Text("字體".localized)
                                    .font(appSkin.typography.caption)
                                    .foregroundStyle(appSkin.palette.tertiaryText)
                                Text(bindings.font.wrappedValue.rawValue)
                                    .font(appSkin.typography.translationTitle)
                                    .foregroundStyle(appSkin.palette.primaryText)
                            }
                            Spacer()
                            HStack(spacing: 6) {
                                Text(fontToneLabel)
                                    .font(appSkin.typography.monoLabel)
                                    .foregroundStyle(appSkin.palette.quaternaryText)
                                Image(systemName: "chevron.down")
                                    .font(appSkin.typography.iconTiny.weight(.bold))
                                    .foregroundStyle(appSkin.palette.tertiaryText)
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
                                .font(appSkin.typography.caption)
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
                    Text("顯示點擊熱區".localized)
                        .font(appSkin.typography.body.weight(.medium))
                        .foregroundStyle(appSkin.palette.primaryText)
                    Text("用於校正閱讀器點擊熱區。".localized)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.tertiaryText)
                }
                Spacer()
                Toggle("", isOn: bindings.showHitTestingDebug)
                    .labelsHidden()
                    .tint(appSkin.palette.primaryText)
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
            Image(systemName: systemImage).font(appSkin.typography.iconTiny)
            Text(title).font(appSkin.typography.caption)
        }
        .foregroundStyle(appSkin.palette.secondaryText)
        .padding(.horizontal, appSkin.spacing.chipHorizontalPadding)
        .padding(.vertical, appSkin.spacing.chipVerticalPaddingLoose)
        .background(Capsule(style: .continuous).fill(appSkin.palette.mutedFill))
    }

    func vocabControlSurface<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VocabChromeSurface(
            fill: appSkin.palette.pageBackground,
            border: appSkin.palette.cardBorder
        ) {
            content()
                .padding(.horizontal, appSkin.metrics.readerSettingsControlHorizontalPadding)
                .padding(.vertical, appSkin.metrics.readerSettingsControlVerticalPadding)
                .contentShape(Rectangle())
        }
    }

    func vocabThemeTile(_ theme: ReaderTheme) -> some View {
        let isSelected = bindings.theme.wrappedValue == theme
        return Button { onSelectTheme(theme) } label: {
            ReaderSelectionTile(isSelected: isSelected) {
                VStack(alignment: .leading, spacing: 12) {
                    Image(systemName: theme.icon).font(appSkin.typography.iconToolbar)
                    Text(theme.rawValue)
                        .font(appSkin.typography.body.weight(isSelected ? .semibold : .regular))
                    Rectangle()
                        .fill(appSkin.readerThemeSwatchColor(theme))
                        .frame(height: 8)
                        .clipShape(Capsule(style: .continuous))
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal, appSkin.metrics.readerSettingsControlHorizontalPadding)
                .padding(.vertical, appSkin.metrics.readerSettingsControlVerticalPadding)
            }
        }
        .buttonStyle(.plain)
    }
}
#endif
