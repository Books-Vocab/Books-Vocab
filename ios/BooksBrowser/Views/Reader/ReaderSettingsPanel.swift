//
//  ReaderSettingsPanel.swift
//  BooksBrowser
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI

struct ReaderSettingsPanel: View {
    @Bindable var settings: ReaderSettings
    @EnvironmentObject private var appearanceStore: AppAppearanceStore
    let onDismiss: () -> Void

    private var presenterState: ReaderSettingsPresenter.State {
        .init(
            fontSizeText: String(format: "%.2gx", settings.fontSize),
            canDecreaseFontSize: settings.fontSize > 0.75,
            canIncreaseFontSize: settings.fontSize < 2.0
        )
    }

    /// 將 AppAppearanceMode 映射到 ReaderTheme 用於 UI 顯示
    private var themeBinding: Binding<ReaderTheme> {
        Binding(
            get: { appearanceStore.selection.readerTheme },
            set: { selectTheme($0) }
        )
    }

    var body: some View {
        panelPresenter
    }

    private var panelPresenter: some View {
        ReaderSettingsPresenter(
            variant: settings.translationPanelMode == .glass ? .glass : .vocab,
            state: presenterState,
            bindings: presenterBindings,
            onDecreaseFontSize: decreaseFontSize,
            onIncreaseFontSize: increaseFontSize,
            onSelectTheme: selectTheme,
            onSelectUnderlineOpacity: selectUnderlineOpacity,
            onDismiss: onDismiss
        )
    }

    private var presenterBindings: ReaderSettingsPresenter.Bindings {
        .init(
            lineHeight: $settings.lineHeight,
            font: $settings.font,
            theme: themeBinding,
            underlineOpacity: $settings.underlineOpacity,
            showHitTestingDebug: $settings.showHitTestingDebug,
            translationPanelMode: $settings.translationPanelMode
        )
    }

    private func decreaseFontSize() {
        settings.fontSize = max(0.75, settings.fontSize - 0.125)
    }

    private func increaseFontSize() {
        settings.fontSize = min(2.0, settings.fontSize + 0.125)
    }

    private func selectTheme(_ theme: ReaderTheme) {
        withAnimation(AppMotion.panelState) {
            appearanceStore.setAppearance(AppAppearanceMode(from: theme))
        }
    }

    private func selectUnderlineOpacity(_ value: Double) {
        withAnimation(AppMotion.panelState) {
            settings.underlineOpacity = value
        }
    }
}

private struct ReaderSettingsPanelPreviewHarness: View {
    let mode: TranslationPanelMode
    let initialFontSizeText: String
    let canDecreaseFontSize: Bool
    let canIncreaseFontSize: Bool

    @State private var lineHeight: Double = 1.5
    @State private var font: ReaderFont = .serif
    @State private var theme: ReaderTheme = .sepia
    @State private var underlineOpacity: Double = 0.35
    @State private var showHitTestingDebug = false
    @State private var translationPanelMode: TranslationPanelMode = .glass

    private var state: ReaderSettingsPresenter.State {
        .init(
            fontSizeText: initialFontSizeText,
            canDecreaseFontSize: canDecreaseFontSize,
            canIncreaseFontSize: canIncreaseFontSize
        )
    }

    private var bindings: ReaderSettingsPresenter.Bindings {
        .init(
            lineHeight: $lineHeight,
            font: $font,
            theme: $theme,
            underlineOpacity: $underlineOpacity,
            showHitTestingDebug: $showHitTestingDebug,
            translationPanelMode: $translationPanelMode
        )
    }

    var body: some View {
        ZStack {
            AppTheme.light.palette.pageBackground.ignoresSafeArea()

            VStack {
                Spacer()

                ReaderSettingsPresenter(
                    variant: mode == .glass ? .glass : .vocab,
                    state: state,
                    bindings: bindings,
                    onDecreaseFontSize: {},
                    onIncreaseFontSize: {},
                    onSelectTheme: { theme = $0 },
                    onSelectUnderlineOpacity: { underlineOpacity = $0 },
                    onDismiss: {}
                )
                .padding(.horizontal)
            }
        }
    }
}

#Preview("Reader Settings / Glass") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(
            mode: .glass,
            initialFontSizeText: "1.0x",
            canDecreaseFontSize: true,
            canIncreaseFontSize: true
        )
    }
}

#Preview("Reader Settings / Vocab") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(
            mode: .vocab,
            initialFontSizeText: "1.0x",
            canDecreaseFontSize: true,
            canIncreaseFontSize: true
        )
    }
}

#Preview("Reader Settings / Glass Bounds") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(
            mode: .glass,
            initialFontSizeText: "0.75x",
            canDecreaseFontSize: false,
            canIncreaseFontSize: true
        )
    }
}
