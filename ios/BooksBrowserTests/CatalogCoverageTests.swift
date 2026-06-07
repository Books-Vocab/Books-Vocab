//
//  CatalogCoverageTests.swift
//  BooksBrowserTests
//
//  Regression guard for the DEBUG Playbook catalog. `CatalogScene.buildPlaybook()`
//  is the single source registering every KG SwiftUI surface for the in-app
//  catalog + `CatalogSnapshotTests` PNG renders. The recurring failure mode is
//  adding a new `*Scenarios.swift` file but forgetting the matching
//  `Scenarios.register(in:)` line in `buildPlaybook()` — the surface then silently
//  drops out of the catalog and snapshot coverage with no compile error.
//
//  This suite turns that omission into a red test by pinning the set of registered
//  group names (Playbook "categories") against the catalog manifest that also
//  drives `buildPlaybook()`.
//

#if DEBUG && canImport(Playbook)
import Foundation
import Testing
import Playbook
@testable import BooksBrowser

@Suite struct CatalogCoverageTests {

    private func registeredGroupNames() -> Set<String> {
        let playbook = CatalogScene.buildPlaybook()
        return Set(playbook.stores.map { $0.category.rawValue })
    }

    // MARK: - Group coverage

    @Test func buildPlaybookRegistersAllKnownGroups() async throws {
        let registered = registeredGroupNames()
        let expected = CatalogScene.Manifest.categoryNames
        let missing = expected.subtracting(registered)
        #expect(
            missing.isEmpty,
            "buildPlaybook() is missing expected catalog group(s): \(missing.sorted())"
        )
        let unexpected = registered.subtracting(expected)
        #expect(
            unexpected.isEmpty,
            "buildPlaybook() registered unexpected catalog group(s): \(unexpected.sorted())"
        )
    }

    @Test func manifestMatchesRegisteredGroupCount() async throws {
        #expect(registeredGroupNames().count == CatalogScene.Manifest.categoryNames.count)
    }

    // MARK: - Scenario population

    @Test func everyRegisteredGroupHasScenarios() async throws {
        // A registered-but-empty store would render a blank catalog category and
        // produce no snapshots — almost always an accidental empty `addScenarios`
        // block. Guard against it.
        let playbook = CatalogScene.buildPlaybook()
        for store in playbook.stores {
            #expect(
                !store.scenarios.isEmpty,
                "Catalog group '\(store.category.rawValue)' registered zero scenarios"
            )
        }
    }

    @Test func buildPlaybookIsDeterministic() async throws {
        // `buildPlaybook()` must produce the same surface set on every call so the
        // in-app catalog and the snapshot test driver stay in lockstep.
        #expect(registeredGroupNames() == registeredGroupNames())
    }

    @Test func filteredPlaybookByGroupKeepsOnlyRequestedStore() async throws {
        let playbook = CatalogScene.buildPlaybook(
            filter: CatalogScene.filter(groups: ["Bookshelf"], scenarios: [])
        )
        #expect(Set(playbook.stores.map { $0.category.rawValue }) == ["Bookshelf"])
        #expect((playbook.stores.first?.scenarios.count ?? 0) > 0)
    }

    @Test func filteredPlaybookByScenarioKeepsOnlyRequestedScenario() async throws {
        let playbook = CatalogScene.buildPlaybook(
            filter: CatalogScene.filter(groups: [], scenarios: ["Today Review/Front"])
        )
        #expect(Set(playbook.stores.map { $0.category.rawValue }) == ["Today Review"])
        #expect(playbook.stores.first?.scenarios.map { $0.title.rawValue } == ["Front"])
    }
}
#endif
