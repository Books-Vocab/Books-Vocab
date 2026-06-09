#if os(iOS)
import SwiftUI

// MARK: - State & Content Mode

struct TranslationPanelPresenterState {
    let word: String
    let partOfSpeech: String?
    let translation: String?
    let isLoading: Bool
    let isSaved: Bool
    let isLoggedIn: Bool
    let isExpanded: Bool
    let explanation: String?
    let isLoadingExplanation: Bool
    let statusMessage: String?
    let isExplanationOnly: Bool
    let translationErrorMessage: String?
    let explanationErrorMessage: String?
    let timerText: String
    let isSpeaking: Bool
    /// 面板高度態：true = 大卡（撐高），false = 小卡。
    let isPanelLarge: Bool
}

enum TranslationPanelContentMode: Equatable {
    case loading
    case guest
    case explanationOnly
    case translation(String)
    case translationError(String)
    case empty
}

enum TranslationExplanationContentMode: Equatable {
    case loading(String)
    case error(String)
    case content(String)
    case empty
}

extension TranslationPanelPresenterState {
    var contentMode: TranslationPanelContentMode {
        if isLoading {
            return .loading
        }
        if !isLoggedIn {
            return .guest
        }
        if isExplanationOnly {
            return .explanationOnly
        }
        if let translationErrorMessage {
            return .translationError(translationErrorMessage)
        }
        if let translation {
            return .translation(translation)
        }
        return .empty
    }

    var activeTimerText: String? {
        guard !timerText.isEmpty, isLoading || isLoadingExplanation else { return nil }
        return timerText
    }

    var statusTimerText: String? {
        timerText.isEmpty ? nil : timerText
    }

    var showsExpandAction: Bool {
        isLoggedIn && translation != nil && !isExplanationOnly
    }

    /// 句子（explanationOnly）模式專屬的「放大／縮小」高度切換鈕。
    /// 單字模式的高度由 `showsExpandAction` 那顆 chevron 連動，不重複出鈕。
    var showsHeightToggle: Bool {
        isExplanationOnly
    }

    var showsSavedStatus: Bool {
        isSaved && isLoggedIn
    }

    var showsDeleteAction: Bool {
        isSaved
    }

    var loadingTitle: String {
        statusMessage ?? "翻譯中...".localized
    }

    var guestMessageTitle: String {
        isSaved ? "已加入待收錄".localized : "正在記錄…".localized
    }

    var guestMessageIcon: String {
        isSaved ? "checkmark.circle.fill" : "clock"
    }

    var explanationLoadingTitle: String {
        statusMessage ?? "載入解釋...".localized
    }

    var explanationContentMode: TranslationExplanationContentMode {
        if isLoadingExplanation {
            return .loading(explanationLoadingTitle)
        }
        if let explanationErrorMessage {
            return .error(explanationErrorMessage)
        }
        if let explanation {
            return .content(explanation)
        }
        return .empty
    }
}

// MARK: - Preview Data

enum TranslationPanelPreviewData {
    static let fullTranslation = TranslationPanelPresenterState(
        word: "ubiquitous", partOfSpeech: "adjective",
        translation: "無處不在的", isLoading: false, isSaved: true,
        isLoggedIn: true, isExpanded: true,
        explanation: "Something that is ubiquitous seems to be everywhere at the same time. For example, smartphones have become ubiquitous in modern life.",
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: nil,
        timerText: "3s", isSpeaking: false, isPanelLarge: true
    )

    static let explanationError = TranslationPanelPresenterState(
        word: "lucid", partOfSpeech: "adjective",
        translation: "清晰的", isLoading: false, isSaved: true,
        isLoggedIn: true, isExpanded: true, explanation: nil,
        isLoadingExplanation: false, statusMessage: nil,
        isExplanationOnly: false, translationErrorMessage: nil, explanationErrorMessage: "目前無法產生語境解釋。".localized,
        timerText: "2s", isSpeaking: false, isPanelLarge: false
    )
}
#endif
