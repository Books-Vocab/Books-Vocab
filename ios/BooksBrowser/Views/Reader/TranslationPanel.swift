//
//  TranslationPanel.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI

struct TranslationPanel: View {
    let word: String
    let result: TranslationResult?
    let isLoading: Bool
    let isSaved: Bool
    let isLoggedIn: Bool

    // Phase 2 展開
    let isExpanded: Bool
    let explanation: String?
    let isLoadingExplanation: Bool
    let statusMessage: String?

    let isExplanationOnly: Bool
    let translationErrorMessage: String?
    let explanationErrorMessage: String?
    let onExpand: () -> Void
    let onDelete: () -> Void
    let onShowDetail: (() -> Void)?
    let onDismiss: () -> Void

    @Environment(\.speechService) private var speechService
    @State private var dragOffset: CGFloat = 0
    @State private var isSpeaking = false
    @State private var elapsedTime: Double = 0

    private let ticker = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()
    private var isActive: Bool { isLoading || isLoadingExplanation }
    private var timerText: String { String(format: "%.1fs", elapsedTime) }
    private var presenterState: TranslationPanelPresenterState {
        .init(
            word: word,
            partOfSpeech: result?.partOfSpeech,
            translation: result?.translation,
            isLoading: isLoading,
            isSaved: isSaved,
            isLoggedIn: isLoggedIn,
            isExpanded: isExpanded,
            explanation: explanation,
            isLoadingExplanation: isLoadingExplanation,
            statusMessage: statusMessage,
            isExplanationOnly: isExplanationOnly,
            translationErrorMessage: translationErrorMessage,
            explanationErrorMessage: explanationErrorMessage,
            timerText: timerText,
            isSpeaking: isSpeaking
        )
    }

    var body: some View {
        panelContent
            .offset(y: dragOffset)
            .gesture(
                DragGesture()
                    .onChanged { value in
                        if value.translation.height > 0 {
                            dragOffset = value.translation.height
                        }
                    }
                    .onEnded { value in
                        if value.translation.height > 100 {
                            onDismiss()
                        }
                        withAnimation(AppMotion.panelSnapBack) {
                            dragOffset = 0
                        }
                    }
            )
            .transition(.readerPanelReveal)
            .sensoryFeedback(.success, trigger: isSaved)
            .onReceive(ticker) { _ in
                if isActive { elapsedTime += 0.1 }
            }
            .onChange(of: isLoading) { _, new in
                if new { elapsedTime = 0 }
            }
            .onChange(of: isLoadingExplanation) { _, new in
                if new { elapsedTime = 0 }
            }
    }

    private var panelContent: some View {
        TranslationVocabPresenter(
            state: presenterState,
            onSpeak: { speechService.speak(word); isSpeaking.toggle() },
            onExpand: onExpand,
            onDelete: onDelete,
            onShowDetail: onShowDetail,
            onDismiss: onDismiss
        )
    }
}

private struct TranslationPanelPreviewScene: View {
    @Environment(\.appTheme) private var appTheme
    var isExpanded: Bool
    var isExplanationOnly: Bool
    var translation: String? = "華麗的；令人驚豔的"
    var explanation: String? = nil
    var isLoading: Bool = false
    var isLoadingExplanation: Bool = false
    var statusMessage: String? = nil
    var translationErrorMessage: String? = nil
    var explanationErrorMessage: String? = nil

    var body: some View {
        ZStack {
            appTheme.palette.scrim.opacity(0.12).ignoresSafeArea()

            VStack {
                Spacer()

                TranslationPanel(
                    word: "gorgeous",
                    result: translation.map {
                        TranslationResult(
                            translation: $0,
                            partOfSpeech: "adj.",
                            explanation: nil
                        )
                    },
                    isLoading: isLoading,
                    isSaved: true,
                    isLoggedIn: true,
                    isExpanded: isExpanded,
                    explanation: explanation ?? (isExpanded
                        ? "常用來描述外觀、氣氛或令人印象深刻的事物，語氣通常偏正面且帶有審美色彩。"
                        : nil),
                    isLoadingExplanation: isLoadingExplanation,
                    statusMessage: statusMessage ?? (isExplanationOnly ? "以解釋模式顯示" : "已加入單字庫"),
                    isExplanationOnly: isExplanationOnly,
                    translationErrorMessage: translationErrorMessage,
                    explanationErrorMessage: explanationErrorMessage,
                    onExpand: {},
                    onDelete: {},
                    onShowDetail: nil,
                    onDismiss: {}
                )
                .padding(.horizontal)
            }
        }
    }
}

#Preview("Translation / Expanded") {
    AppThemeContainer {
        TranslationPanelPreviewScene(isExpanded: true, isExplanationOnly: false)
    }
}

#Preview("Translation / Explain Only") {
    AppThemeContainer {
        TranslationPanelPreviewScene(isExpanded: true, isExplanationOnly: true)
    }
}

#Preview("Translation / Collapsed") {
    AppThemeContainer {
        TranslationPanelPreviewScene(isExpanded: false, isExplanationOnly: false)
    }
}

#Preview("Translation / Error") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            isExpanded: false,
            isExplanationOnly: false,
            translation: nil,
            translationErrorMessage: "翻譯服務逾時，請稍後再試。"
        )
    }
}

#Preview("Explanation / Error") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            isExpanded: true,
            isExplanationOnly: false,
            explanation: nil,
            explanationErrorMessage: "語境分析暫時不可用。"
        )
    }
}
