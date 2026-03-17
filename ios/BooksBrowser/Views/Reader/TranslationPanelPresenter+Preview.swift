import SwiftUI

// MARK: - Preview Data & Previews

enum TranslationPanelPreviewData {
    static let loading = TranslationPanelPresenterState(
        word: "ephemeral", partOfSpeech: nil,
        translation: nil, isLoading: true, isSaved: false,
        isLoggedIn: true, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let guest = TranslationPanelPresenterState(
        word: "serendipity", partOfSpeech: "noun",
        translation: "意外發現美好事物的能力", isLoading: false, isSaved: true,
        isLoggedIn: false, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: "登入以同步詞彙",
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let fullTranslation = TranslationPanelPresenterState(
        word: "ubiquitous", partOfSpeech: "adjective",
        translation: "無處不在的", isLoading: false, isSaved: true,
        isLoggedIn: true, isExpanded: true,
        explanation: "Something that is ubiquitous seems to be everywhere at the same time. For example, smartphones have become ubiquitous in modern life.",
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "3s", isSpeaking: false
    )

    static let explanationOnlyLoading = TranslationPanelPresenterState(
        word: "ameliorate", partOfSpeech: nil,
        translation: nil, isLoading: false, isSaved: false,
        isLoggedIn: true, isExpanded: true, explanation: nil,
        isLoadingExplanation: true, statusMessage: nil,
        isExplanationOnly: true, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let translationError = TranslationPanelPresenterState(
        word: "oblique", partOfSpeech: "adjective",
        translation: nil, isLoading: false, isSaved: false,
        isLoggedIn: true, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: "服務暫時沒有回應，請稍後再試。".localized, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )

    static let explanationError = TranslationPanelPresenterState(
        word: "lucid", partOfSpeech: "adjective",
        translation: "清晰的", isLoading: false, isSaved: true,
        isLoggedIn: true, isExpanded: true, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: "目前無法產生語境解釋。".localized,
        timerText: "2s", isSpeaking: false
    )

    static let empty = TranslationPanelPresenterState(
        word: "quixotic", partOfSpeech: nil,
        translation: nil, isLoading: false, isSaved: false,
        isLoggedIn: true, isExpanded: false, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "", isSpeaking: false
    )
}

private struct TranslationPanelPreviewSurface<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        ZStack {
            AppColors.paperSepiaDeep.ignoresSafeArea()
            VStack {
                Spacer()
                content
            }
        }
    }
}

// MARK: - Previews

#Preview("Translation / Loading") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.loading,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Guest") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.guest,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Full Result") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.fullTranslation,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Explanation Only Loading") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.explanationOnlyLoading,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Error") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.translationError,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Explanation Error") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.explanationError,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}

#Preview("Translation / Empty") {
    TranslationPanelPreviewSurface {
        TranslationPanelPresenter(
            state: TranslationPanelPreviewData.empty,
            onSpeak: {}, onExpand: {}, onDelete: {}, onShowDetail: nil, onDismiss: {}
        )
    }
}
