#if os(iOS) && DEBUG && targetEnvironment(simulator)
import SwiftData

/// Materializes the same UI World catalog seed through the production
/// SharedDeckSummary -> SharedDeck projection. It owns no catalog data.
@MainActor
enum ExploreFixtureMaterializer {
    static func seed(
        _ fixtureID: UIWorldExploreFixtureID,
        into container: ModelContainer
    ) {
        let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
        let fixture = catalog.fixture(for: fixtureID)
        let context = container.mainContext

        do {
            for deck in try context.fetch(FetchDescriptor<SharedDeck>()) {
                context.delete(deck)
            }
            for (sortOrder, remoteId) in fixture.deckIDs.enumerated() {
                guard let seed = catalog.deck(for: remoteId) else {
                    preconditionFailure(
                        "UI World sharedDecks fixture \(fixtureID.rawValue) references missing deck \(remoteId)"
                    )
                }
                SharedDeckCatalogService.upsertDeck(
                    summary: seed.productionSummary,
                    sortOrder: sortOrder,
                    context: context
                )
            }
            try context.save()
        } catch {
            preconditionFailure(
                "Failed to materialize UI World sharedDecks fixture \(fixtureID.rawValue): \(error)"
            )
        }
    }

    static func makeContainer(for fixtureID: UIWorldExploreFixtureID) -> ModelContainer {
        do {
            let container = try ModelContainer(
                for: SharedDeck.self,
                configurations: ModelConfiguration(
                    isStoredInMemoryOnly: true,
                    cloudKitDatabase: .none
                )
            )
            seed(fixtureID, into: container)
            return container
        } catch {
            preconditionFailure("Failed to create Explore UI World container: \(error)")
        }
    }

    static func assetID(
        for remoteId: String,
        in fixtureID: UIWorldExploreFixtureID
    ) -> String? {
        let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
        let fixture = catalog.fixture(for: fixtureID)
        guard fixture.deckIDs.contains(remoteId) else { return nil }
        return catalog.deck(for: remoteId)?.assetID
    }

}
#endif
