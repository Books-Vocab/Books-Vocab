import Foundation
import XCTest

/// Page Object for the Reader (book reading) scene.
struct ReaderPage {
    let app: XCUIApplication

    // MARK: - Chrome

    /// Reader hides the system navigation bar (ReaderView.swift), so the old
    /// A navigation-bar button query could never resolve — the bar is
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

    var tableOfContentsButton: XCUIElement {
        app.buttons["reader.header.tocButton"]
    }

    var tableOfContentsSheet: XCUIElement {
        app.otherElements["reader.toc.sheet"]
    }

    var tocHierarchy: XCUIElement {
        app.otherElements["reader.toc.chapterHierarchy"]
    }

    func tocChapter(_ path: String) -> XCUIElement {
        tableOfContentsSheet.buttons["reader.toc.chapter.\(path)"]
    }

    func tocChapter(
        path: String,
        label: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement {
        let row = tocChapter(path)
        XCTAssertEqual(row.count, 1, file: file, line: line)
        XCTAssertEqual(row.label, label, file: file, line: line)
        return row
    }

    var evidenceAsset: XCUIElement {
        app.staticTexts["reader.evidence.asset"]
    }

    func assertFixtureAsset(
        assetID: String,
        fileName: String,
        sha256: String,
        byteSize: Int,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertEqual(evidenceAsset.count, 1, file: file, line: line)
        guard let descriptor = evidenceAsset.value as? String, !descriptor.isEmpty else {
            XCTFail("reader.evidence.asset must expose a non-empty proof descriptor", file: file, line: line)
            return
        }
        let parts = descriptor
            .split(separator: "|", omittingEmptySubsequences: false)
        XCTAssertEqual(parts.count, 6, file: file, line: line)
        guard parts.count == 6 else { return }
        guard let expectedByteSize = Int(parts[3]), let actualByteSize = Int(parts[5]) else {
            XCTFail("reader.evidence.asset proof byte sizes must be integers", file: file, line: line)
            return
        }
        XCTAssertEqual(String(parts[0]), assetID, file: file, line: line)
        let installedURL = URL(fileURLWithPath: String(parts[1]))
        XCTAssertEqual(installedURL.lastPathComponent, fileName, file: file, line: line)
        XCTAssertTrue(installedURL.path.hasPrefix("/"), file: file, line: line)
        XCTAssertEqual(installedURL.deletingLastPathComponent().lastPathComponent, "Books", file: file, line: line)
        XCTAssertEqual(
            installedURL.path,
            installedURL.deletingLastPathComponent().appendingPathComponent(fileName).path,
            file: file,
            line: line
        )
        XCTAssertEqual(String(parts[2]), sha256, file: file, line: line)
        XCTAssertEqual(expectedByteSize, byteSize, file: file, line: line)
        XCTAssertEqual(String(parts[4]), sha256, file: file, line: line)
        XCTAssertEqual(actualByteSize, byteSize, file: file, line: line)
    }

    var tocLoading: XCUIElement {
        app.otherElements["reader.toc.loading"]
    }

    var tocNavigationLoading: XCUIElement {
        app.activityIndicators["reader.toc.navigation.loading"]
    }

    var tocSelected: XCUIElement {
        tableOfContentsSheet.staticTexts["reader.toc.selected"]
    }

    var tocSuccess: XCUIElement {
        tableOfContentsSheet.staticTexts["reader.toc.sheet.result.success"]
    }

    var tocReaderOverlaySuccess: XCUIElement {
        app.otherElements["reader.toc.readerOverlay"].staticTexts[
            "reader.toc.readerOverlay.result.success"
        ]
    }

    var tocDestination: XCUIElement {
        app.otherElements["reader.toc.readerOverlay"].staticTexts[
            "reader.toc.readerOverlay.destination"
        ]
    }

    var tocError: XCUIElement {
        tableOfContentsSheet.staticTexts["reader.toc.error"]
    }

    var tocMissingDestination: XCUIElement {
        tableOfContentsSheet.staticTexts["reader.toc.missingDestination"]
    }

    var tocRetry: XCUIElement {
        tableOfContentsSheet.buttons["reader.toc.retry"]
    }

    var tocDone: XCUIElement {
        tableOfContentsSheet.buttons["reader.toc.done"]
    }

    var currentLocator: XCUIElement {
        app.staticTexts["reader.currentLocator"]
    }

    // MARK: - Content (Readium WebView)

    var webView: XCUIElement {
        let matches = app.webViews
        guard matches.count == 1,
              let element = matches.allElementsBoundByIndex.first else {
            XCTFail("Reader must expose exactly one Readium web view; found \(matches.count)")
            return matches.element(matching: .any, identifier: "__missing_reader_webview__")
        }
        return element
    }

    /// A rendered text block inside the Readium WebView. Single-word
    /// paragraphs (e.g. a chapter heading line) expose an exact-label
    /// staticText whose center is a deterministic word-tap target.
    func contentText(_ text: String) -> XCUIElement {
        let matches = webView.staticTexts[text]
        guard matches.count == 1,
              let element = matches.allElementsBoundByIndex.first else {
            XCTFail("Reader content selector must resolve exactly once: \(text); found \(matches.count)")
            return matches.element(matching: .any, identifier: "__missing_reader_content__")
        }
        return element
    }

    func assertContentAbsent(
        _ text: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertEqual(
            webView.staticTexts[text].count,
            0,
            "Reader content must remain absent: \(text)",
            file: file,
            line: line
        )
    }

    func assertTOCScopedCounts(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertEqual(tableOfContentsSheet.count, 1, file: file, line: line)
        XCTAssertEqual(
            tableOfContentsSheet.staticTexts["reader.toc.sheet.result.success"].count,
            1,
            file: file,
            line: line
        )
        XCTAssertEqual(
            app.otherElements["reader.toc.readerOverlay"].staticTexts[
                "reader.toc.readerOverlay.destination"
            ].count,
            1,
            file: file,
            line: line
        )
    }

    func assertSingleWebView(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertEqual(app.webViews.count, 1, file: file, line: line)
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
        let chromeButtons = app.buttons.matching(
            NSPredicate(format: "identifier IN %@",
                        ["reader.header.expandButton", "reader.header.backButton"])
        )
        guard chromeButtons.waitForExistence(timeout: 5) else {
            XCTFail("reader chrome not found. Accessibility tree:\n\(app.debugDescription)",
                    file: file, line: line)
            return
        }
        XCTAssertEqual(chromeButtons.count, 1,
                       "reader chrome must expose exactly one active button",
                       file: file, line: line)
    }
}
