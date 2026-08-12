import XCTest

/// Page Object for the Settings sheet (opened from bookshelf toolbar).
struct SettingsSheetPage {
    let app: XCUIApplication

    /// Settings is presented in a sheet with a NavigationStack; the nav bar title is "設定".
    var navBar: XCUIElement {
        let matching = app.navigationBars.allElementsBoundByIndex
        precondition(matching.count == 1, "Expected exactly one settings navigation bar, found \(matching.count)")
        return matching[0]
    }

    var homeScrollView: XCUIElement {
        app.scrollViews["settings.home.scrollView"]
    }

    var closeButton: XCUIElement {
        app.buttons["settings.dismissButton"]
    }

    // MARK: - Home: account section (guest vs logged-in)

    var googleLoginButton: XCUIElement {
        app.buttons["settings.account.googleLoginButton"]
    }

    var appleLoginButton: XCUIElement {
        app.buttons["settings.account.appleLoginButton"]
    }

    var logoutButton: XCUIElement {
        app.buttons["settings.account.logoutButton"]
    }

    // MARK: - Home: preferences rows

    var reviewRhythmRow: XCUIElement {
        app.buttons["settings.preferences.reviewRhythmRow"]
    }

    /// Trailing summary of the 複習節奏 row (e.g. "寬鬆" / "已凍結 · 密集").
    var reviewRhythmValue: XCUIElement {
        app.staticTexts["settings.preferences.reviewRhythmValue"]
    }

    /// 複習卡片 row — card presentation, deliberately separate from 複習節奏.
    var reviewCardLayoutRow: XCUIElement {
        app.buttons["settings.preferences.reviewCardLayoutRow"]
    }

    /// Trailing summary of the 複習卡片 row ("預設" / "自訂").
    var reviewCardLayoutValue: XCUIElement {
        app.staticTexts["settings.preferences.reviewCardLayoutValue"]
    }

    var translationLanguageRow: XCUIElement {
        app.buttons["settings.preferences.translationLanguageRow"]
    }

    /// Trailing summary of the 翻譯語言 row (e.g. "English → 繁體中文").
    var translationLanguageValue: XCUIElement {
        app.staticTexts["settings.preferences.translationLanguageValue"]
    }

    var soundFeedbackToggle: XCUIElement {
        app.switches["settings.preferences.soundFeedbackToggle"]
    }

    var hapticFeedbackToggle: XCUIElement {
        app.switches["settings.preferences.hapticFeedbackToggle"]
    }

    var syncSummaryButton: XCUIElement {
        app.descendants(matching: .button)
            .matching(identifier: "settings.syncSummary")
            .firstMatch
    }

    var syncLifecycle: XCUIElement {
        app.otherElements["settings.syncLifecycle"]
    }

    var syncLifecycleQuery: XCUIElementQuery {
        app.otherElements.matching(identifier: "settings.syncLifecycle")
    }

    var syncLifecycleStatus: XCUIElement {
        app.staticTexts["settings.syncLifecycle.status"]
    }

    var syncLifecycleMessage: XCUIElement {
        app.staticTexts["settings.syncLifecycle.message"]
    }

    var syncLifecycleTerminalMarker: XCUIElement {
        app.staticTexts["settings.syncLifecycle.terminalMarker"]
    }

    var syncLifecycleEvidence: XCUIElement {
        app.staticTexts["settings.syncLifecycle.evidence"]
    }

    var retrySyncButton: XCUIElement {
        app.buttons["settings.syncLifecycle.retryButton"]
    }

    var dismissSyncStatusButton: XCUIElement {
        app.buttons["settings.syncLifecycle.dismissButton"]
    }

    var appearanceGroup: XCUIElement {
        app.otherElements["settings.preferences.appearanceGroup"]
    }

    var learningGroup: XCUIElement {
        app.otherElements["settings.preferences.learningGroup"]
    }

    var feedbackGroup: XCUIElement {
        app.otherElements["settings.preferences.feedbackGroup"]
    }

    var readerGroup: XCUIElement {
        app.otherElements["settings.preferences.readerGroup"]
    }

    var conditionalSyncGroup: XCUIElement {
        app.otherElements["settings.preferences.syncGroup"]
    }

    // MARK: - Account detail danger boundary

    /// Stable child selector inside the production account navigation row. The
    /// row's separate identity fingerprint remains available for account proof;
    /// this selector is the action target and never depends on localized text.
    var accountDetailRow: XCUIElement {
        app.descendants(matching: .any)["settings.account.accountDetailRow"]
    }

    var accountDangerGroup: XCUIElement {
        app.otherElements["settings.account.dangerGroup"]
    }

    var resetBoundary: XCUIElement {
        app.otherElements["settings.account.resetBoundary"]
    }

    var resetBeforeSnapshot: XCUIElement {
        app.otherElements["settings.account.resetBoundary.before"]
    }

    var resetAfterSnapshot: XCUIElement {
        app.otherElements["settings.account.resetBoundary.after"]
    }

    var resetPhase: XCUIElement {
        app.staticTexts["settings.account.resetBoundary.phase"]
    }

    var resetButton: XCUIElement {
        app.buttons["settings.account.resetBoundary.resetButton"]
    }

    // MARK: - Review rhythm section (pushed)

    var pauseReviewClockToggle: XCUIElement {
        app.switches["settings.review.pauseToggle"]
    }

    /// Mode tile inside the 複習節奏 section; `rawValue` ∈ relaxed / intensive / custom.
    func reviewModeTile(_ rawValue: String) -> XCUIElement {
        app.buttons["settings.review.modeTile.\(rawValue)"]
    }

    // MARK: - Translation language section (pushed)

    /// Source-language row; `id` is `TranslationLanguage.rawValue` (e.g. "en", "ja").
    func sourceLanguageRow(_ id: String) -> XCUIElement {
        app.buttons["settings.translation.source.\(id)"]
    }

    /// Target-language row; `id` is `TranslationLanguage.rawValue` (e.g. "zh-Hant", "ja").
    func targetLanguageRow(_ id: String) -> XCUIElement {
        app.buttons["settings.translation.target.\(id)"]
    }

    /// Nav-bar back button of a pushed detail section.
    var backButton: XCUIElement {
        let bars = app.navigationBars.allElementsBoundByIndex.filter { $0.exists }
        let barsWithButtons = bars.filter { !$0.buttons.allElementsBoundByIndex.isEmpty }
        precondition(!barsWithButtons.isEmpty, "Expected a settings navigation bar with a back button")
        // XCTest reports the presented sheet's navigation bar before the
        // underlying tab's bar. The last bar may therefore be the bookshelf
        // chrome and its first button is `bookshelf.settingsButton`.
        let buttons = barsWithButtons.first!.buttons.allElementsBoundByIndex
        precondition(!buttons.isEmpty, "Expected the top settings navigation bar to expose a back button")
        return buttons[0]
    }

    // MARK: - Actions

    func dismiss(file: StaticString = #filePath, line: UInt = UInt(#line)) -> BookshelfPage {
        tapExactlyOne(closeButton, named: "完成", file: file, line: line)
        return BookshelfPage(app: app)
    }

    func openReviewRhythm(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        let row = reviewRhythmRow
        XCTAssertTrue(row.exists, file: file, line: line)
        row.scrollIntoView(file: file, line: line)
        tapExactlyOne(row, named: "settings.preferences.reviewRhythmRow", file: file, line: line)
        return self
    }

    func openTranslationLanguage(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        let row = translationLanguageRow
        XCTAssertTrue(row.exists, file: file, line: line)
        row.scrollIntoView(file: file, line: line)
        tapExactlyOne(row, named: "settings.preferences.translationLanguageRow", file: file, line: line)
        return self
    }

    @discardableResult
    func openAccountDetail(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        accountDetailRow.scrollIntoView(file: file, line: line)
        accountDetailRow.tapWhenReady(file: file, line: line)
        return self
    }

    /// 開啟「複習卡片」列。
    func openReviewCardLayout(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        let row = reviewCardLayoutRow
        XCTAssertTrue(row.exists, file: file, line: line)
        row.scrollIntoView(file: file, line: line)
        tapExactlyOne(row, named: "settings.preferences.reviewCardLayoutRow", file: file, line: line)
        return self
    }

    func openSyncSummary(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        let button = syncSummaryButton
        scrollHomeElementIntoView(button, file: file, line: line)
        tapExactlyOne(button, named: "settings.syncSummary", file: file, line: line)
        return self
    }

    private func scrollHomeElementIntoView(
        _ element: XCUIElement,
        file: StaticString,
        line: UInt
    ) {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if element.exists,
               !element.frame.isEmpty,
               homeScrollView.exists,
               homeScrollView.frame.intersects(element.frame),
               element.isHittable {
                return
            }
            if homeScrollView.exists {
                if element.exists, element.frame.minY < homeScrollView.frame.minY {
                    homeScrollView.swipeDown()
                } else {
                    homeScrollView.swipeUp()
                }
            } else {
                app.swipeUp()
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTAssertTrue(
            element.exists && !element.frame.isEmpty,
            "Settings home element did not become visible: \(element.identifier)",
            file: file,
            line: line
        )
    }

    func goBack(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        tapExactlyOne(backButton, named: "設定 back button", file: file, line: line)
        return self
    }

    // MARK: - Assertions

    func assertIsPresented(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // Confirm by the "完成" (Done) button in the sheet toolbar.
        closeButton.assertExists(file: file, line: line)
        XCTAssertEqual(app.buttons.matching(identifier: "完成").count, 1, file: file, line: line)
        XCTAssertTrue(navBar.exists, file: file, line: line)
        XCTAssertGreaterThan(navBar.frame.width, 0, file: file, line: line)
        XCTAssertGreaterThan(navBar.frame.height, 0, file: file, line: line)
    }

    func assertTerminalFeedback(
        status: String,
        expectedEvidence: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertTrue(syncLifecycle.waitForExistence(timeout: 5), file: file, line: line)
        XCTAssertEqual(syncLifecycleQuery.count, 1, file: file, line: line)
        XCTAssertGreaterThan(syncLifecycle.frame.width, 0, file: file, line: line)
        XCTAssertGreaterThan(syncLifecycle.frame.height, 0, file: file, line: line)
        XCTAssertEqual(app.staticTexts.matching(identifier: "settings.syncLifecycle.status").count, 1, file: file, line: line)
        XCTAssertEqual(syncLifecycleStatus.label, status, file: file, line: line)
        XCTAssertTrue(syncLifecycleTerminalMarker.exists, file: file, line: line)
        XCTAssertGreaterThan(syncLifecycleTerminalMarker.frame.width, 0, file: file, line: line)
        XCTAssertGreaterThan(syncLifecycleTerminalMarker.frame.height, 0, file: file, line: line)
#if DEBUG
        XCTAssertTrue(syncLifecycleEvidence.exists, file: file, line: line)
        XCTAssertEqual(syncLifecycleEvidence.label, expectedEvidence, file: file, line: line)
#endif
    }

    private func tapExactlyOne(
        _ element: XCUIElement,
        named name: String,
        file: StaticString,
        line: UInt
    ) {
        XCTAssertTrue(element.exists, "expected exactly one \(name)", file: file, line: line)
        element.tapWhenReady(file: file, line: line)
    }
}
