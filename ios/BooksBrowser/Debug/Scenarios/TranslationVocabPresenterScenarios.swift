#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `TranslationVocabPresenter` — the Vocab-style render of the
/// reader translation panel. The presenter is a pure value-driven View
/// (`TranslationPanelPresenterState` + closures), so scenarios feed synthetic
/// states covering every `contentMode` branch. No view model / SwiftData / @MainActor
/// init involved, so plain Scenario closures suffice.
enum TranslationVocabPresenterScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Translation Vocab Presenter") {
            Scenario("Full Result · Expanded", layout: .fill) {
                presenter(Self.fullTranslation)
            }
            Scenario("Translation · Collapsed", layout: .fill) {
                presenter(Self.collapsedTranslation)
            }
            Scenario("Sentence Mode · Large", layout: .fill) {
                presenter(Self.explanationOnly)
            }
            Scenario("Loading", layout: .fill) {
                presenter(Self.loading)
            }
            Scenario("Guest Mode", layout: .fill) {
                presenter(Self.guest, onLogin: {})
            }
            Scenario("Translation Error", layout: .fill) {
                presenter(Self.translationError, onRetryTranslation: {})
            }
            Scenario("Explanation Error", layout: .fill) {
                presenter(Self.explanationError, onRetryExplanation: {})
            }
            Scenario("Empty", layout: .fill) {
                presenter(Self.empty)
            }
        }
    }

    // MARK: - Scene builder

    private static func presenter(
        _ state: TranslationPanelPresenterState,
        onLogin: (() -> Void)? = nil,
        onRetryTranslation: (() -> Void)? = nil,
        onRetryExplanation: (() -> Void)? = nil
    ) -> some View {
        AppThemeContainer {
            VStack {
                Spacer()
                TranslationVocabPresenter(
                    state: state,
                    onSpeak: {},
                    onExpand: {},
                    onDelete: {},
                    onShowDetail: {},
                    onDismiss: {},
                    onLogin: onLogin,
                    onRetryTranslation: onRetryTranslation,
                    onRetryExplanation: onRetryExplanation
                )
                .padding()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: - Synthetic fixtures

    private static func makeState(
        word: String = "ubiquitous",
        partOfSpeech: String? = "adjective",
        translation: String? = nil,
        isLoading: Bool = false,
        isSaved: Bool = false,
        isLoggedIn: Bool = true,
        isExpanded: Bool = false,
        explanation: String? = nil,
        isLoadingExplanation: Bool = false,
        statusMessage: String? = nil,
        isExplanationOnly: Bool = false,
        translationErrorMessage: String? = nil,
        explanationErrorMessage: String? = nil,
        timerText: String = "",
        isSpeaking: Bool = false,
        isPanelLarge: Bool = false
    ) -> TranslationPanelPresenterState {
        TranslationPanelPresenterState(
            word: word,
            partOfSpeech: partOfSpeech,
            translation: translation,
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

    private static let fullTranslation = makeState(
        translation: "無處不在的",
        isSaved: true,
        isExpanded: true,
        explanation: "Something that is ubiquitous seems to be everywhere at the same time. Smartphones, for instance, have become ubiquitous in modern life.",
        timerText: "3s",
        isPanelLarge: true
    )

    private static let collapsedTranslation = makeState(
        word: "lucid",
        translation: "清晰的",
        isSaved: true,
        isExpanded: false,
        explanation: "Clear and easy to understand.",
        timerText: "2s"
    )

    private static let explanationOnly = makeState(
        word: "She walked into the room without a word.",
        partOfSpeech: nil,
        isExpanded: true,
        explanation: "此句以零對白的動作描寫營造緊張氣氛，without a word 強調沉默帶來的張力。",
        isExplanationOnly: true,
        isPanelLarge: true
    )

    private static let loading = makeState(
        translation: nil,
        isLoading: true,
        statusMessage: "翻譯中...",
        timerText: "1s"
    )

    private static let guest = makeState(
        translation: nil,
        isSaved: true,
        isLoggedIn: false
    )

    private static let translationError = makeState(
        word: "ephemeral",
        translation: nil,
        isSaved: true,
        translationErrorMessage: "網路連線逾時，請稍後再試。",
        timerText: "5s"
    )

    private static let explanationError = makeState(
        word: "lucid",
        translation: "清晰的",
        isSaved: true,
        isExpanded: true,
        explanation: nil,
        explanationErrorMessage: "目前無法產生語境解釋。",
        timerText: "2s"
    )

    private static let empty = makeState(
        word: "—",
        partOfSpeech: nil,
        translation: nil
    )
}
#endif
