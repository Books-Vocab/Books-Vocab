import XCTest

/// Page Object for the Today Review (flashcard) full-screen cover.
///
/// The cover hides the navigation bar (`platformHideNavigationBar`), so all
/// selectors target accessibility identifiers on the review chrome itself —
/// the previous navigation-bar-based selectors never matched this scene.
struct TodayReviewPage {
    let app: XCUIApplication

    // MARK: - Chrome

    /// "k / N" progress capsule in the top bar — the queue-position truth.
    var progressLabel: XCUIElement {
        element("todayReview.progressLabel")
    }

    /// Top-bar xmark chrome button (L10n `vocab.chromeIcon.todayReview.close`).
    var closeButton: XCUIElement {
        app.buttons["關閉今日複習"]
    }

    // MARK: - Card

    /// Front fold surface (the tappable word side). Exists for the whole
    /// session; flipping is asserted via `cardBack` appearing, not via this.
    var cardFront: XCUIElement {
        element("todayReview.card.front")
    }

    /// Mounted back content. Only exists while the answer is revealed — the
    /// folded state holds a zero-cost stub without this identifier, so
    /// `cardBack.exists` is a REAL flip-state signal.
    var cardBack: XCUIElement {
        element("todayReview.card.back")
    }

    // MARK: - Toolbar

    var rememberedButton: XCUIElement {
        element("todayReview.feedback.remembered")
    }

    var forgotButton: XCUIElement {
        element("todayReview.feedback.forgot")
    }

    // MARK: - Readers

    var progressText: String { progressLabel.label }

    /// Front card label is "複習卡片正面：<word>" (en: "Review card front: <word>");
    /// extract the word after the last colon of either kind.
    var frontWord: String {
        let label = cardFront.label
        for separator in ["：", ": "] {
            if let range = label.range(of: separator, options: .backwards) {
                return String(label[range.upperBound...])
                    .trimmingCharacters(in: .whitespaces)
            }
        }
        return label
    }

    // MARK: - Actions

    @discardableResult
    func flipCard(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        cardFront.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func tapRemembered(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        rememberedButton.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func tapForgot(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        forgotButton.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func close(file: StaticString = #filePath, line: UInt = UInt(#line)) -> NotebookPage {
        closeButton.tapWhenReady(file: file, line: line)
        return NotebookPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        progressLabel.assertExists(file: file, line: line)
    }

    // MARK: - Helpers

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
