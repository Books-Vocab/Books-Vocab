//
//  ReaderSettingsPanel.swift
//  BooksBrowser
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI

/// 仿 Apple Books 的閱讀設定面板
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
        ReaderSettingsPanelPresenter(
            state: presenterState,
            bindings: .init(
                lineHeight: $settings.lineHeight,
                font: $settings.font,
                theme: $settings.theme,
                underlineOpacity: $settings.underlineOpacity,
                showHitTestingDebug: $settings.showHitTestingDebug,
                translationPanelMode: $settings.translationPanelMode
            ),
            onDecreaseFontSize: {
                settings.fontSize = max(0.75, settings.fontSize - 0.125)
            },
            onIncreaseFontSize: {
                settings.fontSize = min(2.0, settings.fontSize + 0.125)
            },
            onSelectTheme: { theme in
                withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) {
                    settings.theme = theme
                }
            },
            onSelectUnderlineOpacity: { value in
                withAnimation(.spring(response: 0.3, dampingFraction: 0.75)) {
                    settings.underlineOpacity = value
                }
            },
            onDismiss: onDismiss
        )
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
