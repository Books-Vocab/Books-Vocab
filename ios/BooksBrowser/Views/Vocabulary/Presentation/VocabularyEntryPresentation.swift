import Foundation

enum VocabularyEntryPresentation {
    static func pendingEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries.filter(\.shouldUploadOnNextSync)
    }

    static func syncedKnowledgeEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries
            .filter(\.shouldAppearInKnowledgeList)
            .sorted(by: compareKnowledgeEntries)
    }

    static func filteredPendingEntries(
        in entries: [VocabularyEntry],
        searchText: String
    ) -> [VocabularyEntry] {
        let sortedPending = pendingEntries(in: entries).sorted(by: comparePendingEntries)

        guard !searchText.isEmpty else { return sortedPending }
        return sortedPending.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    static func filteredKnowledgeEntries(
        in entries: [VocabularyEntry],
        reviewState: VocabularyReviewState,
        searchText: String,
        sortOption: KGVocabSortOption = .default
    ) -> [VocabularyEntry] {
        let baseFiltered = entries
            .filter { $0.shouldAppearInKnowledgeList && $0.reviewState == reviewState }

        let sorted: [VocabularyEntry]
        switch sortOption {
        case .default:
            sorted = baseFiltered.sorted(by: compareKnowledgeEntries)
        case .alphabetical:
            sorted = baseFiltered.sorted {
                $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending
            }
        case .dateAdded:
            sorted = baseFiltered.sorted { $0.dateAdded > $1.dateAdded }
        case .difficulty:
            sorted = baseFiltered.sorted { lhs, rhs in
                let lhsTier = tierPriority(lhs.difficultyTier)
                let rhsTier = tierPriority(rhs.difficultyTier)
                if lhsTier != rhsTier { return lhsTier < rhsTier }
                return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
            }
        }

        guard !searchText.isEmpty else { return sorted }
        return sorted.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    static func knowledgeReviewEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries).filter {
            $0.reviewState == .due || $0.reviewState == .unlearned
        }
    }

    static func knowledgeDueEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries).filter { $0.reviewState == .due }
    }

    static func knowledgeUnlearnedEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries).filter { $0.reviewState == .unlearned }
    }

    static func countKnowledgeEntries(
        in entries: [VocabularyEntry],
        reviewState: VocabularyReviewState
    ) -> Int {
        syncedKnowledgeEntries(in: entries).filter { $0.reviewState == reviewState }.count
    }

    static func archivedEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries
            .filter(\.shouldAppearInArchiveList)
            .sorted { $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending }
    }

    static func filteredArchivedEntries(
        in entries: [VocabularyEntry],
        searchText: String
    ) -> [VocabularyEntry] {
        let all = archivedEntries(in: entries)
        guard !searchText.isEmpty else { return all }
        return all.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    static func compareKnowledgeEntries(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry) -> Bool {
        if reviewPriority(lhs.reviewState) != reviewPriority(rhs.reviewState) {
            return reviewPriority(lhs.reviewState) < reviewPriority(rhs.reviewState)
        }
        if lhs.nextReviewAt != rhs.nextReviewAt {
            return lhs.nextReviewAt < rhs.nextReviewAt
        }
        let lhsTier = tierPriority(lhs.difficultyTier)
        let rhsTier = tierPriority(rhs.difficultyTier)
        if lhsTier != rhsTier {
            return lhsTier < rhsTier
        }
        return lhs.word.localizedCaseInsensitiveCompare(rhs.word) == .orderedAscending
    }

    static func comparePendingEntries(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry) -> Bool {
        if lhs.isReviewDue != rhs.isReviewDue {
            return lhs.isReviewDue && !rhs.isReviewDue
        }
        if lhs.nextReviewAt != rhs.nextReviewAt {
            return lhs.nextReviewAt < rhs.nextReviewAt
        }
        return lhs.dateAdded > rhs.dateAdded
    }

    private static func reviewPriority(_ state: VocabularyReviewState) -> Int {
        switch state {
        case .due: return 0
        case .unlearned: return 1
        case .reviewed: return 2
        }
    }

    private static func tierPriority(_ tier: String?) -> Int {
        switch tier {
        case "core": return 0
        case "intermediate": return 1
        case "advanced": return 2
        case "rare": return 3
        default: return 4
        }
    }
}
