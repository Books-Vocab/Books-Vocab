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
        element("todayReview.close")
    }

    /// Top-bar entry to the shared review-card layout editor (between autoplay
    /// and close).
    var layoutEditorButton: XCUIElement {
        element("todayReview.layoutEditor.open")
    }

    /// Autoplay play/pause control, identified by STATE rather than its localized
    /// label — `…autoplay.paused` exists only while autoplay is paused.
    var autoplayPausedButton: XCUIElement {
        element("todayReview.autoplay.paused")
    }

    var autoplayPlayingButton: XCUIElement {
        element("todayReview.autoplay.playing")
    }

    /// Top-bar autoplay toggle.
    var autoplayToggleButton: XCUIElement {
        element("todayReview.autoplayToggle")
    }

    // NOTE (measured 2026-08-06) said the front face published
    // `todayReview.card.front` on 2–3 nested ~36pt buttons, so the card box height
    // was unreadable from a UI test. That was FIXED on 2026-08-08 by `2ac7ba258`
    // (`.accessibilityElement(children: .contain)` declared before the property
    // modifiers), so `cardFront.frame` is the card box again. Geometry assertions
    // on this card are legitimate — but keep a `height >= 100` positive control:
    // if the container declaration ever regresses, the query resolves a nested
    // button and every geometry assertion silently measures the wrong element.

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

    /// The "tap to expand" zone below the card (front stage only). Its
    /// `frame.minY` is the top boundary of the region directly below the card
    /// region; `expandZone.minY − cardFront.maxY` is the visible gap between the
    /// card and the bottom expand hint.
    var expandZone: XCUIElement {
        element("todayReview.expandZone")
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

    // MARK: - Waits

    /// Poll-based label wait that re-resolves the element query each iteration.
    ///
    /// `waitUntilLabelContains` (XCTNSPredicateExpectation) can keep reading a
    /// STALE accessibility snapshot while the grading fling / card-advance
    /// animations run — observed timing out on "3 / 8" while the live label
    /// already showed it. Explicit RunLoop polling is the same pattern
    /// `PodcastPlaybackPerfUITests` uses for its elapsed-time clock.
    func waitUntilLabel(
        of element: XCUIElement,
        contains substring: String,
        timeout: TimeInterval = 8
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if element.exists, element.label.contains(substring) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        return element.exists && element.label.contains(substring)
    }

    /// Wait until the top-bar progress capsule reads `"k / N"`-style `text`.
    func waitForProgress(_ text: String, timeout: TimeInterval = 8) -> Bool {
        waitUntilLabel(of: progressLabel, contains: text, timeout: timeout)
    }

    // MARK: - Helpers

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}
