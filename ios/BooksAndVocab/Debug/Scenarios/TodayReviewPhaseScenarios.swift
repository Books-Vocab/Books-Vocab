#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `TodayReviewPhaseView` — the 4-state outer matrix
/// (loading / empty / failure / session) that wraps the TodayReview modal.
///
/// Uses the public `init(phase:onClose:)` seam plus synthetic `VocabularyEntry`
/// fixtures. The `.session` phase delegates to `TodayReviewView`, which reads
/// SwiftData via `@Query`, so that scenario is wrapped in an in-memory
/// model container (mirrors the production `#Preview`).
enum TodayReviewPhaseScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review Phase") {
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    TodayReviewPhaseView(phase: .loading, onClose: {})
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Empty", layout: .fill) {
                AppThemeContainer {
                    TodayReviewPhaseView(phase: .empty, onClose: {})
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Failure", layout: .fill) {
                AppThemeContainer {
                    TodayReviewPhaseView(phase: .failure(retry: {}), onClose: {})
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Session · single card", layout: .fill) {
                TodayReviewPhaseSessionScene(entries: TodayReviewPhaseScenarioFixtures.singleEntry)
            }

            Scenario("Session · multi card", layout: .fill) {
                TodayReviewPhaseSessionScene(entries: TodayReviewPhaseScenarioFixtures.multipleEntries)
            }

            // Long-content layout stress (migrated from the former "Today Review
            // Container" surface): one card with very long context + explanation
            // proves the review card stays readable + scrollable under heavy text.
            Scenario("Session · long content stress", layout: .fill) {
                TodayReviewPhaseSessionScene(entries: TodayReviewPhaseScenarioFixtures.longContentEntry)
            }
        }
    }
}

// MARK: - Scene harness

/// `.session` renders `TodayReviewView`, which consumes SwiftData through
/// `@Query`; a `View` body keeps construction on the main actor and supplies an
/// in-memory container so the scene renders without a live store.
private struct TodayReviewPhaseSessionScene: View {
    let entries: [VocabularyEntry]

    var body: some View {
        AppThemeContainer {
            TodayReviewPhaseView(
                phase: .session(
                    entries: entries,
                    allEntries: entries,
                    currentUserID: "preview-user"
                ),
                onClose: {}
            )
            .modelContainer(
                for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self],
                inMemory: true
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Fixtures

private enum TodayReviewPhaseScenarioFixtures {
    static var singleEntry: [VocabularyEntry] {
        [entry(
            word: "meticulous",
            translation: "一絲不苟的",
            context: "The editor was meticulous about every detail.",
            explanation: "做事非常細心、注意細節。",
            partOfSpeech: "adj.",
            book: "Designing Interfaces",
            chapter: "Writing Tone"
        )]
    }

    static var multipleEntries: [VocabularyEntry] {
        [
            entry(
                word: "serendipity",
                translation: "機緣巧合",
                context: "It was pure serendipity that we met.",
                explanation: "意外發現美好事物的能力或運氣。",
                partOfSpeech: "n.",
                book: "A Wanderer's Tale",
                chapter: "Chapter 1"
            ),
            entry(
                word: "ephemeral",
                translation: "短暫的",
                context: "Fame can be ephemeral.",
                explanation: "持續時間很短、稍縱即逝的。",
                partOfSpeech: "adj.",
                book: "On Time",
                chapter: "Fleeting"
            ),
            entry(
                word: "resilience",
                translation: "韌性",
                context: "Her resilience carried the team through.",
                explanation: "從困難中迅速恢復的能力。",
                partOfSpeech: "n.",
                book: "Grit",
                chapter: "Bounce Back"
            ),
        ]
    }

    static var longContentEntry: [VocabularyEntry] {
        [entry(
            word: "circumlocution",
            translation: "迂迴冗長的說法",
            context: "Rather than answering directly, the politician resorted to circumlocution, weaving a lengthy and evasive reply that danced around the question without ever addressing the substance of what had been asked.",
            explanation: "用過多、間接的詞語來表達原本可以簡短說明的意思,常見於迴避正面回答的場合;這個解釋刻意寫得很長,用來壓力測試複習卡片在大量文字下的版面與滾動行為是否仍然穩定且易讀。",
            partOfSpeech: "n.",
            book: "The Art of Rhetoric",
            chapter: "Evasion and Indirection"
        )]
    }

    private static func entry(
        word: String,
        translation: String,
        context: String,
        explanation: String,
        partOfSpeech: String,
        book: String,
        chapter: String
    ) -> VocabularyEntry {
        let e = VocabularyEntry(
            word: word,
            translation: translation,
            context: context,
            explanation: explanation,
            partOfSpeech: partOfSpeech,
            bookTitle: book,
            chapterTitle: chapter
        )
        e.syncState = .synced
        e.reviewMode = .recognition
        return e
    }
}
#endif
