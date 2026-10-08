import XCTest

/// #2040: a review card shows which notebook it belongs to only when the session
/// mixes notebooks. Both entry shapes go through the notebook-list review CTA;
/// the fixture decides whether the queue spans one notebook or two.
final class TodayReviewNotebookBadgeUITests: UITestCase {
    private static let alphaID = "ui-review-notebook"
    private static let betaID = "ui-review-notebook-beta"
    private static let names = [alphaID: "Review Alpha", betaID: "Review Beta"]
    /// `ReviewCardChrome.verticalInset` top part on the front face
    /// (`foldPadding` 28 + `foldHintBottomInset` 22): the badge must sit inside
    /// this reserved band, i.e. it is drawn over existing whitespace rather than
    /// pushing the word down.
    private static let frontTopBand: CGFloat = 50

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 180
    }

    @MainActor
    private func startReview(_ app: XCUIApplication) -> TodayReviewPage? {
        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.alphaID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("fixture 應種出單字本卡片 \(Self.alphaID)")
            return nil
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("fixture 有到期卡片，複習 CTA 必須出現")
            return nil
        }
        let review = notebook.startReview()
        guard review.progressLabel.waitUntilExists(timeout: 10),
              review.waitForFeedbackControls(timeout: 5) else {
            captureStep("review-not-started", app: app)
            XCTFail("tap CTA 後必須進入複習 session")
            return nil
        }
        return review
    }

    @MainActor
    private func assertBadgeNamesItsNotebook(
        _ review: TodayReviewPage,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> String? {
        let badge = review.notebookBadge
        guard badge.waitUntilExists(timeout: 5) else {
            XCTFail("多單字本 session 的卡片必須顯示 todayReview.card.notebook", file: file, line: line)
            return nil
        }
        XCTAssertEqual(review.notebookBadgeCount, 1, "只有互動中的那張卡可被查到標示", file: file, line: line)
        let notebookID = badge.value as? String ?? ""
        guard let name = Self.names[notebookID] else {
            XCTFail("標示的 value 必須是 session 內的 notebookId，實得 \(notebookID)", file: file, line: line)
            return nil
        }
        XCTAssertTrue(badge.label.contains(name), "標示必須顯示單字本名稱 \(name)，實得 \(badge.label)", file: file, line: line)
        XCTAssertFalse(badge.label.contains(notebookID), "標示不得顯示 id 字串", file: file, line: line)
        return notebookID
    }

    @MainActor
    func testMultiNotebookSessionLabelsEveryCardOnFrontAndBack() throws {
        let app = launchIsolatedApp(fixtures: [.notebookReviewDeckMultiNotebook], perfLog: "review")
        guard let review = startReview(app) else { return }

        guard let firstID = assertBadgeNamesItsNotebook(review) else {
            captureStep("badge-missing-front", app: app)
            return
        }
        let front = review.cardFront.frame
        let badge = review.notebookBadge.frame
        XCTAssertGreaterThanOrEqual(front.height, 100, "positive control：cardFront 必須是卡片本體")
        XCTAssertGreaterThanOrEqual(badge.minY, front.minY - 1, "標示不得超出卡片頂端")
        XCTAssertLessThanOrEqual(
            badge.maxY,
            front.minY + Self.frontTopBand + 1,
            "標示必須收在正面既有的頂部留白內，不得把單字往下推"
        )
        captureStep("badge-front", app: app)

        review.flipCard()
        guard review.cardBack.waitUntilExists(timeout: 5) else {
            captureStep("flip-no-back", app: app)
            XCTFail("翻卡後背面必須掛載")
            return
        }
        let backID = assertBadgeNamesItsNotebook(review)
        XCTAssertEqual(backID, firstID, "翻到背面時標示仍在、且仍是同一本")
        captureStep("badge-back", app: app)

        review.tapRemembered()
        let nextBadge = review.notebookBadge
        XCTAssertTrue(
            UITestWaits.wait(
                for: NSPredicate(format: "exists == true AND value != %@", firstID),
                on: nextBadge,
                timeout: 8
            ),
            "fixture 交錯兩本單字本：下一張卡的標示必須換成另一本"
        )
        _ = assertBadgeNamesItsNotebook(review)
        captureStep("badge-next-card", app: app)
    }

    @MainActor
    func testMultiNotebookAddLinkSheetStatesItsNotebookScope() throws {
        let app = launchIsolatedApp(fixtures: [.notebookReviewDeckMultiNotebook], perfLog: "review")
        guard let review = startReview(app) else { return }
        guard let notebookID = assertBadgeNamesItsNotebook(review), let name = Self.names[notebookID] else { return }

        review.flipCard()
        guard review.addLinkButton.waitUntilExists(timeout: 10) else {
            captureStep("add-link-missing", app: app)
            XCTFail("背面必須有新增連結入口")
            return
        }
        review.addLinkButton.tapWhenReady()
        guard app.textFields["addLink.searchField"].waitUntilExists(timeout: 10) else {
            captureStep("add-link-sheet-not-open", app: app)
            XCTFail("必須能開啟 AddLink sheet")
            return
        }
        let scope = app.descendants(matching: .any).matching(identifier: "addLink.notebookScope").firstMatch
        XCTAssertTrue(scope.waitUntilExists(timeout: 5), "多單字本入口的 sheet 必須明示搜尋範圍")
        XCTAssertTrue(scope.label.contains(name), "搜尋範圍必須是來源卡的單字本 \(name)，實得 \(scope.label)")
        captureStep("add-link-scope", app: app)
        app.buttons["addLink.cancel"].tapWhenReady()
    }

    @MainActor
    func testSingleNotebookSessionShowsNoBadge() throws {
        let app = launchIsolatedApp(fixtures: [.notebookReviewDeckVaried], perfLog: "review")
        guard let review = startReview(app) else { return }
        // Positive control first: the card must be on screen before absence means anything.
        XCTAssertTrue(review.cardFront.waitUntilExists(timeout: 5))
        XCTAssertEqual(review.notebookBadgeCount, 0, "單一單字本入口不得顯示單字本標示")

        review.flipCard()
        XCTAssertTrue(review.cardBack.waitUntilExists(timeout: 5), "翻卡後背面必須掛載")
        XCTAssertEqual(review.notebookBadgeCount, 0, "單一單字本入口的背面也不得顯示標示")

        guard review.addLinkButton.waitUntilExists(timeout: 10) else { return }
        review.addLinkButton.tapWhenReady()
        guard app.textFields["addLink.searchField"].waitUntilExists(timeout: 10) else { return }
        XCTAssertEqual(
            app.descendants(matching: .any).matching(identifier: "addLink.notebookScope").count,
            0,
            "單一單字本入口的 sheet 不需要範圍提示"
        )
        app.buttons["addLink.cancel"].tapWhenReady()
    }
}
