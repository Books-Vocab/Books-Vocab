import XCTest

/// Page Object for the Settings sheet (opened from bookshelf toolbar).
struct SettingsSheetPage {
    let app: XCUIApplication

    /// Settings is presented in a sheet with a NavigationStack. The underlying
    /// Bookshelf navigation bar remains in the application-wide AX tree, so
    /// scope this query through the sheet-owned Done button instead of counting
    /// every navigation bar in the app.
    var navBar: XCUIElement {
        let matching = app.navigationBars
            .containing(.button, identifier: "settings.dismissButton")
            .allElementsBoundByIndex
        precondition(matching.count == 1, "Expected exactly one settings navigation bar, found \(matching.count)")
        return matching[0]
    }

    var homeScrollView: XCUIElement {
        exact(.scrollView, "settings.home.scrollView")
    }

    private func exact(_ type: XCUIElement.ElementType, _ identifier: String) -> XCUIElement {
        app.descendants(matching: type)
            .matching(identifier: identifier)
            .element
    }

    var closeButton: XCUIElement {
        exact(.button, "settings.dismissButton")
    }

    // MARK: - Home: account section (guest vs logged-in)

    var googleLoginButton: XCUIElement {
        exact(.button, "settings.account.googleLoginButton")
    }

    var appleLoginButton: XCUIElement {
        exact(.button, "settings.account.appleLoginButton")
    }

    var logoutButton: XCUIElement {
        exact(.button, "settings.account.logoutButton")
    }

    // MARK: - Home: preferences rows

    var reviewRhythmRow: XCUIElement {
        exact(.button, "settings.preferences.reviewRhythmRow")
    }

    /// Trailing summary of the 複習節奏 row (e.g. "寬鬆" / "已凍結 · 密集").
    var reviewRhythmValue: XCUIElement {
        exact(.staticText, "settings.preferences.reviewRhythmValue")
    }

    /// 複習卡片 row — card presentation, deliberately separate from 複習節奏.
    var reviewCardLayoutRow: XCUIElement {
        exact(.button, "settings.preferences.reviewCardLayoutRow")
    }

    /// Trailing summary of the 複習卡片 row ("預設" / "自訂").
    var reviewCardLayoutValue: XCUIElement {
        exact(.staticText, "settings.preferences.reviewCardLayoutValue")
    }

    var translationLanguageRow: XCUIElement {
        exact(.button, "settings.preferences.translationLanguageRow")
    }

    /// Trailing summary of the 翻譯語言 row (e.g. "English → 繁體中文").
    var translationLanguageValue: XCUIElement {
        exact(.staticText, "settings.preferences.translationLanguageValue")
    }

    var soundFeedbackToggle: XCUIElement {
        exact(.switch, "settings.preferences.soundFeedbackToggle")
    }

    var hapticFeedbackToggle: XCUIElement {
        exact(.switch, "settings.preferences.hapticFeedbackToggle")
    }

    var syncSummaryButton: XCUIElement {
        exact(.button, "settings.syncSummary")
    }

    var syncLifecycle: XCUIElement {
        app.otherElements["settings.syncLifecycle"]
    }

    var syncProgress: XCUIElement {
        app.otherElements["settings.syncProgress"]
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
        exact(.other, "settings.preferences.appearanceGroup")
    }

    var learningGroup: XCUIElement {
        exact(.other, "settings.preferences.learningGroup")
    }

    var feedbackGroup: XCUIElement {
        exact(.other, "settings.preferences.feedbackGroup")
    }

    var readerGroup: XCUIElement {
        exact(.other, "settings.preferences.readerGroup")
    }

    var conditionalSyncGroup: XCUIElement {
        exact(.other, "settings.preferences.syncGroup")
    }

    // MARK: - Account detail danger boundary

    /// Stable child selector inside the production account navigation row. The
    /// row's separate identity fingerprint remains available for account proof;
    /// this selector is the action target and never depends on localized text.
    var accountDetailRow: XCUIElement {
        exact(.button, "settings.account.accountDetailRow")
    }

    var accountDangerGroup: XCUIElement {
        exact(.other, "settings.account.dangerGroup")
    }

    var accountScrollView: XCUIElement {
        exact(.scrollView, "settings.account.scrollView")
    }

    var accountNameValue: XCUIElement {
        exact(.staticText, "settings.account.info.name")
    }

    var accountEmailValue: XCUIElement {
        exact(.staticText, "settings.account.info.email")
    }

    var resetBoundary: XCUIElement {
        exact(.other, "settings.account.resetBoundary")
    }

    var resetBeforeSnapshot: XCUIElement {
        exact(.other, "settings.account.resetBoundary.before")
    }

    var resetAfterSnapshot: XCUIElement {
        exact(.other, "settings.account.resetBoundary.after")
    }

    var resetBeforeCardCount: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.before.localCardCount")
    }

    var resetBeforePreferences: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.before.preferences")
    }

    var resetBeforeLoginStatus: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.before.loginStatus")
    }

    var resetAfterCardCount: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.after.localCardCount")
    }

    var resetAfterPreferences: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.after.preferences")
    }

    var resetAfterLoginStatus: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.after.loginStatus")
    }

    var resetPhase: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.phase")
    }

    var resetButton: XCUIElement {
        exact(.button, "settings.account.resetBoundary.resetButton")
    }

    var resetMessage: XCUIElement {
        exact(.staticText, "settings.account.resetBoundary.message")
    }

    var syncSummaryButton: XCUIElement {
        app.buttons["settings.syncSummary"]
    }

    var syncLifecycle: XCUIElement {
        app.otherElements["settings.syncLifecycle"]
    }

    var syncLifecycleStatus: XCUIElement {
        app.staticTexts["settings.syncLifecycle.status"]
    }

    var syncLifecycleMessage: XCUIElement {
        app.staticTexts["settings.syncLifecycle.message"]
    }

    var retrySyncButton: XCUIElement {
        app.buttons["settings.syncLifecycle.retryButton"]
    }

    var dismissSyncStatusButton: XCUIElement {
        app.buttons["settings.syncLifecycle.dismissButton"]
    }

    // MARK: - Review rhythm section (pushed)

    var pauseReviewClockToggle: XCUIElement {
        exact(.switch, "settings.review.pauseToggle")
    }

    /// Mode tile inside the 複習節奏 section; `rawValue` ∈ relaxed / intensive / custom.
    func reviewModeTile(_ rawValue: String) -> XCUIElement {
        exact(.button, "settings.review.modeTile.\(rawValue)")
    }

    // MARK: - Translation language section (pushed)

    /// Source-language row; `id` is `TranslationLanguage.rawValue` (e.g. "en", "ja").
    func sourceLanguageRow(_ id: String) -> XCUIElement {
        exact(.button, "settings.translation.source.\(id)")
    }

    /// Target-language row; `id` is `TranslationLanguage.rawValue` (e.g. "zh-Hant", "ja").
    func targetLanguageRow(_ id: String) -> XCUIElement {
        exact(.button, "settings.translation.target.\(id)")
    }

    /// Nav-bar back button of a pushed detail section.
    var backButton: XCUIElement {
        exact(.button, "settings.detail.backButton")
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
        scrollHomeElementIntoView(accountDetailRow, file: file, line: line)
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

    func scrollHomeElementIntoView(
        _ element: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
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
        // Confirm through the production identifier, not a localized toolbar
        // label. UI World scenarios intentionally exercise multiple app
        // languages (including English), while this navigation contract is
        // language-independent.
        let dismissButton = app.buttons["settings.dismissButton"]
        XCTAssertTrue(
            dismissButton.waitUntilHittable(timeout: 15),
            "Settings dismiss button must materialize and become hittable before cardinality is asserted",
            file: file,
            line: line
        )
        _ = assertExactlyOne(
            .button,
            identifier: "settings.dismissButton",
            visible: true,
            hittable: true,
            file: file,
            line: line
        )
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

    @discardableResult
    func assertExactlyOne(
        _ type: XCUIElement.ElementType,
        identifier: String,
        visible: Bool = true,
        hittable: Bool = false,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement {
        let matches = app.descendants(matching: type).matching(identifier: identifier)
        XCTAssertEqual(
            matches.count,
            1,
            "Expected exactly one production \(type) with identifier \(identifier), got \(matches.count)",
            file: file,
            line: line
        )
        let element = matches.element
        XCTAssertTrue(element.waitForExistence(timeout: 5), "Expected production element to exist: \(identifier)", file: file, line: line)
        XCTAssertEqual(element.elementType, type, "Production element type drifted for \(identifier)", file: file, line: line)
        if visible {
            XCTAssertFalse(element.frame.isEmpty, "Production element has no visible geometry: \(identifier)", file: file, line: line)
        }
        if hittable {
            XCTAssertTrue(element.isHittable, "Production element is not hittable: \(identifier)", file: file, line: line)
        }
        return element
    }

    func assertCount(
        _ type: XCUIElement.ElementType,
        identifier: String,
        equals expected: Int,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let matches = app.descendants(matching: type).matching(identifier: identifier)
        XCTAssertEqual(matches.count, expected, "Unexpected production element count for \(identifier)", file: file, line: line)
    }

    func count(_ type: XCUIElement.ElementType, identifier: String) -> Int {
        app.descendants(matching: type).matching(identifier: identifier).count
    }

    func assertAccountDetailEvidence(
        resetButtonHittable: Bool = false,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        for (type, identifier) in [
            (XCUIElement.ElementType.button, "settings.detail.backButton"),
            (XCUIElement.ElementType.scrollView, "settings.account.scrollView"),
            (XCUIElement.ElementType.other, "settings.account.infoGroup"),
            (XCUIElement.ElementType.other, "settings.account.dataManagementGroup"),
            (XCUIElement.ElementType.other, "settings.account.dangerGroup"),
            (XCUIElement.ElementType.other, "settings.account.resetBoundary"),
            (XCUIElement.ElementType.other, "settings.account.resetBoundary.before"),
            (XCUIElement.ElementType.other, "settings.account.resetBoundary.after"),
            (XCUIElement.ElementType.staticText, "settings.account.resetBoundary.phase"),
            (XCUIElement.ElementType.button, "settings.account.resetBoundary.resetButton"),
            (XCUIElement.ElementType.staticText, "settings.account.info.name"),
            (XCUIElement.ElementType.staticText, "settings.account.info.email"),
        ] {
            _ = assertExactlyOne(type, identifier: identifier, visible: true, file: file, line: line)
        }
        _ = assertExactlyOne(
            .button,
            identifier: "settings.account.resetBoundary.resetButton",
            visible: true,
            hittable: resetButtonHittable,
            file: file,
            line: line
        )
    }

    func scrollAccountValueIntoView(
        _ value: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            if value.exists,
               !value.frame.isEmpty,
               accountScrollView.frame.intersects(value.frame),
               value.isHittable {
                return
            }
            let viewport = accountScrollView.frame
            if value.exists, !value.frame.isEmpty, value.frame.minY < viewport.minY {
                // The preceding probe may have moved the value above the
                // viewport. A one-way swipe-up loop can never recover it.
                accountScrollView.swipeDown()
            } else {
                accountScrollView.swipeUp()
            }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        XCTAssertTrue(
            value.exists && !value.frame.isEmpty && accountScrollView.frame.intersects(value.frame),
            "Account value did not become visible inside the production scroll view: \(value.identifier)",
            file: file,
            line: line
        )
    }

    func assertAccountScrollMoves(
        probing value: XCUIElement,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let before = value.frame
        accountScrollView.swipeUp()
        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline && abs(value.frame.minY - before.minY) <= 1 {
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        let after = value.frame
        XCTAssertGreaterThan(
            abs(after.minY - before.minY),
            1,
            "The production account scroll view did not move long content",
            file: file,
            line: line
        )
        XCTAssertFalse(after.isEmpty, "Scrolled account value lost geometry", file: file, line: line)
    }
}
