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

    @Test func loginSheetCatalogUsesUIWorldAuthSeeds() throws {
        let loginScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("LoginSheetScenarios.swift")
        let source = try String(contentsOf: loginScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("LoginSheetScene()", "Login Sheet default state must select an explicit UI World auth seed"),
            ("LoginSheetScene(isAuthenticating:", "Login Sheet authenticating state belongs in UI World auth seed"),
            ("LoginSheetScene(authError:", "Login Sheet error state belongs in UI World auth seed"),
            ("無法連線至伺服器", "Login Sheet error copy belongs in UI World, not Debug source"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(loginScenarios.lastPathComponent): \(reason)")
        }
        for snippet in [
            "LoginSheetScene(authID: .guest)",
            "LoginSheetScene(authID: .guestAuthenticating)",
            "LoginSheetScene(authID: .guestError)",
            "FixtureDatasetStore.requireAuthSeed(for: authID)",
            "isAuthenticating: seed.isAuthenticating",
            "authError: seed.authError",
        ] {
            #expect(source.contains(snippet), "\(loginScenarios.lastPathComponent): missing manifest-driven auth mapping \(snippet)")
        }
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
            ("Book(", "PDF reader catalog must not inline Book rows"),
            ("try! ModelContainer", "PDF reader catalog must fail fast with explicit materialization errors"),
            ("FixtureDatasetStore.requireInstalledAssetURL(ref: ref)", "PDF reader asset install must go through shared BookshelfFixtures materialization"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(pdfScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("BookshelfFixtures.books(for: .withBooksLibrary)"),
            "PDF reader catalog must source its book row and asset from shared UI World bookshelf materialization"
        )
    }

    @Test func bookshelfViewCatalogUsesUIWorldBookshelfSeeds() throws {
        let bookshelfScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("BookshelfViewScenarios.swift")
        let source = try String(contentsOf: bookshelfScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("private enum BookshelfViewFixture", "Bookshelf catalog must not define local fixture ids"),
            ("Book(title:", "Bookshelf catalog must not inline book rows"),
            ("try? context.save()", "Bookshelf catalog SwiftData save must fail fast through BookshelfFixtures"),
            ("Deep Work", "Bookshelf catalog book titles must come from UI World"),
            ("return\n        case .single", "Bookshelf catalog empty state must be an explicit UI World seed"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(bookshelfScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("BookshelfFixtures.renderModel(for: fixture).container"),
            "Bookshelf catalog must materialize its SwiftData store through UI World BookshelfFixtures"
        )
        #expect(
            source.contains("fixture: .emptyLibrary"),
            "Bookshelf catalog empty state must use UI World bookshelf.empty_library"
        )
    }

    @Test func bookCardCatalogUsesUIWorldBookshelfSeeds() throws {
        let bookCardScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("BookCardScenarios.swift")
        let source = try String(contentsOf: bookCardScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("struct Spec", "Book Card catalog must not keep local book specs"),
            ("Book(", "Book Card catalog must not inline Book rows"),
            ("Date(timeIntervalSince1970:", "Book Card relative dates must come from UI World referenceDate"),
            ("fileName: \"fixture.", "Book Card file names must come from UI World"),
            ("原子習慣", "Book Card title metadata belongs in UI World"),
            ("James Clear", "Book Card author metadata belongs in UI World"),
            ("progression: 0.42", "Book Card progress belongs in UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(bookCardScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("BookshelfFixtures.renderModel(for: fixture.bookshelfID)"),
            "Book Card catalog must materialize book rows from UI World bookshelf seeds"
        )
        #expect(
            source.contains("renderModel.books.count == 1"),
            "Book Card catalog must validate each card seed declares exactly one book"
        )
        #expect(
            source.contains(".environment(\\.fixtureReferenceDate, referenceDate)"),
            "Book Card catalog must use UI World bookshelf referenceDate"
        )
    }

    @Test func podcastEpisodeListCatalogUsesUIWorldRuntimePodcastSeeds() throws {
        let podcastScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("PodcastEpisodeListViewScenarios.swift")
        let source = try String(contentsOf: podcastScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("private enum PodcastEpisodeListFixture", "Podcast episode list catalog must not define local fixture ids"),
            ("series-atomic-habits", "Podcast episode list catalog series id must come from UI World"),
            ("Atomic Habits Unpacked", "Podcast episode list catalog title must come from UI World"),
            ("Catalog Podcast User", "Podcast episode list catalog auth must come from UI World"),
            ("let series = PodcastSeries(", "Podcast episode list catalog must not inline series rows"),
            ("PodcastEpisode(remoteId:", "Podcast episode list catalog must not inline episode rows"),
            ("try? container.mainContext.save()", "Podcast episode list catalog SwiftData save must fail fast"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(podcastScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireRuntimePodcastSeed(for: fixture)"),
            "Podcast episode list catalog must source series and episodes from UI World runtimePodcast"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeRuntimePodcastSeries("),
            "Podcast episode list catalog must use the shared runtime podcast series materializer"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeRuntimePodcastEpisode("),
            "Podcast episode list catalog must use the shared runtime podcast episode materializer"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: .signedIn)"),
            "Podcast episode list catalog auth must come from UI World auth.signedIn"
        )
        #expect(
            source.contains("fixture: .playablePreview, episodeLimit: 0"),
            "Podcast episode list empty state must derive from an explicit UI World runtimePodcast seed"
        )
    }

    @Test func podcastPlayerCatalogUsesUIWorldRuntimePodcastSeeds() throws {
        let playerScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("PodcastPlayerViewScenarios.swift")
        let source = try String(contentsOf: playerScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("sampleSRT", "Podcast player catalog subtitle must come from UI World subtitle asset"),
            ("series-deep-work", "Podcast player catalog series id must come from UI World"),
            ("Deep Work, Decoded", "Podcast player catalog title must come from UI World"),
            ("Catalog Podcast Player User", "Podcast player catalog auth must come from UI World"),
            ("let series = PodcastSeries(", "Podcast player catalog must not inline series rows"),
            ("PodcastEpisode(remoteId:", "Podcast player catalog must not inline episode rows"),
            ("try? container.mainContext.save()", "Podcast player catalog SwiftData save must fail fast"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(playerScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireRuntimePodcastSeed(for: fixture.runtimePodcastID)"),
            "Podcast player catalog must source episode state from UI World runtimePodcast"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeRuntimePodcastSeries("),
            "Podcast player catalog must use the shared runtime podcast series materializer"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeRuntimePodcastEpisode("),
            "Podcast player catalog must use the shared runtime podcast episode materializer"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: fixture.authID)"),
            "Podcast player catalog auth must come from UI World auth seeds"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireInstalledAssetURL(ref: seed.subtitleAssetRef)"),
            "Podcast player catalog subtitle must materialize through the UI World asset manifest"
        )
    }

    @Test func podcastHomeCatalogUsesUIWorldRuntimePodcastSeeds() throws {
        let homeScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("PodcastHomeViewScenarios.swift")
        let source = try String(contentsOf: homeScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("Atomic Habits Unpacked", "Podcast home catalog title must come from UI World"),
            ("Finding Flow", "Podcast home catalog must not keep local series specs"),
            ("private static let palette", "Podcast home catalog color must come from UI World"),
            ("let series = PodcastSeries(", "Podcast home catalog must not inline series row literals"),
            ("PodcastEpisode(remoteId: \"", "Podcast home catalog must not inline episode row literals"),
            ("try? context.save()", "Podcast home catalog SwiftData save must fail fast"),
            ("try? container.mainContext.save()", "Podcast home catalog SwiftData save must fail fast"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(homeScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireRuntimePodcastSeed(for: fixtureID)"),
            "Podcast home catalog must source series and episodes from UI World runtimePodcast"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeRuntimePodcastSeries("),
            "Podcast home catalog must use the shared runtime podcast series materializer"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeRuntimePodcastEpisode("),
            "Podcast home catalog must use the shared runtime podcast episode materializer"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: .signedIn)"),
            "Podcast home catalog auth must come from UI World auth.signedIn"
        )
        #expect(
            source.contains("runtimePodcastIDs: [UIWorldRuntimePodcastFixtureID]"),
            "Podcast home catalog states must be declared as UI World runtimePodcast ids"
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

    @Test func wordDetailCatalogUsesUIWorldVocabularySeed() throws {
        let wordDetailScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("WordDetailScenarios.swift")
        let source = try String(contentsOf: wordDetailScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("= VocabularyEntry(", "Word Detail catalog must not inline SwiftData row literals"),
            ("return VocabularyEntry(", "Word Detail catalog must not inline SwiftData row literals"),
            ("CardDocumentBuilder.build(", "Word Detail catalog card document must derive from seeded cardPresentation"),
            ("Sample Book", "Word Detail catalog book metadata belongs in UI World"),
            ("richEntry", "Word Detail catalog must not keep local rich entry fixtures"),
            ("minimalEntry", "Word Detail catalog must not keep local minimal entry fixtures"),
            ("richDocument", "Word Detail catalog must not keep local rich document fixtures"),
            ("minimalDocument", "Word Detail catalog must not keep local minimal document fixtures"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(wordDetailScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: .wordDetail)"),
            "Word Detail catalog must source entries from UI World vocabulary.wordDetail"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)"),
            "Word Detail catalog must materialize UI World vocabulary entry seeds"
        )
        #expect(
            source.contains("entry(fixture).cardPresentation.document"),
            "Word Detail card document scenarios must derive from the seeded VocabularyEntry"
        )
    }

    @Test func kgVocabSearchCatalogUsesUIWorldVocabularyAndAuthSeeds() throws {
        let searchScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("KGVocabSearchScenarios.swift")
        let source = try String(contentsOf: searchScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("KGVocabSearchFixtures", "KG Vocab search catalog must not keep local vocabulary fixtures"),
            ("VocabularyEntry(", "KG Vocab search catalog must not inline SwiftData row literals"),
            ("Notebook(remoteId:", "KG Vocab search catalog notebook must come from UI World"),
            ("Sample Book", "KG Vocab search catalog book title must come from UI World"),
            ("catalog-vocab-search-user", "KG Vocab search auth user must come from UI World"),
            ("catalog-vocab-search-token", "KG Vocab search auth token must come from UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(searchScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: .searchVocabNotebook)"),
            "KG Vocab search catalog must source rows from UI World vocabulary.searchVocabNotebook"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: .signedIn)"),
            "KG Vocab search catalog must source auth from UI World auth.signedIn"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "KG Vocab search catalog must materialize UI World vocabulary rows into SwiftData"
        )
    }

    @Test func knowledgeGraphCatalogUsesUIWorldVocabularyLinksAndAuthSeeds() throws {
        let graphScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("KnowledgeGraphViewScenarios.swift")
        let source = try String(contentsOf: graphScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("KnowledgeGraphPresenterPreviewData", "Knowledge Graph catalog must not use presenter preview sample graph data"),
            ("allEntries: []", "Knowledge Graph empty state must use a UI World vocabulary seed"),
            ("KnowledgeGraphView(allEntries: [])", "Knowledge Graph catalog must not inline an empty entry array"),
            ("shouldLoadGraphData: true", "Knowledge Graph catalog must not depend on remote graph task"),
            ("DemoDataProvider.demoGraphLinks", "Knowledge Graph catalog links must come from UI World manifest rows"),
            ("subtle", "Knowledge Graph catalog nodes must not come from presenter preview samples"),
            ("nuance", "Knowledge Graph catalog nodes must not come from presenter preview samples"),
            ("precise", "Knowledge Graph catalog nodes must not come from presenter preview samples"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(graphScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)"),
            "Knowledge Graph catalog must source entry rows from UI World vocabulary seeds"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: fixture.authID)"),
            "Knowledge Graph catalog must source auth from UI World auth seeds"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeVocabularyEntry(from: $0, notebookId: seed.notebookRemoteId)"),
            "Knowledge Graph catalog must materialize VocabularyEntry rows from UI World"
        )
        #expect(
            source.contains("initialGraphLinks: graphLinks"),
            "Knowledge Graph catalog must inject manifest-derived graph links"
        )
        #expect(
            source.contains("shouldLoadGraphData: false"),
            "Knowledge Graph catalog must disable remote graph task"
        )
        #expect(
            source.contains("summary.cardId"),
            "Knowledge Graph catalog graph links must be derived from UI World graphLinksByKind"
        )
    }

    @Test func kgVocabRowCatalogUsesUIWorldVocabularySeed() throws {
        let rowScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("KGVocabRowScenarios.swift")
        let source = try String(contentsOf: rowScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("= VocabularyEntry(", "KG Vocab Row catalog must not inline SwiftData row literals"),
            ("return VocabularyEntry(", "KG Vocab Row catalog must not inline SwiftData row literals"),
            ("Sample Book", "KG Vocab Row book metadata belongs in UI World"),
            ("word:", "KG Vocab Row catalog must not keep local word data"),
            ("translation:", "KG Vocab Row catalog must not keep local translation data"),
            ("partOfSpeech:", "KG Vocab Row catalog must not keep local part-of-speech data"),
            ("meticulous", "KG Vocab Row words must come from UI World"),
            ("nuance", "KG Vocab Row words must come from UI World"),
            ("ephemeral", "KG Vocab Row words must come from UI World"),
            ("serendipity", "KG Vocab Row words must come from UI World"),
            ("quintessential", "KG Vocab Row words must come from UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(rowScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: .kgVocabRow)"),
            "KG Vocab Row catalog must source row entries from UI World vocabulary.kgVocabRow"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeVocabularyEntry(from: seed.entries[fixture.entryIndex], notebookId: seed.notebookRemoteId)"),
            "KG Vocab Row catalog must materialize VocabularyEntry from UI World rows"
        )
        #expect(
            source.contains("seed.entries.count == KGVocabRowFixture.allCases.count"),
            "KG Vocab Row catalog must fail fast when manifest row count drifts from scenario states"
        )
    }

    @Test func vocabLinkedCardCatalogUsesUIWorldVocabularySeed() throws {
        let vocabScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("VocabScenarios.swift")
        let source = try String(contentsOf: vocabScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("sampleEntry", "Vocabulary linked-card catalog must not keep local entry factories"),
            ("= VocabularyEntry(", "Vocabulary linked-card catalog must not inline SwiftData row literals"),
            ("return VocabularyEntry(", "Vocabulary linked-card catalog must not inline SwiftData row literals"),
            ("Sample Book", "Vocabulary linked-card book metadata belongs in UI World"),
            ("word:", "Vocabulary linked-card catalog must not keep local word data"),
            ("translation:", "Vocabulary linked-card catalog must not keep local translation data"),
            ("partOfSpeech:", "Vocabulary linked-card catalog must not keep local part-of-speech data"),
            ("serendipity", "Vocabulary linked-card words must come from UI World"),
            ("epiphany", "Vocabulary linked-card words must come from UI World"),
            ("revelation", "Vocabulary linked-card words must come from UI World"),
            ("fortuitous", "Vocabulary linked-card words must come from UI World"),
            ("fortunate", "Vocabulary linked-card words must come from UI World"),
            ("happy accident", "Vocabulary linked-card words must come from UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(vocabScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: .vocabLinkedCards)"),
            "Vocabulary linked-card catalog must source rows from UI World vocabulary.vocabLinkedCards"
        )
        #expect(
            source.contains("seed.entries.count == 6"),
            "Vocabulary linked-card catalog must fail fast when manifest row count drifts"
        )
        #expect(
            source.contains("UITestFixtureSeed.makeVocabularyEntry(from: seed.entries[$0], notebookId: seed.notebookRemoteId)"),
            "Vocabulary linked-card catalog must materialize VocabularyEntry from UI World rows"
        )
    }

    @Test func archivedVocabCatalogUsesUIWorldVocabularySeeds() throws {
        let archivedScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("ArchivedVocabScenarios.swift")
        let source = try String(contentsOf: archivedScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("ArchivedVocabFixtures", "Archived Vocab catalog must not keep local archived entry fixtures"),
            ("VocabularyEntry(", "Archived Vocab catalog must not inline SwiftData row literals"),
            ("Sample Book", "Archived Vocab book metadata belongs in UI World"),
            ("entries: []", "Archived Vocab empty state must be a UI World seed"),
            ("try? context.save()", "Archived Vocab catalog SwiftData save must fail fast"),
            ("try? container.mainContext.save()", "Archived Vocab catalog SwiftData save must fail fast"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(archivedScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)"),
            "Archived Vocab catalog must source rows from UI World archived vocabulary seeds"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "Archived Vocab catalog must materialize UI World vocabulary rows into SwiftData"
        )
        #expect(
            source.contains("visible = entries.filter(\\.shouldAppearInArchiveList)"),
            "Archived Vocab catalog must validate manifest rows are visible archived entries"
        )
    }

    @Test func vocabularyListCatalogUsesUIWorldVocabularyAndAuthSeeds() throws {
        let listScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("VocabularyListViewScenarios.swift")
        let source = try String(contentsOf: listScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("VocabularyListViewFixtures", "Vocabulary List catalog must not keep local vocabulary fixtures"),
            ("VocabularyEntry(", "Vocabulary List catalog must not inline SwiftData row literals"),
            ("Notebook(remoteId:", "Vocabulary List catalog notebook must come from UI World"),
            ("Sample Book", "Vocabulary List book metadata belongs in UI World"),
            ("entries: []", "Vocabulary List empty/logged-out states must use UI World seeds"),
            ("try? context.save()", "Vocabulary List catalog SwiftData save must fail fast"),
            ("try? container.mainContext.save()", "Vocabulary List catalog SwiftData save must fail fast"),
            ("catalog-vocabulary-user", "Vocabulary List auth user must come from UI World"),
            ("catalog-vocabulary-token", "Vocabulary List auth token must come from UI World"),
            ("Catalog Vocabulary User", "Vocabulary List auth display name must come from UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(listScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)"),
            "Vocabulary List catalog must source rows from UI World vocabulary list seeds"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: authID)"),
            "Vocabulary List catalog must source auth from UI World auth seeds"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "Vocabulary List catalog must materialize UI World vocabulary rows into SwiftData"
        )
        #expect(
            source.contains("visible = entries.filter(\\.shouldAppearInKnowledgeList)"),
            "Vocabulary List catalog must validate manifest rows are visible knowledge-list entries"
        )
    }

    @Test func statsViewCatalogUsesUIWorldVocabularyReviewSeeds() throws {
        let statsScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("StatsViewScenarios.swift")
        let source = try String(contentsOf: statsScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("StatsViewFixtures", "Stats View catalog must not keep local vocabulary/review fixtures"),
            ("VocabularyEntry(", "Stats View catalog must not inline SwiftData row literals"),
            ("ReviewRecord(", "Stats View catalog review history must come from UI World"),
            ("Sample Book", "Stats View book metadata belongs in UI World"),
            ("entries: []", "Stats View empty state must use a UI World seed"),
            ("records: []", "Stats View empty review history must use a UI World seed"),
            ("try? context.save()", "Stats View catalog SwiftData save must fail fast"),
            ("try? container.mainContext.save()", "Stats View catalog SwiftData save must fail fast"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(statsScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)"),
            "Stats View catalog must source entries and review history from UI World vocabulary stats seeds"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "Stats View catalog must materialize UI World vocabulary/review rows into SwiftData"
        )
        #expect(
            source.contains("visibleEntries = entries.filter(\\.shouldAppearInKnowledgeList)"),
            "Stats View catalog must validate manifest rows are visible stats entries"
        )
        #expect(
            source.contains("FetchDescriptor<ReviewRecord>()"),
            "Stats View catalog must validate UI World reviewHistory materialized as ReviewRecord rows"
        )
    }

    @Test func reviewCalendarCatalogUsesUIWorldVocabularyReviewSeeds() throws {
        let calendarScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("ReviewCalendarScenarios.swift")
        let source = try String(contentsOf: calendarScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("ReviewCalendarSeed", "Review Calendar catalog must not keep local review history fixtures"),
            ("var records:", "Review Calendar catalog records must come from UI World reviewHistory"),
            ("return []", "Review Calendar empty state must use a UI World seed"),
            ("ReviewRecord(", "Review Calendar catalog must not inline review records"),
            ("try! ModelContainer", "Review Calendar catalog must fail fast with explicit materialization errors"),
            ("Date()", "Review Calendar record dates must come from UI World reviewHistory"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(calendarScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)"),
            "Review Calendar catalog must source review history from UI World vocabulary seeds"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "Review Calendar catalog must materialize UI World reviewHistory into SwiftData"
        )
        #expect(
            source.contains("FetchDescriptor<ReviewRecord>()"),
            "Review Calendar catalog must validate UI World reviewHistory materialized as ReviewRecord rows"
        )
    }

    @Test func todayReviewPhaseCatalogUsesUIWorldReviewDeckAndAuthSeeds() throws {
        let phaseScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("TodayReviewPhaseScenarios.swift")
        let source = try String(contentsOf: phaseScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("TodayReviewPhaseScenarioFixtures", "Today Review Phase catalog must not keep local review deck fixtures"),
            ("VocabularyEntry(", "Today Review Phase catalog must not inline SwiftData row literals"),
            ("preview-user", "Today Review Phase user id must come from UI World auth"),
            ("modelContainer(for:", "Today Review Phase session must use the manifest-backed container"),
            ("syncState = .synced", "Today Review Phase row sync state belongs in UI World reviewDeck entries"),
            ("reviewMode = .recognition", "Today Review Phase review mode belongs in UI World reviewDeck entries"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(phaseScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireReviewDeckSeed(for: fixture.reviewDeckID)"),
            "Today Review Phase catalog must source session cards from UI World reviewDeck seeds"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: .signedIn)"),
            "Today Review Phase catalog must source session user state from UI World auth seeds"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertReviewDeckSeed(reviewSeed, into: container.mainContext)"),
            "Today Review Phase catalog must materialize UI World reviewDeck rows into SwiftData"
        )
        #expect(
            source.contains("entries.count == fixture.expectedEntryCount"),
            "Today Review Phase catalog must validate reviewDeck row count drift"
        )
    }

    @Test func notebookFilterChipCatalogUsesUIWorldNotebookSeeds() throws {
        let filterScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("NotebookFilterChipScenarios.swift")
        let source = try String(contentsOf: filterScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("sampleNotebooks", "Notebook filter catalog must not keep local notebook fixtures"),
            ("Notebook(remoteId:", "Notebook filter catalog must not inline notebook rows"),
            ("notebooks: []", "Notebook filter empty state must be an explicit UI World seed"),
            ("nb-1", "Notebook filter selected id must come from UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(filterScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("NotebookFixtures.renderModel(for: fixture)"),
            "Notebook filter catalog must materialize notebooks through UI World NotebookFixtures"
        )
        #expect(
            source.contains("fixture: .empty"),
            "Notebook filter catalog empty state must use UI World notebook.empty"
        )
    }

    @Test func notebookListCatalogUsesUIWorldNotebookSeedsAndAuth() throws {
        let listScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("NotebookListViewScenarios.swift")
        let source = try String(contentsOf: listScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("catalog-notebook-user", "Notebook List auth userId belongs in UI World auth.signedIn"),
            ("catalog-notebook-token", "Notebook List auth token belongs in UI World auth.signedIn"),
            ("Catalog Notebook User", "Notebook List auth displayName belongs in UI World auth.signedIn"),
            ("catalog-notebook@example.com", "Notebook List auth email belongs in UI World auth.signedIn"),
            ("isLoggedIn: true", "Notebook List auth state must come from UI World auth.signedIn"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(listScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("NotebookFixtures.renderModel(for: fixture).container"),
            "Notebook List catalog must source notebooks from UI World notebook seeds"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: .signedIn)"),
            "Notebook List catalog must source auth from UI World auth.signedIn"
        )
        #expect(
            source.contains("UI World auth.signedIn must be logged in for NotebookListViewScenarios"),
            "Notebook List catalog must fail fast when signedIn auth drifts"
        )
    }

    @Test func notebookCoverCatalogUsesUIWorldNotebookAssetSeed() throws {
        let coverScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("NotebookCoverScenarios.swift")
        let source = try String(contentsOf: coverScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("__kg_catalog_nonexistent_cover__", "Notebook Cover catalog must not exercise missing-path fallback"),
            ("Image path fallback", "Notebook Cover catalog must not name or preserve fallback scenarios"),
            ("patternGrid", "Notebook Cover catalog pattern matrix must come from UI World rows"),
            ("swatches", "Notebook Cover catalog colors must come from UI World rows"),
            ("Color(hex:", "Notebook Cover catalog colors must come from UI World notebook color"),
            ("coverImagePath: \"/tmp/", "Notebook Cover catalog must not inline local image paths"),
            ("Fallback", "Notebook Cover catalog must not use fallback fixture labels"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(coverScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("NotebookFixtures.notebooks(for: .coverGallery)"),
            "Notebook Cover catalog must source covers from UI World notebook.coverGallery"
        )
        #expect(
            source.contains("NotebookPalette.color(for: notebook.color)"),
            "Notebook Cover catalog must derive colors from manifest notebook rows"
        )
        #expect(
            source.contains("notebook.coverPattern.flatMap(NotebookCoverPattern.init(rawValue:))"),
            "Notebook Cover catalog must derive patterns from manifest notebook rows"
        )
        #expect(
            source.contains("FileManager.default.fileExists(atPath: path)"),
            "Notebook Cover catalog must validate image-backed covers are installed"
        )
    }

    @Test func notebooksCardCatalogUsesUIWorldCardGallerySeed() throws {
        let cardScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("NotebooksScenarios.swift")
        let source = try String(contentsOf: cardScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("NotebookCardData(", "Notebooks card catalog must not construct local card data"),
            ("Date().addingTimeInterval", "Notebooks card lastActivity belongs in UI World"),
            ("我的學測必背 7000", "Notebooks card long title belongs in UI World"),
            ("cardCount: 626", "Notebooks card metrics belong in UI World"),
            ("dueCount: 538", "Notebooks card metrics belong in UI World"),
            ("pendingCount: 2", "Notebooks card metrics belong in UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(cardScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("NotebookFixtures.cardData(for: .cardGallery)"),
            "Notebooks card catalog must source card data from UI World notebook.cardGallery"
        )
        #expect(
            source.contains("UI World notebook.cardGallery is missing"),
            "Notebooks card catalog must fail fast when expected card states drift"
        )
    }

    @Test func notebookEditCatalogUsesUIWorldEditGallerySeed() throws {
        let editScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("NotebookEditSheetScenarios.swift")
        let source = try String(contentsOf: editScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("mode: .create", "Notebook Edit create mode must come from UI World"),
            ("mode: .edit(", "Notebook Edit edit mode must come from UI World"),
            ("GRE 高頻字", "Notebook Edit names belong in UI World"),
            ("雅思核心詞彙", "Notebook Edit names belong in UI World"),
            ("莎士比亞十四行詩", "Notebook Edit long names belong in UI World"),
            ("#AFC2D3", "Notebook Edit colors belong in UI World"),
            ("#DCABA4", "Notebook Edit colors belong in UI World"),
            ("NotebookCoverPattern.allCases", "Notebook Edit patterns belong in UI World"),
            ("coverImagePath: nil", "Notebook Edit image state belongs in UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(editScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("NotebookFixtures.editSheetMode(id: stateID, for: .editGallery)"),
            "Notebook Edit catalog must source mode state from UI World notebook.editGallery"
        )
    }

    @Test func readerNotebookPickerCatalogUsesUIWorldNotebookAndBookSeeds() throws {
        let pickerScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("ReaderNotebookPickerScenarios.swift")
        let source = try String(contentsOf: pickerScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("sampleNotebooks", "Reader notebook picker catalog must not keep local notebook fixtures"),
            ("manyNotebooks", "Reader notebook picker catalog must not generate local notebook fixtures"),
            ("Notebook(remoteId:", "Reader notebook picker catalog must not inline notebook rows"),
            ("Book(", "Reader notebook picker book row must come from UI World bookshelf seed"),
            ("The Sample Book", "Reader notebook picker book metadata belongs in UI World"),
            ("try!", "Reader notebook picker catalog must fail fast with explicit precondition failure"),
            ("notebooks: []", "Reader notebook picker empty state must be a UI World seed"),
            ("nb-green", "Reader notebook picker selected notebook id must come from UI World"),
            ("nb-12", "Reader notebook picker selected notebook id must come from UI World"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(pickerScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("NotebookFixtures.notebooks(for: fixture.notebookID)"),
            "Reader notebook picker catalog must source notebooks from UI World notebook seeds"
        )
        #expect(
            source.contains("BookshelfFixtures.books(for: fixture.bookshelfID)"),
            "Reader notebook picker catalog must source current book binding from UI World bookshelf seeds"
        )
        #expect(
            source.contains("notebooks.count == fixture.expectedNotebookCount"),
            "Reader notebook picker catalog must fail fast when notebook row count drifts"
        )
        #expect(
            source.contains("notebooks.contains { $0.remoteId == boundId }"),
            "Reader notebook picker catalog must validate book preferredNotebookId resolves to a seeded notebook"
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

    @Test func syncViewCatalogUsesUIWorldVocabularyAndAuthSeeds() throws {
        let syncScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SyncViewScenarios.swift")
        let source = try String(contentsOf: syncScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("private static func pending", "Sync View catalog must not locally construct pending vocabulary rows"),
            ("VocabularyEntry(", "Sync View catalog must not inline SwiftData row literals"),
            ("Sample Book", "Sync View catalog book metadata belongs in UI World"),
            ("try? context.save()", "Sync View catalog SwiftData save must fail fast"),
            ("try? container.mainContext.save()", "Sync View catalog SwiftData save must fail fast"),
            ("isLoggedIn: false", "logged-out state belongs in UI World auth.guest"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(syncScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireVocabularySeed(for: fixture.vocabularyID)"),
            "Sync View catalog must source rows from UI World vocabulary sync seeds"
        )
        #expect(
            source.contains("FixtureDatasetStore.requireAuthSeed(for: .guest)"),
            "Sync View catalog must source logged-out auth from UI World auth.guest"
        )
        #expect(
            source.contains("UITestFixtureSeed.insertVocabularySeed(seed, into: container.mainContext)"),
            "Sync View catalog must materialize UI World vocabulary rows into SwiftData"
        )
    }

    @Test func syncPresenterCatalogUsesUIWorldSyncPresenterSeeds() throws {
        let syncScenarios = debugDirectory
            .appendingPathComponent("Scenarios", isDirectory: true)
            .appendingPathComponent("SyncScenarios.swift")
        let source = try String(contentsOf: syncScenarios, encoding: .utf8)
        let forbidden: [(String, String)] = [
            ("readyState", "ready presenter state must be a UI World syncPresenter seed"),
            ("runningState", "running presenter state must be a UI World syncPresenter seed"),
            ("completedState", "completed presenter state must be a UI World syncPresenter seed"),
            ("partialFailureState", "partial failure presenter state must be a UI World syncPresenter seed"),
            ("fullFailureState", "full failure presenter state must be a UI World syncPresenter seed"),
            ("pendingRow(word:", "pending rows must be declared in UI World syncPresenter"),
            ("step(id:", "pipeline steps must be declared in UI World syncPresenter"),
            ("isLoggedIn: true", "auth state belongs in UI World syncPresenter"),
            ("isLoggedIn: false", "auth state belongs in UI World syncPresenter"),
            ("ineffable", "pending words belong in UI World syncPresenter"),
            ("ephemeral", "pending words belong in UI World syncPresenter"),
            ("obsolete", "pending words belong in UI World syncPresenter"),
            ("網路連線中斷", "failure summary belongs in UI World syncPresenter"),
            ("上傳新單字", "step labels belong in UI World syncPresenter"),
            ("刪除 Books & Vocab 單字", "step labels belong in UI World syncPresenter"),
        ]
        for (snippet, reason) in forbidden {
            #expect(!source.contains(snippet), "\(syncScenarios.lastPathComponent): \(reason)")
        }
        #expect(
            source.contains("FixtureDatasetStore.requireSyncPresenterSeed(for: fixtureID)"),
            "Sync presenter catalog must fail fast through UI World syncPresenter seeds"
        )
        #expect(
            source.contains("seed.pendingCount == seed.addCount + seed.deleteCount"),
            "Sync presenter catalog must validate pending/add/delete count consistency"
        )
        #expect(
            source.contains("UI World syncPresenter."),
            "Sync presenter catalog failure messages must identify the manifest domain"
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
