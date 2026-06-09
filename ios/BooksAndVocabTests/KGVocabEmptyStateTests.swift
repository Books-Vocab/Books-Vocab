#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `KGVocabEmptyState` — the pure copy/icon resolver behind KGVocabView's
/// empty phase. The three fields (title/description/systemImage) share one
/// branch precedence: `hasNoEntries` > non-empty `searchText` > non-empty
/// `filters` > default. This suite locks that precedence and the icon's
/// distinct `filters.count == 1` branch so a future copy edit can't silently
/// desync the three fields.
struct KGVocabEmptyStateTests {

    private let allFilters: Set<VocabularyReviewState> = [.unlearned, .due, .reviewed]

    // MARK: - Precedence

    @Test func hasNoEntries_winsOverSearchAndFilters() {
        // Even with a search term and filters active, an empty notebook reports
        // the "整本空" copy/icon, never the search/filter variants.
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: true, searchText: "x", filters: allFilters) == "books.vertical")
        let title = KGVocabEmptyState.title(hasNoEntries: true, searchText: "x", filters: allFilters)
        #expect(title == KGVocabEmptyState.title(hasNoEntries: true, searchText: "", filters: []))
    }

    @Test func search_winsOverFilters() {
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: false, searchText: "cat", filters: allFilters) == "magnifyingglass")
    }

    @Test func defaultIcon_whenNothingActive() {
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: false, searchText: "", filters: []) == "line.3.horizontal.decrease.circle")
    }

    // MARK: - Icon: single-filter distinct branch

    @Test func singleFilter_usesPerStateIcon() {
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: false, searchText: "", filters: [.unlearned]) == "sparkles")
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: false, searchText: "", filters: [.due]) == "checkmark.seal")
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: false, searchText: "", filters: [.reviewed]) == "leaf")
    }

    @Test func multipleFilters_fallBackToGenericIcon() {
        // count >= 2 is NOT the single-state branch — falls through to generic.
        #expect(KGVocabEmptyState.systemImage(hasNoEntries: false, searchText: "", filters: [.due, .reviewed]) == "line.3.horizontal.decrease.circle")
    }

    // MARK: - Title / description default-equals-empty invariant

    @Test func title_emptyNotebookEqualsDefault() {
        // The original collapsed hasNoEntries and the fall-through to the same
        // string — pin that so they can't drift apart.
        let emptyNotebook = KGVocabEmptyState.title(hasNoEntries: true, searchText: "", filters: [])
        let defaultCase = KGVocabEmptyState.title(hasNoEntries: false, searchText: "", filters: [])
        #expect(emptyNotebook == defaultCase)
    }

    @Test func description_eachBranchDistinct() {
        let empty = KGVocabEmptyState.description(hasNoEntries: true, searchText: "", filters: [])
        let search = KGVocabEmptyState.description(hasNoEntries: false, searchText: "x", filters: [])
        let filter = KGVocabEmptyState.description(hasNoEntries: false, searchText: "", filters: [.due])
        let fallback = KGVocabEmptyState.description(hasNoEntries: false, searchText: "", filters: [])
        #expect(Set([empty, search, filter, fallback]).count == 4)
    }
}
#endif
