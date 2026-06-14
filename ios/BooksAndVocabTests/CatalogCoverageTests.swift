//
//  CatalogCoverageTests.swift
//  Books & Vocab Tests
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
@testable import BooksAndVocab

@Suite struct CatalogCoverageTests {

    private func registeredGroupNames() -> Set<String> {
        let playbook = CatalogScene.buildPlaybook()
        return Set(playbook.stores.map { $0.category.rawValue })
    }

    private var debugDirectory: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Debug", isDirectory: true)
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

    @Test func catalogPreviewAuthDoesNotFallbackToImplicitUserState() throws {
        let forbidden: [(String, String)] = [
            ("CatalogPreviewAuth(isLoggedIn: true)", "logged-in catalog auth must declare userId/token/name/email"),
            ("CatalogPreviewAuth(isLoggedIn: false)", "logged-out catalog auth must declare nil userId/token/name/email"),
            ("Preview User", "catalog auth displayName must not be a hidden fallback"),
            ("preview@example.com", "catalog auth email must not be a hidden fallback"),
            ("displayName ??", "catalog auth displayName must not fallback"),
            ("userEmail ??", "catalog auth email must not fallback"),
        ]
        let urls = try FileManager.default
            .contentsOfDirectory(at: debugDirectory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "swift" || $0.lastPathComponent == "Scenarios" }
        var swiftFiles: [URL] = []
        for url in urls {
            var isDirectory: ObjCBool = false
            FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory)
            if isDirectory.boolValue {
                swiftFiles += try FileManager.default
                    .contentsOfDirectory(at: url, includingPropertiesForKeys: nil)
                    .filter { $0.pathExtension == "swift" }
            } else if url.pathExtension == "swift" {
                swiftFiles.append(url)
            }
        }

        for url in swiftFiles.sorted(by: { $0.path < $1.path }) {
            let source = try String(contentsOf: url, encoding: .utf8)
            for (snippet, reason) in forbidden {
                #expect(
                    !source.contains(snippet),
                    "\(url.lastPathComponent): \(reason)"
                )
            }
        }
    }

    @Test func paywallCatalogDoesNotDeclareLocalSubscriptionStatusFixtures() throws {
        let paywallScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("PaywallScenarios.swift")
        let source = try String(contentsOf: paywallScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("KGSubscriptionStatus(", "Paywall catalog subscription status must come from UI World entitlements"),
            ("makeStatus", "Paywall catalog must not keep a local subscription status factory"),
            ("source: \"admin\"", "admin entitlement state belongs in UI World, not Debug source"),
            ("last_synced_at:", "subscription sync timestamp belongs in UI World, not Debug source"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(paywallScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireEntitlementsSeed"),
            "Paywall catalog must fail fast through UI World entitlement seeds"
        )
    }

    @Test func pdfReaderCatalogUsesUIWorldBookAsset() throws {
        let pdfScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("PDFReaderViewScenarios.swift")
        let source = try String(contentsOf: pdfScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("catalog-missing.pdf", "PDF reader catalog must not render a synthetic missing-file book"),
            ("Sample PDF", "PDF reader catalog title must come from UI World"),
            ("File unavailable", "PDF reader catalog must not be pinned to the missing-file error state"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(pdfScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireBookshelfSeed(for: .withBooksLibrary)"),
            "PDF reader catalog must source its book row from UI World bookshelf.with_books_library"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireInstalledAssetURL(ref: ref)"),
            "PDF reader catalog must materialize the UI World book asset"
        )
    }

    @Test func wordEditCatalogUsesUIWorldVocabularySeed() throws {
        let wordEditScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("WordEditScenarios.swift")
        let source = try String(contentsOf: wordEditScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("sampleEntry", "Word Edit catalog must not construct local vocabulary entries"),
            ("Sample Book", "Word Edit catalog book title must come from UI World"),
            ("VocabularyEntry(", "Word Edit catalog must not inline SwiftData row literals"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(wordEditScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: .wordEdit)"),
            "Word Edit catalog must source entries from UI World vocabulary.wordEdit"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "Word Edit catalog must materialize UI World vocabulary rows into SwiftData"
        )
    }

    @Test func settingsSubscriptionCatalogUsesUIWorldSettingsSeeds() throws {
        let subscriptionScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SettingsSubscriptionSectionScenarios.swift")
        let source = try String(contentsOf: subscriptionScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("SettingsPresenterPreviewData.subscribedActive.subscription!", "subscription section must load settings.subscribed_active from UI World"),
            ("SettingsPresenterPreviewData.subscriptionLoading.subscription!", "subscription section must load settings.subscription_loading from UI World"),
            ("SettingsPresenterPreviewData.pricingUnavailable.subscription!", "subscription section must load settings.pricing_unavailable from UI World"),
            ("inactiveFreeFixture", "inactive free subscription section must be a UI World settings seed"),
            ("SettingsPresenterState.SubscriptionSection(", "subscription section must not construct local presenter state"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(subscriptionScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("SettingsFixtures.state(for: fixtureID)"),
            "Settings subscription catalog must fail fast through UI World settings seeds"
        )
    }

    @Test func settingsAccountDetailCatalogUsesUIWorldSettingsSeeds() throws {
        let detailScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SettingsAccountDetailScenarios.swift")
        let source = try String(contentsOf: detailScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("SettingsPresenterPreviewData.subscribedActive.auth", "account detail must load settings.subscribed_active from UI World"),
            ("SettingsPresenterPreviewData.deletingAccount.auth", "account detail must load settings.deleting_account from UI World"),
            ("loggedOutAuth", "logged-out account detail must be a UI World settings seed"),
            ("longInfoAuth", "long identity account detail must be a UI World settings seed"),
            ("SettingsPresenterState.AuthSection(", "account detail must not construct local auth presenter state"),
            ("SettingsPresenterState.DangerSection(", "account detail must not construct local danger presenter state"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(detailScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("SettingsFixtures.state(for: fixtureID)"),
            "Settings account detail catalog must fail fast through UI World settings seeds"
        )
    }

    @Test func settingsAccountSectionCatalogUsesUIWorldSettingsSeeds() throws {
        let sectionScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SettingsAccountSectionScenarios.swift")
        let source = try String(contentsOf: sectionScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("loggedOutWithError", "logged-out error account section must be a UI World settings seed"),
            ("longIdentityState", "long identity account summary must be a UI World settings seed"),
            ("SettingsPresenterState.AuthSection(", "account section must not construct local auth presenter state"),
            ("return .init(", "account section must not locally mutate fixture state"),
            ("isProActive: true", "auth summary Pro state must be derived from a UI World subscription seed"),
            ("isProActive: false", "auth summary free state must be derived from a UI World subscription seed"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(sectionScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("SettingsFixtures.state(for: fixtureID)"),
            "Settings account section catalog must fail fast through UI World settings seeds"
        )
    }

    @Test func settingsPreferencesCatalogUsesUIWorldSettingsSeeds() throws {
        let sectionScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SettingsSectionsScenarios.swift")
        let source = try String(contentsOf: sectionScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("SettingsPresenterState.PreferencesSection(", "preferences section must not construct local presenter state"),
            ("autoSyncEnabled: true", "auto-sync on state belongs in UI World settings preferences"),
            ("autoSyncEnabled: false", "auto-sync off state belongs in UI World settings preferences"),
            ("showAutoSync: true", "sync-row visibility belongs in UI World settings preferences"),
            ("showAutoSync: false", "sync-row hidden state belongs in UI World settings preferences"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(sectionScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("SettingsFixtures.state(for: fixtureID).preferences"),
            "Settings preferences catalog must fail fast through UI World settings seeds"
        )
    }

    @Test func settingsReviewCatalogUsesUIWorldSettingsSeeds() throws {
        let sectionScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SettingsSectionsScenarios.swift")
        let source = try String(contentsOf: sectionScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("ReviewSectionScene(settings:", "review section must not receive locally constructed ReviewSettings"),
            ("ReviewSettings(", "review section modes/custom/pause state belong in UI World settings reviewSettings"),
            ("Date(timeIntervalSince1970:", "paused review clock belongs in UI World settings reviewSettings"),
            ("mode: .relaxed", "review mode belongs in UI World settings reviewSettings"),
            ("mode: .intensive", "review mode belongs in UI World settings reviewSettings"),
            ("mode: .custom", "review mode belongs in UI World settings reviewSettings"),
            ("isProgressPaused: true", "review pause state belongs in UI World settings reviewSettings"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(sectionScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("SettingsFixtures.reviewSettings(for: fixtureID)"),
            "Settings review catalog must fail fast through UI World settings reviewSettings seeds"
        )
    }

    @Test func buildPlaybookIsDeterministic() async throws {
        // `buildPlaybook()` must produce the same surface set on every call so the
        // in-app catalog and the snapshot test driver stay in lockstep.
        #expect(registeredGroupNames() == registeredGroupNames())
    }

    @Test func filteredPlaybookByGroupKeepsOnlyRequestedStore() async throws {
        let playbook = CatalogScene.buildPlaybook(
            filter: try CatalogScene.filter(groups: ["Book Card"], scenarios: [])
        )
        #expect(Set(playbook.stores.map { $0.category.rawValue }) == ["Book Card"])
        #expect((playbook.stores.first?.scenarios.count ?? 0) > 0)
    }

    @Test func filteredPlaybookByScenarioKeepsOnlyRequestedScenario() async throws {
        let playbook = CatalogScene.buildPlaybook(
            filter: try CatalogScene.filter(groups: [], scenarios: ["Today Review/Front"])
        )
        #expect(Set(playbook.stores.map { $0.category.rawValue }) == ["Today Review"])
        #expect(playbook.stores.first?.scenarios.map { $0.title.rawValue } == ["Front"])
    }

    @Test func filterFailsFastOnScenarioMissingCategorySeparator() async throws {
        // `-KG_CATALOG_SCENARIOS "Plan Picker"`（忘了 `Settings/` 前綴）過去被
        // descriptor(from:) 的 compactMap 靜默吞掉 → filter 變空 → filteredPlaybook
        // 把空 filter 當「無 scope」靜默跑全量 playbook。必須 fail-fast，
        // 訊息含壞條目本身與格式提示 `<Category>/<Scenario Title>`。
        do {
            _ = try CatalogScene.filter(groups: [], scenarios: ["Plan Picker"])
            Issue.record("filter must throw on scenario entries missing the <Category>/<Scenario Title> separator")
        } catch {
            let message = String(describing: error)
            #expect(message.contains("Plan Picker"))
            #expect(message.contains("<Category>/<Scenario Title>"))
        }
    }

    @Test func filterFailsFastWhenAnyScenarioEntryIsMalformed() async throws {
        // 部分條目打錯同樣不可靜默縮窄 scope（用戶以為兩個都會跑）。
        do {
            _ = try CatalogScene.filter(
                groups: [],
                scenarios: ["Today Review/Front", "Plan Picker"]
            )
            Issue.record("filter must throw when any scenario entry is malformed, not silently drop it")
        } catch {
            let message = String(describing: error)
            #expect(message.contains("Plan Picker"))
            #expect(!message.contains("Today Review/Front"))
        }
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

    @Test func featureScreenSurfacesAllDeclareBacking() async throws {
        // kind == .featureScreen implies a non-nil backing production view type.
        // The compiler already forces this (the `screen()` factory takes a required
        // `any View.Type`), so this test pins the surface→type contract against the
        // factory ever being loosened — the gallery / IndexStore consumers map
        // surface→type from this declaration instead of a hand-maintained name table.
        let missing = CatalogScene.Manifest.featureScreenSurfaces
            .filter { $0.backing == nil }
            .map(\.category)
            .sorted()
        #expect(missing.isEmpty, "featureScreen surface(s) missing a backing type: \(missing)")
    }

    @Test func buildingBlockSurfacesDeclareBackingUnlessExempt() async throws {
        // Completes the surface→type source declaration: every buildingBlock /
        // engineering surface must name its production view, except the explicitly
        // enumerated structural exceptions (generic components / ViewModifiers with
        // no single concrete metatype). A new component added without backing — and
        // not consciously exempted — turns this red, so the gallery / IndexStore
        // never silently fall back to guessing that surface's type.
        let missing = CatalogScene.Manifest.surfaces
            .filter { $0.kind == .buildingBlock || $0.kind == .engineering }
            .filter { $0.backing == nil }
            .map(\.category)
            .filter { !CatalogScene.Manifest.surfacesExemptFromBacking.contains($0) }
            .sorted()
        #expect(
            missing.isEmpty,
            "buildingBlock/engineering surface(s) missing a backing type (and not in surfacesExemptFromBacking): \(missing)"
        )
    }

    @Test func backingExemptSurfacesAreActuallyBackingless() async throws {
        // Keep the exempt set honest: each listed category must exist AND genuinely
        // carry no backing. If someone later gives one a concrete backing (e.g. a
        // generic gets a non-generic wrapper), this turns red until it's removed
        // from the exempt set — the exception list can never silently lie.
        let byCategory = Dictionary(
            CatalogScene.Manifest.surfaces.map { ($0.category, $0) },
            uniquingKeysWith: { first, _ in first }
        )
        for category in CatalogScene.Manifest.surfacesExemptFromBacking.sorted() {
            let surface = byCategory[category]
            #expect(surface != nil, "surfacesExemptFromBacking lists an unknown category: \(category)")
            #expect(
                surface?.backing == nil,
                "Exempt category now declares a backing — remove it from surfacesExemptFromBacking: \(category)"
            )
        }
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
            // backing production view type: featureScreens always carry it, other
            // kinds only when declared. Mirrors indexJSONData's String(describing:).
            #expect(entry?["backing"] == surface.backing.map { String(describing: $0) })
        }
    }
}
#endif
