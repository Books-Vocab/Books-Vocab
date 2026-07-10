//
//  ExploreNavigationUITests.swift
//  Books & Vocab UI Tests
//
//  Explore（共享牌組庫）頂層 tab 的導航 + a11y 可達性 smoke。第 5 個 DEBUG-gated
//  tab（KGFeatureFlags.exploreEnabled）必須：出現在 tab bar、可進入並被選中、進入後
//  section chrome（導航列「探索」）渲染。內容依賴目錄同步（UI-test dummy 伺服器 →
//  空/錯誤態），故此測只驗導航可達 + a11y 骨架，不斷言牌組內容。
//

import XCTest

final class ExploreNavigationUITests: UITestCase {

    @MainActor
    func testExploreTabIsReachableAndRendersSection() throws {
        let app = launchIsolatedApp(fixtures: [.shellNavigation], perfLog: "explore")
        captureStep("launch", app: app)

        let shell = AppPage(app: app)
        try step("explore-tab-visible", app: app) {
            XCTAssertTrue(
                shell.exploreTab.waitForExistence(timeout: 10),
                "Explore tab (探索) should be visible in a DEBUG build (exploreEnabled == true)"
            )
        }

        shell.goToExplore()
        try step("explore-section", app: app) {
            XCTAssertTrue(shell.exploreTab.isSelected, "探索 tab did not become selected after tap")
            shell.assertNavigationChrome(on: "explore")
            XCTAssertTrue(
                app.navigationBars["探索"].waitForExistence(timeout: 5),
                "Explore section navigation title 探索 should render (VoiceOver-reachable heading)"
            )
        }
    }
}
