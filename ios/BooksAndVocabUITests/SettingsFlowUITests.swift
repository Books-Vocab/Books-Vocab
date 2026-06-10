//
//  SettingsFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Real-data Settings flow probe (UI Flow Evidence playbook; PodcastPlaybackPerf
//  is the live template). Supersedes SettingsSmokeUITests while preserving its
//  coverage intent: the sheet's entry path (Done button + nav bar) and exit path
//  (dismiss back to bookshelf) are asserted as steps of this flow.
//
//  Asserted real behavior (not "the button was tapped"):
//    1. Guest account surface — isolated auth session shows login CTAs, no
//       logged-in card (guest vs logged-in 對照, guest side).
//    2. 凍結複習時鐘 toggle → ReviewSettingsStore propagates → settings home
//       複習節奏 row reads 已凍結 · <模式>.
//    3. 複習模式 relaxed → intensive reflected in the same home summary.
//    4. 翻譯語言 target zh-Hant → ja reflected in the home 翻譯語言 row.
//
//  Determinism: `.settingsCleanPreferences` fixture resets review + translation
//  preferences through the production stores' real write paths on every launch,
//  so simulator state left by previous runs cannot leak in. Like the rest of the
//  UI suite (AppPage tab labels), assertions assume a zh-Hant simulator language.
//

import XCTest

final class SettingsFlowUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        // This flow walks four pushed sections end-to-end; cold isolated-session
        // launch (~25-30s) plus AX-snapshot queries can brush the harness default
        // 60s allowance. 120s is the harness maximum (ios_test.sh passes
        // -maximum-test-execution-time-allowance 120).
        executionTimeAllowance = 120
    }

    @MainActor
    func testSettingsFlowAppliesRealPreferenceChanges() throws {
        let app = launchIsolatedApp(
            fixtures: [.settingsCleanPreferences],
            perfLog: "settings"
        )
        captureStep("launch", app: app)

        let bookshelf = try step("bookshelf-tab", app: app) {
            let page = AppPage(app: app).goToBookshelf()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }

        let settings = try step("settings-opened", app: app) {
            let page = bookshelf.tapSettings()
            page.assertIsPresented()
            XCTAssertTrue(
                app.navigationBars.firstMatch.waitForExistence(timeout: 5),
                "Settings sheet presented without a navigation bar"
            )
            return page
        }

        // Guest gate: isolated auth session must start logged out. A logged-in
        // account card means this flow is not testing the guest surface — fail,
        // don't skip.
        if settings.logoutButton.waitUntilExists(timeout: 1) {
            captureStep("unexpected-logged-in-account", app: app)
            XCTFail("isolated auth session must start logged out; a logout button means the guest settings surface is not under test")
            return
        }
        try step("guest-account-state", app: app) {
            XCTAssertTrue(
                settings.googleLoginButton.waitUntilExists(timeout: 5),
                "guest settings must offer the Google login CTA"
            )
            XCTAssertTrue(
                settings.appleLoginButton.waitUntilExists(timeout: 2),
                "guest settings must offer the Apple login CTA"
            )
        }

        // Baseline summaries from the clean-preferences fixture.
        guard settings.reviewRhythmValue.waitUntilExists(timeout: 5),
              settings.translationLanguageValue.waitUntilExists(timeout: 5) else {
            captureStep("no-preference-summaries", app: app)
            XCTFail("settings home must expose 複習節奏 / 翻譯語言 summary values")
            return
        }
        try step("baseline-preferences", app: app) {
            XCTAssertEqual(
                settings.reviewRhythmValue.label, "寬鬆",
                "clean fixture must start relaxed and unfrozen"
            )
            XCTAssertEqual(
                settings.translationLanguageValue.label, "English → 繁體中文",
                "clean fixture must start with the en → zh-Hant pair"
            )
        }

        // 複習節奏: freeze the review clock + switch mode, then verify the home
        // summary reflects BOTH (real state propagation through the store).
        try step("review-rhythm-opened", app: app) {
            settings.openReviewRhythm()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        guard settings.pauseReviewClockToggle.waitUntilExists(timeout: 5) else {
            captureStep("no-pause-toggle", app: app)
            XCTFail("複習節奏 section must expose the 凍結複習時鐘 toggle")
            return
        }
        XCTAssertTrue(
            settings.pauseReviewClockToggle.waitUntilValueEquals("0", timeout: 3),
            "clean fixture must start with the review clock running (toggle off), got \(String(describing: settings.pauseReviewClockToggle.value))"
        )
        try step("freeze-clock-toggled", app: app) {
            settings.pauseReviewClockToggle.tapWhenReady()
            XCTAssertTrue(
                settings.pauseReviewClockToggle.waitUntilValueEquals("1", timeout: 5),
                "toggle must reflect ReviewSettingsStore.isProgressPaused after the async coordinator round-trip, not just the tap"
            )
        }
        guard settings.reviewModeTile("intensive").waitUntilExists(timeout: 3) else {
            captureStep("no-intensive-mode-tile", app: app)
            XCTFail("複習模式 section must expose the intensive mode tile")
            return
        }
        try step("mode-intensive-selected", app: app) {
            settings.reviewModeTile("intensive").tapWhenReady()
        }
        try step("review-rhythm-back", app: app) {
            settings.goBack()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        XCTAssertTrue(
            settings.reviewRhythmValue.waitUntilLabelContains("已凍結", timeout: 5),
            "home 複習節奏 summary must show the frozen state, got \(settings.reviewRhythmValue.label)"
        )
        XCTAssertEqual(
            settings.reviewRhythmValue.label, "已凍結 · 密集",
            "home 複習節奏 summary must combine frozen state with the newly selected mode"
        )
        captureStep("review-summary-frozen-intensive", app: app)

        // 翻譯語言: switch target zh-Hant → ja, verify the home row reflects it.
        try step("translation-opened", app: app) {
            settings.openTranslationLanguage()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        guard settings.targetLanguageRow("ja").waitUntilExists(timeout: 5) else {
            captureStep("no-target-language-row", app: app)
            XCTFail("翻譯語言 section must expose the 日本語 target row")
            return
        }
        try step("target-japanese-selected", app: app) {
            settings.targetLanguageRow("ja").scrollIntoView()
            settings.targetLanguageRow("ja").tapWhenReady()
        }
        try step("translation-back", app: app) {
            settings.goBack()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        XCTAssertTrue(
            settings.translationLanguageValue.waitUntilLabelContains("日本語", timeout: 5),
            "home 翻譯語言 summary must reflect the new target language, got \(settings.translationLanguageValue.label)"
        )
        XCTAssertEqual(settings.translationLanguageValue.label, "English → 日本語")
        captureStep("translation-summary-japanese", app: app)

        attachText(
            """
            guestAccount=loginCTAsVisible
            reviewBaseline=寬鬆
            reviewAfter=\(settings.reviewRhythmValue.label)
            translationBaseline=English → 繁體中文
            translationAfter=\(settings.translationLanguageValue.label)
            """,
            named: "Settings Flow State Transitions"
        )

        // Exit path (SettingsSmoke coverage intent): dismiss returns to bookshelf.
        try step("settings-dismissed", app: app) {
            _ = settings.dismiss()
            settings.closeButton.assertDoesNotExist()
            bookshelf.assertIsActive()
        }
    }
}
