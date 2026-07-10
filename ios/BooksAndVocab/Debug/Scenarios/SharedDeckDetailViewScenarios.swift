#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the full `SharedDeckDetailView` surface (read-only
/// preview — no copy button in Phase 1b-iii). Header reads the seeded SharedDeck
/// from a local in-memory store by deckId; sample cards are injected via the
/// DEBUG `previewCards:` init (network fetch skipped, `CatalogTaskPolicy.disabled`).
enum SharedDeckDetailViewScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Shared Deck Detail View") {
            Scenario("Preview / Official with cards", layout: .fill) {
                SharedDeckDetailScene(fixture: .official)
            }
            Scenario("Preview / No sample cards", layout: .fill) {
                SharedDeckDetailScene(fixture: .noCards)
            }
        }
    }
}

private enum DetailFixture {
    case official
    case noCards

    var previewCards: [SharedDeckCard] {
        switch self {
        case .official: return SharedDeckCatalogFixtures.sampleCards()
        case .noCards: return []
        }
    }
}

private struct SharedDeckDetailScene: View {
    let container: ModelContainer
    let deckId: String
    let previewCards: [SharedDeckCard]

    init(fixture: DetailFixture) {
        let spec = SharedDeckCatalogFixtures.populated[0]
        self.container = SharedDeckCatalogFixtures.makeContainer(specs: [spec])
        self.deckId = spec.remoteId
        self.previewCards = fixture.previewCards
    }

    var body: some View {
        AppThemeContainer {
            NavigationStack {
                SharedDeckDetailView(deckId: deckId, previewCards: previewCards)
                    .modelContainer(container)
                    .environment(\.catalogTaskPolicy, .disabled)
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
