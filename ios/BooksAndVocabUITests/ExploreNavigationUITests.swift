//
//  ExploreNavigationUITests.swift
//  Books & Vocab UI Tests
//
//  Explore（共享牌組庫）頂層 tab 的導航 + a11y 可達性 smoke。第 5 個 tab
//  （KGFeatureFlags.exploreEnabled，2026-08-05 起 Release 亦開）必須：出現在 tab bar、可進入並被選中、進入後
//  section chrome（導航列「探索」）渲染。內容由 named async service fake
//  提供，成功路徑仍經 production materializer；測試驗證真實狀態與 asset proof。
//

import XCTest

final class ExploreNavigationUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        // Required-state and counterexample evidence launch several isolated
        // worlds. The allowance must be set on the test case, not only on the
        // combined helper test, because XCTest applies it per test method.
        executionTimeAllowance = 300
    }

    @MainActor
    private func openExplore(in app: XCUIApplication) -> AppPage {
        // The shared AppPage resolver has a localized/system-image fallback.
        // During back-to-back isolated launches, that fallback can resolve its
        // dynamic first match before the tab tree is complete and tap Bookshelf
        // instead. Wait for the production Explore tab identifier itself so a
        // fixture state is never asserted on the wrong section.
        let exploreTab = app.tabBars.buttons
            .matching(identifier: "tab.explore.button")
            .firstMatch
        XCTAssertTrue(
            exploreTab.waitUntilHittable(timeout: 10),
            "Explore tab must expose its exact semantic button before navigation"
        )
        exploreTab.tap()
        return AppPage(app: app)
    }


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

        _ = openExplore(in: app)
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
    private func runExploreRequiredStateFlow() throws {
        let loadingApp = launchIsolatedApp(fixtures: [.explore("loading")], perfLog: "explore-loading")
        let loading = openExplore(in: loadingApp)
        XCTAssertTrue(loading.exploreLoadingState.waitUntilExists(timeout: 5))
        loading.assertExploreElementIsUnique(identifier: "explore.loadingState")
        XCTAssertTrue(
            loading.exploreAsset(assetID: "images.explore_required").waitUntilExists(timeout: 5)
        )
        loading.assertExploreAssetIsUnique(identifier: "explore.asset.images.explore_required")
        captureStep("explore-loading", app: loadingApp)

        let loadedApp = launchIsolatedApp(fixtures: [.explore("loaded")], perfLog: "explore-loaded")
        let loaded = openExplore(in: loadedApp)
        XCTAssertTrue(loaded.exploreLoadedState.waitUntilExists(timeout: 5))
        XCTAssertTrue(loaded.exploreDeck(id: "deck_official_gre_high_freq").waitUntilExists(timeout: 5))
        loaded.assertExploreElementIsUnique(identifier: "explore.loadedState")
        loaded.assertExploreElementIsUnique(identifier: "explore.deck.deck_official_gre_high_freq")
        XCTAssertTrue(
            loaded.exploreAsset(assetID: "images.explore_required").waitUntilExists(timeout: 5)
        )
        loaded.assertExploreAssetIsUnique(identifier: "explore.asset.images.explore_required")
        captureStep("explore-loaded", app: loadedApp)

        let emptyApp = launchIsolatedApp(fixtures: [.explore("empty")], perfLog: "explore-empty")
        let empty = openExplore(in: emptyApp)
        XCTAssertTrue(empty.exploreEmptyState.waitUntilExists(timeout: 5))
        empty.assertExploreElementIsUnique(identifier: "explore.emptyState")
        captureStep("explore-empty", app: emptyApp)

        let retryApp = launchIsolatedApp(fixtures: [.explore("retry")], perfLog: "explore-retry")
        let retry = openExplore(in: retryApp)
        XCTAssertTrue(retry.exploreErrorState.waitUntilExists(timeout: 5))
        XCTAssertTrue(retry.exploreRetryButton.waitUntilExists(timeout: 5))
        retry.assertExploreElementIsUnique(identifier: "explore.errorState")
        retry.assertExploreElementIsUnique(identifier: "explore.retryButton")
        retry.exploreRetryButton.tapWhenReady()
        XCTAssertTrue(retry.exploreLoadedState.waitUntilExists(timeout: 5))
        retry.assertExploreElementIsUnique(identifier: "explore.loadedState")
        XCTAssertTrue(
            retry.exploreAsset(assetID: "images.explore_required").waitUntilExists(timeout: 5)
        )
        retry.assertExploreAssetIsUnique(identifier: "explore.asset.images.explore_required")
        captureStep("explore-retry", app: retryApp)
    }

    @MainActor
    func testExplorePartialStateUsesCachedProjectionAfterRealFailure() throws {
        let app = launchIsolatedApp(fixtures: [.explore("partial")], perfLog: "explore-partial")
        let partial = openExplore(in: app)

        XCTAssertTrue(partial.explorePartialState.waitUntilExists(timeout: 5))
        partial.assertExploreElementIsUnique(identifier: "explore.partialState")
        XCTAssertTrue(
            partial.exploreDeck(id: "deck_official_gre_high_freq").waitUntilExists(timeout: 5)
        )
        partial.assertExploreElementIsUnique(identifier: "explore.deck.deck_official_gre_high_freq")
        captureStep("explore-partial", app: app)
    }

    @MainActor
    private func runExploreCounterexampleEvidence() throws {
        let emptyApp = launchIsolatedApp(
            fixtures: [.explore("empty-counterexample")],
            perfLog: "explore-empty-counterexample"
        )
        let empty = openExplore(in: emptyApp)
        XCTAssertTrue(empty.exploreEmptyState.waitUntilExists(timeout: 5))
        XCTAssertTrue(
            empty.exploreAsset(assetID: "images.explore_counterexample_empty").waitUntilExists(timeout: 5)
        )
        empty.assertExploreElementIsUnique(identifier: "explore.emptyState")
        empty.assertExploreAssetIsUnique(identifier: "explore.asset.images.explore_counterexample_empty")
        captureStep("explore-empty-counterexample", app: emptyApp)

        let retryApp = launchIsolatedApp(
            fixtures: [.explore("retry-counterexample")],
            perfLog: "explore-retry-counterexample"
        )
        let retry = openExplore(in: retryApp)
        XCTAssertTrue(retry.exploreErrorState.waitUntilExists(timeout: 5))
        retry.assertExploreElementIsUnique(identifier: "explore.errorState")
        retry.exploreRetryButton.tapWhenReady()
        XCTAssertTrue(retry.exploreLoadedState.waitUntilExists(timeout: 5))
        XCTAssertTrue(
            retry.exploreDeck(id: "deck_counterexample_retry").waitUntilExists(timeout: 5)
        )
        XCTAssertTrue(
            retry.exploreAsset(assetID: "images.explore_counterexample_retry").waitUntilExists(timeout: 5)
        )
        retry.assertExploreElementIsUnique(identifier: "explore.loadedState")
        retry.assertExploreElementIsUnique(identifier: "explore.deck.deck_counterexample_retry")
        retry.assertExploreAssetIsUnique(identifier: "explore.asset.images.explore_counterexample_retry")
        captureStep("explore-retry-counterexample", app: retryApp)
    }

    /// Matrix evidence owns all required states and counterexamples in one bundle.
    /// The scenario helpers stay private so XCTest cannot discover and rerun them.
    @MainActor
    func testExploreEvidenceMatrixCoversRequiredAndCounterexampleStates() throws {
        // This evidence selector intentionally launches six isolated apps and
        // serializes six visual states into one immutable bundle. The default
        // one-minute allowance and the old 120s cap terminate during AX/video
        // attachment work even when every product assertion is green.
        executionTimeAllowance = 300
        try runExploreRequiredStateFlow()
        try runExploreCounterexampleEvidence()
    }

    @MainActor
    func testExploreLoadedCardExposesLongEmojiAndRTLTitleAndAssetProof() throws {
        let app = launchIsolatedApp(fixtures: [.explore("loaded")], perfLog: "explore-a11y-content")
        let loaded = openExplore(in: app)
        let card = loaded.exploreDeck(id: "deck_official_gre_high_freq")

        XCTAssertTrue(card.waitUntilExists(timeout: 5))
        loaded.assertExploreElementIsUnique(identifier: "explore.deck.deck_official_gre_high_freq")
        XCTAssertGreaterThan(card.label.count, 80)
        XCTAssertTrue(card.label.contains("🧭"))
        XCTAssertTrue(
            card.label.unicodeScalars.contains { scalar in
                (0x0590...0x08FF).contains(scalar.value)
            }
        )

        let asset = loaded.exploreAsset(assetID: "images.explore_required")
        XCTAssertTrue(asset.waitUntilExists(timeout: 5))
        loaded.assertExploreAssetIsUnique(identifier: "explore.asset.images.explore_required")
        XCTAssertEqual(asset.elementType, .other)
        XCTAssertTrue(String(describing: asset.value).contains("sha256:"))
        XCTAssertTrue(String(describing: asset.value).contains("bytes:30129"))
        XCTAssertTrue(String(describing: asset.value).contains("ExploreAssets"))
        XCTAssertEqual(
            loaded.app.buttons.matching(identifier: "explore.asset.images.explore_required").count,
            0,
            "asset evidence selector must not resolve to the card/navigation button"
        )
        captureStep("explore-a11y-content", app: app)
    }

    @MainActor
    func testExploreDetailUsesProductionCoverAssetProjection() throws {
        let app = launchIsolatedApp(fixtures: [.explore("loaded")], perfLog: "explore-detail")
        let loaded = openExplore(in: app)
        let deckID = "deck_official_gre_high_freq"

        let card = loaded.exploreDeck(id: deckID)
        XCTAssertTrue(card.waitUntilExists(timeout: 5))
        card.tapWhenReady()

        let detailCover = loaded.exploreDetailCover(deckID: deckID)
        XCTAssertTrue(detailCover.waitUntilExists(timeout: 5))
        loaded.assertExploreImageIsUnique(identifier: "explore.detail.cover.\(deckID)")
        switch detailCover.elementType {
        case .image, .other:
            break
        default:
            XCTFail("Explore detail cover must remain an image-backed semantic element, got \(detailCover.elementType)")
        }
        XCTAssertTrue(String(describing: detailCover.value).contains("sha256:"))
        XCTAssertTrue(String(describing: detailCover.value).contains("bytes:30129"))
        XCTAssertTrue(String(describing: detailCover.value).contains("ExploreAssets"))
        captureStep("explore-detail-real-cover", app: app)
    }
}
