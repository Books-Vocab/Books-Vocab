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

#Preview {
    ZStack {
        Color.gray.opacity(0.2).ignoresSafeArea()
        VStack {
            Spacer()
            ReaderSettingsPanel(settings: ReaderSettings.shared) {}
                .padding(.horizontal)
        }
    }
}
