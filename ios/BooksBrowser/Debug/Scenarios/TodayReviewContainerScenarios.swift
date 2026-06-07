#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the FULL `TodayReviewView` container (distinct from the
/// presenter-level `TodayReviewViewScenarios`). `TodayReviewView.init` takes plain
/// arrays (no @Query) and its `.task` is local-only, so it renders safely inside a
/// Playbook scenario when wrapped in an in-memory `.modelContainer`.
///
/// The container builds `@State var state: TodayReviewState` in its initializer, so
/// it MUST be constructed inside a main-actor View `body` — hence the
/// `TodayReviewContainerScene` wrapper rather than a nonisolated helper func.
///
/// Fixtures are synthesized locally (the production preview data is `private`), so
/// no production access-level lift is required.
enum TodayReviewContainerScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Today Review Container") {
            Scenario("Session · multi-card front", layout: .fill) {
                TodayReviewContainerScene(entries: Self.sampleEntries)
            }
            Scenario("Session · single card", layout: .fill) {
                TodayReviewContainerScene(entries: [Self.sampleEntries[0]])
            }
            Scenario("Session · long content stress", layout: .fill) {
                TodayReviewContainerScene(entries: [Self.longEntry])
            }
            Scenario("Session · completed (empty queue)", layout: .fill) {
                TodayReviewContainerScene(entries: [])
            }
        }
    }

    // MARK: - Fixtures

    static let sampleEntries: [VocabularyEntry] = {
        let e1 = VocabularyEntry(
            word: "meticulous",
            translation: "一絲不苟的",
            context: "The editor was meticulous about every detail.",
            explanation: "做事非常細心、注意細節。",
            partOfSpeech: "adj.",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        e1.syncState = .synced
        e1.reviewMode = .recognition

        let e2 = VocabularyEntry(
            word: "ephemeral",
            translation: "短暫的",
            context: "Social media posts are ephemeral by nature.",
            explanation: "形容事物存在時間極短。",
            partOfSpeech: "adj.",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        e2.syncState = .synced
        e2.reviewMode = .recognition

        let e3 = VocabularyEntry(
            word: "serendipity",
            translation: "機緣巧合",
            context: "It was pure serendipity that we met at the conference.",
            explanation: "意外發現美好事物的幸運。",
            partOfSpeech: "n.",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Discovery"
        )
        e3.syncState = .synced
        e3.reviewMode = .recognition

        return [e1, e2, e3]
    }()

    static let longEntry: VocabularyEntry = {
        let e = VocabularyEntry(
            word: "circumlocution",
            translation: "迂迴冗長的說法",
            context: "Rather than answering directly, the politician resorted to circumlocution, weaving a lengthy and evasive reply that danced around the question without ever addressing the substance of what had been asked.",
            explanation: "用過多、間接的詞語來表達原本可以簡短說明的意思,常見於迴避正面回答的場合;這個解釋刻意寫得很長,用來壓力測試複習卡片在大量文字下的版面與滾動行為是否仍然穩定且易讀。",
            partOfSpeech: "n.",
            bookTitle: "The Art of Rhetoric",
            chapterTitle: "Evasion and Indirection"
        )
        e.syncState = .synced
        e.reviewMode = .recognition
        return e
    }()
}

// MARK: - Scene harness

/// Main-actor View wrapper so `TodayReviewState` (built in `TodayReviewView.init`)
/// is constructed in a main-actor-isolated `body`.
private struct TodayReviewContainerScene: View {
    let entries: [VocabularyEntry]

    var body: some View {
        AppThemeContainer {
            TodayReviewView(
                entries: entries,
                allEntries: entries,
                currentUserID: "preview-user",
                onClose: {}
            )
            .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
