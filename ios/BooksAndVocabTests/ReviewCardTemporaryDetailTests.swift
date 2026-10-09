import Foundation
import Testing
@testable import BooksAndVocab

/// #2041 — a compact card can be shown detailed for a moment. The override is
/// per-card, transient (leaving the card forgets it) and never reaches a
/// persisted layout store.
@MainActor
struct ReviewCardTemporaryDetailTests {
    private static let compact = ReviewCardLayoutProfile(recognition: .compact, production: .compact)

    // MARK: Pure value

    @Test func toggleIsScopedToOneCard() {
        var detail = ReviewCardTemporaryDetail()
        #expect(!detail.isDetailed(cardKey: "a"))

        detail.toggle(cardKey: "a")
        #expect(detail.isDetailed(cardKey: "a"))
        #expect(!detail.isDetailed(cardKey: "b"), "another card must never inherit the override")

        detail.toggle(cardKey: "a")
        #expect(!detail.isDetailed(cardKey: "a"), "the same button restores compact")
    }

    @Test func resetReportsWhetherItChangedAnything() {
        var detail = ReviewCardTemporaryDetail()
        #expect(detail.reset() == false, "an idle reset must not write (no spurious observation)")
        detail.toggle(cardKey: "a")
        #expect(detail.reset() == true)
        #expect(!detail.isDetailed(cardKey: "a"))
    }

    @Test func buttonOnlyExistsForCompactCards() {
        #expect(
            ReviewCardTemporaryDetail.toggleState(profile: .default, mode: .recognition, isDetailed: false)
                == .unavailable,
            "a card already on the standard preset shows no button"
        )
        #expect(
            ReviewCardTemporaryDetail.toggleState(profile: Self.compact, mode: .recognition, isDetailed: false)
                == .showDetail
        )
        #expect(
            ReviewCardTemporaryDetail.toggleState(profile: Self.compact, mode: .recognition, isDetailed: true)
                == .restoreCompact
        )
        let mixed = ReviewCardLayoutProfile(recognition: .standard, production: .compact)
        #expect(ReviewCardTemporaryDetail.toggleState(profile: mixed, mode: .recognition, isDetailed: false) == .unavailable)
        #expect(ReviewCardTemporaryDetail.toggleState(profile: mixed, mode: .production, isDetailed: false) == .showDetail)
    }

    @Test func renderProfileRestoresTheStandardFacesForThatModeOnly() {
        let rendered = ReviewCardTemporaryDetail.renderProfile(Self.compact, mode: .production, isDetailed: true)
        #expect(rendered.production == .standard)
        #expect(rendered.recognition == .compact, "the other direction is not this card's business")
        // Production's standard FRONT carries the example back too (issue: 正面例句也要還原).
        #expect(rendered.layout(for: .production).front.contains(.example))
        #expect(rendered.layout(for: .production).back.contains(.explanation))

        #expect(ReviewCardTemporaryDetail.renderProfile(Self.compact, mode: .production, isDetailed: false) == Self.compact)
        #expect(ReviewCardTemporaryDetail.renderProfile(.default, mode: .production, isDetailed: true) == .default)
    }

    @Test func prospectiveFieldsAreExactlyWhatDetailWouldAdd() {
        let available = ReviewCardContentAvailability.forReviewCard(
            partOfSpeech: "v.",
            difficultyTier: "B2",
            exampleCount: 1,
            explanationParagraphCount: 1,
            collocationCount: 2
        )
        #expect(
            ReviewCardTemporaryDetail.prospectiveBlockFields(
                profile: Self.compact, mode: .recognition, face: .back, availability: available
            ) == [.example, .explanation, .collocations]
        )
        #expect(
            ReviewCardTemporaryDetail.prospectiveBlockFields(
                profile: Self.compact, mode: .production, face: .front, availability: available
            ) == [.example]
        )
        #expect(
            ReviewCardTemporaryDetail.prospectiveBlockFields(
                profile: .default, mode: .recognition, face: .back, availability: available
            ).isEmpty,
            "a standard card has nothing to pre-measure"
        )
        let noExtras = ReviewCardContentAvailability.forReviewCard(
            partOfSpeech: nil,
            difficultyTier: nil,
            exampleCount: 0,
            explanationParagraphCount: 0,
            collocationCount: 0
        )
        #expect(
            ReviewCardTemporaryDetail.prospectiveBlockFields(
                profile: Self.compact, mode: .recognition, face: .back, availability: noExtras
            ).isEmpty,
            "fields with no content must not leave a probe mounted forever"
        )
    }

    // MARK: Session state

    @Test func leavingTheCardRestoresCompactAndComingBackStaysCompact() throws {
        let entries = Self.makeEntries(count: 3)
        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        let firstKey = try #require(state.currentCardForTesting?.card.reviewCardKey)

        state.toggleTemporaryDetail()
        #expect(state.presenterState.temporaryDetailCardKey == firstKey)

        state.goNext()
        #expect(state.presenterState.temporaryDetailCardKey == nil, "advancing must forget the override")

        state.goPrevious()
        #expect(state.currentCardForTesting?.card.reviewCardKey == firstKey)
        #expect(state.presenterState.temporaryDetailCardKey == nil, "returning to the card must NOT restore detail")
    }

    @Test func shufflingAlsoLeavesTheCard() {
        let entries = Self.makeEntries(count: 4)
        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        state.toggleTemporaryDetail()
        #expect(state.presenterState.temporaryDetailCardKey != nil)
        state.shuffleQueue()
        #expect(state.presenterState.temporaryDetailCardKey == nil)
    }

    @Test func toggleNeverWritesThePersistedLayoutProfile() {
        let key = ReviewCardLayoutStore.storageKey
        func snapshot() -> [String: String] {
            let all = UserDefaults.standard.dictionaryRepresentation()
            return all.filter { $0.key.hasSuffix(key) }.compactMapValues { $0 as? String }
        }
        let before = snapshot()
        let entries = Self.makeEntries(count: 2)
        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)

        state.toggleTemporaryDetail()
        state.toggleTemporaryDetail()
        state.toggleTemporaryDetail()

        #expect(snapshot() == before, "the override is session memory, not a setting")
    }

    @Test func aNewSessionStartsCompact() {
        let entries = Self.makeEntries(count: 2)
        let first = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        first.toggleTemporaryDetail()
        #expect(first.presenterState.temporaryDetailCardKey != nil)

        let reentered = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        #expect(reentered.presenterState.temporaryDetailCardKey == nil)
    }

    @Test func showingDetailPausesAutoplayAndRestoringDoesNotResumeIt() {
        let entries = Self.makeEntries(count: 3)
        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        state.toggleAutoPlay()
        defer { state.stopAutoPlay() }
        #expect(state.isAutoPlaying && !state.isAutoPlayPaused)

        state.toggleTemporaryDetail()
        #expect(state.presenterState.temporaryDetailCardKey != nil)
        #expect(state.isAutoPlayPaused, "an autoplay advance would forget the detailed view within one interval")

        state.toggleTemporaryDetail()
        #expect(state.presenterState.temporaryDetailCardKey == nil)
        #expect(state.isAutoPlayPaused, "restoring compact must not silently resume playback")
    }

    @Test func togglingDetailWithoutAutoplayDoesNotStartOrPausePlayback() {
        let entries = Self.makeEntries(count: 2)
        let state = TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
        state.toggleTemporaryDetail()
        #expect(!state.isAutoPlaying)
        #expect(!state.isAutoPlayPaused)
    }

    private static func makeEntries(count: Int) -> [VocabularyEntry] {
        (0..<count).map { index in
            let entry = VocabularyEntry(
                word: "temporary-\(index)",
                translation: "translation-\(index)",
                context: "A sample sentence for word \(index).",
                bookTitle: "Sample"
            )
            entry.dateAdded = Date(timeIntervalSinceReferenceDate: TimeInterval(index))
            entry.markSynced()
            return entry
        }
    }
}
