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

    var backButton: XCUIElement { app.buttons["reader.header.backButton"] }
    var translationPanel: XCUIElement { app.otherElements["reader.translationPanel"] }
    var settingsPanel: XCUIElement { app.otherElements["reader.settingsPanel"] }
    var settingsButton: XCUIElement { app.buttons["reader.header.settingsButton"] }
    var settingsDoneButton: XCUIElement { app.buttons["reader.settings.done"] }
    var settingsPreview: XCUIElement { app.otherElements["reader.settings.preview"] }
    var fontSizeStepper: XCUIElement { app.steppers["reader.settings.fontSizeStepper"] }
    var lineHeightSlider: XCUIElement { app.sliders["reader.settings.lineHeight"] }
    var readingModePicker: XCUIElement { app.buttons["reader.settings.readingMode"] }
    var fontPicker: XCUIElement { app.buttons["reader.settings.font"] }
    var themePicker: XCUIElement { app.otherElements["reader.settings.theme"] }
    func themeOption(_ theme: String) -> XCUIElement {
        app.buttons["reader.settings.theme.\(theme)"]
    }
    var highlightColorPicker: XCUIElement { app.otherElements["reader.settings.highlightColor"] }
    var highlightOpacityPicker: XCUIElement { app.buttons["reader.settings.highlightOpacity"] }
    var resetMenu: XCUIElement { app.buttons["reader.settings.resetMenu"] }
    var resetAllButton: XCUIElement { app.buttons["reader.settings.reset.all"] }
    var progressBadge: XCUIElement { app.staticTexts["reader.header.progressBadge"] }

    // MARK: - Query definitions

    /// Reader hides the system navigation bar. Every Reader action resolves its
    /// query through `exactlyOneElement` immediately before acting; this keeps
    /// compact/expanded transitions explicit and makes duplicate IDs fail fast.
    private var expandHeaderButtonQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.header.expandButton")
    }

    private var backButtonQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.header.backButton")
    }

    private var translationPanelQuery: XCUIElementQuery {
        app.otherElements.matching(identifier: "reader.translationPanel")
    }

    private var settingsPanelQuery: XCUIElementQuery {
        app.otherElements.matching(identifier: "reader.settingsPanel")
    }

    private var settingsButtonQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.header.settingsButton")
    }

    private var settingsDoneButtonQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.settings.done")
    }

    private var settingsPreviewQuery: XCUIElementQuery {
        app.otherElements.matching(identifier: "reader.settings.preview")
    }

    private var fontSizeStepperQuery: XCUIElementQuery {
        app.steppers.matching(identifier: "reader.settings.fontSizeStepper")
    }

    private var fontSizeIncrementQuery: XCUIElementQuery {
        fontSizeStepperQuery.buttons.matching(identifier: "Increment")
    }

    private var lineHeightSliderQuery: XCUIElementQuery {
        app.sliders.matching(identifier: "reader.settings.lineHeight")
    }

    private var themeOptionQuery: (String) -> XCUIElementQuery {
        { theme in app.buttons.matching(identifier: "reader.settings.theme.\(theme)") }
    }

    private var resetMenuQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.settings.resetMenu")
    }

    private var resetAllButtonQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.settings.reset.all")
    }

    private var progressBadgeQuery: XCUIElementQuery {
        app.staticTexts.matching(identifier: "reader.header.progressBadge")
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

    private var webViewQuery: XCUIElementQuery { app.webViews }

    private var settingsStateQuery: XCUIElementQuery {
        app.descendants(matching: .any)
            .matching(identifier: "reader.webView.settingsState")
    }

    private func exactlyOne(
        _ query: XCUIElementQuery,
        named name: String,
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        query.exactlyOneElement(timeout: timeout, named: name, file: file, line: line)
    }

    private func exactlyOneIfPresent(
        _ query: XCUIElementQuery,
        named name: String,
        timeout: TimeInterval = 0.5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        query.exactlyOneElementIfPresent(timeout: timeout, named: name, file: file, line: line)
    }

    // MARK: - Exact element accessors

    func settingsPanelElement(file: StaticString = #filePath, line: UInt = UInt(#line)) -> XCUIElement? {
        exactlyOne(settingsPanelQuery, named: "Reader settings panel", file: file, line: line)
    }

    func settingsPreviewElement(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        exactlyOne(settingsPreviewQuery, named: "Reader settings preview", timeout: timeout, file: file, line: line)
    }

    func settingsDoneButtonElement(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        exactlyOne(settingsDoneButtonQuery, named: "Reader settings done button", timeout: timeout, file: file, line: line)
    }

    func lineHeightSliderElement(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        exactlyOne(lineHeightSliderQuery, named: "Reader line-height slider", timeout: timeout, file: file, line: line)
    }

    func webViewElement(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        exactlyOne(webViewQuery, named: "production Reader WebView", timeout: timeout, file: file, line: line)
    }

    func settingsStateElement(
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement? {
        exactlyOne(settingsStateQuery, named: "production Reader settings state", timeout: timeout, file: file, line: line)
    }

    func settingsStateValue(timeout: TimeInterval = 5) -> String? {
        guard let state = exactlyOne(
            settingsStateQuery,
            named: "production Reader settings state",
            timeout: timeout
        ) else {
            return nil
        }
        return String(describing: state.value ?? "")
    }

    /// A rendered text block inside the Readium WebView. Single-word
    /// paragraphs expose an exact-label staticText whose center is a
    /// deterministic word-tap target.
    private func contentTextQuery(_ text: String) -> XCUIElementQuery {
        app.webViews.staticTexts
            .matching(identifier: text)
            .matching(NSPredicate(format: "hittable == true"))
    }

    func waitForContent(_ text: String, timeout: TimeInterval = 45) -> Bool {
        exactlyOne(contentTextQuery(text), named: "Reader content \(text)", timeout: timeout) != nil
    }

    // MARK: - Translation Panel

    private var translationWordQuery: XCUIElementQuery {
        app.staticTexts.matching(identifier: "reader.translationPanel.word")
    }

    private var translationTextQuery: XCUIElementQuery {
        app.staticTexts.matching(identifier: "reader.translationPanel.translation")
    }

    private var translationDismissButtonQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.translationPanel.dismissButton")
    }

    func waitForTranslationPanel(timeout: TimeInterval = 5) -> Bool {
        exactlyOne(translationPanelQuery, named: "Reader translation panel", timeout: timeout) != nil
    }

    func translationWordContains(_ text: String, timeout: TimeInterval = 5) -> Bool {
        guard let word = exactlyOne(translationWordQuery, named: "translation word", timeout: timeout) else {
            return false
        }
        return word.waitUntilLabelContains(text, timeout: timeout)
    }

    func translationTextContains(_ text: String, timeout: TimeInterval = 5) -> Bool {
        guard let translation = exactlyOne(translationTextQuery, named: "translation text", timeout: timeout) else {
            return false
        }
        return translation.waitUntilLabelContains(text, timeout: timeout)
    }

    var translationWord: XCUIElement { app.staticTexts["reader.translationPanel.word"] }
    var translationText: XCUIElement { app.staticTexts["reader.translationPanel.translation"] }
    var translationDismissButton: XCUIElement { app.buttons["reader.translationPanel.dismissButton"] }

    @discardableResult
    func dismissTranslation(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard let dismiss = exactlyOne(
            translationDismissButtonQuery,
            named: "translation dismiss button",
            file: file,
            line: line
        ) else { return false }
        dismiss.tapWhenReady(file: file, line: line)
        return translationPanelQuery.waitUntilEmpty(timeout: 5)
    }

    // MARK: - Progress

    /// Parse the compact-header progress badge ("12.3%") into a Double.
    /// Returns nil while the badge is absent (totalProgression == 0 or
    /// chrome hidden behind an overlay).
    func progressPercent() -> Double? {
        guard let progressBadge = exactlyOneIfPresent(
            progressBadgeQuery,
            named: "Reader progress badge"
        ) else { return nil }
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
        if let backButton = exactlyOneIfPresent(
            backButtonQuery,
            named: "Reader back button",
            file: file,
            line: line
        ) {
            backButton.tapWhenReady(file: file, line: line)
            return BookshelfPage(app: app)
        }

        guard let expandButton = exactlyOne(
            expandHeaderButtonQuery,
            named: "Reader expand button",
            timeout: 5,
            file: file,
            line: line
        ) else { return BookshelfPage(app: app) }
        expandButton.tapWhenReady(file: file, line: line)
        guard let backButton = exactlyOne(
            backButtonQuery,
            named: "Reader back button after expand",
            timeout: 5,
            file: file,
            line: line
        ) else { return BookshelfPage(app: app) }
        backButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    @discardableResult
    func openSettings(file: StaticString = #filePath, line: UInt = UInt(#line)) -> ReaderPage {
        var settingsButton = exactlyOneIfPresent(
            settingsButtonQuery,
            named: "Reader settings button",
            file: file,
            line: line
        )
        if settingsButton == nil {
            guard let expandButton = exactlyOne(
                expandHeaderButtonQuery,
                named: "Reader expand button",
                timeout: 5,
                file: file,
                line: line
            ) else { return self }
            expandButton.tapWhenReady(file: file, line: line)
            settingsButton = exactlyOne(
                settingsButtonQuery,
                named: "Reader settings button after expand",
                timeout: 5,
                file: file,
                line: line
            )
        }

        guard let settingsButton else { return self }
        settingsButton.tapWhenReady(file: file, line: line)
        _ = exactlyOne(settingsPanelQuery, named: "Reader settings panel", timeout: 5, file: file, line: line)
        return self
    }

    @discardableResult
    func selectTheme(_ theme: String, timeout: TimeInterval = 8) -> Bool {
        let optionQuery = themeOptionQuery(theme)
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let option = exactlyOneIfPresent(
                optionQuery,
                named: "Reader theme option \(theme)",
                timeout: 0.25
            ), option.isHittable {
                option.tap()
                return true
            }
            app.swipeUp()
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return false
    }

    @discardableResult
    func showPreview(timeout: TimeInterval = 8) -> Bool {
        // `isHittable` is true even when a Form row is only partially exposed.
        // Move the scroll view to its canonical top position before sampling
        // geometry; otherwise the first frame can be a clipped intersection.
        app.swipeDown()
        RunLoop.current.run(until: Date().addingTimeInterval(0.3))

        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let preview = exactlyOneIfPresent(
                settingsPreviewQuery,
                named: "Reader settings preview",
                timeout: 0.25
            ), preview.isHittable {
                return true
            }
            app.swipeDown()
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return exactlyOneIfPresent(
            settingsPreviewQuery,
            named: "Reader settings preview",
            timeout: 0.25
        ) != nil
    }

    @discardableResult
    func resetReaderSettings(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard let resetMenu = exactlyOne(
            resetMenuQuery,
            named: "Reader settings reset menu",
            file: file,
            line: line
        ) else { return false }
        resetMenu.tapWhenReady(file: file, line: line)
        guard let resetAllButton = exactlyOne(
            resetAllButtonQuery,
            named: "Reader settings reset action",
            timeout: 5,
            file: file,
            line: line
        ) else { return false }
        resetAllButton.tapWhenReady(file: file, line: line)
        return true
    }

    @discardableResult
    func incrementFontSize(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard exactlyOne(
            fontSizeStepperQuery,
            named: "Reader font-size stepper",
            file: file,
            line: line
        ) != nil else { return false }
        guard let increment = exactlyOne(
            fontSizeIncrementQuery,
            named: "Reader font-size increment button",
            file: file,
            line: line
        ) else { return false }
        increment.tapWhenReady(file: file, line: line)
        return true
    }

    @discardableResult
    func adjustLineHeight(
        toNormalizedSliderPosition position: CGFloat,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> Bool {
        guard let slider = exactlyOne(
            lineHeightSliderQuery,
            named: "Reader line-height slider",
            file: file,
            line: line
        ) else { return false }
        slider.adjust(toNormalizedSliderPosition: position)
        return true
    }

    func lineHeightValue(timeout: TimeInterval = 5) -> Double? {
        guard let slider = exactlyOne(lineHeightSliderQuery, named: "Reader line-height slider", timeout: timeout) else {
            return nil
        }
        guard let raw = slider.value else { return nil }
        return Double(String(describing: raw))
    }

    @discardableResult
    func waitForLineHeightValue(_ value: String, timeout: TimeInterval = 5) -> Bool {
        guard let slider = exactlyOne(lineHeightSliderQuery, named: "Reader line-height slider", timeout: timeout) else {
            return false
        }
        return slider.waitUntilValueEquals(value, timeout: timeout)
    }

    @discardableResult
    func closeSettings(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard let done = exactlyOne(
            settingsDoneButtonQuery,
            named: "Reader settings done button",
            file: file,
            line: line
        ) else { return false }
        done.tapWhenReady(file: file, line: line)
        return settingsPanelQuery.waitUntilEmpty(timeout: 5)
    }

    @discardableResult
    func tapContentText(_ text: String, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard let content = exactlyOne(
            contentTextQuery(text),
            named: "Reader content \(text)",
            timeout: 5,
            file: file,
            line: line
        ) else { return false }
        content.tapWhenReady(file: file, line: line)
        return true
    }

    @discardableResult
    func swipeWebViewLeft(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard let webView = exactlyOne(webViewQuery, named: "production Reader WebView", file: file, line: line) else {
            return false
        }
        webView.swipeLeft()
        return true
    }

    func waitForSettingsStateContaining(_ fragments: [String], timeout: TimeInterval = 10) -> Bool {
        guard let state = exactlyOne(settingsStateQuery, named: "production Reader settings state", timeout: timeout) else {
            return false
        }
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let value = String(describing: state.value ?? "")
            if fragments.allSatisfy(value.contains) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    func themeIsSelected(_ theme: String, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard let option = exactlyOne(
            themeOptionQuery(theme),
            named: "Reader theme option \(theme)",
            file: file,
            line: line
        ) else { return false }
        return option.isSelected
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
        guard exactlyOneIfPresent(
            chromeButtons,
            named: "Reader chrome button",
            timeout: 5,
            file: file,
            line: line
        ) != nil else {
            XCTFail("reader chrome not found. Accessibility tree:\n\(app.debugDescription)",
                    file: file, line: line)
            return
        }
        XCTAssertEqual(chromeButtons.count, 1,
                       "reader chrome must expose exactly one active button",
                       file: file, line: line)
    }
}
