#if os(iOS)
//
//  PodcastTranslationHandler.swift
//  BooksBrowser
//
//  Podcast 專用翻譯橋接：word tap → TranslationService → TranslationPanel
//

import Foundation
import Observation

@MainActor @Observable
final class PodcastTranslationHandler {
    var wordSelection: WordSelection?
    var translationResult: TranslationResult?
    var isTranslating: Bool = false
    var isSaved: Bool = false
    var translationErrorMessage: String?

    @ObservationIgnored
    private let translationService: any Translating
    @ObservationIgnored
    private var currentTask: Task<Void, Never>?

    init(translationService: any Translating = TranslationService()) {
        self.translationService = translationService
    }

    func handleWordTap(word: String, context: String) {
        let normalized = word
            .trimmingCharacters(in: .punctuationCharacters.union(.symbols))
            .lowercased()
        guard !normalized.isEmpty else { return }

        currentTask?.cancel()
        wordSelection = WordSelection(word: normalized, context: context, position: .zero)
        translationResult = nil
        translationErrorMessage = nil
        isTranslating = true
        isSaved = false

        currentTask = Task {
            do {
                let result = try await translationService.translateQuick(
                    word: normalized,
                    context: context,
                    onRetry: nil
                )
                guard !Task.isCancelled else { return }
                translationResult = result
                isTranslating = false
            } catch {
                guard !Task.isCancelled else { return }
                isTranslating = false
                translationErrorMessage = error.localizedDescription
            }
        }
    }

    func dismiss() {
        currentTask?.cancel()
        wordSelection = nil
        translationResult = nil
        isTranslating = false
        isSaved = false
        translationErrorMessage = nil
    }
}
#endif
