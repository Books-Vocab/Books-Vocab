//
//  PodcastNavigationUITests.swift
//  Books & Vocab UI Tests
//
//  Regression: Mac Catalyst 點 podcast 集數曾 pop-to-root 回書架。
//  根因（commit 1c5bd7d0）：BookshelfView bare `NavigationStack { }` 在
//  detailRouter.show 牽動 body 重評時整個重建、隱式 path reset → 已 push 的
//  集數列表被 pop。修法：root 改 `NavigationStack(path: $navigationPath)`。
//  本 test 在 Catalyst（regular inline 路徑）點集數後斷言集數列表「不消失」，
//  即不 pop 回書架根。Podcast data 由 UI World + explicit fixture seed 提供；
//  缺資料即失敗，不允許 ambient simulator state 接管。
//

import XCTest

final class PodcastNavigationUITests: UITestCase {
    @MainActor
    func testEpisodeTapDoesNotPopToRoot() throws {
        let app = launchIsolatedApp(
            fixtures: [.podcastPlayablePreview],
            extraEnvironment: PodcastFixture.assetEnvironment.merging([
                "KG_UI_TEST_PODCAST_SERIES_TITLE": "Atomic Habits",
                "KG_UI_TEST_PODCAST_EPISODE_TITLE": "Actual Lab Episode",
                "KG_UI_TEST_PODCAST_HOST": "Lab Podcast"
            ]) { _, new in new }
        )

        // 1. podcast series 卡片：accessibilityLabel = "<title>, podcast"
        let series = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", ", podcast"))
            .firstMatch
        guard series.waitUntilExists(timeout: 15) else {
            XCTFail("UI World + podcast.playablePreview fixture should render a podcast series")
            return
        }
        series.tap()

        // 2. 集數列表出現。
        let episode = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Actual Lab Episode"))
            .firstMatch
        guard episode.waitUntilExists(timeout: 10) else {
            XCTFail("podcast.playablePreview fixture should render Actual Lab Episode")
            return
        }

        // 3. 點集數 → regular inline 走 detailRouter.show（不 push），右欄掛 player。
        episode.tap()

        // 4. 等可能的 pop-to-root 動畫，斷言集數仍在畫面。
        //    修復前：BookshelfView NavigationStack 重建 → 集數列表被 pop → episode 消失。
        //    修復後：path-bound stack 保留 path → 集數列表常駐 → episode 仍在。
        XCTAssertTrue(app.waitForNavigationToSettle(timeout: 3))
        XCTAssertTrue(
            episode.exists,
            "點集數後集數從畫面消失 → pop-to-root 回書架（path-bound 修法失效）"
        )
    }
}
