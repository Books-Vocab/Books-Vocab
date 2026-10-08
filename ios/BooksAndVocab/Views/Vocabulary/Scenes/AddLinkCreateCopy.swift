import Foundation

/// Copy for the Add Link "create" entry (#2037): one sentence that says the whole
/// action ("create X and link it to Y") plus the notebook the new card lands in.
///
/// Pure and `nonisolated`: the sheet, the tests and any future surface read the
/// same strings. The legacy `建立` key is deliberately untouched — it is also the
/// progress step label of `create_card`.
enum AddLinkCreateCopy {
    /// Longest word (in user-perceived characters) shown verbatim inside the
    /// sentence. Longer words are shortened so the verb and the source word stay
    /// whole.
    nonisolated static let wordDisplayLimit = 20

    /// Straight apostrophe: never one of the quote marks the copy wraps words in.
    private nonisolated static let neutralQuote: Character = "'"
    private nonisolated static let quoteMarks: Set<Character> = ["「", "」", "『", "』", "“", "”", "\""]

    /// Trims, folds any run of whitespace/newlines into one space, swaps quote
    /// marks that would collide with the sentence's own quoting, and shortens to
    /// `limit` characters with a trailing ellipsis.
    nonisolated static func displayWord(_ word: String, limit: Int = wordDisplayLimit) -> String {
        let flattened = word
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
            .map { quoteMarks.contains($0) ? neutralQuote : $0 }
        let text = String(flattened)
        guard limit > 1, text.count > limit else { return text }
        let head = String(text.prefix(limit - 1)).trimmingCharacters(in: .whitespaces)
        return head + "…"
    }

    nonisolated static func title(target: String, source: String, language: AppLanguage? = nil) -> String {
        let target = displayWord(target)
        let source = displayWord(source)
        if let language {
            return L10n.format("addLink.create.title", language: language, target, source)
        }
        return L10n.format("addLink.create.title", target, source)
    }

    /// `notebookName` is already resolved (never an id) — see
    /// `ReviewCardNotebookBadgeResolver.badge(for:notebooks:)`.
    nonisolated static func notebookLine(notebookName: String, language: AppLanguage? = nil) -> String {
        let name = displayNotebookName(notebookName)
        if let language {
            return L10n.format("addLink.create.notebook", language: language, name)
        }
        return L10n.format("addLink.create.notebook", name)
    }

    private nonisolated static func displayNotebookName(_ name: String) -> String {
        name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }
}
