//
//  NotebookListViewScenarios.swift
//  Books & Vocab
//
//  Catalog scenarios for `NotebookListView` (the app's notebook home screen).
//

#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the full `NotebookListView` surface (單字本首頁).
///
/// `NotebookListView` is `@Query`-backed over `Notebook` + `VocabularyEntry` and
/// its `.task(id: authManager.isLoggedIn)` runs a cold-start reconcile (sync /
/// network). We disable catalog tasks through `CatalogTaskPolicy` so the seeded
/// notebook list shows deterministically, inject a logged-in `CatalogPreviewAuth`
/// (the list chrome + create affordance are auth-gated), and seed a fresh
/// in-memory store inside a `@MainActor` View body.
///
/// The zero-notebooks empty state is intentionally not catalogued here: it is
/// gated on `coordinator.hasLoadedOnce`, which only flips after the reconcile
/// task the catalog seam skips — so it cannot be reached deterministically.
enum NotebookListViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook List View") {
            Scenario("Populated · multiple notebooks", layout: .fill) {
                NotebookListViewScene(fixture: .populated)
            }
            Scenario("Single notebook", layout: .fill) {
                NotebookListViewScene(fixture: .single)
            }
        }
    }
}

// MARK: - Fixtures

private enum NotebookListFixture {
    case populated
    case single
}

// MARK: - Scene harness

private struct NotebookListViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth

    init(fixture: NotebookListFixture) {
        let container = try! ModelContainer(
            for: Notebook.self, VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        Self.seed(fixture, into: container.mainContext)
        try? container.mainContext.save()
        self.container = container
        self.auth = CatalogPreviewAuth(isLoggedIn: true)
    }

    var body: some View {
        AppThemeContainer {
            NotebookListView()
                .modelContainer(container)
                .environment(\.authManager, auth)
                .environment(\.catalogTaskPolicy, .disabled)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Seeding

    private static func notebook(_ remoteId: String, _ name: String, order: Int, isDefault: Bool = false) -> Notebook {
        let nb = Notebook(remoteId: remoteId, name: name, isDefault: isDefault)
        nb.sortOrder = order
        nb.syncStatus = 1
        return nb
    }

    private static func entry(_ word: String, _ translation: String, notebookId: String) -> VocabularyEntry {
        let e = VocabularyEntry(
            word: word,
            translation: translation,
            context: "A sentence using \(word).",
            explanation: "A short gloss for \(word).",
            partOfSpeech: "n.",
            bookTitle: "Sample Book",
            chapterTitle: "第一章"
        )
        e.notebookId = notebookId
        e.isArchived = false
        e.syncStatus = VocabularySyncState.synced.rawValue
        e.actionType = VocabularySyncAction.add.rawValue
        return e
    }

    private static func seed(_ fixture: NotebookListFixture, into context: ModelContext) {
        let defaultNb = notebook("default", "我的單字本", order: 0, isDefault: true)
        context.insert(defaultNb)
        context.insert(entry("serendipity", "機緣巧合", notebookId: "default"))
        context.insert(entry("ephemeral", "短暫的", notebookId: "default"))
        context.insert(entry("petrichor", "雨後泥土香", notebookId: "default"))

        guard fixture == .populated else { return }

        let classics = notebook("nb-classics", "經典文學", order: 1)
        context.insert(classics)
        context.insert(entry("melancholy", "憂鬱", notebookId: "nb-classics"))
        context.insert(entry("sublime", "崇高的", notebookId: "nb-classics"))

        let science = notebook("nb-science", "科普閱讀", order: 2)
        context.insert(science)
        context.insert(entry("entropy", "熵", notebookId: "nb-science"))
    }
}
#endif
