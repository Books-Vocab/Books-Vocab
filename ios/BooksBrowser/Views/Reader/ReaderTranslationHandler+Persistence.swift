import SwiftUI
import os

extension ReaderTranslationHandler {
    func deleteFromVocabulary(_ word: String, context: ReaderVocabularyContext) {
        context.deleteEntry(matching: word)
        dismiss()
    }

    func loadLookedUpWords(from vocabulary: [VocabularyEntry]) {
        lookedUpWords = ReaderVocabularyContext.lookedUpWords(from: vocabulary)
    }

    func dismiss() {
        withAnimation(AppMotion.panelState) {
            wordSelection = nil
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
            translationErrorMessage = nil
            explanationErrorMessage = nil
        }
        clearHighlightTrigger = UUID()
    }

    func autoSaveToVocabulary(
        selection: WordSelection,
        result: TranslationResult,
        pronunciation: String?,
        context: ReaderVocabularyContext
    ) {
        if context.existingEntry(matching: selection.word) != nil {
            appendLookedUpWordIfNeeded(selection.word)
            withAnimation(AppMotion.feedbackPulse) { isSaved = true }
            return
        }

        let inserted = context.saveEntry(
            selection: selection,
            translation: result.translation,
            pronunciation: pronunciation,
            rootForm: result.rootForm
        )
        if inserted {
            AppLog.reader.info("Auto-saved: \(selection.word)")
        }
        appendLookedUpWordIfNeeded(selection.word)
        withAnimation(AppMotion.feedbackPulse) { isSaved = true }
    }

    func guestSaveToVocabulary(
        selection: WordSelection,
        pronunciation: String?,
        context: ReaderVocabularyContext
    ) {
        if context.existingEntry(matching: selection.word) != nil {
            appendLookedUpWordIfNeeded(selection.word)
            withAnimation(AppMotion.feedbackPulse) { isSaved = true }
            return
        }

        let inserted = context.saveEntry(
            selection: selection,
            translation: "",
            pronunciation: pronunciation
        )
        if inserted {
            AppLog.reader.info("Guest saved: \(selection.word)")
        }
        appendLookedUpWordIfNeeded(selection.word)
        withAnimation(AppMotion.feedbackPulse) { isSaved = true }
    }

    func normalizeWord(_ word: String) -> String {
        word.precomposedStringWithCompatibilityMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func appendLookedUpWordIfNeeded(_ word: String) {
        let normalizedWord = word.lowercased()
        if !lookedUpWords.contains(normalizedWord) {
            lookedUpWords.append(normalizedWord)
        }
    }
}
