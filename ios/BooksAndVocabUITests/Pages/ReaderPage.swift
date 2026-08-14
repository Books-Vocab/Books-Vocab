import Foundation
import XCTest

/// Page Object for the Reader (book reading) scene.
struct ReaderPage {
    let app: XCUIApplication

    static let seededContentMarker =
        "This UI World reader book is installed from a complete EPUB asset manifest entry."

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
    var lineHeightIncrementButton: XCUIElement {
        app.buttons["reader.settings.lineHeight.increment"]
    }
    var lineHeightSlider: XCUIElement { app.sliders["reader.settings.lineHeight"] }
    var readingModePicker: XCUIElement { app.buttons["reader.settings.readingMode"] }
    var fontPicker: XCUIElement { app.buttons["reader.settings.font"] }
    var themePicker: XCUIElement { app.otherElements["reader.settings.theme"] }
    func themeOption(_ theme: String) -> XCUIElement {
        app.buttons["reader.settings.theme.\(theme)"]
    }
    var highlightColorPicker: XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: "reader.settings.highlightColor")
            .element(boundBy: 0)
    }
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
        // SwiftUI Form materializes the accessibility container as a
        // CollectionView, even though the view intentionally exposes a stable
        // identifier independent of that UIKit-backed element type.
        app.collectionViews.matching(identifier: "reader.settingsPanel")
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

    private var lineHeightIncrementQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.settings.lineHeight.increment")
    }

    private var lineHeightDecrementQuery: XCUIElementQuery {
        app.buttons.matching(identifier: "reader.settings.lineHeight.decrement")
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
        // NavigationStack/List may materialize this SwiftUI accessibility
        // container as CollectionView on the simulator. This concrete query
        // keeps the appearance wait contract valid while avoiding the previous
        // wrong `Other` type.
        app.collectionViews["reader.toc.sheet"]
    }

    var isTableOfContentsSheetPresent: Bool {
        app.debugDescription.contains("identifier: 'reader.toc.sheet'")
    }

    @discardableResult
    func waitUntilTableOfContentsSheetExists(timeout: TimeInterval = 5) -> Bool {
        UITestWaits.waitUntilAccessibilityIdentifierPresent(
            "reader.toc.sheet",
            in: app,
            timeout: timeout
        )
    }

    @discardableResult
    func waitUntilTableOfContentsSheetGone(timeout: TimeInterval = 5) -> Bool {
        UITestWaits.waitUntilAccessibilityIdentifierGone(
            "reader.toc.sheet",
            in: app,
            timeout: timeout
        )
    }

    var tocHierarchy: XCUIElement {
        app.otherElements["reader.toc.chapterHierarchy"]
    }

    func tocChapter(_ path: String) -> XCUIElement {
        app.buttons["reader.toc.chapter.\(path)"]
    }

    func tocChapter(
        path: String,
        label: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement {
        let row = tocChapter(path)
        XCTAssertEqual(
            app.buttons.matching(identifier: "reader.toc.chapter.\(path)").count,
            1,
            file: file,
            line: line
        )
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
        XCTAssertEqual(
            app.staticTexts.matching(identifier: "reader.evidence.asset").count,
            1,
            file: file,
            line: line
        )
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
        // SwiftUI's ProgressView may materialize as an Other rather than an
        // ActivityIndicator on the simulator. The identifier is the contract;
        // do not couple the Page Object to UIKit's bridged element type.
        app.descendants(matching: .any)["reader.toc.navigation.loading"]
    }

    var tocNavigationStateReceipt: XCUIElement {
        app.descendants(matching: .any)["reader.toc.navigation.state"]
    }

    var tocSelected: XCUIElement {
        app.staticTexts["reader.toc.selected"]
    }

    var tocSuccess: XCUIElement {
        app.staticTexts["reader.toc.sheet.result.success"]
    }

    var tocReaderOverlaySuccess: XCUIElement {
        app.staticTexts["reader.toc.readerOverlay.result.success"]
    }

    var tocDestination: XCUIElement {
        app.staticTexts["reader.toc.readerOverlay.destination"]
    }

    var tocError: XCUIElement {
        app.staticTexts["reader.toc.error"]
    }

    var tocMissingDestination: XCUIElement {
        app.staticTexts["reader.toc.missingDestination"]
    }

    var tocMissingDestinationCount: Int {
        app.staticTexts.matching(identifier: "reader.toc.missingDestination").count
    }

    var tocRetry: XCUIElement {
        app.buttons["reader.toc.retry"]
    }

    var tocRetryCount: Int {
        app.buttons.matching(identifier: "reader.toc.retry").count
    }

    var tocDone: XCUIElement {
        app.buttons["reader.toc.done"]
    }

    var currentLocator: XCUIElement {
        app.staticTexts["reader.currentLocator"]
    }

    var runtimeState: XCUIElement {
        app.otherElements["reader.runtime.state"]
    }

    var runtimeStateCount: Int {
        app.otherElements.matching(identifier: "reader.runtime.state").count
    }

    func progressState(_ state: UITestReaderProgressScenario) -> XCUIElement {
        app.otherElements["reader.progress.\(state.progressAccessibilitySuffix)"]
    }

    func progressStateCount(_ state: UITestReaderProgressScenario) -> Int {
        app.otherElements.matching(identifier: "reader.progress.\(state.progressAccessibilitySuffix)").count
    }

    func loadingState(_ state: UITestReaderRuntimeScenario) -> XCUIElement {
        let phase = state == .loadingSlow ? "slow" : "opening"
        return app.otherElements["reader.loading.\(phase)"]
    }

    func loadingStateCount(_ state: UITestReaderRuntimeScenario) -> Int {
        let phase = state == .loadingSlow ? "slow" : "opening"
        return app.otherElements.matching(identifier: "reader.loading.\(phase)").count
    }

    func errorState(_ state: UITestReaderRuntimeScenario) -> XCUIElement {
        let failure = state == .loadingMissing ? "missing" : "retryable"
        return app.otherElements["reader.error.\(failure)"]
    }

    func errorStateCount(_ state: UITestReaderRuntimeScenario) -> Int {
        let failure = state == .loadingMissing ? "missing" : "retryable"
        return app.otherElements.matching(identifier: "reader.error.\(failure)").count
    }

    var emptyState: XCUIElement {
        app.otherElements["reader.empty"]
    }

    var emptyStateCount: Int {
        app.otherElements.matching(identifier: "reader.empty").count
    }

    var retryButton: XCUIElement {
        app.buttons["reader.retry"]
    }

    var retryButtonCount: Int {
        app.buttons.matching(identifier: "reader.retry").count
    }

    var loadingOverlayCount: Int {
        app.otherElements.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "reader.loading.")
        ).count
    }

    var slowLoadingResolveButton: XCUIElement {
        app.buttons["reader.loading.resolve"]
    }

    // MARK: - Content (Readium WebView)

    var webView: XCUIElement {
        // A query property must stay side-effect free: callers need to be able
        // to wait for the web view before asserting cardinality. Failing here
        // makes `webView.waitUntilExists` impossible during Readium startup.
        app.webViews.element(boundBy: 0)
    }

    /// A rendered text block inside the Readium WebView. Single-word
    /// paragraphs (e.g. a chapter heading line) expose an exact-label
    /// staticText whose center is a deterministic word-tap target.
    func contentText(_ text: String) -> XCUIElement {
        // Keep this query side-effect free: Readium may replace the WebView's
        // accessibility subtree after a locator change. Callers can wait for
        // the text to materialize before asserting its cardinality.
        app.webViews.staticTexts[text]
    }

    func assertContentAbsent(
        _ text: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertEqual(
            webView.staticTexts.matching(identifier: text).count,
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
        XCTAssertEqual(
            app.descendants(matching: .any).matching(identifier: "reader.toc.sheet").count,
            1,
            file: file,
            line: line
        )
        XCTAssertEqual(
            app.staticTexts.matching(identifier: "reader.toc.sheet.result.success").count,
            1,
            file: file,
            line: line
        )
        XCTAssertEqual(
            app.staticTexts.matching(identifier: "reader.toc.readerOverlay.destination")
                .count,
            1,
            file: file,
            line: line
        )
    }

    func assertReaderWebViewSurface(
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let projections = app.webViews.allElementsBoundByIndex.filter { !$0.frame.isEmpty }
        XCTAssertFalse(
            projections.isEmpty,
            "Reader must expose at least one Readium web view projection",
            file: file,
            line: line
        )
        XCTAssertTrue(
            projections.contains { $0.exists && $0.isHittable },
            "Reader must expose a hittable Readium web view projection",
            file: file,
            line: line
        )
    }

    private var webViewQuery: XCUIElementQuery { app.webViews }

    private var settingsStateQuery: XCUIElementQuery {
        // The production receipt is an `Other` accessibility container. Query
        // its concrete type so iOS 26 WebKit's legacy/modern AX projections
        // cannot duplicate the same receipt in a broad `.any` query.
        app.otherElements
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
        // Readium exposes one logical navigator through multiple WebKit AX
        // projections (ReadiumNavigator.WebView, WebView, WKContentView), all
        // sharing the same frame. This accessor is geometry-only, so presence
        // plus the bounded representative used by `webView` is the correct
        // contract; content and action selectors still use their own exact
        // typed queries.
        guard webViewQuery.waitUntilAtLeastOne(timeout: timeout) else {
            XCTFail("production Reader must expose at least one WebView", file: file, line: line)
            return nil
        }
        return webView
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
        // Readium/WebKit publishes several WebView AX projections for the same
        // navigator. Scope the lookup to the representative projection instead
        // of asking XCTest to scan every static text in every projection.
        webView.staticTexts.matching(identifier: text)
    }

    func waitForContent(_ text: String, timeout: TimeInterval = 45) -> Bool {
        let query = contentTextQuery(text)
        let candidate = query.element(boundBy: 0)
        guard candidate.waitForExistence(timeout: timeout) else {
            XCTFail("Reader content \(text) did not materialize within \(timeout)s")
            return false
        }
        let count = query.count
        guard count == 1 else {
            XCTFail("Reader content \(text) must resolve exactly one element, observed \(count)")
            return false
        }
        guard candidate.isHittable, !candidate.frame.isEmpty else {
            XCTFail("Reader content \(text) materialized but is not hittable")
            return false
        }
        return true
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
    /// Returns nil while the numeric badge is not applicable (unknown/restore
    /// failure or chrome hidden behind an overlay).
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
        UITestWaits.wait(
            for: NSPredicate { [app] _, _ in
                let badges = app.staticTexts.matching(identifier: "reader.header.progressBadge")
                let badge = badges.element
                guard badges.count == 1,
                      badge.exists,
                      let value = Double(badge.label.replacingOccurrences(of: "%", with: ""))
                else { return false }
                return value > threshold
            },
            on: app,
            timeout: timeout
        )
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
    func selectHighlightColor(_ color: String, timeout: TimeInterval = 8) -> Bool {
        let option = app.buttons["reader.settings.highlightColor.\(color)"]
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if option.exists, option.isHittable {
                option.tap()
                return true
            }

            let pickerIsActionable = highlightColorPicker.exists
                && highlightColorPicker.isHittable
                && !highlightColorPicker.frame.isEmpty
                && highlightColorPicker.frame.intersects(app.frame)
            if pickerIsActionable {
                highlightColorPicker.tap()
            } else {
                // ColorPicker is below the preview on the production Form.
                // Reveal it with the real scroll container; never derive a
                // coordinate from a clipped or invalid AX frame.
                scrollSettingsPanel(towardTop: false)
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return option.exists && option.isHittable
    }

    @discardableResult
    func showPreview(timeout: TimeInterval = 8) -> Bool {
        // `isHittable` is true even when a Form row is only partially exposed.
        // Move the scroll view to its canonical top position before sampling
        // geometry; otherwise the first frame can be a clipped intersection.
        scrollSettingsPanel(towardTop: true)
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
            scrollSettingsPanel(towardTop: true)
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
        guard revealLineHeightSlider(timeout: 8, file: file, line: line) else { return false }
        guard let slider = exactlyOne(
            lineHeightSliderQuery,
            named: "Reader line-height slider",
            timeout: 2,
            file: file,
            line: line
        ) else { return false }

        let previousValue = String(describing: slider.value ?? "")
        slider.adjust(toNormalizedSliderPosition: position)
        let expected: String?
        if position <= 0.01 {
            expected = "1.0"
        } else if position >= 0.99 {
            expected = "2.5"
        } else {
            expected = nil
        }
        if let expected {
            return waitForSliderValueEquals(expected, timeout: 8)
        }
        return waitForSliderValueChange(
            from: previousValue,
            timeout: 8
        )
    }

    @discardableResult
    func adjustLineHeight(
        toValue expectedValue: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> Bool {
        guard let numericValue = Double(expectedValue) else { return false }
        guard let currentValue = lineHeightValue(timeout: 5) else { return false }

        let delta = Int(((numericValue - currentValue) / 0.1).rounded())
        guard delta != 0 else { return true }
        let buttonQuery = delta > 0 ? lineHeightIncrementQuery : lineHeightDecrementQuery
        guard let button = exactlyOne(
            buttonQuery,
            named: delta > 0 ? "Reader line-height increment" : "Reader line-height decrement",
            timeout: 5,
            file: file,
            line: line
        ) else { return false }

        for _ in 0..<abs(delta) {
            button.tapWhenReady(timeout: 5, file: file, line: line)
        }
        return waitForLineHeightValue(expectedValue, timeout: 5)
    }

    private func revealLineHeightSlider(
        timeout: TimeInterval,
        file: StaticString,
        line: UInt
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let slider = exactlyOneIfPresent(
                lineHeightSliderQuery,
                named: "Reader line-height slider",
                timeout: 0.25,
                file: file,
                line: line
            ), slider.isHittable, !slider.frame.isEmpty {
                return true
            }
            scrollSettingsPanel(towardTop: false)
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return false
    }

    private func scrollSettingsPanel(
        towardTop: Bool
    ) {
        if let panel = exactlyOneIfPresent(
            settingsPanelQuery,
            named: "Reader settings panel",
            timeout: 0.25
        ), panel.isHittable {
            if towardTop {
                panel.swipeUp()
            } else {
                panel.swipeDown()
            }
        } else {
            if towardTop {
                app.swipeUp()
            } else {
                app.swipeDown()
            }
        }
    }

    private func waitForSliderValueChange(
        from previousValue: String,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let currentValue = currentLineHeightSliderValue(), currentValue != previousValue {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return currentLineHeightSliderValue().map { $0 != previousValue } ?? false
    }

    private func waitForSliderValueEquals(
        _ expectedValue: String,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let value = currentLineHeightSliderValue(),
               sliderValue(value, equals: expectedValue) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        guard let value = currentLineHeightSliderValue() else { return false }
        return sliderValue(value, equals: expectedValue)
    }

    private func currentLineHeightSliderValue() -> String? {
        guard let slider = exactlyOneIfPresent(
            lineHeightSliderQuery,
            named: "Reader line-height slider",
            timeout: 0.25
        ), let value = slider.value else {
            return nil
        }
        return String(describing: value)
    }

    private func sliderValue(_ value: Any, equals expected: String) -> Bool {
        let rendered = String(describing: value)
        if rendered == expected { return true }
        guard let actualNumber = Double(rendered),
              let expectedNumber = Double(expected) else {
            return false
        }
        return abs(actualNumber - expectedNumber) < 0.001
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
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let slider = exactlyOneIfPresent(
                lineHeightSliderQuery,
                named: "Reader line-height slider",
                timeout: 0.25
            ), let current = slider.value, sliderValue(current, equals: value) {
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
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

    /// Tap a duplicated reader word by its unique same-line context instead of
    /// relying on the AX bridge's element order. Readium may expose a chapter
    /// title, TOC anchor, and body word with the same identifier; the context
    /// node is the semantic anchor and the nearest hittable word is the target.
    @discardableResult
    func tapContentText(
        _ text: String,
        nearestTo contextText: String,
        timeout: TimeInterval = 5,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> Bool {
        guard let context = exactlyOne(
            contentTextQuery(contextText),
            named: "Reader content context \(contextText)",
            timeout: timeout,
            file: file,
            line: line
        ) else { return false }

        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let candidates = contentTextQuery(text).allElementsBoundByIndex.filter {
                $0.exists && $0.isHittable && !$0.frame.isEmpty
            }
            guard context.exists, context.isHittable, !context.frame.isEmpty else {
                RunLoop.current.run(until: Date().addingTimeInterval(0.1))
                continue
            }

            if let target = candidates.min(by: {
                abs($0.frame.midY - context.frame.midY) < abs($1.frame.midY - context.frame.midY)
            }) {
                target.tapWhenReady(file: file, line: line)
                return true
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }

        XCTFail(
            "Reader content \(text) did not resolve to a hittable node near context \(contextText)",
            file: file,
            line: line
        )
        return false
    }

    @discardableResult
    func swipeWebViewLeft(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        guard webViewQuery.waitUntilAtLeastOne(timeout: 5) else {
            XCTFail("production Reader must expose at least one WebView", file: file, line: line)
            return false
        }
        webView.swipeLeft()
        return true
    }

    func waitForSettingsStateContaining(_ fragments: [String], timeout: TimeInterval = 10) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if let state = exactlyOneIfPresent(
                settingsStateQuery,
                named: "production Reader settings state",
                timeout: 0.25
            ) {
                let value = String(describing: state.value ?? "")
                if fragments.allSatisfy(value.contains) { return true }
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return false
    }

    func themeIsSelected(_ theme: String, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Bool {
        let deadline = Date().addingTimeInterval(8)
        while Date() < deadline {
            if let option = exactlyOneIfPresent(
                themeOptionQuery(theme),
                named: "Reader theme option \(theme)",
                timeout: 0.25,
                file: file,
                line: line
            ) {
                return option.isSelected
            }
            // SwiftUI Form virtualizes rows; after a close/reopen the theme
            // rows may not yet be in the accessibility tree at the top.
            app.swipeUp()
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        XCTFail("Reader theme option \(theme) did not materialize", file: file, line: line)
        return false
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
