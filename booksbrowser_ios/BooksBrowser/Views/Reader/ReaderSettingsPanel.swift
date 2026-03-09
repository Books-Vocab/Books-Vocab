//
//  ReaderSettingsPanel.swift
//  BooksBrowser
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI

struct ReaderSettingsPanel: View {
    @Bindable var settings: ReaderSettings
    let onDismiss: () -> Void

    private var presenterState: ReaderSettingsPanelPresenter.State {
        .init(
            fontSizeText: String(format: "%.2gx", settings.fontSize),
            canDecreaseFontSize: settings.fontSize > 0.75,
            canIncreaseFontSize: settings.fontSize < 2.0
        )
    }
    
    var body: some View {
        panelPresenter
    }

    @ViewBuilder
    private var panelPresenter: some View {
        switch settings.translationPanelMode {
        case .glass:
            ReaderSettingsPanelPresenter(
                state: presenterState,
                bindings: presenterBindings,
                onDecreaseFontSize: decreaseFontSize,
                onIncreaseFontSize: increaseFontSize,
                onSelectTheme: selectTheme,
                onSelectUnderlineOpacity: selectUnderlineOpacity,
                onDismiss: onDismiss
            )
        case .vocab:
            ReaderSettingsVocabPresenter(
                state: presenterState,
                bindings: presenterBindings,
                onDecreaseFontSize: decreaseFontSize,
                onIncreaseFontSize: increaseFontSize,
                onSelectTheme: selectTheme,
                onSelectUnderlineOpacity: selectUnderlineOpacity,
                onDismiss: onDismiss
            )
        }
    }

    private var presenterBindings: ReaderSettingsPanelPresenter.Bindings {
        .init(
            lineHeight: $settings.lineHeight,
            font: $settings.font,
            theme: $settings.theme,
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
        withAnimation(AppMotion.standardSpring) {
            settings.theme = theme
        }
    }

    private func selectUnderlineOpacity(_ value: Double) {
        withAnimation(AppMotion.standardSpring) {
            settings.underlineOpacity = value
        }
    }
}

private struct ReaderSettingsPanelPreviewHarness: View {
    let mode: TranslationPanelMode

    @State private var lineHeight: Double = 1.5
    @State private var font: ReaderFont = .serif
    @State private var theme: ReaderTheme = .sepia
    @State private var underlineOpacity: Double = 0.35
    @State private var showHitTestingDebug = false
    @State private var translationPanelMode: TranslationPanelMode = .glass

    private var state: ReaderSettingsPanelPresenter.State {
        .init(
            fontSizeText: "1.0x",
            canDecreaseFontSize: true,
            canIncreaseFontSize: true
        )
    }

    private var bindings: ReaderSettingsPanelPresenter.Bindings {
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

                Group {
                    switch mode {
                    case .glass:
                        ReaderSettingsPanelPresenter(
                            state: state,
                            bindings: bindings,
                            onDecreaseFontSize: {},
                            onIncreaseFontSize: {},
                            onSelectTheme: { theme = $0 },
                            onSelectUnderlineOpacity: { underlineOpacity = $0 },
                            onDismiss: {}
                        )
                    case .vocab:
                        ReaderSettingsVocabPresenter(
                            state: state,
                            bindings: bindings,
                            onDecreaseFontSize: {},
                            onIncreaseFontSize: {},
                            onSelectTheme: { theme = $0 },
                            onSelectUnderlineOpacity: { underlineOpacity = $0 },
                            onDismiss: {}
                        )
                    }
                }
                .padding(.horizontal)
            }
        }
    }
}

#Preview("Reader Settings / Glass") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(mode: .glass)
    }
}

#Preview("Reader Settings / Vocab") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(mode: .vocab)
    }
}
