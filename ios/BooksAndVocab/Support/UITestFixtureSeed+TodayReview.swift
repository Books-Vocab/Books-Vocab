#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    @MainActor
    static func seedTodayReview(_ id: String, into container: ModelContainer) {
        switch id {
        case "deck":
            seedReviewProbeDeck(into: container)
        default:
            AppLog.app.warning("Unknown todayReview fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedReviewProbeDeck(into container: ModelContainer) {
        let context = container.mainContext
        do {
            for entry in try context.fetch(FetchDescriptor<VocabularyEntry>()) {
                context.delete(entry)
            }
            let requested = ProcessInfo.processInfo.environment["KG_UI_TEST_REVIEW_DECK_SIZE"]
                .flatMap(Int.init) ?? 40
            let deck = makeReviewProbeDeck(size: requested)
            for entry in deck {
                context.insert(entry)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: todayReview.deck size=\(deck.count)")
        } catch {
            AppLog.app.error("Failed to seed todayReview fixture: \(error)")
        }
    }

    /// Deterministic 量測卡組。內容形狀貼近真實詞條的中等案例（譯文 + 例句 +
    /// 解釋 + 詞性），讓翻卡渲染成本有代表性；word 零填充編號使
    /// `FetchDescriptor(sortBy: word)` 的順序跨 run 穩定 — 每次量測翻的是
    /// 同一副牌、同一個順序，數字才可跨 build 比較。
    static func makeReviewProbeDeck(size: Int) -> [VocabularyEntry] {
        (1...max(size, 1)).map { i in
            let entry = VocabularyEntry(
                word: String(format: "probeword%03d", i),
                translation: "量測卡片 \(i) 的譯文，長度貼近真實詞條的中等案例。",
                context: "The probe deck keeps every card deterministic so run number \(i) stays comparable across builds.",
                explanation: "Deterministic fixture card #\(i): identical content shape across runs keeps frame-gap numbers comparable.",
                partOfSpeech: "n.",
                bookTitle: "Review Probe Fixture",
                chapterTitle: "Probe Chapter \(1 + (i - 1) / 10)"
            )
            entry.reviewMode = .recognition
            entry.syncState = .synced
            return entry
        }
    }
}
#endif
