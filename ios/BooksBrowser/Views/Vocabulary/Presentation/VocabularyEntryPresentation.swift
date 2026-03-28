import Foundation

enum VocabularyEntryPresentation {
    static func pendingEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries.filter(\.shouldUploadOnNextSync)
    }

    static func syncedKnowledgeEntries(in entries: [VocabularyEntry], now: Date = Date()) -> [VocabularyEntry] {
        entries
            .filter(\.shouldAppearInKnowledgeList)
            .sorted { compareKnowledgeEntries($0, $1, now: now) }
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
        sortOption: KGVocabSortOption = .default,
        now: Date = Date()
    ) -> [VocabularyEntry] {
        let baseFiltered = entries
            .filter { $0.shouldAppearInKnowledgeList && $0.reviewState(at: now) == reviewState }

        let sorted: [VocabularyEntry]
        switch sortOption {
        case .default:
            sorted = baseFiltered.sorted { compareKnowledgeEntries($0, $1, now: now) }
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

    static func knowledgeReviewEntries(in entries: [VocabularyEntry], now: Date = Date()) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries, now: now).filter {
            let state = $0.reviewState(at: now)
            return state == .due || state == .unlearned
        }
    }

    static func knowledgeDueEntries(in entries: [VocabularyEntry], now: Date = Date()) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries, now: now).filter { $0.reviewState(at: now) == .due }
    }

    static func knowledgeUnlearnedEntries(in entries: [VocabularyEntry], now: Date = Date()) -> [VocabularyEntry] {
        syncedKnowledgeEntries(in: entries, now: now).filter { $0.reviewState(at: now) == .unlearned }
    }

    static func countKnowledgeEntries(
        in entries: [VocabularyEntry],
        reviewState: VocabularyReviewState,
        now: Date = Date()
    ) -> Int {
        entries.count { $0.shouldAppearInKnowledgeList && $0.reviewState(at: now) == reviewState }
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

    static func compareKnowledgeEntries(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry, now: Date) -> Bool {
        if reviewPriority(lhs.reviewState(at: now)) != reviewPriority(rhs.reviewState(at: now)) {
            return reviewPriority(lhs.reviewState(at: now)) < reviewPriority(rhs.reviewState(at: now))
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
