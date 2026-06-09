import Foundation
import Testing
@testable import BooksAndVocab

/// Pins the `TodayReviewPresenterState.PostExampleMetrics.from(_:)` pure-function that
/// drives the `answerExampleRadius` layout calculation every frame during a review session.
/// A regression here would cause the answer-fold geometry to jitter or clip on real cards,
/// so the iteration must stay deterministic across every CardDocumentBlock variant.
struct TodayReviewPostExampleMetricsTests {

    // MARK: - Helpers

    private func meaning(_ paragraphCount: Int) -> CardDocumentBlock {
        let paragraphs = (0..<paragraphCount).map { _ in
            CardDocumentParagraph(inlines: [.text("x")])
        }
        return .meaning(CardDocumentMeaning(title: "", paragraphs: paragraphs))
    }

    private func example() -> CardDocumentBlock {
        .example(CardDocumentParagraph(inlines: [.text("sample sentence.")]))
    }

    private func hero() -> CardDocumentBlock {
        .hero(CardDocumentHero(
            word: "test",
            partOfSpeech: nil,
            difficultyTier: nil,
            reviewModeTitle: ""
        ))
    }

    private func source() -> CardDocumentBlock {
        .source(CardDocumentSource(
            context: CardDocumentParagraph(inlines: [.text("ctx")]),
            bookTitle: "Book",
            chapterTitle: nil
        ))
    }

    // MARK: - Empty / pre-example branches contribute nothing

    @Test func empty_document_yields_zero_metrics() {
        let metrics = TodayReviewPresenterState.PostExampleMetrics
            .from(CardDocument(blocks: []))
        #expect(metrics.fixedHeight == 0)
        #expect(metrics.gapCount == 0)
        #expect(metrics.totalHeight(gap: 8) == 0)
    }

    @Test func blocks_before_example_are_ignored() {
        // Only blocks AFTER the first `.example` contribute — heroes/meanings before
        // it must be skipped entirely.
        let doc = CardDocument(blocks: [
            hero(),
            meaning(2),
            .divider
        ])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 0)
        #expect(metrics.gapCount == 0)
    }

    @Test func example_itself_does_not_contribute_height() {
        // The `.example` case in the switch only flips `seenExample = true`; it must not
        // bump fixedHeight or gapCount on its own.
        let doc = CardDocument(blocks: [example()])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 0)
        #expect(metrics.gapCount == 0)
    }

    // MARK: - Per-block branch coverage (each post-example case)

    @Test func divider_after_example_contributes_thin_height_and_one_gap() {
        let doc = CardDocument(blocks: [example(), .divider])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == AppMetrics.dividerThin)
        #expect(metrics.gapCount == 1)
    }

    @Test func meaning_after_example_height_scales_with_paragraph_count() {
        // Formula: lineCount = paragraphs.count * 3, heightPerLine = 22.
        // 2 paragraphs → 6 lines → 132pt.
        let doc = CardDocument(blocks: [example(), meaning(2)])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 132)
        #expect(metrics.gapCount == 1)
    }

    @Test func meaning_after_example_with_single_paragraph() {
        // 1 paragraph → 3 lines → 66pt.
        let doc = CardDocument(blocks: [example(), meaning(1)])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 66)
        #expect(metrics.gapCount == 1)
    }

    @Test func collocations_after_example_two_items_one_row() {
        // rows = max(1, (count + 1) / 2). 2 items → (2+1)/2 = 1 row → 32pt.
        let doc = CardDocument(blocks: [example(), .collocations(["a", "b"])])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 32)
        #expect(metrics.gapCount == 1)
    }

    @Test func collocations_after_example_three_items_two_rows() {
        // 3 items → (3+1)/2 = 2 rows → 64pt.
        let doc = CardDocument(blocks: [example(), .collocations(["a", "b", "c"])])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 64)
        #expect(metrics.gapCount == 1)
    }

    @Test func collocations_after_example_empty_array_still_one_row_min() {
        // `max(1, …)` guard means even an empty collocations block reserves one row.
        let doc = CardDocument(blocks: [example(), .collocations([])])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 32)
        #expect(metrics.gapCount == 1)
    }

    @Test func source_after_example_takes_default_30_branch() {
        // `.source` is not handled explicitly → falls through to `default: 30pt`.
        let doc = CardDocument(blocks: [example(), source()])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 30)
        #expect(metrics.gapCount == 1)
    }

    @Test func hero_after_example_takes_default_30_branch() {
        // `.hero` similarly hits the default branch — pinned so a future explicit case
        // forces a deliberate test update.
        let doc = CardDocument(blocks: [example(), hero()])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 30)
        #expect(metrics.gapCount == 1)
    }

    @Test func second_example_after_first_falls_into_default_branch() {
        // After the first `.example` flips `seenExample`, a second `.example` matches
        // `case .example:` again — that arm sets `seenExample = true` but adds nothing.
        let doc = CardDocument(blocks: [example(), example()])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == 0)
        #expect(metrics.gapCount == 0)
    }

    // MARK: - Composite documents

    @Test func mixed_blocks_after_example_accumulate() {
        // divider (0.5) + meaning(1) (66) + collocations 2 (32) = 98.5pt, 3 gaps.
        let doc = CardDocument(blocks: [
            hero(),                             // pre-example, ignored
            example(),                          // flips seenExample
            .divider,                           // +0.5, +1 gap
            meaning(1),                         // +66, +1 gap
            .collocations(["a", "b"])           // +32, +1 gap
        ])
        let metrics = TodayReviewPresenterState.PostExampleMetrics.from(doc)
        #expect(metrics.fixedHeight == AppMetrics.dividerThin + 66 + 32)
        #expect(metrics.gapCount == 3)
    }

    // MARK: - totalHeight gap arithmetic

    @Test func total_height_applies_gap_per_block() {
        let metrics = TodayReviewPresenterState.PostExampleMetrics
            .from(CardDocument(blocks: [example(), .divider, meaning(1)]))
        // fixedHeight = 0.5 + 66 = 66.5, gapCount = 2, gap = 10 → 66.5 + 20 = 86.5.
        #expect(metrics.totalHeight(gap: 10) == 86.5)
    }

    @Test func total_height_zero_gap_equals_fixed_height() {
        let metrics = TodayReviewPresenterState.PostExampleMetrics
            .from(CardDocument(blocks: [example(), meaning(2), .collocations(["a", "b"])]))
        // fixedHeight = 132 + 32 = 164.
        #expect(metrics.totalHeight(gap: 0) == 164)
        #expect(metrics.fixedHeight == 164)
    }

    @Test func total_height_negative_gap_subtracts_per_block() {
        // Defensive: callers should never pass negative gap, but the function is pure
        // arithmetic — pin the math so it stays predictable.
        let metrics = TodayReviewPresenterState.PostExampleMetrics
            .from(CardDocument(blocks: [example(), .divider, .divider]))
        // fixedHeight = 1.0, gapCount = 2, gap = -2 → 1.0 - 4 = -3.
        #expect(metrics.totalHeight(gap: -2) == -3)
    }
}
