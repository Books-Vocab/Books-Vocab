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
//  group names (Playbook "categories") against the known surface inventory. Group
//  names below were enumerated directly from `buildPlaybook()`'s registration body,
//  not from any doc.
//

#if DEBUG && canImport(Playbook)
import Foundation
import Testing
import Playbook
@testable import BooksBrowser

@Suite struct CatalogCoverageTests {

    /// Group names ("categories") that `buildPlaybook()` is currently expected to
    /// register. Sourced from the `addScenarios(of:)` calls across
    /// `Debug/Scenarios/*.swift`. Note several providers register more than one
    /// group (e.g. `NotebookDetailScenarios` adds both "· Row" and "· CTA Pill"),
    /// so this list is longer than the number of `register(in:)` calls.
    private static let expectedGroups: Set<String> = [
        "Bookshelf",
        "Settings",
        "Notebook Detail · Row",
        "Notebook Detail · CTA Pill",
        "Notebooks · Stack",
        "Notebooks · Card",
        "Today Review",
        "Design Tokens",
        "Welcome",
    ]

    private func registeredGroupNames() -> Set<String> {
        let playbook = CatalogScene.buildPlaybook()
        return Set(playbook.stores.map { $0.category.rawValue })
    }

    // MARK: - Group coverage

    @Test func buildPlaybookRegistersAllKnownGroups() async throws {
        let registered = registeredGroupNames()
        // Every known surface group must still be wired into the catalog. A missing
        // entry here means a `Scenarios.register(in:)` line was dropped (or a group
        // was renamed without updating this inventory).
        let missing = Self.expectedGroups.subtracting(registered)
        #expect(
            missing.isEmpty,
            "buildPlaybook() is missing expected catalog group(s): \(missing.sorted())"
        )
    }

    @Test func buildPlaybookCoversAtLeastKnownGroupCount() async throws {
        // Defense-in-depth floor: the catalog is known to expose 9 groups. New
        // surfaces should only grow this number; a drop signals a lost registration.
        #expect(registeredGroupNames().count >= 9)
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
}
#endif
