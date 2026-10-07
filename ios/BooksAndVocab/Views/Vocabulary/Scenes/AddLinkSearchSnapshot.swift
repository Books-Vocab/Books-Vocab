import Foundation

/// Everything the Add Link sheet derives from one search query, computed once
/// per render instead of once per reader (lookup marker, list, row selection).
struct AddLinkSearchSnapshot {
    /// The query with surrounding whitespace removed.
    let trimmedQuery: String
    let candidates: [VocabularyEntry]
    /// Exact-word state of the query; only meaningful (and only computed) when
    /// there are no candidates, which is when the sheet shows it.
    let missingTargetState: AddLinkLocalTargetState?

    var isEmptyQuery: Bool { trimmedQuery.isEmpty }

    func containsCandidate(_ entry: VocabularyEntry) -> Bool {
        candidates.contains { $0.id == entry.id }
    }

    static func make(
        query: String,
        sourceEntry: VocabularyEntry,
        allEntries: [VocabularyEntry]
    ) -> AddLinkSearchSnapshot {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidates = AddLinkCoordinator.localCandidates(
            query: query,
            sourceEntry: sourceEntry,
            allEntries: allEntries
        )
        let missingTargetState: AddLinkLocalTargetState? = trimmed.isEmpty || !candidates.isEmpty
            ? nil
            : AddLinkCreationCoordinator.localTargetState(
                query: query,
                sourceEntry: sourceEntry,
                allEntries: allEntries
            )
        return AddLinkSearchSnapshot(
            trimmedQuery: trimmed,
            candidates: candidates,
            missingTargetState: missingTargetState
        )
    }
}
