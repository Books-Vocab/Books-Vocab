import SwiftUI

extension ReaderTranslationHandler {
    func handleWordSelected(
        word: String,
        context: String,
        vocabularyContext: ReaderVocabularyContext
    ) {
        let normalizedWord = normalizeWord(word)
        let selection = WordSelection(word: normalizedWord, context: context, position: .zero)
        wordSelection = selection

        if let existing = vocabularyContext.existingEntry(matching: word) {
            withAnimation(.spring(response: 0.3)) {
                translationResult = TranslationResult(
                    translation: existing.translation,
                    partOfSpeech: nil,
                    pronunciation: nil,
                    explanation: nil
                )
                pronunciation = existing.pronunciation
                isSaved = true
                isTranslating = false
                isExpanded = false
                explanationText = nil
            }
            print("📦 從生詞庫載入: \(word) → \(existing.word)")
            return
        }

        if !authManager.isLoggedIn {
            withAnimation(.spring(response: 0.3)) {
                isTranslating = false
                translationResult = nil
                isSaved = false
                isExpanded = false
                explanationText = nil
            }
            Task { @MainActor in
                let fetchedPron = await DictionaryService.fetchPronunciation(word: word)
                pronunciation = fetchedPron
                guestSaveToVocabulary(
                    selection: selection,
                    pronunciation: fetchedPron,
                    context: vocabularyContext
                )
            }
            return
        }

        withAnimation(.spring(response: 0.3)) {
            isTranslating = true
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
        }

        currentTranslationTask?.cancel()
        currentTranslationTask = Task { @MainActor in
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

            let pronTask = Task {
                await DictionaryService.fetchPronunciation(word: word)
            }

            do {
                let result = try await translationTask.value
                withAnimation {
                    translationResult = result
                    isTranslating = false
                    translationStatus = nil
                }

                let fetchedPron = await pronTask.value
                withAnimation {
                    pronunciation = fetchedPron
                }
                if let selection = wordSelection {
                    autoSaveToVocabulary(
                        selection: selection,
                        result: result,
                        pronunciation: fetchedPron,
                        context: vocabularyContext
                    )
                }
            } catch {
                guard !(error is CancellationError) else { return }
                print("❌ 翻譯錯誤: \(error)")
                let fetchedPron = await pronTask.value
                translationResult = TranslationResult(
                    translation: L10n.format("翻譯失敗：%@", error.localizedDescription),
                    partOfSpeech: nil,
                    pronunciation: nil,
                    explanation: nil
                )
                pronunciation = fetchedPron
                isTranslating = false
                translationStatus = nil
            }
        }
    }

    func handlePhraseSelected(
        phrase: String,
        context: String,
        vocabularyContext: ReaderVocabularyContext
    ) {
        let selection = WordSelection(word: phrase, context: context, position: .zero)
        wordSelection = selection

        withAnimation(.spring(response: 0.3)) {
            isTranslating = true
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
        }

        Task { @MainActor in
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
                    pronunciation: nil,
                    explanation: nil
                )
                withAnimation {
                    translationResult = result
                    isTranslating = false
                    translationStatus = nil
                }
                autoSaveToVocabulary(
                    selection: selection,
                    result: result,
                    pronunciation: nil,
                    context: vocabularyContext
                )
            } catch {
                translationResult = TranslationResult(
                    translation: L10n.format("翻譯失敗：%@", error.localizedDescription),
                    partOfSpeech: nil,
                    pronunciation: nil,
                    explanation: nil
                )
                isTranslating = false
                translationStatus = nil
            }
        }
    }

    func handleExplainSelected(text: String, context: String) {
        let selection = WordSelection(word: text, context: context, position: .zero)
        wordSelection = selection

        withAnimation(.spring(response: 0.3)) {
            isTranslating = false
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = true
            isLoadingExplanation = true
            explanationText = nil
        }

        Task { @MainActor in
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
                withAnimation {
                    explanationText = explanation
                    isLoadingExplanation = false
                    explanationStatus = nil
                }
            } catch {
                explanationText = L10n.format("載入失敗：%@", error.localizedDescription)
                isLoadingExplanation = false
                explanationStatus = nil
            }
        }
    }

    func handleExpand() {
        withAnimation(.spring(response: 0.3)) {
            isExpanded.toggle()
        }

        guard authManager.isLoggedIn, isExpanded, !isLoadingExplanation,
              let selection = wordSelection else { return }

        explanationText = nil
        isLoadingExplanation = true
        explanationStatus = nil

        Task { @MainActor in
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
                withAnimation {
                    explanationText = explanation
                    isLoadingExplanation = false
                    explanationStatus = nil
                    if var updatedResult = translationResult {
                        updatedResult.latency = latency
                        translationResult = updatedResult
                    }
                }
            } catch {
                print("❌ 解釋錯誤: \(error)")
                explanationText = L10n.format("載入失敗：%@", error.localizedDescription)
                isLoadingExplanation = false
                explanationStatus = nil
            }
        }
    }
}
