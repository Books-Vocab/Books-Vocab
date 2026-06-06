#if os(iOS)
import SwiftUI

// MARK: - Vocab Layout & Sections

extension ReaderSettingsPresenter {

    // MARK: Layout

    var vocabLayout: some View {
        let chrome = ReaderPanelChromeStyle(layoutMode: LayoutMode(horizontalSizeClass: sizeClass))

        return VocabCard(padding: 0) {
            VStack(spacing: 0) {
                if chrome.showsDragHandle {
                    Capsule(style: .continuous)
                        .fill(appSkin.palette.quaternaryText.opacity(appSkin.metrics.panelHandleOpacity))
                        .frame(
                            width: ReaderMetrics.settingsHandleWidth,
                            height: ReaderMetrics.settingsHandleHeight
                        )
                        .padding(.top, ReaderMetrics.settingsHandleTopInset)
                        .padding(.bottom, ReaderMetrics.settingsHandleBottomInset)
                }
                vocabHeaderBlock
                    .padding(.top, chrome.contentTopInset)
                ScrollView {
                    // Mochi 北極星 #2：群組分隔靠 AppAirDivider + 留白,
                    // 不再用 settings card 背景色塊包每個 section。
                    VStack(alignment: .leading, spacing: 0) {
                        vocabTypographySection
                        AppAirDivider()
                        vocabAppearanceSection
                        AppAirDivider()
                        vocabHighlightSection
                        AppAirDivider()
                        vocabDebugSection
                    }
                    .padding(.horizontal, ReaderMetrics.settingsHorizontalInset)
                    .padding(.bottom, ReaderMetrics.settingsBottomInset)
                }
            }
        }
        // Mochi 北極星 #3：shadow 收兩階 — z3 → z2。
        .appElevation(.z2, direction: .up)
    }

    // MARK: Header

    var vocabHeaderBlock: some View {
        HStack(alignment: .top, spacing: ReaderMetrics.settingsHeaderSpacing) {
            Text("閱讀設定".localized)
                .font(appSkin.typography.sectionTitle)
                .foregroundStyle(appSkin.palette.primaryText)
            Spacer()
            VocabChromeIconButton(
                systemImage: "xmark",
                label: L10n.string("vocab.chromeIcon.readerSettings.dismiss"),
                action: onDismiss
            )
        }
        .padding(.horizontal, ReaderMetrics.settingsHorizontalInset)
        .padding(.bottom, ReaderMetrics.settingsHeaderBottomInset)
    }

    // MARK: Typography

    var vocabTypographySection: some View {
        vocabSettingsSection(title: "排版".localized) {
            VStack(alignment: .leading, spacing: AppSpacing.s4) {
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
                HStack(alignment: .center, spacing: AppSpacing.s3) {
                    vocabLabelChip(title: "行距".localized, systemImage: "text.line.spacing")
                    Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                        .tint(appSkin.palette.primaryText)
                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                        .font(appSkin.typography.monoBodyStrong)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .frame(width: ReaderMetrics.vocabValueReadoutWidth, alignment: .trailing)
                }
                Divider().overlay(appSkin.palette.divider)
                vocabReadingModeRow
            }
        }
    }

    private var vocabReadingModeRow: some View {
        HStack(alignment: .center, spacing: AppSpacing.s3) {
            vocabLabelChip(title: L10n.string("閱讀模式"), systemImage: "book.pages")
            Spacer(minLength: AppSpacing.s3)
            HStack(spacing: AppSpacing.s2) {
                ForEach([false, true], id: \.self) { isScroll in
                    let isSelected = bindings.scrollMode.wrappedValue == isScroll
                    Button {
                        withAnimation(AppMotion.panelState) { bindings.scrollMode.wrappedValue = isScroll }
                    } label: {
                        ReaderSelectionTile(isSelected: isSelected) {
                            Text(isScroll ? L10n.string("捲動") : L10n.string("翻頁"))
                                .font(appSkin.typography.caption)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, AppSpacing.s2)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            .frame(maxWidth: ReaderMetrics.vocabModeToggleMaxWidth)
        }
    }

    // MARK: Appearance

    var vocabAppearanceSection: some View {
        vocabSettingsSection(title: "外觀".localized) {
            VStack(alignment: .leading, spacing: AppSpacing.s4) {
                vocabFontMenu()
                HStack(spacing: 10) {
                    ForEach(ReaderTheme.allCases) { theme in vocabThemeTile(theme) }
                }
            }
        }
    }

    // MARK: Highlight

    var vocabHighlightSection: some View {
        vocabSettingsSection(title: "生字標記".localized) {
            VStack(alignment: .leading, spacing: AppSpacing.s4) {
                VocabHighlightColorPresetPicker(
                    selection: bindings.vocabHighlightColorPreset,
                    title: L10n.string("vocab.highlight.color.label")
                )

                Divider().overlay(appSkin.palette.divider)

                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Text(L10n.string("vocab.highlight.opacity.label"))
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                    HStack(spacing: AppSpacing.s2) {
                        ForEach(opacityOptions, id: \.label) { option in
                            let isSelected = bindings.underlineOpacity.wrappedValue == option.value
                            Button { onSelectUnderlineOpacity(option.value) } label: {
                                ReaderSelectionTile(isSelected: isSelected) {
                                    Text(option.label.localized)
                                        .font(appSkin.typography.caption)
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, ReaderMetrics.vocabOptionVerticalPadding)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    // MARK: Debug

    var vocabDebugSection: some View {
        vocabSettingsSection(title: "開發者與除錯".localized) {
            HStack(spacing: AppSpacing.s3) {
                VStack(alignment: .leading, spacing: AppSpacing.s1) {
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
        // flat=true：移除群組卡片背景,改靠 vocabLayout 內 AppAirDivider 切群組。
        AppSectionBlock(title: title, flat: true) { content() }
    }

    func vocabFontMenu() -> some View {
        Menu {
            ForEach(ReaderFont.allCases) { font in
                Button(font.rawValue) { bindings.font.wrappedValue = font }
            }
        } label: {
            vocabControlSurface {
                HStack(spacing: AppSpacing.s3) {
                    VStack(alignment: .leading, spacing: AppSpacing.tinyGap) {
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
        // Mochi 北極星 #2：control surface border 退場,只留 fill。
        VocabChromeSurface(
            fill: appSkin.palette.pageBackground,
            border: .clear
        ) {
            content()
                .padding(.horizontal, ReaderMetrics.settingsControlHorizontalPadding)
                .padding(.vertical, ReaderMetrics.settingsControlVerticalPadding)
                .contentShape(Rectangle())
        }
    }

    func vocabThemeTile(_ theme: ReaderTheme) -> some View {
        let isSelected = bindings.theme.wrappedValue == theme
        return Button { onSelectTheme(theme) } label: {
            ReaderSelectionTile(isSelected: isSelected) {
                VStack(alignment: .leading, spacing: AppSpacing.s3) {
                    Image(systemName: theme.icon).font(appSkin.typography.iconToolbar)
                    Text(theme.rawValue)
                        .font(appSkin.typography.body.weight(isSelected ? .semibold : .regular))
                    Rectangle()
                        .fill(appSkin.readerThemeSwatchColor(theme))
                        .frame(height: ReaderMetrics.vocabThemeSwatchHeight)
                        .clipShape(Capsule(style: .continuous))
                }
                .frame(maxWidth: .infinity)
                .padding(.horizontal, ReaderMetrics.settingsControlHorizontalPadding)
                .padding(.vertical, ReaderMetrics.settingsControlVerticalPadding)
            }
        }
        .buttonStyle(.plain)
    }
}
#endif
