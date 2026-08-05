import Foundation
import SwiftUI
import Testing
@testable import BooksAndVocab

// MARK: - Viewport budget

/// The front face's budget is not the GeometryReader's height: the card region
/// pads itself, and the reveal affordance holds a hard floor BELOW the card for
/// the whole front stage. `ReviewCardViewport` owns that arithmetic once so the
/// solver's budget and the drawn clamp cannot disagree.
struct ReviewCardViewportTests {

    @Test func front_budget_excludes_the_outer_inset_and_the_reveal_zone() {
        let viewport = ReviewCardViewport(containerHeight: 600)
        let insets = TodayReviewMetrics.cardTopInset + TodayReviewMetrics.cardBottomInset

        #expect(viewport.contentHeight == 600 - insets)
        #expect(viewport.revealZoneReserve == TodayReviewMetrics.revealZoneMinHeight)
        #expect(viewport.frontHeight == 600 - insets - TodayReviewMetrics.revealZoneMinHeight)
        // The defect this pins: the raw container height must never reach the solver.
        #expect(viewport.frontHeight < viewport.containerHeight)
    }

    @Test func reveal_zone_reserve_follows_the_ratio_once_it_beats_the_floor() {
        // 1000 × 0.22 = 220 > 180 floor.
        #expect(ReviewCardViewport(containerHeight: 1000).revealZoneReserve == 220)
        // 400 × 0.22 = 88 < 180 floor → the floor wins, exactly as the zone draws it.
        #expect(ReviewCardViewport(containerHeight: 400).revealZoneReserve == TodayReviewMetrics.revealZoneMinHeight)
    }

    @Test func back_budget_starts_from_the_inset_content_height_not_the_container() {
        let viewport = ReviewCardViewport(containerHeight: 600)
        #expect(viewport.backHeight(frontOccupied: 200) == viewport.contentHeight - 200)
        #expect(viewport.backHeight(frontOccupied: 10_000) == 0)
    }

    @Test func a_viewport_shorter_than_its_own_chrome_never_reports_negative_room() {
        let viewport = ReviewCardViewport(containerHeight: 10)
        #expect(viewport.contentHeight == 0)
        #expect(viewport.frontHeight == 0)
        #expect(viewport.backHeight(frontOccupied: 0) == 0)
    }

    /// On a region too short for the 180pt floor the zone must give way, not
    /// starve the card: reserving the floor there would leave the front ~0pt.
    @Test func the_reveal_zone_never_takes_more_than_half_a_short_region() {
        let short = ReviewCardViewport(containerHeight: 300)
        #expect(short.revealZoneReserve == short.contentHeight / 2)
        #expect(short.frontHeight == short.contentHeight / 2)
        #expect(short.frontHeight > 0)
        // The cap is inactive at every normal portrait size.
        #expect(ReviewCardViewport(containerHeight: 600).revealZoneReserve
            == TodayReviewMetrics.revealZoneMinHeight)
    }

    /// The defect in one assertion. 600pt container: the honest front budget is
    /// 600 − 16 inset − 180 reveal zone − 78 front chrome = 326pt, while the raw
    /// height gives the solver 522pt. A face measuring 468pt therefore "fits" on
    /// the naive budget — the ladder never runs and the VStack pushes through the
    /// expand zone's floor — but must compact on the honest one.
    @Test func an_overfull_front_face_compacts_inside_the_honest_budget() {
        let viewport = ReviewCardViewport(containerHeight: 600)
        let measurements: [ReviewCardLayoutSolver.Section: ReviewCardLayoutSolver.Measurement] = [
            .core: .init(naturalHeight: 120),
            .example: .init(naturalHeight: 150, compactHeight: 60),
            .explanation: .init(naturalHeight: 150, intermediateHeight: 100, compactHeight: 50)
        ]
        func solve(_ height: CGFloat) -> ReviewCardLayoutSolver.Result {
            ReviewCardLayoutSolver.solve(.init(
                face: .front,
                fields: [.example, .explanation],
                measurements: measurements,
                viewportHeight: height,
                minimumHeight: 0
            ))
        }

        let honest = solve(viewport.frontHeight)
        #expect(honest.policy(for: .example).exampleRadius == 3)
        #expect(honest.cardHeight <= viewport.frontHeight)

        let naive = solve(viewport.containerHeight)
        #expect(naive.policy(for: .example).exampleRadius == nil)
        #expect(naive.cardHeight > viewport.frontHeight)
    }
}

// MARK: - Default parity

struct ReviewCardDefaultParityTests {

    @Test func graph_link_section_stays_available_on_a_card_with_no_links() {
        let availability = ReviewCardContentAvailability.forReviewCard(
            partOfSpeech: "n.",
            difficultyTier: nil,
            exampleCount: 0,
            explanationParagraphCount: 0,
            collocationCount: 0
        )
        // The add-link affordance is the only entry point for the first link, so
        // the section must survive an empty link set.
        #expect(availability.graphLinks)
        #expect(availability.partOfSpeech)
        #expect(!availability.difficultyTier)
        #expect(!availability.example)
        #expect(!availability.explanation)
        #expect(!availability.collocations)
    }

    @Test func the_default_back_face_keeps_every_section_of_a_bare_card() {
        let plan = ReviewCardRenderPlan.make(
            profile: .default,
            mode: .recognition,
            availability: .forReviewCard(
                partOfSpeech: nil,
                difficultyTier: nil,
                exampleCount: 0,
                explanationParagraphCount: 0,
                collocationCount: 0
            )
        )
        #expect(plan.back.fields == [.graphLinks])
    }

    /// The shipped picture is the old `compact: true` document: explanation clamped
    /// to 3 lines, collocations to 2 rows. Those are the NATURAL tier here, not an
    /// already-compacted one — otherwise the default card starts looser than today.
    @Test func natural_tier_reproduces_todays_compact_document_presentation() {
        #expect(ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: nil) == 3)
        #expect(ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: 2) == 2)
        #expect(ReviewCardLayoutSolver.explanationLineLimit(policyLineLimit: 1) == 1)

        #expect(ReviewCardLayoutSolver.collocationRowLimit(lineLimit: nil) == 2)
        #expect(ReviewCardLayoutSolver.collocationRowLimit(lineLimit: 2) == 2)
        #expect(ReviewCardLayoutSolver.collocationRowLimit(lineLimit: 1) == 1)
    }

    /// The back face used to expand the example into whatever space was free
    /// (`answerExampleRadius`, effectively "show the sentence"); the front kept the
    /// static skin radius. The solver replaces the budget maths, so natural back =
    /// no truncation, natural front = the same static radius as before.
    @Test func natural_example_radius_is_face_dependent() {
        #expect(ReviewCardLayoutSolver.naturalExampleRadius(for: .back, staticRadius: 5) == nil)
        #expect(ReviewCardLayoutSolver.naturalExampleRadius(for: .front, staticRadius: 5) == 5)
    }

    @Test func the_answer_divider_is_drawn_only_when_something_follows_it() {
        #expect(!ReviewCardLayoutSolver.drawsAnswerDivider(fields: []))
        #expect(ReviewCardLayoutSolver.drawsAnswerDivider(fields: [.graphLinks]))
    }
}

