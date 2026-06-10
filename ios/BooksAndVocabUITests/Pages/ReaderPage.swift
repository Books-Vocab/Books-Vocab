import XCTest

/// Page Object for the Reader (book reading) scene.
struct ReaderPage {
    let app: XCUIApplication

    // MARK: - Chrome

    var backButton: XCUIElement {
        app.navigationBars.buttons.firstMatch
    }

    var translationPanel: XCUIElement {
        app.otherElements["reader.translationPanel"]
    }

    var settingsPanel: XCUIElement {
        app.otherElements["reader.settingsPanel"]
    }

    /// Compact header progress badge text (e.g. "12.3%"); only present once
    /// `totalProgression > 0` and no overlay is shown.
    var progressBadge: XCUIElement {
        app.staticTexts["reader.header.progressBadge"]
    }

    // MARK: - Content (Readium WebView)

    var webView: XCUIElement {
        app.webViews.firstMatch
    }

    /// A rendered text block inside the Readium WebView. Single-word
    /// paragraphs (e.g. a chapter heading line) expose an exact-label
    /// staticText whose center is a deterministic word-tap target.
    func contentText(_ text: String) -> XCUIElement {
        app.webViews.staticTexts[text].firstMatch
    }

    // MARK: - Translation Panel

    var translationWord: XCUIElement {
        app.staticTexts["reader.translationPanel.word"]
    }

    var translationText: XCUIElement {
        app.staticTexts["reader.translationPanel.translation"]
    }

    var translationDismissButton: XCUIElement {
        app.buttons["reader.translationPanel.dismissButton"]
    }

    // MARK: - Progress

    /// Parse the compact-header progress badge ("12.3%") into a Double.
    /// Returns nil while the badge is absent (totalProgression == 0 or
    /// chrome hidden behind an overlay).
    func progressPercent() -> Double? {
        guard progressBadge.exists else { return nil }
        let label = progressBadge.label
        return Double(label.replacingOccurrences(of: "%", with: ""))
    }

    /// Poll the progress badge until it reports a value strictly greater
    /// than `threshold` (real page-turn evidence, not just a gesture).
    @discardableResult
    func waitUntilProgressExceeds(_ threshold: Double, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let value = progressPercent(), value > threshold {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.25))
        }
        return false
    }

    // MARK: - Actions

    @discardableResult
    func goBack(file: StaticString = #filePath, line: UInt = UInt(#line)) -> BookshelfPage {
        backButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        backButton.assertExists(timeout: 5, file: file, line: line)
    }
}
