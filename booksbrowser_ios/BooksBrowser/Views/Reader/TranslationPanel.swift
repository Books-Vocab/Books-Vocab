//
//  TranslationPanel.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI

// MARK: - Environment Key

private struct ReaderPanelModeKey: EnvironmentKey {
    static let defaultValue: TranslationPanelMode = .glass
}

extension EnvironmentValues {
    var readerPanelMode: TranslationPanelMode {
        get { self[ReaderPanelModeKey.self] }
        set { self[ReaderPanelModeKey.self] = newValue }
    }
}

struct TranslationPanel: View {
    let word: String
    let result: TranslationResult?
    let pronunciation: String?
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
    let onDismiss: () -> Void

    @State private var dragOffset: CGFloat = 0
    @State private var isSpeaking = false
    @State private var elapsedTime: Double = 0

    private let ticker = Timer.publish(every: 0.1, on: .main, in: .common).autoconnect()
    private var isActive: Bool { isLoading || isLoadingExplanation }
    private var timerText: String { String(format: "%.1fs", elapsedTime) }
    private var presenterState: TranslationPanelPresenterState {
        .init(
            word: word,
            pronunciation: pronunciation,
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
        // ⚠️ TranslationPanelPresenterState 若有更動，
        //    TranslationPanelPresenter 與 TranslationVocabPresenter 需同步確認。
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

    // MARK: - 模式分支

    @Environment(\.readerPanelMode) private var panelMode

    @ViewBuilder
    private var panelContent: some View {
        switch panelMode {
        case .glass:
            TranslationPanelPresenter(
                state: presenterState,
                onSpeak: { SpeechService.shared.speak(word); isSpeaking.toggle() },
                onExpand: onExpand,
                onDelete: onDelete,
                onDismiss: onDismiss
            )
        case .vocab:
            TranslationVocabPresenter(
                state: presenterState,
                onSpeak: { SpeechService.shared.speak(word); isSpeaking.toggle() },
                onExpand: onExpand,
                onDelete: onDelete,
                onDismiss: onDismiss
            )
        }
    }
}

private struct TranslationPanelPreviewScene: View {
    let mode: TranslationPanelMode
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
            AppTheme.light.palette.scrim.opacity(0.12).ignoresSafeArea()

            VStack {
                Spacer()

                TranslationPanel(
                    word: "gorgeous",
                    result: translation.map {
                        TranslationResult(
                            translation: $0,
                            partOfSpeech: "adj.",
                            pronunciation: nil,
                            explanation: nil
                        )
                    },
                    pronunciation: "/ɡɔːrˈdʒəs/",
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
                    onDismiss: {}
                )
                .environment(\.readerPanelMode, mode)
                .padding(.horizontal)
            }
        }
    }
}

#Preview("Translation / Glass") {
    AppThemeContainer {
        TranslationPanelPreviewScene(mode: .glass, isExpanded: false, isExplanationOnly: false)
    }
}

#Preview("Translation / Vocab Expanded") {
    AppThemeContainer {
        TranslationPanelPreviewScene(mode: .vocab, isExpanded: true, isExplanationOnly: false)
    }
}

#Preview("Translation / Explain Only") {
    AppThemeContainer {
        TranslationPanelPreviewScene(mode: .vocab, isExpanded: true, isExplanationOnly: true)
    }
}

#Preview("Translation / Empty") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            mode: .glass,
            isExpanded: false,
            isExplanationOnly: false,
            translation: nil,
            explanation: nil,
            statusMessage: nil
        )
    }
}

#Preview("Translation / Error") {
    AppThemeContainer {
        TranslationPanelPreviewScene(
            mode: .vocab,
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
            mode: .vocab,
            isExpanded: true,
            isExplanationOnly: false,
            explanation: nil,
            explanationErrorMessage: "語境分析暫時不可用。"
        )
    }
}
