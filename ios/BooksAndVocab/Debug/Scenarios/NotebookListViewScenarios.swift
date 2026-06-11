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

// MARK: - Scene harness

private struct NotebookListViewScene: View {
    let container: ModelContainer
    let auth: CatalogPreviewAuth

    init(fixture: NotebookFixtureID) {
        container = NotebookFixtures.renderModel(for: fixture).container ?? (try! ModelContainer(
            for: Notebook.self, VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        ))
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

}
#endif
