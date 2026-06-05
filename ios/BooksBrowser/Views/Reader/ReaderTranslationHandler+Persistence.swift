#if os(iOS)
import SwiftUI
import os

extension ReaderTranslationHandler {
    func deleteFromVocabulary(_ word: String, context: any VocabularyContextProtocol) {
        context.deleteEntry(matching: word)
        dismiss()
    }

    func loadLookedUpWords(from vocabulary: [VocabularyEntry]) {
        lookedUpWords = ReaderVocabularyContext.lookedUpWords(from: vocabulary)
    }

    func dismiss() {
        cancelCurrentTranslationTask()
        withAnimation(AppMotion.panelState) {
            wordSelection = nil
            translationResult = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
            translationStatus = nil
            explanationStatus = nil
            translationErrorMessage = nil
            explanationErrorMessage = nil
        }
        clearHighlightTrigger = UUID()
    }

    func autoSaveToVocabulary(
        selection: WordSelection,
        result: TranslationResult,
        context: any VocabularyContextProtocol
    ) {
        if handleExistingEntry(selection.word, in: context) { return }

        let inserted = context.saveEntry(
            selection: selection,
            translation: result.translation,
            rootForm: result.rootForm
        )
        if inserted {
            AppLog.reader.info("Auto-saved: \(selection.word)")
        }
        markAlreadySaved(selection.word)
    }

    func guestSaveToVocabulary(
        selection: WordSelection,
        context: any VocabularyContextProtocol
    ) {
        if handleExistingEntry(selection.word, in: context) { return }

        let inserted = context.saveEntry(
            selection: selection,
            translation: ""
        )
        if inserted {
            AppLog.reader.info("Guest saved: \(selection.word)")
        }
        markAlreadySaved(selection.word)
    }

    func normalizeWord(_ word: String) -> String {
        word.precomposedStringWithCompatibilityMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func markAlreadySaved(_ word: String) {
        appendLookedUpWordIfNeeded(word)
        withAnimation(AppMotion.feedbackPulse) { isSaved = true }
    }

    private func handleExistingEntry(_ word: String, in context: any VocabularyContextProtocol) -> Bool {
        if let existing = context.existingEntry(matching: word),
           existing.syncAction != .delete {
            markAlreadySaved(word)
            return true
        }
        return false
    }

    private func appendLookedUpWordIfNeeded(_ word: String) {
        let normalizedWord = word.lowercased()
        if !lookedUpWords.contains(normalizedWord) {
            lookedUpWords.append(normalizedWord)
        }
    }
}
#endif
