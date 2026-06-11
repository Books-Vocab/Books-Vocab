//
//  KGVocabSearchScenarios.swift
//  Books & Vocab
//
//  Catalog scenarios for `KGVocabView` driven into its active-search state.
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `KGVocabView` (the knowledge-list presenter host) with a
/// **non-empty search query** bound.
///
/// 為什麼補:`VocabularyListView` owns `searchText` as internal `@State` and only
/// flips it via a 300ms debounce `.task` that snapshot runs can't reliably await —
/// so the parent-screen scenarios never reach the live searched list. Hosting
/// `KGVocabView` directly with a literal `searchText` binding is the only way to
/// snapshot the *searched* surface: query-filtered rows, the chip+sort bar under
/// an active query, and the in-list "no match" empty state (distinct from the
/// `KGVocabEmptyState` copy-resolver scenarios, which render the empty card in
/// isolation rather than inside the live scene shell).
///
/// `KGVocabView` is never presented standalone in production — `VocabularyListView`
/// renders it — so per the `CatalogScene` taxonomy note it is catalogued as an
/// engineering surface ("KG Vocab Presenter") backed by `KGVocabView`, not a
/// `featureScreen`. We inject a logged-in `CatalogPreviewAuth`, seed a fresh
/// in-memory store inside a `@MainActor` View body, and disable catalog tasks so
/// `loadInitialData` (sync/network) never fires.
enum KGVocabSearchScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "KG Vocab Presenter") {
            // Query matches a subset of the seeded list → filtered rows + the
            // chip/sort bar render under an active query.
            Scenario("Search · matches", layout: .fill) {
                KGVocabSearchScene(query: "ous")
            }
            // Single exact-ish match → narrowest non-empty searched list.
            Scenario("Search · single match", layout: .fill) {
                KGVocabSearchScene(query: "serendipity")
            }
            // Query matches nothing in the seeded list → the in-scene "no match"
            // empty state (no CTA, since searchText is non-empty).
            Scenario("Search · no match", layout: .fill) {
                KGVocabSearchScene(query: "zzzznotaword")
            }
        }
    }
}

// MARK: - Fixtures

private enum KGVocabSearchFixtures {
    static let notebookId = "default"

    /// A synced + non-archived + non-delete entry → satisfies
    /// `knowledgeListPredicate`, so it renders in the knowledge list.
    static func synced(
        word: String,
        translation: String,
        partOfSpeech: String? = "n."
    ) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: translation,
            context: "It was pure \(word) — the moment lingered in memory.",
            explanation: "A short AI-style contextual gloss for \(word).",
            partOfSpeech: partOfSpeech,
            bookTitle: "Sample Book",
            chapterTitle: "第一章"
        )
        entry.notebookId = notebookId
        entry.isArchived = false
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        return entry
    }

    /// A realistic notebook of synced words. "ous" matches `meticulous`,
    /// `ingenious`, `tenacious`; "serendipity" matches exactly one.
    static var library: [VocabularyEntry] {
        [
            synced(word: "serendipity", translation: "機緣巧合"),
            synced(word: "meticulous", translation: "一絲不苟的", partOfSpeech: "adj."),
            synced(word: "ingenious", translation: "巧妙的；獨創的", partOfSpeech: "adj."),
            synced(word: "tenacious", translation: "堅韌不拔的", partOfSpeech: "adj."),
            synced(word: "ephemeral", translation: "短暫的", partOfSpeech: "adj."),
            synced(word: "petrichor", translation: "雨後泥土香"),
            synced(word: "nuance", translation: "細微差異"),
        ]
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and the
/// `MainActor.assumeIsolated` env-default services resolve on the main actor
/// before `@Query` reads. `searchText` is a fixed constant binding so the
/// searched surface renders deterministically (no debounce / parent state).
private struct KGVocabSearchScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let query: String

    init(query: String) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext

        let notebook = Notebook(remoteId: "default", name: "我的單字本", isDefault: true)
        notebook.syncStatus = 1
        context.insert(notebook)

        for entry in KGVocabSearchFixtures.library {
            context.insert(entry)
        }
        try? context.save()

        self.container = container
        self.auth = CatalogPreviewAuth(isLoggedIn: true)
        self.query = query
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                KGVocabView(searchText: .constant(query), notebookId: "default")
                    .environment(\.catalogTaskPolicy, .disabled)
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
