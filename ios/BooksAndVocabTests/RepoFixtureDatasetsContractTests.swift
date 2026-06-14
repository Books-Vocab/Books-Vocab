#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

/// Contract gate for every named UI World under `ops/fixtures/ui_worlds/`.
///
/// `FixtureDatasetStore` is the UI World SoT. A broken dataset must be caught at
/// the contract boundary: each repo dataset must decode, carry a `datasetID`
/// matching its filename, and only key into fixture IDs that exist in the Swift
/// registries.
struct RepoFixtureDatasetsContractTests {
    private static var datasetsDirectory: URL {
        // …/ios/BooksAndVocabTests/RepoFixtureDatasetsContractTests.swift → repo root
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repo root
            .appendingPathComponent("ops/fixtures/ui_worlds", isDirectory: true)
    }

    private static func datasetURLs() throws -> [URL] {
        try FileManager.default
            .contentsOfDirectory(at: datasetsDirectory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    @Test func repoContainsAtLeastOneDataset() throws {
        #expect(try !Self.datasetURLs().isEmpty)
    }

    @Test func generatedDemoDatasetDecodes() throws {
        let url = Self.datasetsDirectory
            .deletingLastPathComponent() // ui_worlds
            .deletingLastPathComponent() // fixtures
            .appendingPathComponent("demo/generated/ios_fixture_dataset.json")
        let data = try Data(contentsOf: url)
        let document = try FixtureDatasetStore.decode(data)

        #expect(document.schema == "kg.fixture.dataset.v2")
        #expect(document.datasetID == "demo-demo-user")
        #expect(document.assets.isEmpty)
        #expect(document.auth["signedIn"]?.isLoggedIn == true)
        #expect(document.auth["signedIn"]?.keychainTokenState == .available)
        #expect(document.entitlements["pro"]?.pro.is_active == true)
    }

    @Test func everyRepoDatasetDeclaresValidAssetManifest() throws {
        for url in try Self.datasetURLs() {
            let data = try Data(contentsOf: url)
            let document = try FixtureDatasetStore.decode(data)
            let stem = url.deletingPathExtension().lastPathComponent

            #expect(document.schema == "kg.fixture.dataset.v2", "\(stem): repo UI Worlds must use the asset-manifest schema")
            #expect(!document.assets.isEmpty, "\(stem): repo UI Worlds must declare assets")
            #expect(!document.preferences.isEmpty, "\(stem): repo UI Worlds must declare preferences")
            let topLevel = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
            expectNoLegacyAssetPathKeys(topLevel, dataset: stem)
            expectAuthKeychainStateKeys(topLevel, dataset: stem)
            expectRuntimePodcastDownloadKeys(topLevel, dataset: stem)
            expectSwiftDataRowStateKeys(topLevel, dataset: stem)
            expectValidPreferenceKeys(document.preferences.userDefaults.keys, dataset: stem, domain: "preferences.userDefaults")
            expectValidPreferenceKeys(document.preferences.ubiquitousKeyValueStore.keys, dataset: stem, domain: "preferences.ubiquitousKeyValueStore")

            for ref in document.assets.refs {
                let asset = try #require(document.assets.asset(for: ref), "\(stem): asset \(ref) must resolve")
                let url = URL(fileURLWithPath: asset.sourcePath)
                #expect(asset.byteSize > 0, "\(stem): asset \(ref) byteSize must be positive")
                #expect(FileManager.default.fileExists(atPath: url.path), "\(stem): asset \(ref) missing at \(url.path)")
                #expect(
                    try FixtureDatasetStore.byteSize(for: url) == asset.byteSize,
                    "\(stem): asset \(ref) byteSize drift"
                )
                #expect(
                    try FixtureDatasetStore.sha256Hex(for: url) == asset.sha256,
                    "\(stem): asset \(ref) sha256 drift"
                )
            }
            expectUniqueInstallPaths(document: document, dataset: stem)

            for (fixtureKey, seed) in document.runtimePodcast {
                expectInstallableAssetRef(
                    seed.audioAssetRef,
                    document: document,
                    dataset: stem,
                    owner: "runtimePodcast.\(fixtureKey).audioAssetRef"
                )
                expectInstallableAssetRef(
                    seed.subtitleAssetRef,
                    document: document,
                    dataset: stem,
                    owner: "runtimePodcast.\(fixtureKey).subtitleAssetRef"
                )
                for episode in seed.episodes {
                    guard let download = episode.download else { continue }
                    expectInstallableAssetRef(
                        download.audioAssetRef,
                        document: document,
                        dataset: stem,
                        owner: "runtimePodcast.\(fixtureKey).episode.\(episode.remoteId).download.audioAssetRef"
                    )
                    if let subtitleAssetRef = download.subtitleAssetRef {
                        expectInstallableAssetRef(
                            subtitleAssetRef,
                            document: document,
                            dataset: stem,
                            owner: "runtimePodcast.\(fixtureKey).episode.\(episode.remoteId).download.subtitleAssetRef"
                        )
                    }
                }
            }

            for (fixtureKey, seed) in document.reader {
                expectNotebookSyncStatus(
                    seed.notebookSyncStatus,
                    dataset: stem,
                    owner: "reader.\(fixtureKey).notebookSyncStatus"
                )
                expectVocabularyRowState(
                    seed.entry,
                    dataset: stem,
                    owner: "reader.\(fixtureKey).entry.\(seed.entry.word)"
                )
                expectInstallableAssetRef(
                    seed.textAssetRef,
                    document: document,
                    dataset: stem,
                    owner: "reader.\(fixtureKey).textAssetRef"
                )
            }

            for (fixtureKey, seed) in document.bookshelf {
                for book in seed.books {
                    guard let ref = book.bookAssetRef?.trimmingCharacters(in: .whitespacesAndNewlines),
                          !ref.isEmpty else {
                        Issue.record("\(stem): bookshelf.\(fixtureKey) book \(book.title) is missing bookAssetRef")
                        continue
                    }
                    expectBookAssetRef(
                        ref,
                        document: document,
                        dataset: stem,
                        owner: "bookshelf.\(fixtureKey).\(book.title)",
                        fileName: book.fileName
                    )
                }
            }

            for (fixtureKey, seed) in document.notebook {
                for notebook in seed.notebooks {
                    expectNotebookSyncStatus(
                        notebook.syncStatus,
                        dataset: stem,
                        owner: "notebook.\(fixtureKey).\(notebook.remoteId).syncStatus"
                    )
                    for entry in notebook.entries {
                        expectNotebookEntryRowState(
                            entry,
                            dataset: stem,
                            owner: "notebook.\(fixtureKey).\(notebook.remoteId).entry.\(entry.word)"
                        )
                    }
                }
            }

            for (fixtureKey, seed) in document.vocabulary {
                expectNotebookSyncStatus(
                    seed.notebookSyncStatus,
                    dataset: stem,
                    owner: "vocabulary.\(fixtureKey).notebookSyncStatus"
                )
                for entry in seed.entries {
                    expectVocabularyRowState(
                        entry,
                        dataset: stem,
                        owner: "vocabulary.\(fixtureKey).entry.\(entry.word)"
                    )
                }
            }

            for (fixtureKey, seed) in document.reviewDeck {
                expectNotebookSyncStatus(
                    seed.notebookSyncStatus,
                    dataset: stem,
                    owner: "reviewDeck.\(fixtureKey).notebookSyncStatus"
                )
                for entry in seed.entries {
                    expectVocabularyRowState(
                        entry,
                        dataset: stem,
                        owner: "reviewDeck.\(fixtureKey).entry.\(entry.word)"
                    )
                }
            }

            for (fixtureKey, seed) in document.auth {
                expectAuthKeychainState(
                    seed,
                    dataset: stem,
                    owner: "auth.\(fixtureKey)"
                )
            }
        }
    }

    @Test func everyRepoDatasetDecodesAndMatchesKnownFixtureIDs() throws {
        for url in try Self.datasetURLs() {
            let data = try Data(contentsOf: url)
            let document = try FixtureDatasetStore.decode(data)
            let stem = url.deletingPathExtension().lastPathComponent

            #expect(document.schema == "kg.fixture.dataset.v2", "\(stem): unexpected schema")
            #expect(document.datasetID == stem, "\(stem): datasetID must match filename")

            // Keyed decoding ignores unknown top-level keys, so a domain-level
            // typo ("podcasts") silently drops the whole domain — exactly the
            // failure class this suite exists to close.
            let topLevel = try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
            let unknownTopLevel = Set(topLevel.keys).subtracting(FixtureDatasetDocument.knownTopLevelKeys)
            #expect(
                unknownTopLevel.isEmpty,
                "\(stem): unknown top-level keys \(unknownTopLevel.sorted()) would be silently ignored"
            )

            expectKnownKeys(document.settings.keys, SettingsFixtureID.self, domain: "settings", dataset: stem)
            expectKnownKeys(document.auth.keys, UIWorldAuthFixtureID.self, domain: "auth", dataset: stem)
            expectKnownKeys(document.entitlements.keys, UIWorldEntitlementsFixtureID.self, domain: "entitlements", dataset: stem)
            expectKnownKeys(document.bookshelf.keys, BookshelfFixtureID.self, domain: "bookshelf", dataset: stem)
            expectKnownKeys(document.todayReview.keys, TodayReviewFixtureID.self, domain: "todayReview", dataset: stem)
            expectKnownKeys(document.notebook.keys, NotebookFixtureID.self, domain: "notebook", dataset: stem)
            expectKnownKeys(document.podcast.keys, PodcastFixtureID.self, domain: "podcast", dataset: stem)
            expectKnownKeys(document.runtimePodcast.keys, UIWorldRuntimePodcastFixtureID.self, domain: "runtimePodcast", dataset: stem)
            expectKnownKeys(document.reader.keys, UIWorldReaderFixtureID.self, domain: "reader", dataset: stem)
            expectKnownKeys(document.vocabulary.keys, UIWorldVocabularyFixtureID.self, domain: "vocabulary", dataset: stem)
            expectKnownKeys(document.reviewDeck.keys, UIWorldReviewDeckFixtureID.self, domain: "reviewDeck", dataset: stem)

            // Duplicate identities render undefined (ForEach ids / notebookId
            // joins derive from them), so they must be unique within a seed.
            for (fixtureKey, seed) in document.podcast {
                let numbers = seed.episodes.map(\.episodeNumber)
                #expect(
                    Set(numbers).count == numbers.count,
                    "\(stem): podcast.\(fixtureKey) has duplicate episodeNumber values"
                )
            }
            for (fixtureKey, seed) in document.notebook {
                let ids = seed.notebooks.map(\.remoteId)
                #expect(
                    Set(ids).count == ids.count,
                    "\(stem): notebook.\(fixtureKey) has duplicate notebook remoteId values"
                )
            }
            for (fixtureKey, seed) in document.runtimePodcast {
                let ids = seed.episodes.map(\.remoteId)
                #expect(
                    Set(ids).count == ids.count,
                    "\(stem): runtimePodcast.\(fixtureKey) has duplicate episode remoteId values"
                )
            }
            for (fixtureKey, seed) in document.reviewDeck {
                let words = seed.entries.map(\.word)
                #expect(
                    Set(words).count == words.count,
                    "\(stem): reviewDeck.\(fixtureKey) has duplicate word values"
                )
            }
        }
    }

    private func expectKnownKeys<ID: RawRepresentable & CaseIterable>(
        _ keys: some Sequence<String>,
        _ idType: ID.Type,
        domain: String,
        dataset: String
    ) where ID.RawValue == String {
        let known = Set(idType.allCases.map(\.rawValue))
        let unknown = Set(keys).subtracting(known)
        #expect(
            unknown.isEmpty,
            "\(dataset): domain \(domain) keys \(unknown.sorted()) have no matching fixture ID — they would silently never render"
        )
    }

    private func expectNoLegacyAssetPathKeys(_ topLevel: [String: Any], dataset: String) {
        let runtimePodcast = topLevel["runtimePodcast"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in runtimePodcast {
            let legacy = Set(seed.keys).intersection(["audioPath", "subtitlePath"])
            #expect(
                legacy.isEmpty,
                "\(dataset): runtimePodcast.\(fixtureKey) uses legacy bare path keys \(legacy.sorted()); use audioAssetRef/subtitleAssetRef"
            )
        }

        let reader = topLevel["reader"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in reader {
            let legacy = Set(seed.keys).intersection(["textPath"])
            #expect(
                legacy.isEmpty,
                "\(dataset): reader.\(fixtureKey) uses legacy bare path keys \(legacy.sorted()); use textAssetRef"
            )
        }
    }

    private func expectRuntimePodcastDownloadKeys(_ topLevel: [String: Any], dataset: String) {
        let runtimePodcast = topLevel["runtimePodcast"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in runtimePodcast {
            let episodes = seed["episodes"] as? [[String: Any]] ?? []
            for episode in episodes {
                let remoteId = episode["remoteId"] as? String ?? "<missing-remote-id>"
                #expect(
                    episode.keys.contains("download"),
                    "\(dataset): runtimePodcast.\(fixtureKey).episode.\(remoteId) must explicitly declare download (object or null)"
                )
            }
        }
    }

    private func expectAuthKeychainStateKeys(_ topLevel: [String: Any], dataset: String) {
        let authFixtures = topLevel["auth"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in authFixtures {
            #expect(
                seed.keys.contains("keychainTokenState"),
                "\(dataset): auth.\(fixtureKey) must explicitly declare keychainTokenState"
            )
        }
    }

    private func expectSwiftDataRowStateKeys(_ topLevel: [String: Any], dataset: String) {
        let requiredEntryKeys: Set<String> = ["syncStatus", "actionType", "isArchived", "isExcludedFromReader"]
        let requiredUIWorldEntryKeys = requiredEntryKeys.union(["bookTitle", "reviewMode"])

        let notebookFixtures = topLevel["notebook"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in notebookFixtures {
            let notebooks = seed["notebooks"] as? [[String: Any]] ?? []
            for notebook in notebooks {
                let remoteId = notebook["remoteId"] as? String ?? "<missing-remote-id>"
                #expect(
                    notebook.keys.contains("syncStatus"),
                    "\(dataset): notebook.\(fixtureKey).\(remoteId) must explicitly declare syncStatus"
                )
                let entries = notebook["entries"] as? [[String: Any]] ?? []
                for entry in entries {
                    let word = entry["word"] as? String ?? "<missing-word>"
                    let missing = requiredEntryKeys.subtracting(entry.keys)
                    #expect(
                        missing.isEmpty,
                        "\(dataset): notebook.\(fixtureKey).\(remoteId).entry.\(word) missing row state keys \(missing.sorted())"
                    )
                }
            }
        }

        let readerFixtures = topLevel["reader"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in readerFixtures {
            #expect(
                seed.keys.contains("notebookSyncStatus"),
                "\(dataset): reader.\(fixtureKey) must explicitly declare notebookSyncStatus"
            )
            if let entry = seed["entry"] as? [String: Any] {
                let word = entry["word"] as? String ?? "<missing-word>"
                let missing = requiredUIWorldEntryKeys.subtracting(entry.keys)
                #expect(
                    missing.isEmpty,
                    "\(dataset): reader.\(fixtureKey).entry.\(word) missing row state keys \(missing.sorted())"
                )
            }
        }

        for domain in ["vocabulary", "reviewDeck"] {
            let fixtures = topLevel[domain] as? [String: [String: Any]] ?? [:]
            for (fixtureKey, seed) in fixtures {
                #expect(
                    seed.keys.contains("notebookSyncStatus"),
                    "\(dataset): \(domain).\(fixtureKey) must explicitly declare notebookSyncStatus"
                )
                if domain == "reviewDeck" {
                    for key in ["notebookRemoteId", "notebookName"] {
                        #expect(
                            seed[key] is String,
                            "\(dataset): reviewDeck.\(fixtureKey) must explicitly declare non-null \(key)"
                        )
                    }
                }
                let entries = seed["entries"] as? [[String: Any]] ?? []
                for entry in entries {
                    let word = entry["word"] as? String ?? "<missing-word>"
                    let missing = requiredUIWorldEntryKeys.subtracting(entry.keys)
                    #expect(
                        missing.isEmpty,
                        "\(dataset): \(domain).\(fixtureKey).entry.\(word) missing row state keys \(missing.sorted())"
                    )
                }
            }
        }
    }

    private func expectNotebookSyncStatus(_ syncStatus: Int, dataset: String, owner: String) {
        #expect(
            [0, 1].contains(syncStatus),
            "\(dataset): \(owner) must be a valid Notebook.syncStatus (0=pending, 1=synced)"
        )
    }

    private func expectAuthKeychainState(
        _ seed: UIWorldAuthSeed,
        dataset: String,
        owner: String
    ) {
        switch seed.keychainTokenState {
        case .available:
            #expect(seed.isLoggedIn, "\(dataset): \(owner) keychainTokenState=available requires isLoggedIn=true")
            #expect(
                seed.token?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false,
                "\(dataset): \(owner) keychainTokenState=available requires non-empty token"
            )
        case .readFailed:
            #expect(seed.isLoggedIn, "\(dataset): \(owner) keychainTokenState=readFailed requires isLoggedIn=true")
            #expect(seed.userId != nil, "\(dataset): \(owner) keychainTokenState=readFailed requires persisted userId")
            #expect(seed.token == nil, "\(dataset): \(owner) keychainTokenState=readFailed must not also expose a readable token")
        case .absent:
            #expect(!seed.isLoggedIn, "\(dataset): \(owner) keychainTokenState=absent requires isLoggedIn=false")
            #expect(seed.token == nil, "\(dataset): \(owner) keychainTokenState=absent must not include token")
        }
    }

    private func expectVocabularyRowState(
        _ entry: UIWorldVocabularyEntrySeed,
        dataset: String,
        owner: String
    ) {
        expectVocabularyRowState(
            syncStatus: entry.syncStatus,
            actionType: entry.actionType,
            isArchived: entry.isArchived,
            isExcludedFromReader: entry.isExcludedFromReader,
            dataset: dataset,
            owner: owner
        )
    }

    private func expectNotebookEntryRowState(
        _ entry: NotebookEntrySeed,
        dataset: String,
        owner: String
    ) {
        expectVocabularyRowState(
            syncStatus: entry.syncStatus,
            actionType: entry.actionType,
            isArchived: entry.isArchived,
            isExcludedFromReader: entry.isExcludedFromReader,
            dataset: dataset,
            owner: owner
        )
    }

    private func expectVocabularyRowState(
        syncStatus: Int,
        actionType: String,
        isArchived: Bool,
        isExcludedFromReader: Bool,
        dataset: String,
        owner: String
    ) {
        #expect(
            [0, 1, 2].contains(syncStatus),
            "\(dataset): \(owner).syncStatus must be valid VocabularyEntry.syncStatus (0=pending, 1=synced, 2=failed)"
        )
        #expect(
            ["add", "delete", "edit"].contains(actionType),
            "\(dataset): \(owner).actionType must be add/delete/edit"
        )
        _ = isArchived
        _ = isExcludedFromReader
    }

    private func expectInstallableAssetRef(
        _ ref: String,
        document: FixtureDatasetDocument,
        dataset: String,
        owner: String
    ) {
        guard let asset = document.assets.asset(for: ref) else {
            Issue.record("\(dataset): \(owner) \(ref) is not declared")
            return
        }
        let installAs = asset.installAs?.trimmingCharacters(in: .whitespacesAndNewlines)
        #expect(
            installAs.map { !$0.isEmpty } ?? false,
            "\(dataset): \(owner) \(ref) must declare installAs so the asset is materialized into the app container"
        )
    }

    private func expectUniqueInstallPaths(document: FixtureDatasetDocument, dataset: String) {
        var seen: [String: String] = [:]
        for ref in document.assets.refs {
            guard let asset = document.assets.asset(for: ref),
                  let installAs = asset.installAs?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !installAs.isEmpty else {
                continue
            }
            if let previous = seen[installAs] {
                Issue.record("\(dataset): assets \(previous) and \(ref) share installAs \(installAs)")
            } else {
                seen[installAs] = ref
            }
        }
    }

    private func expectValidPreferenceKeys(
        _ keys: some Sequence<String>,
        dataset: String,
        domain: String
    ) {
        for key in keys {
            #expect(
                !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                "\(dataset): \(domain) contains an empty key"
            )
        }
    }

    private func expectBookAssetRef(
        _ ref: String,
        document: FixtureDatasetDocument,
        dataset: String,
        owner: String,
        fileName: String
    ) {
        #expect(ref.hasPrefix("books."), "\(dataset): \(owner) bookAssetRef must point into assets.books, got \(ref)")
        guard let asset = document.assets.asset(for: ref) else {
            Issue.record("\(dataset): \(owner) \(ref) is not declared")
            return
        }
        let installAs = asset.installAs?.trimmingCharacters(in: .whitespacesAndNewlines)
        #expect(
            installAs == "Books/\(fileName)",
            "\(dataset): \(owner) \(ref) must install as Books/\(fileName), got \(installAs ?? "<nil>")"
        )
    }
}
#endif
