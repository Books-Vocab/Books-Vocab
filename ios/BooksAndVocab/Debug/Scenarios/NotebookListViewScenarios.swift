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
/// notebook list shows deterministically, inject UI World `auth.signedIn` (the
/// list chrome + create affordance are auth-gated), and source the seeded
/// in-memory store from `NotebookFixtures` (dataset-overridable).
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
        self.container = NotebookFixtures.renderModel(for: fixture).container
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        self.auth = Self.makeAuth(from: authSeed)
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

private extension NotebookListViewScene {
    static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        guard seed.isLoggedIn else {
            preconditionFailure("UI World auth.signedIn must be logged in for NotebookListViewScenarios")
        }
        return CatalogPreviewAuth(
            isLoggedIn: seed.isLoggedIn,
            userId: seed.userId,
            token: seed.token,
            displayName: seed.displayName,
            userEmail: seed.email
        )
    }
}
#endif
