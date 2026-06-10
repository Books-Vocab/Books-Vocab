//
//  AuthFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Auth 狀態機 UI flow（登入閘門 / 訪客分層 UX）— 真資料 + 視覺證據。
//  不測真 SSO（Apple/Google 外部流程不可自動化）；測的是閘門行為本身：
//  訪客 tap 鎖定內容 → LoginSheet 真的彈出且不進 player；已登入 fixture
//  絕不出現 login gate；Settings 帳號區隨登入/登出真實翻轉。
//  Fixture: `-seedFixture:auth:tieredCatalog`（真 lab 音訊/字幕的 podcast
//  catalog，不登入）+ `-seedFixture:auth:signedIn`（isolated auth session
//  內注入已登入 session）。
//

import XCTest

final class AuthFlowUITests: UITestCase {
    private static let seriesCardID = "podcast.series.ui-auth-series"
    private static let episode1RowID = "podcast.episode.ui-auth-series_ep_01"
    private static let episode2RowID = "podcast.episode.ui-auth-series_ep_02"
    private static let podcastFixtureRoot =
        "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts"

    private static let fixtureEnvironment: [String: String] = [
        "KG_UI_TEST_PODCAST_AUDIO": "\(podcastFixtureRoot)/ep_1_flash.m4a",
        "KG_UI_TEST_PODCAST_SUBTITLE": "\(podcastFixtureRoot)/ep_1_flash.srt",
        "KG_UI_TEST_PODCAST_DURATION": "1034.6"
    ]

    // MARK: - 訪客態：閘門行為

    @MainActor
    func testGuestGateLocksPodcastAndRoutesEntryPointsToLoginSheet() throws {
        let app = launchIsolatedApp(
            fixtures: [.authTieredCatalog],
            extraEnvironment: Self.fixtureEnvironment,
            perfLog: "auth"
        )
        captureStep("guest-launch", app: app)

        let auth = AuthPage(app: app)
        let podcast = PodcastPage(app: app)

        // 1. 書架空狀態的登入 entry point（訪客可見）。
        try step("guest-bookshelf-login-entry", app: app) {
            AppPage(app: app).goToBookshelf()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard auth.bookshelfLoginEntry.waitUntilExists(timeout: 10) else {
                captureStep("no-bookshelf-login-entry", app: app)
                XCTFail("訪客 + 空書架必須出現「登入帳號」entry point（fixture 已清空書架）")
                return
            }
        }

        // 2. tap entry → LoginSheet 真的彈出，且可取消回到原畫面。
        try step("guest-bookshelf-login-sheet", app: app) {
            auth.bookshelfLoginEntry.tapWhenReady()
            auth.assertLoginSheetPresented()
        }
        try step("guest-bookshelf-login-sheet-dismissed", app: app) {
            auth.cancelLoginSheet()
            auth.assertLoginSheetGone()
        }

        // 3. 訪客可瀏覽 podcast catalog（browse 不被閘門擋）。
        try step("guest-podcast-catalog", app: app) {
            AppPage(app: app).goToPodcasts()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard podcast.seriesCard(id: "ui-auth-series").waitUntilExists(timeout: 15) else {
                captureStep("no-series-card", app: app)
                XCTFail("auth tieredCatalog fixture 未種出 series — 訪客瀏覽前提不成立")
                return
            }
        }
        try step("guest-episode-list", app: app) {
            podcast.seriesCard(id: "ui-auth-series").tapWhenReady()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard episodeRow(Self.episode1RowID, in: app).waitUntilExists(timeout: 10) else {
                captureStep("no-episode-row", app: app)
                XCTFail("episode list 未顯示 fixture 集數")
                return
            }
        }

        // 4. 訪客 tap 集數（含 preview 集）→ LoginSheet 彈出、絕不進 player。
        try step("guest-episode1-gated", app: app) {
            episodeRow(Self.episode1RowID, in: app).tapWhenReady()
            auth.assertLoginSheetPresented()
            assertPlayerNotEntered(podcast: podcast, app: app)
        }
        try step("guest-episode1-gate-dismissed", app: app) {
            auth.cancelLoginSheet()
            auth.assertLoginSheetGone()
            assertPlayerNotEntered(podcast: podcast, app: app)
        }
        try step("guest-episode2-gated", app: app) {
            episodeRow(Self.episode2RowID, in: app).tapWhenReady()
            auth.assertLoginSheetPresented()
            assertPlayerNotEntered(podcast: podcast, app: app)
        }
        try step("guest-episode2-gate-dismissed", app: app) {
            auth.cancelLoginSheet()
            auth.assertLoginSheetGone()
            episodeRow(Self.episode2RowID, in: app).assertExists(
                timeout: 5
            )
        }
    }

    // MARK: - 已登入態：閘門不出現 + 登出回訪客

    @MainActor
    func testSignedInSessionHidesLoginGateAndLogoutRestoresGuest() throws {
        let app = launchIsolatedApp(
            fixtures: [.authTieredCatalog, .authSignedIn],
            extraEnvironment: Self.fixtureEnvironment,
            perfLog: "auth"
        )
        captureStep("signedin-launch", app: app)

        let auth = AuthPage(app: app)
        let podcast = PodcastPage(app: app)

        // 1. 已登入：書架空狀態不得出現登入 entry point。
        try step("signedin-bookshelf-no-login-entry", app: app) {
            let bookshelf = AppPage(app: app).goToBookshelf()
            XCTAssertTrue(app.waitForNavigationToSettle())
            bookshelf.assertIsActive()
            if auth.bookshelfLoginEntry.waitUntilExists(timeout: 2) {
                captureStep("unexpected-bookshelf-login-entry", app: app)
                XCTFail("signedIn fixture 不該在書架看到登入 entry — fixture 沒有真的登入")
                return
            }
        }

        // 2. free tier tap preview 集 → 直接進 player，login gate 不得出現。
        try step("signedin-episode1-opens-player", app: app) {
            AppPage(app: app).goToPodcasts()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard podcast.seriesCard(id: "ui-auth-series").waitUntilExists(timeout: 15) else {
                captureStep("no-series-card", app: app)
                XCTFail("auth tieredCatalog fixture 未種出 series")
                return
            }
            podcast.seriesCard(id: "ui-auth-series").tapWhenReady()
            XCTAssertTrue(app.waitForNavigationToSettle())
            episodeRow(Self.episode1RowID, in: app).tapWhenReady(timeout: 10)
            XCTAssertTrue(app.waitForNavigationToSettle())
        }
        if auth.loginSheet.waitUntilExists(timeout: 1) {
            captureStep("unexpected-login-sheet", app: app)
            XCTFail("已登入 fixture 不得彈出 LoginSheet — 閘門誤判訪客")
            return
        }
        if podcast.playerLoginGate.waitUntilExists(timeout: 1) {
            captureStep("unexpected-player-login-gate", app: app)
            XCTFail("已登入 fixture 不得出現 player login gate")
            return
        }
        guard podcast.playPauseButton.waitUntilExists(timeout: 10) else {
            captureStep("player-not-playable", app: app)
            XCTFail("已登入 free tier 應進入可播放 player（preview 集）")
            return
        }
        captureStep("signedin-player-ready", app: app)

        // 全螢幕 player 蓋住 tab bar — 先退回 episode list 才能切 tab。
        try step("signedin-player-back", app: app) {
            app.navigationBars.buttons.firstMatch.tapWhenReady()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }

        // 3. Settings 顯示帳號區（logged-in panel + 登出按鈕）。
        try step("signedin-settings-account", app: app) {
            AppPage(app: app).goToBookshelf()
            XCTAssertTrue(app.waitForNavigationToSettle())
            BookshelfPage(app: app).tapSettings()
            guard auth.settingsLoggedInPanel.waitUntilExists(timeout: 10) else {
                captureStep("no-logged-in-panel", app: app)
                XCTFail("已登入時 Settings 帳號區必須顯示 logged-in panel")
                return
            }
            auth.settingsLogoutButton.assertExists(timeout: 5)
        }

        // 4. 登出 → 帳號區翻回訪客 panel（auth 狀態機真實切換）。
        try step("signedin-logout", app: app) {
            auth.settingsLogoutButton.tapWhenReady()
            guard auth.settingsLoginPanel.waitUntilExists(timeout: 10) else {
                captureStep("no-login-panel-after-logout", app: app)
                XCTFail("登出後 Settings 帳號區必須翻回訪客 login panel")
                return
            }
            auth.settingsLoggedInPanel.assertDoesNotExist(timeout: 5)
        }

        // 5. 關閉 Settings → 書架重新出現訪客登入 entry point。
        try step("guest-restored-after-logout", app: app) {
            SettingsSheetPage(app: app).dismiss()
            guard auth.bookshelfLoginEntry.waitUntilExists(timeout: 10) else {
                captureStep("no-login-entry-after-logout", app: app)
                XCTFail("登出後書架空狀態必須恢復訪客登入 entry point")
                return
            }
        }
    }

    // MARK: - Helpers

    private func episodeRow(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    /// 閘門守門斷言：鎖定列 tap 後絕不進 player。
    private func assertPlayerNotEntered(
        podcast: PodcastPage,
        app: XCUIApplication,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        if podcast.playPauseButton.exists || podcast.playerSettingsButton.exists {
            captureStep("unexpected-player-entry", app: app)
            XCTFail("訪客 tap 鎖定集數後不得進入 player", file: file, line: line)
        }
    }
}
