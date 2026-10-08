import Foundation
import SwiftUI

/// What the search field's Return key does for the current input (#2038).
///
/// Creating a word spends AI quota, so Return NEVER creates: with nothing in the
/// notebook it only puts the keyboard away and points at the create entry. It
/// also never links a merely partial match, even a lone one — only a word that is
/// exactly the typed word (normalized like the backend's `_clean_content`).
/// Linking the wrong word is cheap to undo, but only an exact match is certain.
enum AddLinkReturnBehavior: Equatable {
    /// The typed word is exactly a linkable existing word: link it.
    case linkExact(UUID)
    /// The typed word is exactly a word the source already links to: do nothing
    /// but say so.
    case alreadyLinked
    /// Partial matches (including a single one) or a word that cannot be linked:
    /// just put the keyboard away so the whole list is visible.
    case dismissKeyboard
    /// Nothing in the notebook has this word: keyboard away, create entry
    /// highlighted. Never creates.
    case revealCreate

    /// The keyboard key label announces what Return will do. `SubmitLabel` has no
    /// custom text, so "link" maps to `.join` (the system-localized word closest
    /// to "add / link") and everything else to `.done`.
    var submitLabel: SubmitLabel {
        switch self {
        case .linkExact: .join
        case .alreadyLinked, .dismissKeyboard, .revealCreate: .done
        }
    }

    /// The decision's name, exposed as the value of the hidden
    /// `addLink.return.action` element so UITests (which cannot read the
    /// keyboard label) can assert what Return will do.
    var accessibilityValue: String {
        switch self {
        case .linkExact: "linkExact"
        case .alreadyLinked: "alreadyLinked"
        case .dismissKeyboard: "dismissKeyboard"
        case .revealCreate: "revealCreate"
        }
    }

    /// True only when Return would link: the matching row shows the "↵" hint.
    var linksOnReturn: Bool {
        if case .linkExact = self { return true }
        return false
    }

    static func resolve(_ snapshot: AddLinkSearchSnapshot) -> AddLinkReturnBehavior {
        guard !snapshot.isEmptyQuery, let state = snapshot.exactTargetState else { return .dismissKeyboard }
        switch state {
        case .active:
            let typed = AddLinkCreationCoordinator.normalizeWord(snapshot.trimmedQuery)
            if let exact = snapshot.candidates.first(where: {
                AddLinkCreationCoordinator.normalizeWord($0.word) == typed
            }) {
                return .linkExact(exact.id)
            }
            // The exact word exists but fell outside the candidate list (the list
            // is capped): never guess among partial matches.
            return .dismissKeyboard
        case .linked:
            return .alreadyLinked
        case .missing:
            return snapshot.candidates.isEmpty ? .revealCreate : .dismissKeyboard
        case .pending, .failed, .archived, .source:
            return .dismissKeyboard
        }
    }
}
