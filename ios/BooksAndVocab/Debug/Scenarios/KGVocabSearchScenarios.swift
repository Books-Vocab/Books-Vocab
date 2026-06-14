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
/// `featureScreen`. Auth comes from UI World `auth.signedIn`; vocabulary rows
/// come from UI World `vocabulary.searchVocabNotebook` and are materialized into
/// SwiftData before rendering. Missing seed, malformed auth, query drift, or
/// SwiftData seed failure all fail at catalog construction time.
enum KGVocabSearchScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "KG Vocab Presenter") {
            // Query matches a subset of the seeded list → filtered rows + the
            // chip/sort bar render under an active query.
            Scenario("Search · matches", layout: .fill) {
                KGVocabSearchScene(query: "影響", expectedMatches: .multiple)
            }
            // Single exact-ish match → narrowest non-empty searched list.
            Scenario("Search · single match", layout: .fill) {
                KGVocabSearchScene(query: "ambiguous", expectedMatches: .exactly(1))
            }
            // Query matches nothing in the seeded list → the in-scene "no match"
            // empty state (no CTA, since searchText is non-empty).
            Scenario("Search · no match", layout: .fill) {
                KGVocabSearchScene(query: "zzzznotaword", expectedMatches: .exactly(0))
            }
        }
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
    let notebookId: String
    let query: String

    init(query: String, expectedMatches: ExpectedMatches) {
        let container = try! ModelContainer(
            for: VocabularyEntry.self, Notebook.self, ReviewRecord.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        let seed = FixtureDatasetStore.requireVocabularySeed(for: .searchVocabNotebook)
        let authSeed = FixtureDatasetStore.requireAuthSeed(for: .signedIn)
        do {
            let entries = try MainActor.assumeIsolated {
                try UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)
            }
            let matchCount = entries.filter {
                $0.word.localizedCaseInsensitiveContains(query) ||
                    $0.translation.localizedCaseInsensitiveContains(query)
            }.count
            switch expectedMatches {
            case .multiple:
                guard matchCount > 1 else {
                    preconditionFailure("UI World vocabulary.searchVocabNotebook query \(query) must match multiple entries, got \(matchCount)")
                }
            case .exactly(let expected):
                guard matchCount == expected else {
                    preconditionFailure("UI World vocabulary.searchVocabNotebook query \(query) must match \(expected) entries, got \(matchCount)")
                }
            }
        } catch {
            preconditionFailure("Failed to seed UI World vocabulary.searchVocabNotebook: \(error)")
        }

        self.container = container
        self.auth = Self.makeAuth(from: authSeed)
        self.notebookId = seed.notebookRemoteId
        self.query = query
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                KGVocabView(searchText: .constant(query), notebookId: notebookId)
                    .environment(\.catalogTaskPolicy, .disabled)
            }
            .modelContainer(container)
            .environment(\.authManager, auth)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    private static func makeAuth(from seed: UIWorldAuthSeed) -> CatalogPreviewAuth {
        guard seed.isLoggedIn else {
            preconditionFailure("UI World auth.signedIn must be logged in for KGVocabSearchScenarios")
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

private enum ExpectedMatches {
    case multiple
    case exactly(Int)
}
#endif
