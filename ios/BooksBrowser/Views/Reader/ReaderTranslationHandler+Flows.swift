import SwiftUI
import os

extension ReaderTranslationHandler {
    func handleWordSelected(
        word: String,
        context: String,
        vocabularyContext: ReaderVocabularyContext
    ) {
        cancelCurrentTranslationTask()
        let normalizedWord = normalizeWord(word)
        let selection = WordSelection(word: normalizedWord, context: context, position: .zero)
        wordSelection = selection

        if let existing = vocabularyContext.existingEntry(matching: word) {
            withAnimation(AppMotion.panelState) {
                translationResult = TranslationResult(
                    translation: existing.translation,
                    partOfSpeech: nil,
                    explanation: nil
                )
                isSaved = true
                isTranslating = false
                isExpanded = false
                explanationText = nil
                translationErrorMessage = nil
                explanationErrorMessage = nil
            }
            AppLog.reader.debug("從生詞庫載入: \(word) → \(existing.word)")
            return
        }

        if !authManager.isLoggedIn {
            withAnimation(AppMotion.panelState) {
                isTranslating = false
                translationResult = nil
                isSaved = false
                isExpanded = false
                explanationText = nil
                translationErrorMessage = nil
                explanationErrorMessage = nil
            }
            guestSaveToVocabulary(
                selection: selection,
                context: vocabularyContext
            )
            return
        }

        withAnimation(AppMotion.panelState) {
            isTranslating = true
            translationResult = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
            translationErrorMessage = nil
            explanationErrorMessage = nil
        }

        let newTask = Task { @MainActor in
            guard !Task.isCancelled else { return }

            let translationTask = Task {
                try await translationService.translateQuick(
                    word: word,
                    context: context,
                    onRetry: { [weak self] (attempt: Int, total: Int) in
                        Task { @MainActor in
                            self?.translationStatus = L10n.format(
                                "正在重試 (%@/%@)...",
                                "\(attempt)",
                                "\(total)"
                            )
                        }
                    }
                )
            }

            do {
                let result = try await translationTask.value
                guard !Task.isCancelled else { return }
                withAnimation(AppMotion.feedbackPulse) {
                    translationResult = result
                    isTranslating = false
                    translationStatus = nil
                    translationErrorMessage = nil
                }
                await Task.yield()
                if let selection = wordSelection {
                    autoSaveToVocabulary(
                        selection: selection,
                        result: result,
                        context: vocabularyContext
                    )
                }
            } catch {
                guard !(error is CancellationError), !Task.isCancelled else { return }
                AppLog.reader.error("翻譯錯誤: \(error.localizedDescription)")
                translationResult = nil
                isTranslating = false
                translationStatus = nil
                translationErrorMessage = L10n.format("翻譯失敗：%@", error.localizedDescription)
            }
        }
        replaceCurrentTranslationTask(with: newTask)
    }

    func handlePhraseSelected(
        phrase: String,
        context: String,
        vocabularyContext: ReaderVocabularyContext
    ) {
        cancelCurrentTranslationTask()
        let selection = WordSelection(word: phrase, context: context, position: .zero)
        wordSelection = selection

        withAnimation(AppMotion.panelState) {
            isTranslating = true
            translationResult = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
            translationErrorMessage = nil
            explanationErrorMessage = nil
        }

        let task = Task { @MainActor in
            do {
                let translation = try await translationService.translatePhrase(
                    phrase: phrase,
                    context: context,
                    onRetry: { [weak self] (attempt: Int, total: Int) in
                        Task { @MainActor in
                            self?.translationStatus = L10n.format(
                                "正在重試 (%@/%@)...",
                                "\(attempt)",
                                "\(total)"
                            )
                        }
                    }
                )
                let result = TranslationResult(
                    translation: translation,
                    partOfSpeech: nil,
                    explanation: nil
                )
                guard !Task.isCancelled else { return }
                withAnimation(AppMotion.feedbackPulse) {
                    translationResult = result
                    isTranslating = false
                    translationStatus = nil
                    translationErrorMessage = nil
                }
                guard !Task.isCancelled else { return }
                await Task.yield()
                autoSaveToVocabulary(
                    selection: selection,
                    result: result,
                    context: vocabularyContext
                )
            } catch {
                translationResult = nil
                isTranslating = false
                translationStatus = nil
                translationErrorMessage = L10n.format("翻譯失敗：%@", error.localizedDescription)
            }
        }
        replaceCurrentTranslationTask(with: task)
    }

    func handleExplainSelected(text: String, context: String) {
        cancelCurrentTranslationTask()
        let selection = WordSelection(word: text, context: context, position: .zero)
        wordSelection = selection

        withAnimation(AppMotion.panelState) {
            isTranslating = false
            translationResult = nil
            isSaved = false
            isExpanded = true
            isLoadingExplanation = true
            explanationText = nil
            translationErrorMessage = nil
            explanationErrorMessage = nil
        }

        let task = Task { @MainActor in
            do {
                let (explanation, _) = try await translationService.fetchExplanation(
                    word: text,
                    context: context,
                    onRetry: { [weak self] (attempt: Int, total: Int) in
                        Task { @MainActor in
                            self?.explanationStatus = L10n.format(
                                "正在重試 (%@/%@)...",
                                "\(attempt)",
                                "\(total)"
                            )
                        }
                    }
                )
                withAnimation(AppMotion.feedbackPulse) {
                    explanationText = explanation
                    isLoadingExplanation = false
                    explanationStatus = nil
                    explanationErrorMessage = nil
                }
            } catch {
                explanationText = nil
                isLoadingExplanation = false
                explanationStatus = nil
                explanationErrorMessage = L10n.format("載入失敗：%@", error.localizedDescription)
            }
        }
        replaceCurrentTranslationTask(with: task)
    }

    func handleExpand() {
        withAnimation(AppMotion.panelState) {
            isExpanded.toggle()
        }

        guard authManager.isLoggedIn, isExpanded, !isLoadingExplanation,
              let selection = wordSelection else { return }

        explanationText = nil
        isLoadingExplanation = true
        explanationStatus = nil
        explanationErrorMessage = nil

        let task = Task { @MainActor in
            do {
                let (explanation, latency) = try await translationService.fetchExplanation(
                    word: selection.word,
                    context: selection.context,
                    onRetry: { [weak self] (attempt: Int, total: Int) in
                        Task { @MainActor in
                            self?.explanationStatus = L10n.format(
                                "正在重試 (%@/%@)...",
                                "\(attempt)",
                                "\(total)"
                            )
                        }
                    }
                )
                withAnimation(AppMotion.feedbackPulse) {
                    explanationText = explanation
                    isLoadingExplanation = false
                    explanationStatus = nil
                    explanationErrorMessage = nil
                    if var updatedResult = translationResult {
                        updatedResult.latency = latency
                        translationResult = updatedResult
                    }
                }
            } catch {
                AppLog.reader.error("解釋錯誤: \(error.localizedDescription)")
                explanationText = nil
                isLoadingExplanation = false
                explanationStatus = nil
                explanationErrorMessage = L10n.format("載入失敗：%@", error.localizedDescription)
            }
        }
        replaceCurrentTranslationTask(with: task)
    }
}
