#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Notebook → Today Review flow fixture (`-seedFixture:notebook:reviewDeck`).
    ///
    /// Seeds the UI World-owned notebook review deck so the notebook list
    /// renders a real card and the review action bar surfaces a real unlearned
    /// count. No login: today review is a fully local flow.
    @MainActor
    static func seedNotebook(_ id: String, into container: ModelContainer) {
        switch id {
        case "reviewDeck":
            seedNotebookReviewDeck(into: container)
        case "reviewDeckVaried":
            seedNotebookReviewDeckVaried(into: container)
        default:
            failFixtureSeed("Unknown notebook fixture ID: \(id)")
        }
    }

    /// Height-VARIED review deck for the flip-gap investigation
    /// (`-seedFixture:notebook:reviewDeckVaried`). Alternates SHORT recognition
    /// cards (single-line word front) with TALL production cards (long front
    /// example) so a short active card can sit in front of a taller background
    /// slot — the exact shape that reproduces "card detached from the expand
    /// zone" IF the resident-slot ZStack takes its layout height from the tallest
    /// slot (H1). The reveal→grade cycle over the same deck also exercises the
    /// answer-collapse path (H2). Reuses the reviewDeck notebookId so the notebook
    /// page object resolves the same card.
    @MainActor
    private static func seedNotebookReviewDeckVaried(into container: ModelContainer) {
        let context = container.mainContext
        let notebookId = "ui-review-notebook"
        let longExample = "The negotiator patiently coaxed every reluctant stakeholder back to the table, reframing each objection until the whole room drifted, almost imperceptibly, toward the compromise that nobody in the building had honestly believed was reachable when the morning began."
        // (word, translation, mode, tall) — tall cards render a long front example.
        let specs: [(String, String, VocabularyCardMode, Bool)] = [
            ("gapshort0", "短卡零的譯文", .recognition, false),
            ("gaptall1", "高卡一：正面帶長例句所以明顯較高", .production, true),
            ("gapshort2", "短卡二的譯文", .recognition, false),
            ("gapshort3", "短卡三的譯文", .recognition, false),
            ("gapshort4", "短卡四的譯文", .recognition, false),
            ("gaptall5", "高卡五：正面帶長例句所以明顯較高", .production, true),
            // fixedSize 多行 recognition 長片語：正面單字本身就撐到 3 行 → 比短卡高，
            // 且 fixedSize 會堅持自然高度而溢出 cap frame（不像 production 例句被截斷）
            // → 專門驗證非 active slot 的 .clipShape 有把溢出裁掉。放在 gapshort6
            // 之前（queue 依 dateAdded 遞減 → gapshort6 先 active、此片語卡落其 preview
            // 窗被 cap），確保「較高卡當被 cap 的背景」這條路徑真的被走到。
            ("a rather long recognition phrase that wraps across three lines", "多行 recognition 長片語（fixedSize 會溢出被 clip）", .recognition, false),
            ("gapshort6", "短卡六的譯文", .recognition, false)
        ]
        do {
            for notebook in try context.fetch(
                FetchDescriptor<Notebook>(predicate: #Predicate { $0.remoteId == notebookId })
            ) {
                context.delete(notebook)
            }
            try clearVocabularyEntries(from: context)

            let notebook = Notebook(remoteId: notebookId, name: "Review Gap Varied")
            notebook.syncStatus = 1
            context.insert(notebook)

            let base = Date(timeIntervalSince1970: 1_700_000_000)
            for (i, spec) in specs.enumerated() {
                let (word, translation, mode, tall) = spec
                let example = tall ? longExample : "A short \(word) example sentence."
                let entry = VocabularyEntry(
                    word: word,
                    translation: translation,
                    context: example,
                    explanation: nil,
                    partOfSpeech: "n.",
                    bookTitle: "Review Gap Fixture",
                    chapterTitle: nil
                )
                entry.notebookId = notebookId
                entry.kgCardId = "gap-\(String(format: "%03d", i))"
                entry.reviewMode = mode
                entry.reviewExamples = [example]
                entry.syncStatus = 1
                entry.actionType = "add"
                entry.reviewCount = 0
                entry.reviewStreak = 0
                entry.dateAdded = base.addingTimeInterval(Double(i))
                entry.nextReviewAt = base           // due (far in the past)
                entry.lastReviewedAt = nil
                context.insert(entry)
            }
            try context.save()
            AppLog.app.info("UI-test fixture seeded: notebook.reviewDeckVaried (\(specs.count) cards)")
        } catch {
            failFixtureSeed("Failed to seed notebook.reviewDeckVaried fixture: \(error)")
        }
    }

    @MainActor
    private static func seedNotebookReviewDeck(into container: ModelContainer) {
        let seed = FixtureDatasetStore.requireReviewDeckSeed(for: .notebookReviewDeck)
        let notebookId = seed.notebookRemoteId
        let context = container.mainContext
        do {
            // Idempotent re-seed: the simulator container persists across runs.
            for notebook in try context.fetch(
                FetchDescriptor<Notebook>(predicate: #Predicate { $0.remoteId == notebookId })
            ) {
                context.delete(notebook)
            }
            for entry in try context.fetch(FetchDescriptor<VocabularyEntry>()) {
                context.delete(entry)
            }

            let deck = try insertReviewDeckSeed(seed, into: context)
            AppLog.app.info("UI-test fixture seeded: notebook.reviewDeck (\(deck.count) cards)")
        } catch {
            failFixtureSeed("Failed to seed notebook.reviewDeck fixture: \(error)")
        }
    }
}
#endif
