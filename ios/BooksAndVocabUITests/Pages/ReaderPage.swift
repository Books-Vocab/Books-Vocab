import XCTest

/// Page Object for the Reader (book reading) scene.
struct ReaderPage {
    let app: XCUIApplication

    // MARK: - Chrome

    /// Reader hides the system navigation bar (ReaderView.swift), so the old
    /// `app.navigationBars.buttons.firstMatch` could never resolve — the bar is
    /// not in the hierarchy at all. Anchored to the chrome's own identifiers.
    ///
    /// The reader opens in the COMPACT chrome state (`ReaderChromeState.header`
    /// defaults to `.compact`), which shows only the progress badge and the
    /// expand button — there is no back button until the header is expanded.
    /// So "is the reader active" must be asked of the chrome root, not the back
    /// button, and `goBack()` has to expand first.
    var expandHeaderButton: XCUIElement {
        app.buttons["reader.header.expandButton"]
    }

    var backButton: XCUIElement {
        app.buttons["reader.header.backButton"]
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
        // compact 狀態沒有返回鍵，得先展開。已展開時 expand 按鈕不存在，直接按返回。
        if !backButton.exists, expandHeaderButton.waitForExistence(timeout: 5) {
            expandHeaderButton.tapWhenReady(file: file, line: line)
        }
        backButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // 兩個 chrome 狀態各有一顆必然存在的按鈕：compact = expand、expanded = back。
        // 不要在 chrome root 掛 identifier——實測 SwiftUI 會把它往下推、蓋掉子按鈕
        // 自己的 id（a11y 樹裡 expand 按鈕變成 identifier: 'reader.header'）。
        let anyChromeButton = app.buttons.matching(
            NSPredicate(format: "identifier IN %@",
                        ["reader.header.expandButton", "reader.header.backButton"])
        ).firstMatch
        if !anyChromeButton.waitForExistence(timeout: 5) {
            XCTFail("reader chrome not found. Accessibility tree:\n\(app.debugDescription)",
                    file: file, line: line)
        }
    }
}
