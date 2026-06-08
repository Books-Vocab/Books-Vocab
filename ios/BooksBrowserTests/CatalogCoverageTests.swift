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
            filter: CatalogScene.filter(groups: ["Book Card"], scenarios: [])
        )
        #expect(Set(playbook.stores.map { $0.category.rawValue }) == ["Book Card"])
        #expect((playbook.stores.first?.scenarios.count ?? 0) > 0)
    }

    @Test func filteredPlaybookByScenarioKeepsOnlyRequestedScenario() async throws {
        let playbook = CatalogScene.buildPlaybook(
            filter: CatalogScene.filter(groups: [], scenarios: ["Today Review/Front"])
        )
        #expect(Set(playbook.stores.map { $0.category.rawValue }) == ["Today Review"])
        #expect(playbook.stores.first?.scenarios.map { $0.title.rawValue } == ["Front"])
    }

    // MARK: - Taxonomy contract (source-of-truth guards)
    //
    // The iOS Manifest is the single source of truth for each surface's
    // kind/feature/screen. These guards make the two recurring failure modes —
    // duplicate surfaces for one screen, and screens with no coverage — into red
    // tests so they cannot silently regress. The gallery (ops/catalog_review_*.py)
    // consumes this declared taxonomy via catalog_index.json.

    @Test func everyRegisteredCategoryHasDeclaredKind() async throws {
        // A registered category with no CatalogSurface means an addScenarios(of:)
        // landed without declaring its taxonomy — the gallery would be forced to
        // guess the lane from pixels/regex (the exact failure we're retiring).
        let declared = Set(CatalogScene.Manifest.surfaces.map(\.category))
        let undeclared = registeredGroupNames().subtracting(declared)
        #expect(
            undeclared.isEmpty,
            "Registered catalog category(ies) with no declared CatalogSurface: \(undeclared.sorted())"
        )
    }

    @Test func featureScreensHaveNoDuplicateScreen() async throws {
        // The core no-dup contract: each ScreenID maps to AT MOST one
        // featureScreen surface. Re-adding e.g. "Today Review View" (a 2nd surface
        // for .todayReview rendering the same fixture) turns this red.
        let screens = CatalogScene.Manifest.featureScreenSurfaces.compactMap(\.screen)
        let dupes = Dictionary(grouping: screens, by: { $0 })
            .filter { $0.value.count > 1 }
            .keys
            .map(\.rawValue)
            .sorted()
        #expect(dupes.isEmpty, "Multiple featureScreen surfaces share a ScreenID: \(dupes)")
    }

    @Test func featureScreenSurfacesAllDeclareAScreen() async throws {
        // kind == .featureScreen implies a non-nil screen identity.
        let missing = CatalogScene.Manifest.featureScreenSurfaces
            .filter { $0.screen == nil }
            .map(\.category)
            .sorted()
        #expect(missing.isEmpty, "featureScreen surface(s) missing a ScreenID: \(missing)")
    }

    @Test func everyScreenIsCoveredExceptPending() async throws {
        // The coverage contract: every ScreenID has a featureScreen surface,
        // except those explicitly tracked as P3 debt in Manifest.pendingCoverage.
        let covered = Set(CatalogScene.Manifest.featureScreenSurfaces.compactMap(\.screen))
        let expected = Set(CatalogScene.ScreenID.allCases)
            .subtracting(CatalogScene.Manifest.pendingCoverage)
        let uncovered = expected.subtracting(covered).map(\.rawValue).sorted()
        #expect(
            uncovered.isEmpty,
            "Screen(s) with no featureScreen surface (and not in pendingCoverage): \(uncovered)"
        )
    }

    @Test func pendingCoverageScreensAreActuallyMissing() async throws {
        // Keep pendingCoverage honest: a pending screen must NOT already have a
        // surface. When P3 authors it, this turns red until it's removed from the
        // pending set — so the debt list can never silently lie.
        let covered = Set(CatalogScene.Manifest.featureScreenSurfaces.compactMap(\.screen))
        let pendingButCovered = CatalogScene.Manifest.pendingCoverage
            .intersection(covered)
            .map(\.rawValue)
            .sorted()
        #expect(
            pendingButCovered.isEmpty,
            "Screen(s) in pendingCoverage that already have a surface (remove them): \(pendingButCovered)"
        )
    }

    // MARK: - Ground-truth index emit (P4: Python consumes, not guesses)

    @Test func indexJSONCoversEveryCategoryWithDeclaredKind() async throws {
        // The emitted catalog_index.json is the gallery's ground truth. It must
        // round-trip every declared surface: one entry per category, each carrying
        // the source-declared kind + feature, so the Python side never has to fall
        // back to pixel/regex guessing for a surface the source knows.
        let data = try CatalogScene.Manifest.indexJSONData()
        let root = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        #expect(root?["version"] as? Int == 1)
        let surfaces = try #require(root?["surfaces"] as? [String: [String: String]])

        let declared = CatalogScene.Manifest.surfaces
        #expect(Set(surfaces.keys) == Set(declared.map(\.category)))
        for surface in declared {
            let entry = surfaces[surface.category]
            #expect(entry?["kind"] == surface.kind.rawValue)
            #expect(entry?["feature"] == surface.feature.rawValue)
            // featureScreens carry their screen id; other kinds omit it
            #expect(entry?["screen"] == surface.screen?.rawValue)
        }
    }
}
#endif
