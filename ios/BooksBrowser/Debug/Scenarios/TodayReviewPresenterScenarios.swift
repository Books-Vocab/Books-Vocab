#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Today Review surface (TodayReviewPresenter).
///
/// Drives the presenter through its session phases using the existing
/// `TodayReviewFixtureScene` harness + `TodayReviewFixtureID` recipes
/// (`TodayReviewFixtures`). No production code lifts required — the harness,
/// fixture IDs, and preview data are all internal and the fixture build is
/// fully synchronous, so the scenes can be constructed directly inside the
/// Scenario closures.
enum TodayReviewPresenterScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review Presenter") {
            // 卡片正面 — reveal stage = .front，含 first-run hint。
            Scenario("Front (card face)", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .front)
            }

            // 翻面 — reveal stage = .back，展開答案 / 釋義 / 連結群組。
            Scenario("Back (answer revealed)", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .back)
            }

            // 自動播放 — isAutoPlaying = true，已翻面狀態下的自動播放 chrome。
            Scenario("Autoplay", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .autoplay)
            }

            // 完成態 — currentCard == nil，渲染 completionState 慶祝畫面。
            Scenario("Completed", layout: .fill) {
                TodayReviewFixtureScene(fixtureID: .completed)
            }
        }
    }
}
#endif
