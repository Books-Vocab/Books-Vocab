#if os(iOS) && DEBUG && targetEnvironment(simulator)
import SwiftData

/// Materializes the same UI World catalog seed through the production
/// SharedDeckSummary -> SharedDeck projection. It owns no catalog data.
@MainActor
enum ExploreFixtureMaterializer {
    /// Install and validate fixture assets without pre-seeding catalog rows.
    /// The async service owns the state transition so loading/error/partial are
    /// observable rather than being replaced by a static preview phase.
    static func prepare(_ fixtureID: UIWorldExploreFixtureID) {
        do {
            let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
            _ = try installAssets(for: catalog.fixture(for: fixtureID))
        } catch {
            preconditionFailure(
                "Failed to prepare Explore UI World fixture \(fixtureID.rawValue): \(error)"
            )
        }
    }

    static func seed(
        _ fixtureID: UIWorldExploreFixtureID,
        into container: ModelContainer
    ) {
        do {
            try materialize(fixtureID, into: container.mainContext)
        } catch {
            preconditionFailure(
                "Failed to materialize UI World sharedDecks fixture \(fixtureID.rawValue): \(error)"
            )
        }
    }

    static func makeContainer(
        for fixtureID: UIWorldExploreFixtureID,
        seedCatalog: Bool = true
    ) -> ModelContainer {
        do {
            let container = try ModelContainer(
                for: SharedDeck.self,
                configurations: ModelConfiguration(
                    isStoredInMemoryOnly: true,
                    cloudKitDatabase: .none
                )
            )
            if seedCatalog {
                try materialize(fixtureID, into: container.mainContext)
            } else {
                let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
                _ = try installAssets(for: catalog.fixture(for: fixtureID))
            }
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

    static func materialize(
        _ fixtureID: UIWorldExploreFixtureID,
        into context: ModelContext
    ) throws {
        let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
        let fixture = catalog.fixture(for: fixtureID)
        let installedAssets = try installAssets(for: fixture)

        for deck in try context.fetch(FetchDescriptor<SharedDeck>()) {
            context.delete(deck)
        }
        for (sortOrder, remoteId) in fixture.deckIDs.enumerated() {
            guard let seed = catalog.deck(for: remoteId) else {
                throw UIWorldSharedDeckCatalogContractError.invalid(
                    "sharedDecks fixture \(fixtureID.rawValue) references missing deck \(remoteId)"
                )
            }
            let installedAsset: UIWorldInstalledAsset?
            if let assetID = seed.assetID {
                guard let asset = installedAssets[assetID] else {
                    throw UIWorldSharedDeckCatalogContractError.invalid(
                        "sharedDecks deck \(remoteId) references asset \(assetID) that was not installed"
                    )
                }
                installedAsset = asset
            } else {
                installedAsset = nil
            }
            SharedDeckCatalogService.upsertDeck(
                summary: seed.productionSummary,
                sortOrder: sortOrder,
                context: context,
                installedAsset: installedAsset
            )
        }
        try context.save()
    }

    private static func installAssets(
        for fixture: UIWorldExploreFixtureSeed
    ) throws -> [String: UIWorldInstalledAsset] {
        var installed: [String: UIWorldInstalledAsset] = [:]
        for assetID in fixture.assetIDs {
            installed[assetID] = try FixtureDatasetStore.requireInstalledAsset(ref: assetID)
        }
        return installed
    }
}

/// Named protocol fake for UI World only. It uses the production catalog
/// service's upsert projection while supplying deterministic async outcomes.
@MainActor
final class ExploreUIWorldCatalogService: SharedDeckCatalogServicing {
    let fixtureID: UIWorldExploreFixtureID
    let initialCacheFixtureID: UIWorldExploreFixtureID?
    private var requestCount = 0

    init(
        fixtureID: UIWorldExploreFixtureID,
        initialCacheFixtureID: UIWorldExploreFixtureID? = nil
    ) {
        self.fixtureID = fixtureID
        self.initialCacheFixtureID = initialCacheFixtureID
    }

    func syncAll(context: ModelContext) async -> SharedDeckCatalogService.SyncOutcome {
        requestCount += 1
        let catalog = FixtureDatasetStore.requireSharedDeckCatalogSeed()
        let fixture = catalog.fixture(for: fixtureID)

        do {
            if requestCount == 1, let initialCacheFixtureID {
                try ExploreFixtureMaterializer.materialize(initialCacheFixtureID, into: context)
                _ = try Self.installAssets(for: fixture)
            } else {
                _ = try Self.installAssets(for: fixture)
            }
        } catch {
            preconditionFailure(
                "Failed to install Explore UI World assets \(fixtureID.rawValue): \(error)"
            )
        }

        switch fixture.phase {
        case .loading:
            do {
                try await Task.sleep(nanoseconds: 30_000_000_000)
            } catch {
                return .cancelled
            }
            return .completed(catalogCount: 0)
        case .empty, .loaded:
            do {
                try ExploreFixtureMaterializer.materialize(fixtureID, into: context)
                return .completed(catalogCount: fixture.deckIDs.count)
            } catch {
                preconditionFailure(
                    "Failed to project Explore UI World fixture \(fixtureID.rawValue): \(error)"
                )
            }
        case .error:
            guard requestCount > 1, fixture.retryPhase == .loaded else {
                return .listFetchFailed
            }
            do {
                try ExploreFixtureMaterializer.materialize(fixtureID, into: context)
                return .completed(catalogCount: fixture.deckIDs.count)
            } catch {
                preconditionFailure(
                    "Failed to project Explore UI World retry \(fixtureID.rawValue): \(error)"
                )
            }
        }
    }

    private static func installAssets(
        for fixture: UIWorldExploreFixtureSeed
    ) throws -> [String: UIWorldInstalledAsset] {
        var installed: [String: UIWorldInstalledAsset] = [:]
        for assetID in fixture.assetIDs {
            installed[assetID] = try FixtureDatasetStore.requireInstalledAsset(ref: assetID)
        }
        return installed
    }
}
#endif
