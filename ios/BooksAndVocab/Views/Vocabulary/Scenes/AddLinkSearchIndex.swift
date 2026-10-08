import Foundation

/// Per-entry search keys for the Add Link candidate list (#2406).
///
/// `localCandidates` runs on every keystroke. Locale-folding `word` and `translation` allocates a
/// new string per entry and used to be repeated for the whole store on each query. The sheet owns
/// one index for its lifetime, so each entry is folded once on first use and every later keystroke
/// only pays a dictionary lookup, two string equality checks and a `contains` on the cached key.
///
/// A slot remembers the raw `word` / `translation` it was built from; an edit to either is noticed
/// on the next lookup and the slot is rebuilt, so the index never serves a stale key. Folding is
/// still `locale: .current`, so a locale change drops every slot. Not thread-safe: create and use
/// it from one actor (the sheet's main actor). Passing no index (the default) gives a throwaway
/// one, which behaves exactly like the old uncached scan.
final class AddLinkSearchIndex {
    private struct Slot {
        let word: String
        let translation: String
        var foldedWord: String?
        var foldedTranslation: String?
        var normalizedWord: String?
    }

    private static let foldOptions: String.CompareOptions = [.caseInsensitive, .diacriticInsensitive]

    private var slots: [UUID: Slot] = [:]
    private var localeIdentifier = Locale.current.identifier

    init() {}

    /// Case- and diacritic-insensitive fold in the current locale; the query and every cached key
    /// go through this single function so they can never disagree.
    static func fold(_ value: String) -> String {
        value.folding(options: foldOptions, locale: .current)
    }

    /// Drops every cached key when the user's locale changed since they were built.
    func syncLocale() {
        let current = Locale.current.identifier
        guard current != localeIdentifier else { return }
        localeIdentifier = current
        slots.removeAll(keepingCapacity: true)
    }

    /// True when the folded `word` or `translation` contains `foldedQuery`. Like the old inline
    /// `||`, the translation is only folded when the word did not match.
    func matches(_ entry: VocabularyEntry, foldedQuery: String) -> Bool {
        var slot = resolvedSlot(for: entry)
        var dirty = false
        defer { if dirty { slots[entry.id] = slot } }

        let foldedWord: String
        if let cached = slot.foldedWord {
            foldedWord = cached
        } else {
            foldedWord = Self.fold(slot.word)
            slot.foldedWord = foldedWord
            dirty = true
        }
        if foldedWord.contains(foldedQuery) { return true }

        let foldedTranslation: String
        if let cached = slot.foldedTranslation {
            foldedTranslation = cached
        } else {
            foldedTranslation = Self.fold(slot.translation)
            slot.foldedTranslation = foldedTranslation
            dirty = true
        }
        return foldedTranslation.contains(foldedQuery)
    }

    /// True when the entry's word is the typed word after the backend's own normalisation.
    func isExactWord(_ entry: VocabularyEntry, normalizedQuery: String) -> Bool {
        var slot = resolvedSlot(for: entry)
        if let cached = slot.normalizedWord { return cached == normalizedQuery }
        let normalized = AddLinkCreationCoordinator.normalizeWord(slot.word)
        slot.normalizedWord = normalized
        slots[entry.id] = slot
        return normalized == normalizedQuery
    }

    private func resolvedSlot(for entry: VocabularyEntry) -> Slot {
        let word = entry.word
        let translation = entry.translation
        if let slot = slots[entry.id], slot.word == word, slot.translation == translation {
            return slot
        }
        return Slot(word: word, translation: translation)
    }
}
