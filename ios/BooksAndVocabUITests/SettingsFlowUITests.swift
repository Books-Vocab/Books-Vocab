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
import Foundation

final class SettingsFlowUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        // This flow walks four pushed sections end-to-end; cold isolated-session
        // launch (~25-30s) plus AX-snapshot queries can exceed the generic UI
        // smoke allowance. This value must be set on the XCTest case itself;
        // the runner max alone cannot extend it.
        executionTimeAllowance = 360
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
            return page
        }

        captureStep(
            "required-settings",
            assetID: try SettingsFixtureManifest.evidenceAssetID(for: "preferences_auto_sync_off"),
            app: app
        )
        for identifier in [
            "settings.preferences.appearanceGroup",
            "settings.preferences.learningGroup",
            "settings.preferences.feedbackGroup",
            "settings.preferences.readerGroup",
        ] {
            _ = settings.assertExactlyOne(.other, identifier: identifier, visible: true)
        }

        // Guest gate: isolated auth session must start logged out. A logged-in
        // account card means this flow is not testing the guest surface — fail,
        // don't skip.
        settings.assertCount(.button, identifier: "settings.account.logoutButton", equals: 0)
        if settings.count(.button, identifier: "settings.account.logoutButton") != 0 {
            captureStep("unexpected-logged-in-account", app: app)
            XCTFail("isolated auth session must start logged out; a logout button means the guest settings surface is not under test")
            return
        }
        try step("guest-account-state", app: app) {
            _ = settings.assertExactlyOne(.button, identifier: "settings.account.googleLoginButton", visible: true, hittable: true)
            _ = settings.assertExactlyOne(.button, identifier: "settings.account.appleLoginButton", visible: true, hittable: true)
        }

        // Baseline summaries from the clean-preferences fixture.
        _ = settings.assertExactlyOne(.scrollView, identifier: "settings.home.scrollView", visible: true)
        _ = settings.assertExactlyOne(.staticText, identifier: "settings.preferences.reviewRhythmValue", visible: true)
        _ = settings.assertExactlyOne(.staticText, identifier: "settings.preferences.translationLanguageValue", visible: true)
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

        try step("feedback-preferences-toggle", app: app) {
            settings.scrollHomeElementIntoView(settings.soundFeedbackToggle)
            _ = settings.assertExactlyOne(.switch, identifier: "settings.preferences.soundFeedbackToggle", visible: true)
            settings.scrollHomeElementIntoView(settings.hapticFeedbackToggle)
            _ = settings.assertExactlyOne(.switch, identifier: "settings.preferences.hapticFeedbackToggle", visible: true)

            XCTAssertTrue(settings.soundFeedbackToggle.waitUntilValueEquals("0", timeout: 3))
            settings.soundFeedbackToggle.tapWhenReady()
            XCTAssertTrue(settings.soundFeedbackToggle.waitUntilValueEquals("1", timeout: 3))
            settings.soundFeedbackToggle.tapWhenReady()
            XCTAssertTrue(settings.soundFeedbackToggle.waitUntilValueEquals("0", timeout: 3))

            settings.hapticFeedbackToggle.scrollIntoView()
            XCTAssertTrue(settings.hapticFeedbackToggle.waitUntilValueEquals("1", timeout: 3))
            settings.hapticFeedbackToggle.tapWhenReady()
            XCTAssertTrue(settings.hapticFeedbackToggle.waitUntilValueEquals("0", timeout: 3))
            settings.hapticFeedbackToggle.tapWhenReady()
            XCTAssertTrue(settings.hapticFeedbackToggle.waitUntilValueEquals("1", timeout: 3))
        }

        // 複習節奏: freeze the review clock + switch mode, then verify the home
        // summary reflects BOTH (real state propagation through the store).
        try step("review-rhythm-opened", app: app) {
            settings.openReviewRhythm()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        captureStep(
            "section-navigation",
            assetID: try SettingsFixtureManifest.evidenceAssetID(for: "preferences_logged_out_no_sync"),
            app: app
        )
        guard settings.pauseReviewClockToggle.waitUntilExists(timeout: 5) else {
            captureStep("no-pause-toggle", app: app)
            XCTFail("複習節奏 section must expose the 凍結複習時鐘 toggle")
            return
        }
        XCTAssertEqual(
            settings.pauseReviewClockToggle.label,
            "凍結複習時鐘",
            "the iOS accessibility control must retain the visible review-clock label"
        )
        _ = settings.assertExactlyOne(.switch, identifier: "settings.review.pauseToggle", visible: true)
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
        _ = settings.assertExactlyOne(.button, identifier: "settings.review.modeTile.intensive", visible: true, hittable: true)
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
        _ = settings.assertExactlyOne(.button, identifier: "settings.translation.target.ja", visible: true, hittable: true)
        try step("target-japanese-selected", app: app) {
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

    @MainActor
    func testSettingsLongContentCounterexampleResolvesProductionSelectors() throws {
        let longDisplayName = try SettingsFixtureManifest.authValue(
            fixtureID: "long_content_counterexample",
            key: "displayName"
        )
        let longEmail = try SettingsFixtureManifest.authValue(
            fixtureID: "long_content_counterexample",
            key: "email"
        )
        let app = launchIsolatedApp(
            fixtures: [.settingsLongContent],
            extraEnvironment: [
                "UIPreferredContentSizeCategoryName": "UICTContentSizeCategoryAccessibilityXXXL"
            ],
            perfLog: "settings-long-content-counterexample"
        )
        let bookshelf = AppPage(app: app).goToBookshelf()
        XCTAssertTrue(app.waitForNavigationToSettle())

        let settings = bookshelf.tapSettings()
        settings.assertIsPresented()
        captureStep("settings", app: app)
        _ = settings.assertExactlyOne(.button, identifier: "settings.account.logoutButton", visible: true, hittable: true)
        _ = settings.assertExactlyOne(.other, identifier: "settings.preferences.syncGroup", visible: true)
        _ = settings.assertExactlyOne(.scrollView, identifier: "settings.home.scrollView", visible: true)

        settings.openAccountDetail()
        XCTAssertTrue(app.waitForNavigationToSettle())
        settings.assertAccountDetailEvidence()
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("preReset", timeout: 5))

        XCTAssertGreaterThan(settings.accountScrollView.frame.width, 0)
        XCTAssertGreaterThan(settings.accountScrollView.frame.height, 0)
        XCTAssertEqual(settings.accountNameValue.elementType, .staticText)
        XCTAssertEqual(settings.accountEmailValue.elementType, .staticText)
        XCTAssertEqual(settings.accountNameValue.label, longDisplayName)
        XCTAssertEqual(settings.accountEmailValue.label, longEmail)
        XCTAssertTrue(settings.accountScrollView.frame.intersects(settings.accountNameValue.frame))

        // A real gesture must move the production scroll content; a static
        // frame/AX existence check is insufficient for the XXXL counterexample.
        settings.assertAccountScrollMoves(probing: settings.accountNameValue)
        XCTAssertEqual(settings.accountNameValue.label, longDisplayName)
        settings.scrollAccountValueIntoView(settings.accountEmailValue)
        XCTAssertEqual(settings.accountEmailValue.label, longEmail, "long account value must remain fully visible")
        XCTAssertEqual(settings.accountEmailValue.elementType, .staticText)
        XCTAssertFalse(settings.accountEmailValue.frame.isEmpty)
        XCTAssertGreaterThan(settings.accountEmailValue.frame.height, 0)
        XCTAssertTrue(
            settings.accountScrollView.frame.intersects(settings.accountEmailValue.frame),
            "long account value must remain inside the scrollable account content"
        )

        captureStep("long-content", app: app)

        captureStep(
            "long-content-counterexample",
            assetID: try SettingsFixtureManifest.evidenceAssetID(for: "long_content_counterexample"),
            app: app
        )
    }

    @MainActor
    func testSettingsResetCounterexampleShowsObservableBoundary() throws {
        let beforeCardCount = try SettingsFixtureManifest.snapshotInt(
            fixtureID: "reset_counterexample",
            phase: "before",
            key: "localCardCount"
        )
        let beforeHasCustomPreferences = try SettingsFixtureManifest.snapshotBool(
            fixtureID: "reset_counterexample",
            phase: "before",
            key: "hasCustomPreferences"
        )
        let beforeIsLoggedIn = try SettingsFixtureManifest.snapshotBool(
            fixtureID: "reset_counterexample",
            phase: "before",
            key: "isLoggedIn"
        )
        let afterCardCount = try SettingsFixtureManifest.snapshotInt(
            fixtureID: "reset_counterexample",
            phase: "after",
            key: "localCardCount"
        )
        let afterHasCustomPreferences = try SettingsFixtureManifest.snapshotBool(
            fixtureID: "reset_counterexample",
            phase: "after",
            key: "hasCustomPreferences"
        )
        let afterIsLoggedIn = try SettingsFixtureManifest.snapshotBool(
            fixtureID: "reset_counterexample",
            phase: "after",
            key: "isLoggedIn"
        )
        XCTAssertGreaterThan(beforeCardCount, 0)
        let beforeCardValue = "\(beforeCardCount)"
        let partialCardValue = "\(beforeCardCount - 1)"
        let afterCardValue = "\(afterCardCount)"
        XCTAssertNotEqual(beforeHasCustomPreferences, afterHasCustomPreferences)
        XCTAssertEqual(beforeIsLoggedIn, afterIsLoggedIn)
        let app = launchIsolatedApp(
            fixtures: [.settingsResetLifecycle],
            extraEnvironment: ["KG_UI_TEST_SETTINGS_RESET_FAIL_ONCE": "1"],
            perfLog: "settings-reset-counterexample"
        )
        let bookshelf = AppPage(app: app).goToBookshelf()
        XCTAssertTrue(app.waitForNavigationToSettle())

        let settings = bookshelf.tapSettings()
        settings.assertIsPresented()
        _ = settings.assertExactlyOne(.button, identifier: "settings.account.logoutButton", visible: true, hittable: true)
        _ = settings.assertExactlyOne(.other, identifier: "settings.preferences.syncGroup", visible: true)
        _ = settings.assertExactlyOne(.scrollView, identifier: "settings.home.scrollView", visible: true)

        settings.openAccountDetail()
        XCTAssertTrue(app.waitForNavigationToSettle())
        settings.assertAccountDetailEvidence()
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("preReset", timeout: 5))
        XCTAssertTrue(
            settings.resetBeforeCardCount.waitUntilLabelContains(beforeCardValue, timeout: 5),
            "reset before card count AX label=\(settings.resetBeforeCardCount.label) value=\(String(describing: settings.resetBeforeCardCount.value)) expected numeric value=\(beforeCardValue)"
        )
        XCTAssertTrue(settings.resetBeforePreferences.waitUntilExists(timeout: 5))
        XCTAssertFalse(settings.resetBeforePreferences.label.isEmpty)
        let beforePreferencesAXLabel = settings.resetBeforePreferences.label
        XCTAssertTrue(settings.resetBeforeLoginStatus.waitUntilExists(timeout: 5))
        XCTAssertFalse(settings.resetBeforeLoginStatus.label.isEmpty)
        let beforeLoginStatusAXLabel = settings.resetBeforeLoginStatus.label
        XCTAssertTrue(settings.resetAfterCardCount.waitUntilLabelContains(beforeCardValue, timeout: 5))
        XCTAssertTrue(settings.resetAfterPreferences.waitUntilExists(timeout: 5))
        XCTAssertEqual(settings.resetAfterPreferences.label, beforePreferencesAXLabel)
        XCTAssertTrue(settings.resetAfterLoginStatus.waitUntilExists(timeout: 5))
        XCTAssertEqual(settings.resetAfterLoginStatus.label, beforeLoginStatusAXLabel)
        XCTAssertTrue(settings.resetAfterCardCount.label.contains(beforeCardValue))

        _ = settings.assertExactlyOne(
            .button,
            identifier: "settings.account.resetBoundary.resetButton",
            visible: true,
            hittable: true
        )
        captureStep("reset", app: app)
        settings.resetButton.tapWhenReady()
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("failed", timeout: 10))
        _ = settings.assertExactlyOne(
            .staticText,
            identifier: "settings.account.resetBoundary.message",
            visible: true
        )
        XCTAssertTrue(settings.resetMessage.label.contains("失敗") || settings.resetMessage.label.contains("殘留"))
        XCTAssertTrue(settings.resetAfterCardCount.waitUntilLabelContains(partialCardValue, timeout: 5))
        XCTAssertTrue(settings.resetAfterPreferences.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetAfterLoginStatus.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetAfterCardCount.label.contains(partialCardValue))
        XCTAssertFalse(settings.resetAfterCardCount.label.contains(beforeCardValue))
        XCTAssertEqual(settings.resetAfterPreferences.label, beforePreferencesAXLabel)
        XCTAssertEqual(settings.resetAfterLoginStatus.label, beforeLoginStatusAXLabel)

        _ = settings.assertExactlyOne(
            .button,
            identifier: "settings.account.resetBoundary.resetButton",
            visible: true,
            hittable: true
        )
        settings.resetButton.tapWhenReady()
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("succeeded", timeout: 10))
        XCTAssertTrue(settings.resetBeforeCardCount.waitUntilLabelContains(beforeCardValue, timeout: 5))
        XCTAssertTrue(settings.resetBeforePreferences.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetBeforeLoginStatus.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetAfterCardCount.waitUntilLabelContains(afterCardValue, timeout: 5))
        XCTAssertTrue(settings.resetAfterPreferences.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetAfterLoginStatus.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetBeforeCardCount.label.contains(beforeCardValue))
        XCTAssertEqual(settings.resetBeforePreferences.label, beforePreferencesAXLabel)
        XCTAssertEqual(settings.resetBeforeLoginStatus.label, beforeLoginStatusAXLabel)
        XCTAssertTrue(settings.resetAfterCardCount.label.contains(afterCardValue))
        XCTAssertFalse(settings.resetAfterPreferences.label.isEmpty)
        XCTAssertNotEqual(settings.resetAfterPreferences.label, beforePreferencesAXLabel)
        XCTAssertEqual(settings.resetAfterLoginStatus.label, beforeLoginStatusAXLabel)
        _ = settings.assertExactlyOne(.other, identifier: "settings.account.dangerGroup", visible: true)
        _ = settings.assertExactlyOne(.other, identifier: "settings.account.resetBoundary", visible: true)
        _ = settings.assertExactlyOne(.staticText, identifier: "settings.account.resetBoundary.message", visible: true)
        _ = settings.assertExactlyOne(
            .button,
            identifier: "settings.account.resetBoundary.resetButton",
            visible: true,
            hittable: false
        )
        XCTAssertFalse(settings.resetButton.isEnabled, "completed reset must not expose an enabled retry action")
        captureStep(
            "reset-counterexample",
            assetID: try SettingsFixtureManifest.evidenceAssetID(for: "reset_counterexample"),
            app: app
        )
    }
}

private enum SettingsFixtureManifest {
    private static var url: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabUITests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repo root
            .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
    }

    static func evidenceAssetID(for fixtureID: String) throws -> String {
        let seed = try settingsSeed(for: fixtureID)
        let evidence = try requiredDictionary(seed["evidence"], context: "settings.\(fixtureID).evidence")
        return try requiredString(evidence["assetID"], context: "settings.\(fixtureID).evidence.assetID")
    }

    static func authValue(fixtureID: String, key: String) throws -> String {
        let seed = try settingsSeed(for: fixtureID)
        let auth = try requiredDictionary(seed["auth"], context: "settings.\(fixtureID).auth")
        return try requiredString(auth[key], context: "settings.\(fixtureID).auth.\(key)")
    }

    static func snapshotInt(fixtureID: String, phase: String, key: String) throws -> Int {
        let snapshot = try snapshot(fixtureID: fixtureID, phase: phase)
        guard let value = snapshot[key] as? Int else {
            throw NSError(domain: "SettingsFixtureManifest", code: 3)
        }
        return value
    }

    static func snapshotBool(fixtureID: String, phase: String, key: String) throws -> Bool {
        let snapshot = try snapshot(fixtureID: fixtureID, phase: phase)
        guard let value = snapshot[key] as? Bool else {
            throw NSError(domain: "SettingsFixtureManifest", code: 4)
        }
        return value
    }

    private static func settingsSeed(for fixtureID: String) throws -> [String: Any] {
        let data = try Data(contentsOf: url)
        let root = try requiredDictionary(JSONSerialization.jsonObject(with: data), context: "UI World root")
        let settings = try requiredDictionary(root["settings"], context: "UI World settings")
        return try requiredDictionary(settings[fixtureID], context: "settings.\(fixtureID)")
    }

    private static func snapshot(fixtureID: String, phase: String) throws -> [String: Any] {
        let seed = try settingsSeed(for: fixtureID)
        let lifecycle = try requiredDictionary(seed["resetLifecycle"], context: "settings.\(fixtureID).resetLifecycle")
        return try requiredDictionary(lifecycle[phase], context: "settings.\(fixtureID).resetLifecycle.\(phase)")
    }

    private static func requiredDictionary(_ value: Any?, context: String) throws -> [String: Any] {
        guard let value = value as? [String: Any] else {
            throw NSError(domain: "SettingsFixtureManifest", code: 1, userInfo: [NSLocalizedDescriptionKey: context])
        }
        return value
    }

    private static func requiredString(_ value: Any?, context: String) throws -> String {
        guard let value = value as? String, !value.isEmpty else {
            throw NSError(domain: "SettingsFixtureManifest", code: 2, userInfo: [NSLocalizedDescriptionKey: context])
        }
        return value
    }
}
