#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `WordEditSheet` — the translation / teaching-note editor
/// reached by editing a vocabulary entry.
///
/// The backing notebook and entries come from UI World `vocabulary.wordEdit`.
/// The scene inserts that seed into an in-memory SwiftData container before
/// rendering; missing seed, missing word, malformed row state, or save failure
/// all fail at catalog construction time.
enum WordEditScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Word Edit") {
            Scenario("Populated", layout: .fill) {
                WordEditScene(word: "serendipity")
            }

            Scenario("Empty explanation", layout: .fill) {
                WordEditScene(word: "ephemeral")
            }

            Scenario("Long content stress", layout: .fill) {
                WordEditScene(word: "verisimilitude")
            }

            Scenario("Long word title", layout: .fill) {
                WordEditScene(word: "antidisestablishmentarianism")
            }
        }
    }
}

// MARK: - Scene harness

private struct WordEditScene: View {
    let container: ModelContainer
    let entry: VocabularyEntry

    init(word: String) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let seed = FixtureDatasetStore.requireVocabularySeed(for: .wordEdit)
        do {
            let entries = try MainActor.assumeIsolated {
                try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
            }
            guard let entry = entries.first(where: { $0.word == word }) else {
                preconditionFailure("UI World vocabulary.wordEdit is missing entry \(word)")
            }
            self.container = container
            self.entry = entry
        } catch {
            preconditionFailure("Failed to seed UI World vocabulary.wordEdit: \(error)")
        }
    }

    var body: some View {
        AppThemeContainer {
            WordEditSheet(entry: entry)
        }
        .environmentObject(AppAppearanceStore.preview)
        .modelContainer(container)
    }
}
#endif
