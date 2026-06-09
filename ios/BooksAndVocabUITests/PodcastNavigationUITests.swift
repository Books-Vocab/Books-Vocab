//
//  PodcastNavigationUITests.swift
//  Books & Vocab UI Tests
//
//  Regression: Mac Catalyst 點 podcast 集數曾 pop-to-root 回書架。
//  根因（commit 1c5bd7d0）：BookshelfView bare `NavigationStack { }` 在
//  detailRouter.show 牽動 body 重評時整個重建、隱式 path reset → 已 push 的
//  集數列表被 pop。修法：root 改 `NavigationStack(path: $navigationPath)`。
//  本 test 在 Catalyst（regular inline 路徑）點集數後斷言集數列表「不消失」，
//  即不 pop 回書架根。需真實 container 有 podcast 資料（-ui-testing 不 reset），
//  無資料時 XCTSkip。
//

import XCTest

final class PodcastNavigationUITests: UITestCase {
    @MainActor
    func testEpisodeTapDoesNotPopToRoot() throws {
        let app = launchApp()

        // 1. podcast series 卡片：accessibilityLabel = "<title>, podcast"
        let series = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", ", podcast"))
            .firstMatch
        guard series.waitUntilExists(timeout: 15) else {
            throw XCTSkip("無 podcast 測試資料（fresh container），無法 runtime 驗證 pop-to-root")
        }
        series.tap()

        // 2. 集數列表出現（找任一集標題；測試資料含 "The Two Words That Do the Work"，
        //    用較寬鬆的關鍵字避免綁死特定 series）
        let episode = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] %@", "Two Words"))
            .firstMatch
        guard episode.waitUntilExists(timeout: 10) else {
            throw XCTSkip("集數列表未載入預期集數，跳過（資料不符）")
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
