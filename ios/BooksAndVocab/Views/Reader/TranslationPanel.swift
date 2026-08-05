#if os(iOS)
//
//  TranslationPanel.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Combine
import SwiftUI

struct TranslationPanel: View {
    @ObserveInjection private var inject
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
    var onLogin: (() -> Void)? = nil
    /// 翻譯失敗時，error card 內顯示「重試」CTA；nil 則隱藏（preview / 未提供 retry 來源時）
    var onRetryTranslation: (() -> Void)? = nil
    /// 語境解釋失敗時的「重試」CTA；nil 則隱藏
    var onRetryExplanation: (() -> Void)? = nil
    let isPanelLarge: Bool
    var onToggleHeight: () -> Void

    @Environment(\.speechService) private var speechService
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var dragOffset: CGFloat = 0
    @State private var isSpeaking = false
    @State private var elapsedTime: Double = 0
    @State private var timerCancellable: (any Cancellable)?

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
            isSpeaking: isSpeaking,
            isPanelLarge: isPanelLarge
        )
    }

    var body: some View {
        interactivePanelContent
            .transition(.readerPanelReveal)
            .appFeedback(.success, trigger: isSaved) { oldValue, newValue in
                !oldValue && newValue
            }
            .onChange(of: isLoading) { _, new in
                if new { elapsedTime = 0 }
            }
            .onChange(of: isLoadingExplanation) { _, new in
                if new { elapsedTime = 0 }
            }
            .onChange(of: isActive) { _, active in
                if active { startTimer() } else { stopTimer() }
            }
            .onAppear {
                if isActive { startTimer() }
            }
            .onDisappear {
                stopTimer()
            }
            .enableInjection()
    }

    @ViewBuilder
    private var interactivePanelContent: some View {
        let chrome = ReaderPanelChromeStyle(layoutMode: LayoutMode(horizontalSizeClass: sizeClass))

        if chrome.allowsDragDismiss {
            panelContent
                .offset(y: dragOffset)
                .gesture(dragDismissGesture)
        } else {
            panelContent
        }
    }

    private var dragDismissGesture: some Gesture {
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
                withAnimation(AppMotion.panelState) {
                    dragOffset = 0
                }
            }
    }

    private func startTimer() {
        guard timerCancellable == nil else { return }
        timerCancellable = Timer.publish(every: 0.1, on: .main, in: .common)
            .autoconnect()
            .sink { _ in elapsedTime += 0.1 }
    }

    private func stopTimer() {
        timerCancellable?.cancel()
        timerCancellable = nil
    }

    private var panelContent: some View {
        TranslationVocabPresenter(
            state: presenterState,
            onSpeak: { speechService.speak(word); isSpeaking.toggle() },
            onExpand: onExpand,
            onDelete: onDelete,
            onShowDetail: onShowDetail,
            onDismiss: onDismiss,
            onLogin: onLogin,
            onRetryTranslation: onRetryTranslation,
            onRetryExplanation: onRetryExplanation,
            onToggleHeight: onToggleHeight
        )
    }
}

struct TranslationPanelPreviewScene: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    var isExpanded: Bool
    var isExplanationOnly: Bool
    var isPanelLarge: Bool = false
    var translation: String? = "華麗的；令人驚豔的"
    var explanation: String? = nil
    var isLoading: Bool = false
    var isLoadingExplanation: Bool = false
    var statusMessage: String? = nil
    var translationErrorMessage: String? = nil
    var explanationErrorMessage: String? = nil

    var body: some View {
        ZStack {
            appTheme.palette.scrim.opacity(ReaderMetrics.translationPanelScrimOpacity).ignoresSafeArea()

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
                    onDismiss: {},
                    isPanelLarge: isPanelLarge,
                    onToggleHeight: {}
                )
                .padding(.horizontal)
            }
        }
        .enableInjection()
    }
}

#Preview("Translation / Expanded") {
    AppThemeContainer {
        TranslationPanelPreviewScene(isExpanded: true, isExplanationOnly: false)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Translation / Explain Only") {
    AppThemeContainer {
        TranslationPanelPreviewScene(isExpanded: true, isExplanationOnly: true)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Translation / Collapsed") {
    AppThemeContainer {
        TranslationPanelPreviewScene(isExpanded: false, isExplanationOnly: false)
    }
    .environmentObject(AppAppearanceStore.preview)
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
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Translation / Empty") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            isExpanded: false,
            isExplanationOnly: false,
            translation: nil,
            statusMessage: nil
        )
    }
    .environmentObject(AppAppearanceStore.preview)
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
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Translation / Loading") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            isExpanded: false,
            isExplanationOnly: false,
            translation: nil,
            isLoading: true
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Explanation / Loading") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            isExpanded: true,
            isExplanationOnly: false,
            explanation: nil,
            isLoadingExplanation: true
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
