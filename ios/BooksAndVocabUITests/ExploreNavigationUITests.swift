//
//  ExploreNavigationUITests.swift
//  Books & Vocab UI Tests
//
//  Explore（共享牌組庫）頂層 tab 的導航 + a11y 可達性 smoke。第 5 個 tab
//  （KGFeatureFlags.exploreEnabled，2026-08-05 起 Release 亦開）必須：出現在 tab bar、可進入並被選中、進入後
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
                "Explore tab (探索) should be visible whenever exploreEnabled == true"
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

    @MainActor
    func testExploreRequiredStateFlowProducesSeparateEvidenceSteps() throws {
        let loadingApp = launchIsolatedApp(fixtures: [.explore("loading")], perfLog: "explore-loading")
        let loading = AppPage(app: loadingApp).goToExplore()
        XCTAssertTrue(loading.exploreLoadingState.waitUntilExists(timeout: 5))
        captureStep("explore-loading", app: loadingApp)

        let loadedApp = launchIsolatedApp(fixtures: [.explore("loaded")], perfLog: "explore-loaded")
        let loaded = AppPage(app: loadedApp).goToExplore()
        XCTAssertTrue(loaded.exploreLoadedState.waitUntilExists(timeout: 5))
        XCTAssertTrue(loaded.exploreDeck(id: "deck_official_gre_high_freq").waitUntilExists(timeout: 5))
        XCTAssertTrue(
            loaded.exploreAsset(assetID: "images.explore_required").waitUntilExists(timeout: 5)
        )
        captureStep("explore-loaded", app: loadedApp)

        let emptyApp = launchIsolatedApp(fixtures: [.explore("empty")], perfLog: "explore-empty")
        let empty = AppPage(app: emptyApp).goToExplore()
        XCTAssertTrue(empty.exploreEmptyState.waitUntilExists(timeout: 5))
        captureStep("explore-empty", app: emptyApp)

        let retryApp = launchIsolatedApp(fixtures: [.explore("retry")], perfLog: "explore-retry")
        let retry = AppPage(app: retryApp).goToExplore()
        XCTAssertTrue(retry.exploreErrorState.waitUntilExists(timeout: 5))
        XCTAssertTrue(retry.exploreRetryButton.waitUntilExists(timeout: 5))
        retry.exploreRetryButton.tapWhenReady()
        XCTAssertTrue(retry.exploreLoadedState.waitUntilExists(timeout: 5))
        XCTAssertTrue(
            retry.exploreAsset(assetID: "images.explore_required").waitUntilExists(timeout: 5)
        )
        captureStep("explore-retry", app: retryApp)
    }

    @MainActor
    func testExploreCounterexampleEvidenceUsesDistinctAssets() throws {
        let emptyApp = launchIsolatedApp(
            fixtures: [.explore("empty-counterexample")],
            perfLog: "explore-empty-counterexample"
        )
        let empty = AppPage(app: emptyApp).goToExplore()
        XCTAssertTrue(empty.exploreEmptyState.waitUntilExists(timeout: 5))
        XCTAssertTrue(
            empty.exploreAsset(assetID: "images.explore_counterexample_empty").waitUntilExists(timeout: 5)
        )
        captureStep("explore-empty-counterexample", app: emptyApp)

        let retryApp = launchIsolatedApp(
            fixtures: [.explore("retry-counterexample")],
            perfLog: "explore-retry-counterexample"
        )
        let retry = AppPage(app: retryApp).goToExplore()
        XCTAssertTrue(retry.exploreErrorState.waitUntilExists(timeout: 5))
        retry.exploreRetryButton.tapWhenReady()
        XCTAssertTrue(retry.exploreLoadedState.waitUntilExists(timeout: 5))
        XCTAssertTrue(
            retry.exploreDeck(id: "deck_counterexample_retry").waitUntilExists(timeout: 5)
        )
        XCTAssertTrue(
            retry.exploreAsset(assetID: "images.explore_counterexample_retry").waitUntilExists(timeout: 5)
        )
        captureStep("explore-retry-counterexample", app: retryApp)
    }
}
