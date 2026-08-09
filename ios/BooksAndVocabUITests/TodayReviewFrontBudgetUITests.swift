import XCTest

/// APP-20260808-255c5e — 正面必須貼合內容，而不是瓜分卡片區。
///
/// a5885e228 把正面的 `.frame(minHeight: frontMinHeight)`（貼合、只保下限）換成
/// `.frame(maxHeight:)`。SwiftUI 的彈性 frame 給了 max 之後是**貪婪**的：它回報
/// `min(max, 父提案)` 而不是內容高度。正面與 reveal zone 是同一個 `VStack(spacing: 0)`
/// 的兩個子節點，zone 的彈性上界是 ∞，於是 VStack 先服務彈性較小者、提案 H/2，
/// 正面連 padding 照單全收 —— 卡框 = H/2 − 32、zone = H/2，一個只有一行單字的
/// 正面照樣佔掉半個卡片區，底下留一大片沒人用的空白。
///
/// 判準是 `region/2 − 卡框高度` 而**不是** `高度 ≤ region × 比例`：後者的紅是裝置
/// 相依的（壞掉的 ratio = (H/2 − 32)/(H − 16) 隨 H 單調遞減，小螢幕上壞掉的版面
/// 本來就會低於任何固定比例，判準會對著沒修的碼變綠）。`slack` 壞掉時**恆為 24pt**
/// （32 − 16/2），與裝置尺寸無關。
final class TodayReviewFrontBudgetUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    @MainActor
    func testFrontCardHugsItsContentNotHalfTheRegion() throws {
        // 出貨預設牌組（core + 詞性），不是 gap 調查用的高度參差 varied deck。
        let app = launchIsolatedApp(fixtures: [.notebookReviewDeck], perfLog: "review")
        captureStep("launch", app: app)

        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("notebook.reviewDeck fixture 應種出單字本卡片 \(Self.notebookCardID)")
            return
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("預設牌組有未學卡片，複習 CTA 必須出現")
            return
        }
        let review = notebook.startReview()
        guard review.progressLabel.waitUntilExists(timeout: 10) else {
            captureStep("review-not-started", app: app)
            XCTFail("tap CTA 後必須進入複習 session；progress label 缺席")
            return
        }

        _ = review.cardFront.waitUntilExists(timeout: 8)
        // 讓 reveal / promote 的 spring 停下來再讀 frame。
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))

        guard review.cardFront.exists, review.expandZone.exists else {
            captureStep("missing-elements", app: app)
            // 刻意 XCTFail 後 return，不用 break：元素消失若只是跳出迴圈，
            // 「什麼都沒量到」會變成靜默的綠。
            XCTFail("卡片正面與 expand zone 都必須存在才量得到版面")
            return
        }

        let card = review.cardFront.frame
        let zone = review.expandZone.frame
        // 卡頂到 zone 底 = 整個卡片區。
        let region = zone.maxY - card.minY
        let slack = region / 2 - card.height

        captureStep("front-card-h\(Int(card.height))-slack\(Int(slack))", app: app)
        add(XCTAttachment(string: "card=\(card.height) region=\(region) slack=\(slack)")
            .named("front budget"))

        // 正控：任一條紅代表量錯東西，不是缺陷本體，**不准為了讓它綠而調門檻**。
        XCTAssertGreaterThanOrEqual(
            card.height, 100,
            "量到的應該是卡框；~36pt 代表 query 解析到巢狀按鈕（a11y 容器宣告回歸）"
        )
        XCTAssertLessThan(card.minY, zone.minY, "卡片必須在 expand zone 之上")
        XCTAssertGreaterThan(region, 300, "卡片區讀不出來（退化值）")

        // 缺陷本體：壞掉時 slack 恆為 24pt；修好後正面 ≈ 165–240pt，slack 破百。
        XCTAssertGreaterThan(
            slack, 60,
            "正面仍佔掉半個卡片區（slack=\(slack)pt，壞掉時恆為 24pt）"
        )
    }
}
