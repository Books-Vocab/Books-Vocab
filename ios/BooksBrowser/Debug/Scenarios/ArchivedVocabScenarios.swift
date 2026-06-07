#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `ArchivedVocabSheet`.
///
/// The sheet is `@Query`-backed (filter `isArchived == true`, further narrowed
/// at runtime by `shouldAppearInArchiveList`, i.e. `isSynced && action != .delete
/// && isArchived`). Each scenario seeds a fresh in-memory `ModelContainer` with
/// synthetic archived entries (or none, for the empty state) inside a
/// `@MainActor` View body so the env-default services (`KGService`, toast
/// coordinator — all `MainActor.assumeIsolated` constructed) resolve safely.
enum ArchivedVocabScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Archived Vocab") {
            Scenario("Populated", layout: .fill) {
                ArchivedVocabScene(entries: ArchivedVocabFixtures.populated)
            }
            Scenario("Single card", layout: .fill) {
                ArchivedVocabScene(entries: ArchivedVocabFixtures.single)
            }
            Scenario("Long list (stress)", layout: .fill) {
                ArchivedVocabScene(entries: ArchivedVocabFixtures.long)
            }
            Scenario("Empty", layout: .fill) {
                ArchivedVocabScene(entries: [])
            }
        }
    }
}

// MARK: - Fixtures

private enum ArchivedVocabFixtures {
    /// Builds a synced + archived entry (satisfies `shouldAppearInArchiveList`).
    static func archived(
        word: String,
        translation: String,
        explanation: String? = nil,
        partOfSpeech: String? = "n.",
        bookTitle: String = "Sample Book",
        chapterTitle: String? = "第一章"
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: translation,
            context: "It was pure \(word) — the moment lingered in memory.",
            explanation: explanation ?? "A short AI-style contextual gloss for \(word).",
            partOfSpeech: partOfSpeech,
            bookTitle: bookTitle,
            chapterTitle: chapterTitle
        )
        entry.isArchived = true
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        return entry
    }

    static var single: [VocabularyEntry] {
        [archived(word: "serendipity", translation: "機緣巧合")]
    }

    static var populated: [VocabularyEntry] {
        [
            archived(word: "serendipity", translation: "機緣巧合"),
            archived(word: "ephemeral", translation: "短暫的", partOfSpeech: "adj."),
            archived(word: "petrichor", translation: "雨後泥土香"),
            archived(word: "ineffable", translation: "難以言喻的", partOfSpeech: "adj."),
            archived(word: "quintessential", translation: "典型的", partOfSpeech: "adj."),
        ]
    }

    static var long: [VocabularyEntry] {
        (1...40).map { idx in
            archived(
                word: "archived-word-\(idx)",
                translation: "封存單字 \(idx)",
                bookTitle: "Book \(idx % 5)"
            )
        }
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and env-default
/// services resolve on the main actor before `@Query` reads.
private struct ArchivedVocabScene: View {
    let container: ModelContainer

    init(entries: [VocabularyEntry]) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext
        for entry in entries {
            context.insert(entry)
        }
        try? context.save()
        self.container = container
    }

    var body: some View {
        AppThemeContainer {
            ArchivedVocabSheet()
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
