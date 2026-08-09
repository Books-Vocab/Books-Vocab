import XCTest

/// Page Object for the Settings sheet (opened from bookshelf toolbar).
struct SettingsSheetPage {
    let app: XCUIApplication

    /// Settings is presented in a sheet with a NavigationStack; the nav bar title is "設定".
    var navBar: XCUIElement {
        app.navigationBars.firstMatch
    }

    var closeButton: XCUIElement {
        app.buttons["完成"]
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
        app.navigationBars.firstMatch.buttons.element(boundBy: 0)
    }

    // MARK: - Actions

    @discardableResult
    func dismiss(file: StaticString = #filePath, line: UInt = UInt(#line)) -> BookshelfPage {
        closeButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    @discardableResult
    func openReviewRhythm(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        reviewRhythmRow.scrollIntoView(file: file, line: line)
        reviewRhythmRow.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func openTranslationLanguage(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        translationLanguageRow.scrollIntoView(file: file, line: line)
        translationLanguageRow.tapWhenReady(file: file, line: line)
        return self
    }

    /// 開啟「複習卡片」列。
    @discardableResult
    func openReviewCardLayout(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        reviewCardLayoutRow.scrollIntoView(file: file, line: line)
        reviewCardLayoutRow.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func goBack(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        backButton.tapWhenReady(file: file, line: line)
        return self
    }

    // MARK: - Assertions

    func assertIsPresented(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // Confirm by the "完成" (Done) button in the sheet toolbar.
        closeButton.assertExists(file: file, line: line)
    }
}
