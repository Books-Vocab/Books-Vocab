import SwiftUI
import SwiftData

/// `-reviewProbe` 啟動時的 root scene：從 live container 撈 fixture 卡組、
/// 直接掛真 `TodayReviewView`（真 state、真 submit、真 deferred flush），
/// 並把 `ReviewProbeDriver` 經 Environment 下發給 view / presenter。
///
/// 已知與真實使用的差異（量測解讀時要記得）：review 畫面直接作為 root
/// mount，而非從單字本 push/cover 進場 — 進場轉場不在量測範圍，
/// 量測對象是畫面內的 flip → settle 動態。
struct ReviewProbeScene: View {
    @Environment(\.modelContext) private var modelContext
    @State private var driver: ReviewProbeDriver
    @State private var entries: [VocabularyEntry]?

    init(plan: ReviewProbePlan) {
        let driver = ReviewProbeDriver(plan: plan)
        driver.metrics = ReviewProbeMetrics(plan: plan)
        _driver = State(initialValue: driver)
    }

    var body: some View {
        Group {
            if let entries, !entries.isEmpty {
                TodayReviewView(
                    entries: entries,
                    allEntries: entries,
                    // per-run 唯一 ID：上一次 abort 留下的 session snapshot /
                    // 洗牌順序（UserDefaults，按 userID 鍵）永遠 restore-miss，
                    // 跨 run 不互相污染（殘 key 極小，probe 裝置可忽略）。
                    currentUserID: "review-probe-\(UUID().uuidString)",
                    onClose: { driver.emit("KG_REVIEW_PROBE closed") }
                )
                .environment(\.reviewProbeDriver, driver)
            } else {
                // deck=0（fixture 未注入）時停在空畫面；driver script 以
                // deck marker 判定失敗，不靠 timeout 猜。
                Color.clear
            }
        }
        .task { loadDeck() }
    }

    private func loadDeck() {
        guard entries == nil else { return }
        let descriptor = FetchDescriptor<VocabularyEntry>(sortBy: [SortDescriptor(\.word)])
        let fetched = (try? modelContext.fetch(descriptor)) ?? []
        driver.emit("KG_REVIEW_PROBE deck=\(fetched.count)")
        entries = fetched
    }
}
