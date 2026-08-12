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

        captureStep(
            "required-settings",
            assetID: try SettingsFixtureManifest.evidenceAssetID(for: "preferences_auto_sync_off"),
            app: app
        )
        for group in [
            settings.appearanceGroup,
            settings.learningGroup,
            settings.feedbackGroup,
            settings.readerGroup,
        ] {
            XCTAssertTrue(group.waitUntilExists(timeout: 5), "Settings section group must expose a stable accessibility identifier")
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

        try step("feedback-preferences-toggle", app: app) {
            guard settings.soundFeedbackToggle.waitUntilExists(timeout: 5),
                  settings.hapticFeedbackToggle.waitUntilExists(timeout: 5) else {
                captureStep("no-feedback-toggles", app: app)
                XCTFail("settings home must expose sound and haptic feedback toggles")
                return
            }

            settings.soundFeedbackToggle.scrollIntoView()
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
        XCTAssertTrue(settings.logoutButton.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.conditionalSyncGroup.waitUntilExists(timeout: 5))

        settings.openAccountDetail()
        XCTAssertTrue(app.waitForNavigationToSettle())
        XCTAssertTrue(settings.accountDangerGroup.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetBoundary.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("preReset", timeout: 5))
        XCTAssertTrue(settings.accountScrollView.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.accountNameValue.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.accountEmailValue.waitUntilExists(timeout: 5))

        for (element, expected) in [
            (settings.accountNameValue, longDisplayName),
            (settings.accountEmailValue, longEmail),
        ] {
            element.scrollIntoView()
            XCTAssertEqual(element.label, expected, "long account value must remain fully visible")
            XCTAssertTrue(
                settings.accountScrollView.frame.intersects(element.frame),
                "long account value must remain inside the scrollable account content"
            )
        }

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
        let beforeCardLabel = "\(beforeCardCount) 張"
        let beforePreferencesLabel = beforeHasCustomPreferences ? "已自訂" : "預設值"
        let beforeLoginLabel = beforeIsLoggedIn ? "已登入" : "未登入"
        let afterCardLabel = "\(afterCardCount) 張"
        let afterPreferencesLabel = afterHasCustomPreferences ? "已自訂" : "預設值"
        let afterLoginLabel = afterIsLoggedIn ? "已登入" : "未登入"
        let app = launchIsolatedApp(
            fixtures: [.settingsResetLifecycle],
            extraEnvironment: ["KG_UI_TEST_SETTINGS_RESET_FAIL_ONCE": "1"],
            perfLog: "settings-reset-counterexample"
        )
        let bookshelf = AppPage(app: app).goToBookshelf()
        XCTAssertTrue(app.waitForNavigationToSettle())

        let settings = bookshelf.tapSettings()
        settings.assertIsPresented()
        XCTAssertTrue(settings.logoutButton.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.conditionalSyncGroup.waitUntilExists(timeout: 5))

        settings.openAccountDetail()
        XCTAssertTrue(app.waitForNavigationToSettle())
        XCTAssertTrue(settings.accountDangerGroup.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetBoundary.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetBeforeSnapshot.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetAfterSnapshot.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("preReset", timeout: 5))
        XCTAssertTrue(settings.resetBeforeCardCount.waitUntilLabelContains(beforeCardLabel, timeout: 5))
        XCTAssertTrue(settings.resetBeforePreferences.waitUntilLabelContains(beforePreferencesLabel, timeout: 5))
        XCTAssertTrue(settings.resetBeforeLoginStatus.waitUntilLabelContains(beforeLoginLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterCardCount.waitUntilLabelContains(beforeCardLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterPreferences.waitUntilLabelContains(beforePreferencesLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterLoginStatus.waitUntilLabelContains(beforeLoginLabel, timeout: 5))
        XCTAssertEqual(settings.resetBeforeCardCount.label, beforeCardLabel)
        XCTAssertEqual(settings.resetBeforePreferences.label, beforePreferencesLabel)
        XCTAssertEqual(settings.resetBeforeLoginStatus.label, beforeLoginLabel)
        XCTAssertEqual(settings.resetAfterCardCount.label, beforeCardLabel)
        XCTAssertEqual(settings.resetAfterPreferences.label, beforePreferencesLabel)
        XCTAssertEqual(settings.resetAfterLoginStatus.label, beforeLoginLabel)

        settings.resetButton.tapWhenReady()
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("failed", timeout: 10))
        XCTAssertTrue(settings.resetAfterCardCount.waitUntilLabelContains(beforeCardLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterPreferences.waitUntilLabelContains(beforePreferencesLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterLoginStatus.waitUntilLabelContains(beforeLoginLabel, timeout: 5))
        XCTAssertEqual(settings.resetAfterCardCount.label, beforeCardLabel)
        XCTAssertEqual(settings.resetAfterPreferences.label, beforePreferencesLabel)
        XCTAssertEqual(settings.resetAfterLoginStatus.label, beforeLoginLabel)

        settings.resetButton.tapWhenReady()
        XCTAssertTrue(settings.resetPhase.waitUntilValueEquals("succeeded", timeout: 10))
        XCTAssertTrue(settings.resetBeforeCardCount.waitUntilLabelContains(beforeCardLabel, timeout: 5))
        XCTAssertTrue(settings.resetBeforePreferences.waitUntilLabelContains(beforePreferencesLabel, timeout: 5))
        XCTAssertTrue(settings.resetBeforeLoginStatus.waitUntilLabelContains(beforeLoginLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterCardCount.waitUntilLabelContains(afterCardLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterPreferences.waitUntilLabelContains(afterPreferencesLabel, timeout: 5))
        XCTAssertTrue(settings.resetAfterLoginStatus.waitUntilLabelContains(afterLoginLabel, timeout: 5))
        XCTAssertEqual(settings.resetBeforeCardCount.label, beforeCardLabel)
        XCTAssertEqual(settings.resetBeforePreferences.label, beforePreferencesLabel)
        XCTAssertEqual(settings.resetBeforeLoginStatus.label, beforeLoginLabel)
        XCTAssertEqual(settings.resetAfterCardCount.label, afterCardLabel)
        XCTAssertEqual(settings.resetAfterPreferences.label, afterPreferencesLabel)
        XCTAssertEqual(settings.resetAfterLoginStatus.label, afterLoginLabel)
        XCTAssertTrue(settings.accountDangerGroup.waitUntilExists(timeout: 5))
        XCTAssertTrue(settings.resetBoundary.waitUntilExists(timeout: 5))
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
