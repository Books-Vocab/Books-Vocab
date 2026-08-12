#if DEBUG && canImport(Playbook) && targetEnvironment(simulator)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `SharedDeckDetailView` surface. Header reads the
/// seeded SharedDeck from a local in-memory store by deckId; sample cards are
/// injected via the DEBUG `previewCards:` init (network fetch skipped,
/// `CatalogTaskPolicy.disabled`). The Phase-2c copy CTA's four states
/// (idle/inflight/success/failure) are pinned deterministically via the DEBUG
/// `previewCopyState:` seam — no auth / network needed for the snapshot.
enum SharedDeckDetailViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Shared Deck Detail View") {
            Scenario("Preview / Official with cards", layout: .fill) {
                SharedDeckDetailScene(fixture: .official)
            }
            Scenario("Preview / No sample cards", layout: .fill) {
                SharedDeckDetailScene(fixture: .noCards)
            }
            Scenario("Copy CTA / idle", layout: .fill) {
                SharedDeckDetailScene(fixture: .official, copyState: .idle)
            }
            Scenario("Copy CTA / inflight", layout: .fill) {
                SharedDeckDetailScene(fixture: .official, copyState: .inflight)
            }
            Scenario("Copy CTA / success", layout: .fill) {
                SharedDeckDetailScene(
                    fixture: .official,
                    copyState: .success(.init(
                        notebookId: "nb-copied", notebookName: "GRE 3000",
                        cardCount: 42, alreadyCopied: false
                    ))
                )
            }
            Scenario("Copy CTA / failure", layout: .fill) {
                SharedDeckDetailScene(
                    fixture: .official,
                    copyState: .failure(L10n.string("explore.copy.error.generic"))
                )
            }
        }
    }
}

private enum DetailFixture {
    case official
    case noCards

    func previewCards(
        catalog: UIWorldSharedDeckCatalogSeed,
        remoteId: String
    ) -> [SharedDeckCard] {
        switch self {
        case .official: return catalog.deck(for: remoteId)?.sampleCards ?? []
        case .noCards: return []
        }
    }
}

private struct SharedDeckDetailScene: View {
    let container: ModelContainer
    let deckId: String
    let previewCards: [SharedDeckCard]
    let copyState: SharedDeckCopyController.CopyState?

    init(fixture: DetailFixture, copyState: SharedDeckCopyController.CopyState? = nil) {
        let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
        let loaded = catalog.fixture(for: .loaded)
        guard let deckId = loaded.deckIDs.first else {
            preconditionFailure("UI World sharedDecks.loaded must contain a deck for detail preview")
        }
        self.container = ExploreFixtureMaterializer.makeContainer(for: .loaded)
        self.deckId = deckId
        self.previewCards = fixture.previewCards(catalog: catalog, remoteId: deckId)
        self.copyState = copyState
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                SharedDeckDetailView(deckId: deckId, previewCards: previewCards, previewCopyState: copyState)
                    .modelContainer(container)
                    .environment(\.catalogTaskPolicy, .disabled)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
