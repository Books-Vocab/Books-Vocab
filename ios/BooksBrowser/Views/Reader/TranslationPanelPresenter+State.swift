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

    var showsSavedStatus: Bool {
        isSaved && isLoggedIn
    }

    var showsDeleteAction: Bool {
        isSaved
    }

    var loadingTitle: String {
        statusMessage ?? "翻譯中..."
    }

    var guestMessageTitle: String {
        isSaved ? "已加入待收錄" : "正在記錄…"
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
