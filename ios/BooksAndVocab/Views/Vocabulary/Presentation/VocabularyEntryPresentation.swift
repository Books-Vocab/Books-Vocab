import Foundation

enum VocabularyRoleFilter: String, CaseIterable, Identifiable {
    case all
    case learning
    case dictionary

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: L10n.string("dictionary.filter.all")
        case .learning: L10n.string("dictionary.filter.learning")
        case .dictionary: L10n.string("dictionary.filter.dictionary")
        }
    }
}

/// The complete query for the vocabulary library. Content scope, learning state,
/// search, and ordering are separate dimensions; none is inferred from another
/// domain field or cleared as a View side effect.
struct VocabularyLibraryQuery: Equatable {
    var contentScope: VocabularyRoleFilter
    var reviewStates: Set<VocabularyReviewState>
    var searchText: String
    var sort: KGVocabSortOption

    init(
        contentScope: VocabularyRoleFilter = .all,
        reviewStates: Set<VocabularyReviewState> = [],
        searchText: String = "",
        sort: KGVocabSortOption = .default
    ) {
        self.contentScope = contentScope
        self.reviewStates = reviewStates
        self.searchText = searchText
        self.sort = sort
    }

    /// Returns the only valid query representation. Dictionary cards have no
    /// review dimension, and the review-priority sort has no meaning there.
    var normalized: Self {
        var value = self
        value.searchText = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        if contentScope == .dictionary {
            value.reviewStates = []
            if !KGVocabSortOption.dictionaryOptions.contains(sort) {
                value.sort = .alphabetical
            }
        }
        return value
    }

    func withSearchText(_ text: String) -> Self {
        var value = self
        value.searchText = text
        return value
    }

    mutating func setContentScope(_ scope: VocabularyRoleFilter) {
        contentScope = scope
        if scope == .dictionary {
            reviewStates = []
            if !KGVocabSortOption.dictionaryOptions.contains(sort) {
                sort = .alphabetical
            }
        }
    }

    mutating func toggleReviewState(_ state: VocabularyReviewState) {
        if reviewStates.contains(state) {
            reviewStates.remove(state)
        } else {
            reviewStates.insert(state)
        }
    }

    mutating func setSort(_ option: KGVocabSortOption) {
        if contentScope == .dictionary,
           !KGVocabSortOption.dictionaryOptions.contains(option) {
            sort = .alphabetical
        } else {
            sort = option
        }
    }

    mutating func setReviewState(_ state: VocabularyReviewState?) {
        reviewStates = state.map { [$0] } ?? []
    }
}

struct VocabularyReviewQueue: Equatable {
    let due: [VocabularyEntry]
    let unlearned: [VocabularyEntry]

    var isEmpty: Bool { due.isEmpty && unlearned.isEmpty }
    var all: [VocabularyEntry] { due + unlearned }
}

struct VocabularyFacetCounts: Equatable {
    let content: [VocabularyRoleFilter: Int]
    let review: [VocabularyReviewState: Int]

    func contentCount(for filter: VocabularyRoleFilter) -> Int {
        content[filter, default: 0]
    }

    func reviewCount(for state: VocabularyReviewState) -> Int {
        review[state, default: 0]
    }
}

struct VocabularyEmptyStateContext: Equatable {
    let hasNoEntries: Bool
    let hasEntriesInScope: Bool
    let hasVisibleEntries: Bool
    let contentScope: VocabularyRoleFilter
    let searchText: String
    let reviewStates: Set<VocabularyReviewState>

    /// Kept as a named alias so callers can read the domain term used in
    /// acceptance criteria without reintroducing a second source of truth.
    var roleFilter: VocabularyRoleFilter { contentScope }
}

struct VocabularyLibraryProjection {
    let effectiveQuery: VocabularyLibraryQuery
    let visibleEntries: [VocabularyEntry]
    let facetCounts: VocabularyFacetCounts
    let reviewQueue: VocabularyReviewQueue
    let emptyStateContext: VocabularyEmptyStateContext

    func count(for filter: VocabularyRoleFilter) -> Int {
        facetCounts.contentCount(for: filter)
    }

    func reviewCount(for state: VocabularyReviewState) -> Int {
        facetCounts.reviewCount(for: state)
    }

    var hasEntriesInScope: Bool { emptyStateContext.hasEntriesInScope }
}

enum VocabularyEntryPresentation {
    static func pendingEntries(in entries: [VocabularyEntry]) -> [VocabularyEntry] {
        entries.filter(\.shouldUploadOnNextSync)
    }

    static func filterByRole(
        _ entries: [VocabularyEntry], filter: VocabularyRoleFilter
    ) -> [VocabularyEntry] {
        switch filter {
        case .all: entries
        case .learning: entries.filter { $0.cardRole == .learning }
        case .dictionary: entries.filter { $0.cardRole == .dictionary }
        }
    }

    /// Produces one query contract with two explicit layers:
    /// scope-wide facets/CTA (stable while searching) and visible rows (search /
    /// review selection applied last). Naming the layers here prevents a future
    /// caller from treating a scope-wide facet as if it were a visible-row count.
    static func project(
        _ entries: [VocabularyEntry],
        query: VocabularyLibraryQuery,
        now: Date
    ) -> VocabularyLibraryProjection {
        let effectiveQuery = query.normalized
        let allEntriesInScope = filterByRole(entries, filter: effectiveQuery.contentScope)
        let searchMatches = filterBySearch(allEntriesInScope, searchText: effectiveQuery.searchText)
        let classified = classifyKnowledgeEntries(in: allEntriesInScope, now: now)
        let selectedEntries: [VocabularyEntry]
        if effectiveQuery.reviewStates.isEmpty {
            selectedEntries = searchMatches
        } else {
            let selectedIDs = Set(classified.mergedBucket(for: effectiveQuery.reviewStates).map(\.id))
            selectedEntries = searchMatches.filter { selectedIDs.contains($0.id) }
        }
        let visibleEntries = sortAndFilter(
            selectedEntries,
            searchText: "",
            sortOption: effectiveQuery.sort,
            now: now
        )

        let contentCounts = Dictionary(uniqueKeysWithValues: VocabularyRoleFilter.allCases.map { filter in
            (filter, filterByRole(entries, filter: filter).count)
        })
        let reviewCounts = Dictionary(uniqueKeysWithValues: VocabularyReviewState.allCases.map { state in
            (state, classified.count(for: state))
        })
        let reviewVisible = allEntriesInScope.filter { $0.shouldAppearInReview }
        let reviewQueue = VocabularyReviewQueue(
            due: reviewVisible.filter { $0.reviewState(at: now) == .due },
            unlearned: reviewVisible.filter { $0.reviewState(at: now) == .unlearned }
        )

        return VocabularyLibraryProjection(
            effectiveQuery: effectiveQuery,
            visibleEntries: visibleEntries,
            facetCounts: VocabularyFacetCounts(content: contentCounts, review: reviewCounts),
            reviewQueue: reviewQueue,
            emptyStateContext: VocabularyEmptyStateContext(
                hasNoEntries: entries.isEmpty,
                hasEntriesInScope: !allEntriesInScope.isEmpty,
                hasVisibleEntries: !visibleEntries.isEmpty,
                contentScope: effectiveQuery.contentScope,
                searchText: effectiveQuery.searchText,
                reviewStates: effectiveQuery.reviewStates
            )
        )
    }

    /// 多選模式下實際可被選取的 row id。
    ///
    /// 字典卡不參與批次刪除 / 封存，所以「全選」只挑得動 learning row。**同一份
    /// 集合必須同時餵給 `selectAll` 與 `updateVisibleCount`** —— 兩邊各自算一次
    /// 就會分岔：在「全部」tab 上只要畫面有任何一張字典卡，`isAllSelected`
    /// （`selectedIDs.count == visibleCount`）永遠不成立，toolbar 只會一直提供
    /// 「全選」，使用者按不到「取消全選」。
    static func selectableIDs(in entries: [VocabularyEntry]) -> [UUID] {
        entries.filter { $0.cardRole == .learning }.map(\.id)
    }

    /// Single-pass partition of knowledge entries into review-state buckets.
    /// Returns counts and the filtered+sorted list for the selected state.
    struct ClassifiedResult {
        var dueBucket: [VocabularyEntry]
        var unlearnedBucket: [VocabularyEntry]
        var reviewedBucket: [VocabularyEntry]

        var dueCount: Int { dueBucket.count }
        var unlearnedCount: Int { unlearnedBucket.count }
        var reviewedCount: Int { reviewedBucket.count }

        func count(for state: VocabularyReviewState) -> Int {
            switch state {
            case .due: return dueCount
            case .unlearned: return unlearnedCount
            case .reviewed: return reviewedCount
            }
        }

        func bucket(for state: VocabularyReviewState) -> [VocabularyEntry] {
            switch state {
            case .due: return dueBucket
            case .unlearned: return unlearnedBucket
            case .reviewed: return reviewedBucket
            }
        }

        func mergedBucket(for states: Set<VocabularyReviewState>) -> [VocabularyEntry] {
            if states.isEmpty {
                return dueBucket + unlearnedBucket + reviewedBucket
            }
            var result: [VocabularyEntry] = []
            for state in VocabularyReviewState.allCases where states.contains(state) {
                result.append(contentsOf: bucket(for: state))
            }
            return result
        }
    }

    static func classifyKnowledgeEntries(
        in entries: [VocabularyEntry],
        now: Date
    ) -> ClassifiedResult {
        var due: [VocabularyEntry] = []
        var unlearned: [VocabularyEntry] = []
        var reviewed: [VocabularyEntry] = []

        for entry in entries {
            guard entry.shouldAppearInReview else { continue }
            switch entry.reviewState(at: now) {
            case .due: due.append(entry)
            case .unlearned: unlearned.append(entry)
            case .reviewed: reviewed.append(entry)
            }
        }

        return ClassifiedResult(
            dueBucket: due,
            unlearnedBucket: unlearned,
            reviewedBucket: reviewed
        )
    }

    static func sortAndFilter(
        _ entries: [VocabularyEntry],
        searchText: String,
        sortOption: KGVocabSortOption = .default,
        now: Date
    ) -> [VocabularyEntry] {
        // Filter first to reduce sort input size
        let base = searchText.isEmpty ? entries : entries.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }

        switch sortOption {
        case .default:
            return base.sorted { compareKnowledgeEntries($0, $1, now: now) }
        case .alphabetical:
            return base.sorted { compareWords($0, $1) }
        case .dateAdded:
            return base.sorted { lhs, rhs in
                if lhs.effectiveDateAdded != rhs.effectiveDateAdded {
                    return lhs.effectiveDateAdded > rhs.effectiveDateAdded
                }
                return compareWords(lhs, rhs)
            }
        case .difficulty:
            return base.sorted { lhs, rhs in
                if lhs.reviewEligible != rhs.reviewEligible {
                    return lhs.reviewEligible
                }
                let lhsTier = tierPriority(lhs.difficultyTier)
                let rhsTier = tierPriority(rhs.difficultyTier)
                if lhsTier != rhsTier { return lhsTier < rhsTier }
                return compareWords(lhs, rhs)
            }
        }
    }

    private static func filterBySearch(
        _ entries: [VocabularyEntry],
        searchText: String
    ) -> [VocabularyEntry] {
        guard !searchText.isEmpty else { return entries }
        return entries.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
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
        if lhs.reviewEligible != rhs.reviewEligible {
            return lhs.reviewEligible
        }
        if !lhs.reviewEligible {
            if lhs.effectiveDateAdded != rhs.effectiveDateAdded {
                return lhs.effectiveDateAdded > rhs.effectiveDateAdded
            }
            return compareWords(lhs, rhs)
        }
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
        return compareWords(lhs, rhs)
    }

    /// Swift's `sorted` is not a stable-sort contract. Every sort branch must
    /// therefore end at the persisted UUID after comparing the visible word,
    /// otherwise two equal-looking cards can reorder between renders and make
    /// both lazy-list identity and Simulator evidence nondeterministic.
    private static func compareWords(_ lhs: VocabularyEntry, _ rhs: VocabularyEntry) -> Bool {
        let wordOrder = lhs.word.localizedCaseInsensitiveCompare(rhs.word)
        if wordOrder != .orderedSame {
            return wordOrder == .orderedAscending
        }
        return lhs.id.uuidString < rhs.id.uuidString
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
