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
            isPanelLarge = false
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

    /// Capture-normalize for single-word selections before translate/save.
    ///
    /// Steps: NFC compat mapping (NFKC) → trim whitespace → strip *trailing*
    /// sentence punctuation `.,;:!?`. Only the last two steps are a shared
    /// contract with backend `_clean_content` (`backend/src/kg/vocab_shared.py`,
    /// `.strip().rstrip(".,;:!?")`); the NFC step is iOS-only — `_clean_content`
    /// does no Unicode normalization (backend's NFC lives in the separate
    /// dedup-key path `_normalize_word`, and is canonical NFC, not NFKC). See
    /// `docs/reference/card_format.md` §"Word capture normalization" for the
    /// per-end step table. Podcast (UITextView) and PDF (PDFKit) selections
    /// arrive with trailing punctuation attached; stripping here keeps the local
    /// card / vocab preview clean instead of relying on the backend as the only
    /// cleanup point. Case and word-internal punctuation (`don't`, `well-known`)
    /// are preserved; lowercasing is the backend's dedup concern, not capture's.
    /// This is *capture* normalize, not
    /// *match* normalize — highlight matching has its own looser rules
    /// (`PodcastVocabHighlightResolver` / EPUB JS) applied live on both sides.
    func normalizeWord(_ word: String) -> String {
        var result = Substring(
            word.precomposedStringWithCompatibilityMapping
                .trimmingCharacters(in: .whitespacesAndNewlines)
        )
        while let last = result.last, Self.trailingCapturePunctuation.contains(last) {
            result = result.dropLast()
        }
        return String(result)
    }

    /// Trailing sentence punctuation removed at capture time. Mirrors backend
    /// `_clean_content`'s `.rstrip(".,;:!?")`.
    private static let trailingCapturePunctuation: Set<Character> = [".", ",", ";", ":", "!", "?"]

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
