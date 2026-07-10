import XCTest

/// Flip-gap investigation (`debug/review-flip-gap`).
///
/// Reproduces + measures the reported bug: after some flips the card detaches
/// from the bottom "tap to expand" zone, leaving a large vertical gap that
/// persists across flips and only resets on shuffle. Two hypotheses, both a
/// consequence of the Phase-4 resident-slot ZStack taking its layout height
/// from the TALLEST of its three slots:
///   - H1 (content height): a taller background card (preview / underPreview)
///     inflates the region and pushes the expand zone down. Repro signature =
///     gap appears at a SHORT active card that has a TALL neighbour in its
///     preview window.
///   - H2 (stuck answer): a recycled slot's answer surface fails to collapse to
///     height 0 after grading. Repro signature = gap appears even when the whole
///     preview window is short (e.g. `gapshort2`, whose window is 3 short cards).
///
/// The deck (`notebook:reviewDeckVaried`) is deliberately height-varied so both
/// signatures are observable in one run. The on-screen gap is measured directly
/// as `expandZone.minY − cardFront.maxY`; the DEBUG `gap.geom` PerfLog (per-slot
/// layout heights, captured from os_log alongside) attributes the inflating slot
/// and its answer height for a decisive H1-vs-H2 verdict.
final class TodayReviewGapUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"
    private static let deckSize = 8
    /// Healthy gap = card-bottom inset + micro offsets (tens of pt). A tall
    /// background slot inflates it by the card-height delta (100pt+), so a
    /// generous 44pt threshold cleanly separates healthy from bug.
    private static let gapThreshold: CGFloat = 44

    override func setUpWithError() throws {
        try super.setUpWithError()
        // 8 cards × (reveal + grade) springs push this past the 60s default.
        executionTimeAllowance = 240
    }

    private struct GapSample {
        let index: Int
        let word: String
        let gap: CGFloat
        let cardHeight: CGFloat
        let cardMaxY: CGFloat
        let zoneMinY: CGFloat
    }

    @MainActor
    func testCardStaysAttachedToExpandZoneAcrossVariedDeck() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeckVaried],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("varied review deck fixture 應種出單字本卡片 \(Self.notebookCardID)")
            return
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("varied deck 有未學卡片，複習 CTA 必須出現")
            return
        }
        let review = notebook.startReview()
        guard review.progressLabel.waitUntilExists(timeout: 10) else {
            captureStep("review-not-started", app: app)
            XCTFail("tap CTA 後必須進入複習 session；progress label 缺席")
            return
        }

        var samples: [GapSample] = []

        for i in 0..<Self.deckSize {
            // Settle before reading frames (grading fling + advance spring).
            _ = review.cardFront.waitUntilExists(timeout: 8)
            RunLoop.current.run(until: Date().addingTimeInterval(0.6))
            guard review.cardFront.exists, review.expandZone.exists else {
                captureStep("card-\(i)-missing-elements", app: app)
                break
            }

            let word = review.frontWord
            let cardFrame = review.cardFront.frame
            let zoneFrame = review.expandZone.frame
            let gap = zoneFrame.minY - cardFrame.maxY
            samples.append(GapSample(
                index: i,
                word: word,
                gap: gap,
                cardHeight: cardFrame.height,
                cardMaxY: cardFrame.maxY,
                zoneMinY: zoneFrame.minY
            ))

            // 逐張截圖：gap 斷言是數值 guard，截圖是視覺證據（此 bug 有視覺成分——
            // 被 cap 的較高背景卡若溢出會顯示在 expand zone 區）。命名含 gap 值。
            captureStep("card-\(i)-\(word)-gap\(Int(gap))", app: app)

            // Advance: reveal + grade (exercises the answer-collapse path, H2).
            guard i < Self.deckSize - 1 else { break }
            review.flipCard()
            _ = review.cardBack.waitUntilExists(timeout: 5)
            RunLoop.current.run(until: Date().addingTimeInterval(0.3))
            review.tapRemembered()
            _ = review.waitForProgress("\(i + 2) / \(Self.deckSize)")
            _ = review.cardBack.waitUntilGone(timeout: 5)
        }

        // Full table → offline correlation with the gap.geom per-slot PerfLog.
        let table = samples.map { s in
            String(
                format: "  [%d] %@ gap=%.1f cardH=%.1f cardMaxY=%.1f zoneMinY=%.1f",
                s.index, s.word, s.gap, s.cardHeight, s.cardMaxY, s.zoneMinY
            )
        }.joined(separator: "\n")
        let tableAttachment = XCTAttachment(string: table)
        tableAttachment.name = "gap-samples"
        add(tableAttachment)

        let offenders = samples.filter { $0.gap >= Self.gapThreshold }
        XCTAssertTrue(
            offenders.isEmpty,
            "卡片與 expand zone 出現大縫隙（gap >= \(Self.gapThreshold)pt）:\n"
                + offenders.map {
                    "  card[\($0.index)] \($0.word) gap=\(String(format: "%.1f", $0.gap))pt"
                        + " (cardH=\(String(format: "%.1f", $0.cardHeight)))"
                }.joined(separator: "\n")
                + "\n全表:\n" + table
        )
    }
}
