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
        _driver = State(initialValue: ReviewProbeDriver(plan: plan))
    }

    var body: some View {
        Group {
            if let entries, !entries.isEmpty {
                TodayReviewView(
                    entries: entries,
                    allEntries: entries,
                    currentUserID: "review-probe",
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
