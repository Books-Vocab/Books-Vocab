//
//  NotebookReviewFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Notebook → Today Review flashcard flow with REAL seeded vocabulary +
//  visual evidence, following the PodcastPlaybackPerfUITests model
//  (docs/sop/ui_flow_evidence.md 六件套).
//
//  Fixture: `-seedFixture:notebook:reviewDeck` — a real notebook scoped over
//  the deterministic review probe deck (reuses the existing
//  `makeReviewProbeDeck` builder; real-shaped entries, no mock rows).
//
//  Core behaviors asserted as STATE CHANGES, not taps:
//    - flip: back content really mounts, and its translation pairs with the
//      front word (card N front ↔ "量測卡片 N 的譯文…" back)
//    - grading: progress "k / N" really advances, per-feedback counters
//      really increment, and the next card arrives with the back unmounted
//  Gate assertions: fixture has unlearned cards, so a missing notebook card,
//  missing review CTA, or an empty review phase is XCTFail — never skip.
//

import XCTest

final class NotebookReviewFlowUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"
    private static let deckSize = 8

    override func setUpWithError() throws {
        try super.setUpWithError()
        // List → session → flip → two gradings → close; the reveal/fling
        // springs push this past the harness default 60s allowance.
        executionTimeAllowance = 120
    }

    @MainActor
    func testNotebookReviewFlipAndGradingAdvanceQueue() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
            // The guest session reviews locally; point networking at an
            // unreachable port anyway so no part of the flow can reach a
            // real backend (same hermetic seam as AuthFlowUITests).
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        // ── 1. Notebook list renders the real seeded notebook card ──────────
        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("notebook.reviewDeck fixture 應種出單字本卡片 \(Self.notebookCardID)；列表空狀態 = fixture 未生效")
            return
        }
        try step("notebook-list", app: app) {
            XCTAssertTrue(app.waitForNavigationToSettle())
        }

        // ── 2. Review CTA gate: 8 unlearned cards MUST surface a CTA ────────
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("fixture 有 \(Self.deckSize) 張未學卡片，今日複習 CTA 必須出現；缺席 = 統計或 fixture 壞掉")
            return
        }
        let review = notebook.startReview()

        // ── 3. Session really started (NOT the empty/loading phase) ─────────
        guard review.progressLabel.waitUntilExists(timeout: 10) else {
            captureStep("review-not-started", app: app)
            XCTFail("tap CTA 後必須進入複習 session；progress label 缺席 = 落入空/載入/錯誤 phase")
            return
        }
        try step("review-started", app: app) {
            XCTAssertEqual(
                review.progressText,
                "1 / \(Self.deckSize)",
                "deck fixture 應產生 \(Self.deckSize) 張卡的 session"
            )
            review.cardFront.assertExists()
            XCTAssertFalse(review.cardBack.exists, "翻卡前背面內容不得已掛載（應為 stub）")
        }

        // ── 4. Flip: back content mounts AND pairs with the front word ──────
        let firstWord = review.frontWord
        XCTAssertTrue(
            firstWord.hasPrefix("probeword"),
            "正面必須顯示 fixture 詞條，實際讀到：\(firstWord)"
        )
        review.flipCard()
        guard review.cardBack.waitUntilExists(timeout: 5) else {
            captureStep("flip-no-back", app: app)
            XCTFail("翻卡後背面內容必須掛載（todayReview.card.back 未出現）")
            return
        }
        try step("card-flipped", app: app) {
            let expectedTranslation = "量測卡片 \(Self.cardNumber(fromWord: firstWord)) 的譯文"
            XCTAssertTrue(
                app.descendants(matching: .any)
                    .matching(NSPredicate(format: "label CONTAINS %@", expectedTranslation))
                    .firstMatch.waitUntilExists(timeout: 3),
                "背面譯文必須與正面單字同卡配對（期望含「\(expectedTranslation)」）"
            )
        }

        // ── 5. Grade remembered: the queue really advances ──────────────────
        review.tapRemembered()
        XCTAssertTrue(
            review.waitForProgress("2 / \(Self.deckSize)"),
            "評分後 progress 必須前進到 2 / \(Self.deckSize)，實際：\(review.progressText)"
        )
        try step("graded-remembered", app: app) {
            XCTAssertTrue(
                review.waitUntilLabel(of: review.rememberedButton, contains: "·1"),
                "記得計數應顯示 ·1，實際 label：\(review.rememberedButton.label)"
            )
        }

        // ── 6. Next card arrives front-side with the back unmounted ─────────
        let secondWord = try step("second-card-front", app: app) { () -> String in
            XCTAssertTrue(
                review.cardBack.waitUntilGone(timeout: 5),
                "進到下一張卡時背面必須回到未掛載"
            )
            let word = review.frontWord
            XCTAssertNotEqual(word, firstWord, "下一張卡必須是不同詞條")
            XCTAssertTrue(word.hasPrefix("probeword"), "第二張卡也必須是 fixture 詞條：\(word)")
            return word
        }

        // ── 7. Grade forgot: independent counter + further advance ──────────
        review.tapForgot()
        XCTAssertTrue(
            review.waitForProgress("3 / \(Self.deckSize)"),
            "第二次評分後 progress 必須前進到 3 / \(Self.deckSize)，實際：\(review.progressText)"
        )
        try step("graded-forgot", app: app) {
            XCTAssertTrue(
                review.waitUntilLabel(of: review.forgotButton, contains: "·1"),
                "忘記計數應顯示 ·1，實際 label：\(review.forgotButton.label)"
            )
        }

        // ── 8. Close: back to the notebook list with the card still there ───
        try step("closed-back-to-list", app: app) {
            review.close()
            XCTAssertTrue(
                notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 5),
                "關閉複習後必須回到單字本列表"
            )
        }

        attachText(
            """
            fixture=notebook.reviewDeck notebook=\(Self.notebookCardID) deck=\(Self.deckSize)
            firstWord=\(firstWord)
            secondWord=\(secondWord)
            gradedRemembered=1 gradedForgot=1
            """,
            named: "Notebook Review Flow Metrics"
        )
    }

    /// "probeword003" → 3 (deck translation format: "量測卡片 3 的譯文…")
    private static func cardNumber(fromWord word: String) -> Int {
        Int(word.drop(while: { !$0.isNumber })) ?? -1
    }
}
