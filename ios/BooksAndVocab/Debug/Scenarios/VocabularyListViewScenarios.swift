//
//  VocabularyListViewScenarios.swift
//  Books & Vocab
//
//  Catalog scenarios for `VocabularyListView` (a notebook's recorded vocab list).
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `VocabularyListView`.
///
/// The view is `@Query`-backed (filter `notebookId == "default"`, sort by
/// `dateAdded` reverse) and branches on `authManager.isLoggedIn`:
/// - logged out → `loggedOutState` empty card + demo CTA (the env-default
///   `AuthManager.shared` is logged out, so that path is honest by default);
/// - logged in → the real `KGVocabView` knowledge list, which itself queries
///   `knowledgeListPredicate` (syncStatus == synced, action != delete, not
///   archived).
///
/// To exercise the populated / empty *list* paths we inject a logged-in
/// `AuthManaging` mock (DEBUG-only, no production change) and seed a fresh
/// in-memory `ModelContainer` inside a `@MainActor` View body so the
/// `MainActor.assumeIsolated`-constructed env-default services (`KGService`,
/// `SubscriptionManager`, toast coordinator) resolve before `@Query` reads.
/// Catalog uses a DEBUG seam to skip non-render side effects (`healthCheck`,
/// `KGVocabView.loadInitialData`) so the full-screen surface stays deterministic
/// and does not trigger real sync/network work during snapshot runs.
enum VocabularyListViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocabulary List View") {
            Scenario("Populated · mixed sync states", layout: .fill) {
                VocabularyListViewScene(
                    entries: VocabularyListViewFixtures.populated,
                    loggedIn: true
                )
            }
            Scenario("Single card", layout: .fill) {
                VocabularyListViewScene(
                    entries: VocabularyListViewFixtures.single,
                    loggedIn: true
                )
            }
            Scenario("Long list (stress)", layout: .fill) {
                VocabularyListViewScene(
                    entries: VocabularyListViewFixtures.long,
                    loggedIn: true
                )
            }
            Scenario("Empty · zero data", layout: .fill) {
                VocabularyListViewScene(
                    entries: [],
                    loggedIn: true
                )
            }
            // Toolbar sync chrome active: a `.running` SyncCoordinator drives the
            // toolbar glyph's pulse + the pending-add fixtures drive the badge count,
            // so the web counterpart has a baseline for the "syncing · N pending"
            // toolbar state. Every other scenario injects the env-default `.ready`
            // coordinator, so this is the only one that exercises `isSyncing == true`.
            Scenario("Syncing · pending badge + active sync", layout: .fill) {
                VocabularyListViewScene(
                    entries: VocabularyListViewFixtures.syncing,
                    loggedIn: true,
                    syncPhase: .running
                )
            }
            Scenario("Logged out", layout: .fill) {
                VocabularyListViewScene(
                    entries: [],
                    loggedIn: false
                )
            }
        }
    }
}

// MARK: - Fixtures

private enum VocabularyListViewFixtures {
    static let notebookId = "default"

    /// A synced + non-archived + non-delete entry → satisfies
    /// `knowledgeListPredicate` so it renders in the knowledge list.
    static func synced(
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
        entry.notebookId = notebookId
        entry.isArchived = false
        entry.syncStatus = VocabularySyncState.synced.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        return entry
    }

    /// A pending-add entry: present in the view's `allEntries` (drives the
    /// toolbar pending badge) but filtered out of the synced knowledge list.
    static func pendingAdd(word: String, translation: String) -> VocabularyEntry {
        let entry = synced(word: word, translation: translation)
        entry.syncStatus = VocabularySyncState.pending.rawValue
        entry.actionType = VocabularySyncAction.add.rawValue
        return entry
    }

    static var single: [VocabularyEntry] {
        [synced(word: "serendipity", translation: "機緣巧合")]
    }

    static var populated: [VocabularyEntry] {
        [
            synced(word: "serendipity", translation: "機緣巧合"),
            synced(word: "ephemeral", translation: "短暫的", partOfSpeech: "adj."),
            synced(word: "petrichor", translation: "雨後泥土香"),
            synced(word: "ineffable", translation: "難以言喻的", partOfSpeech: "adj."),
            pendingAdd(word: "quintessential", translation: "典型的"),
        ]
    }

    static var long: [VocabularyEntry] {
        (1...40).map { idx in
            synced(
                word: "knowledge-word-\(idx)",
                translation: "知識單字 \(idx)",
                bookTitle: "Book \(idx % 5)"
            )
        }
    }

    /// Synced words (render in the knowledge list) plus two pending-add entries
    /// (drive the toolbar pending badge → "2"). Paired with `syncPhase: .running`
    /// in its scenario so both the badge count and the active-sync glyph render.
    static var syncing: [VocabularyEntry] {
        [
            synced(word: "serendipity", translation: "機緣巧合"),
            synced(word: "ephemeral", translation: "短暫的", partOfSpeech: "adj."),
            synced(word: "petrichor", translation: "雨後泥土香"),
            pendingAdd(word: "quintessential", translation: "典型的"),
            pendingAdd(word: "ineffable", translation: "難以言喻的"),
        ]
    }
}

// MARK: - Scene harness

/// `@MainActor` body so the in-memory container is seeded and the
/// `MainActor.assumeIsolated` env-default services resolve on the main actor
/// before `@Query` reads. Mirrors `ArchivedVocabScene`.
private struct VocabularyListViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth
    let syncCoordinator: SyncCoordinator

    init(entries: [VocabularyEntry], loggedIn: Bool, syncPhase: SyncPhase = .ready) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let context = container.mainContext

        let notebook = Notebook(remoteId: "default", name: "我的單字本", isDefault: true)
        notebook.syncStatus = 1
        context.insert(notebook)

        for entry in entries {
            context.insert(entry)
        }
        try? context.save()

        self.container = container
        self.auth = CatalogPreviewAuth(isLoggedIn: loggedIn)
        // Pin the toolbar's `isSyncing` to what the scenario declares. The env
        // default is a fresh `.ready` coordinator; setting `.phase` directly
        // (no real pipeline kicked off) renders the active-sync glyph state
        // deterministically without any network/SwiftData side effect.
        let coordinator = SyncCoordinator()
        coordinator.phase = syncPhase
        self.syncCoordinator = coordinator
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                VocabularyListView(notebookId: "default")
                    .environment(\.catalogTaskPolicy, .disabled)
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
            .environment(\.syncCoordinator, syncCoordinator)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
