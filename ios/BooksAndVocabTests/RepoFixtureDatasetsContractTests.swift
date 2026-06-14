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
        #expect(!document.assets.books.isEmpty)
        #expect(!document.assets.audio.isEmpty)
        #expect(!document.assets.subtitles.isEmpty)
        #expect(document.auth["signedIn"]?.isLoggedIn == true)
        #expect(document.auth["signedIn"]?.keychainTokenState == .available)
        #expect(document.entitlements["pro"]?.pro.is_active == true)
        #expect(Set(document.bookshelf.keys) == Set(BookshelfFixtureID.allCases.map(\.rawValue)))
        #expect(Set(document.podcast.keys) == Set(PodcastFixtureID.allCases.map(\.rawValue)))
        #expect(Set(document.runtimePodcast.keys) == Set(UIWorldRuntimePodcastFixtureID.allCases.map(\.rawValue)))
        #expect(Set(document.todayReview.keys) == Set(TodayReviewFixtureID.allCases.map(\.rawValue)))
        #expect(document.settings["preferences_auto_sync_off"] != nil)
        #expect(document.settings["preferences_logged_out_no_sync"] != nil)
        #expect(document.settings["subscription_free"]?.reviewSettings != nil)
        #expect(document.settings["preferences_auto_sync_off"]?.reviewSettings != nil)
        #expect(document.settings["account_long_identity"]?.reviewSettings != nil)
        #expect(document.settings["preferences_logged_out_no_sync"]?.reviewSettings != nil)
        #expect(Set(document.syncPresenter.keys) == Set(UIWorldSyncPresenterFixtureID.allCases.map(\.rawValue)))
        try expectValidAssetManifest(document: document, dataset: "ios_fixture_dataset")
        expectUniqueInstallPaths(document: document, dataset: "ios_fixture_dataset")
        expectRuntimePodcastAssetRefs(document: document, dataset: "ios_fixture_dataset")
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
            expectAuthUIStateKeys(topLevel, dataset: stem)
            expectCatalogPodcastPlaybackKeys(topLevel, dataset: stem)
            expectRuntimePodcastDownloadKeys(topLevel, dataset: stem)
            expectSwiftDataRowStateKeys(topLevel, document: document, dataset: stem)
            expectSyncPresenterKeys(topLevel, dataset: stem)
            expectValidPreferenceKeys(document.preferences.userDefaults.keys, dataset: stem, domain: "preferences.userDefaults")
            expectValidPreferenceKeys(document.preferences.ubiquitousKeyValueStore.keys, dataset: stem, domain: "preferences.ubiquitousKeyValueStore")

            try expectValidAssetManifest(document: document, dataset: stem)
            expectUniqueInstallPaths(document: document, dataset: stem)

            expectRuntimePodcastAssetRefs(document: document, dataset: stem)

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
                        fileName: book.fileName,
                        format: book.format
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
                    if let coverImageAssetRef = notebook.coverImageAssetRef {
                        expectAssetRef(
                            coverImageAssetRef,
                            document: document,
                            expectedPrefix: "images.",
                            dataset: stem,
                            owner: "notebook.\(fixtureKey).\(notebook.remoteId).coverImageAssetRef"
                        )
                    }
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
            expectKnownKeys(document.syncPresenter.keys, UIWorldSyncPresenterFixtureID.self, domain: "syncPresenter", dataset: stem)

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
            #expect(
                seed.keys.contains("sortOrder"),
                "\(dataset): runtimePodcast.\(fixtureKey) must explicitly declare sortOrder"
            )
            let episodes = seed["episodes"] as? [[String: Any]] ?? []
            for episode in episodes {
                let remoteId = episode["remoteId"] as? String ?? "<missing-remote-id>"
                for key in ["durationSec", "previewDurationSec"] {
                    #expect(
                        episode.keys.contains(key),
                        "\(dataset): runtimePodcast.\(fixtureKey).episode.\(remoteId) must explicitly declare \(key)"
                    )
                }
                #expect(
                    episode.keys.contains("download"),
                    "\(dataset): runtimePodcast.\(fixtureKey).episode.\(remoteId) must explicitly declare download (object or null)"
                )
            }
        }
    }

    private func expectCatalogPodcastPlaybackKeys(_ topLevel: [String: Any], dataset: String) {
        let podcast = topLevel["podcast"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in podcast {
            let episodes = seed["episodes"] as? [[String: Any]] ?? []
            for episode in episodes {
                let episodeNumber = episode["episodeNumber"] as? Int ?? -1
                #expect(
                    episode.keys.contains("durationSec"),
                    "\(dataset): podcast.\(fixtureKey).episode.\(episodeNumber) must explicitly declare durationSec"
                )
            }
        }
    }

    private func expectValidAssetManifest(document: FixtureDatasetDocument, dataset: String) throws {
        for ref in document.assets.refs {
            let asset = try #require(document.assets.asset(for: ref), "\(dataset): asset \(ref) must resolve")
            let url = URL(fileURLWithPath: asset.sourcePath)
            #expect(asset.byteSize > 0, "\(dataset): asset \(ref) byteSize must be positive")
            expectAssetContentType(asset, ref: ref, dataset: dataset)
            #expect(FileManager.default.fileExists(atPath: url.path), "\(dataset): asset \(ref) missing at \(url.path)")
            #expect(
                try FixtureDatasetStore.byteSize(for: url) == asset.byteSize,
                "\(dataset): asset \(ref) byteSize drift"
            )
            #expect(
                try FixtureDatasetStore.sha256Hex(for: url) == asset.sha256,
                "\(dataset): asset \(ref) sha256 drift"
            )
        }
    }

    private func expectAssetContentType(_ asset: UIWorldAsset, ref: String, dataset: String) {
        let contentType = asset.contentType.trimmingCharacters(in: .whitespacesAndNewlines)
        #expect(!contentType.isEmpty, "\(dataset): asset \(ref) contentType must not be empty")

        let allowedByDomain: [String: [String]] = [
            "books": ["application/epub+zip", "application/pdf", "text/markdown; charset=utf-8", "text/plain; charset=utf-8"],
            "audio": ["audio/mp4", "audio/mpeg"],
            "subtitles": ["application/x-subrip; charset=utf-8", "text/vtt; charset=utf-8"],
            "text": ["text/markdown; charset=utf-8", "text/plain; charset=utf-8"],
            "images": ["image/png", "image/jpeg"],
        ]
        let domain = ref.split(separator: ".", maxSplits: 1).first.map(String.init) ?? "<missing-domain>"
        #expect(
            allowedByDomain[domain]?.contains(contentType) == true,
            "\(dataset): asset \(ref) contentType \(contentType) is invalid for domain \(domain)"
        )

        let installExtension = asset.installAs.map { URL(fileURLWithPath: $0).pathExtension.lowercased() }
        let sourceExtension = URL(fileURLWithPath: asset.sourcePath).pathExtension.lowercased()
        let ext = installExtension?.isEmpty == false ? installExtension! : sourceExtension
        let expectedByExtension: [String: String] = [
            "epub": "application/epub+zip",
            "pdf": "application/pdf",
            "md": "text/markdown; charset=utf-8",
            "txt": "text/plain; charset=utf-8",
            "m4a": "audio/mp4",
            "mp3": "audio/mpeg",
            "srt": "application/x-subrip; charset=utf-8",
            "vtt": "text/vtt; charset=utf-8",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
        ]
        if let expected = expectedByExtension[ext] {
            #expect(
                contentType == expected,
                "\(dataset): asset \(ref) contentType \(contentType) must match .\(ext) as \(expected)"
            )
        }
    }

    private func expectRuntimePodcastAssetRefs(document: FixtureDatasetDocument, dataset: String) {
        for (fixtureKey, seed) in document.runtimePodcast {
            expectInstallableAssetRef(
                seed.audioAssetRef,
                document: document,
                dataset: dataset,
                owner: "runtimePodcast.\(fixtureKey).audioAssetRef"
            )
            expectInstallableAssetRef(
                seed.subtitleAssetRef,
                document: document,
                dataset: dataset,
                owner: "runtimePodcast.\(fixtureKey).subtitleAssetRef"
            )
            for episode in seed.episodes {
                guard let download = episode.download else { continue }
                expectInstallableAssetRef(
                    download.audioAssetRef,
                    document: document,
                    dataset: dataset,
                    owner: "runtimePodcast.\(fixtureKey).episode.\(episode.remoteId).download.audioAssetRef"
                )
                if let subtitleAssetRef = download.subtitleAssetRef {
                    expectInstallableAssetRef(
                        subtitleAssetRef,
                        document: document,
                        dataset: dataset,
                        owner: "runtimePodcast.\(fixtureKey).episode.\(episode.remoteId).download.subtitleAssetRef"
                    )
                }
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

    private func expectAuthUIStateKeys(_ topLevel: [String: Any], dataset: String) {
        let authFixtures = topLevel["auth"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in authFixtures {
            for key in ["authError", "isAuthenticating"] {
                #expect(
                    seed.keys.contains(key),
                    "\(dataset): auth.\(fixtureKey) must explicitly declare \(key)"
                )
            }
        }
    }

    private func expectSwiftDataRowStateKeys(_ topLevel: [String: Any], document: FixtureDatasetDocument, dataset: String) {
        let requiredEntryKeys: Set<String> = ["syncStatus", "actionType", "isArchived", "isExcludedFromReader"]
        let requiredNotebookEntryKeys = requiredEntryKeys.union(["context", "explanation", "partOfSpeech", "bookTitle", "chapterTitle"])
        let requiredUIWorldEntryKeys = requiredEntryKeys.union(["bookTitle", "reviewMode"])

        let notebookFixtures = topLevel["notebook"] as? [String: [String: Any]] ?? [:]
        for (fixtureKey, seed) in notebookFixtures {
            #expect(
                seed.keys.contains("editStates"),
                "\(dataset): notebook.\(fixtureKey) must explicitly declare editStates"
            )
            let editStates = seed["editStates"] as? [[String: Any]] ?? []
            for editState in editStates {
                expectNotebookEditStateKeys(
                    editState,
                    document: document,
                    dataset: dataset,
                    owner: "notebook.\(fixtureKey).editStates.\(editState["id"] as? String ?? "<missing-id>")"
                )
            }
            let notebooks = seed["notebooks"] as? [[String: Any]] ?? []
            for notebook in notebooks {
                let remoteId = notebook["remoteId"] as? String ?? "<missing-remote-id>"
                #expect(
                    notebook.keys.contains("syncStatus"),
                    "\(dataset): notebook.\(fixtureKey).\(remoteId) must explicitly declare syncStatus"
                )
                for key in ["isDefault", "sortOrder", "coverPattern", "coverImageAssetRef", "cardState"] {
                    #expect(
                        notebook.keys.contains(key),
                        "\(dataset): notebook.\(fixtureKey).\(remoteId) must explicitly declare \(key)"
                    )
                }
                if let cardState = notebook["cardState"] as? [String: Any] {
                    expectNotebookCardStateKeys(cardState, dataset: dataset, owner: "notebook.\(fixtureKey).\(remoteId).cardState")
                }
                let entries = notebook["entries"] as? [[String: Any]] ?? []
                for entry in entries {
                    let word = entry["word"] as? String ?? "<missing-word>"
                    let missing = requiredNotebookEntryKeys.subtracting(entry.keys)
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

    private func expectSyncPresenterKeys(_ topLevel: [String: Any], dataset: String) {
        guard let fixtures = topLevel["syncPresenter"] as? [String: [String: Any]] else {
            Issue.record("\(dataset): UI World must explicitly declare syncPresenter")
            return
        }
        let requiredSeedKeys: Set<String> = [
            "isLoggedIn",
            "isConnected",
            "phase",
            "failureKind",
            "pendingCount",
            "addCount",
            "deleteCount",
            "steps",
            "summaryText",
            "pendingRows",
        ]
        let requiredStepKeys: Set<String> = ["id", "label", "status", "current", "total", "detail"]
        let requiredPendingRowKeys: Set<String> = [
            "id",
            "word",
            "partOfSpeech",
            "translation",
            "wordTone",
            "isStrikethrough",
            "actionSystemImage",
            "actionTone",
            "actionAccessibilityLabel",
        ]
        let validPhases = ["ready", "running", "completed", "failed"]
        let validFailureKinds = ["partial", "full", "cancelled"]
        let validStepStatuses = ["waiting", "running", "retry", "done", "skipped", "error"]
        let validTones = ["primary", "secondary", "tertiary", "quaternary", "destructive", "reviewDue"]

        for (fixtureKey, seed) in fixtures {
            let missingSeedKeys = requiredSeedKeys.subtracting(seed.keys)
            #expect(
                missingSeedKeys.isEmpty,
                "\(dataset): syncPresenter.\(fixtureKey) missing keys \(missingSeedKeys.sorted())"
            )

            let phase = seed["phase"] as? String ?? "<missing-phase>"
            #expect(validPhases.contains(phase), "\(dataset): syncPresenter.\(fixtureKey).phase is invalid")
            if let failureKind = seed["failureKind"] as? String {
                #expect(
                    validFailureKinds.contains(failureKind),
                    "\(dataset): syncPresenter.\(fixtureKey).failureKind is invalid"
                )
                #expect(phase == "failed", "\(dataset): syncPresenter.\(fixtureKey) non-null failureKind requires failed phase")
            } else {
                #expect(
                    seed["failureKind"] is NSNull || seed.keys.contains("failureKind"),
                    "\(dataset): syncPresenter.\(fixtureKey).failureKind must be explicit null when absent"
                )
            }

            let pendingCount = seed["pendingCount"] as? Int ?? -1
            let addCount = seed["addCount"] as? Int ?? -1
            let deleteCount = seed["deleteCount"] as? Int ?? -1
            #expect(pendingCount >= 0, "\(dataset): syncPresenter.\(fixtureKey).pendingCount must be non-negative")
            #expect(addCount >= 0, "\(dataset): syncPresenter.\(fixtureKey).addCount must be non-negative")
            #expect(deleteCount >= 0, "\(dataset): syncPresenter.\(fixtureKey).deleteCount must be non-negative")
            #expect(
                pendingCount == addCount + deleteCount,
                "\(dataset): syncPresenter.\(fixtureKey).pendingCount must equal addCount + deleteCount"
            )

            let steps = seed["steps"] as? [[String: Any]] ?? []
            for step in steps {
                let id = step["id"] as? String ?? "<missing-id>"
                let missingStepKeys = requiredStepKeys.subtracting(step.keys)
                #expect(
                    missingStepKeys.isEmpty,
                    "\(dataset): syncPresenter.\(fixtureKey).steps.\(id) missing keys \(missingStepKeys.sorted())"
                )
                let status = step["status"] as? String ?? "<missing-status>"
                #expect(
                    validStepStatuses.contains(status),
                    "\(dataset): syncPresenter.\(fixtureKey).steps.\(id).status is invalid"
                )
                #expect((step["current"] as? Int ?? -1) >= 0, "\(dataset): syncPresenter.\(fixtureKey).steps.\(id).current must be non-negative")
                #expect((step["total"] as? Int ?? -1) >= 0, "\(dataset): syncPresenter.\(fixtureKey).steps.\(id).total must be non-negative")
            }

            let pendingRows = seed["pendingRows"] as? [[String: Any]] ?? []
            if phase == "ready" {
                #expect(
                    pendingRows.count == pendingCount,
                    "\(dataset): syncPresenter.\(fixtureKey).pendingRows count must equal pendingCount in ready phase"
                )
            }
            for row in pendingRows {
                let word = row["word"] as? String ?? "<missing-word>"
                let missingRowKeys = requiredPendingRowKeys.subtracting(row.keys)
                #expect(
                    missingRowKeys.isEmpty,
                    "\(dataset): syncPresenter.\(fixtureKey).pendingRows.\(word) missing keys \(missingRowKeys.sorted())"
                )
                let id = row["id"] as? String ?? ""
                #expect(UUID(uuidString: id) != nil, "\(dataset): syncPresenter.\(fixtureKey).pendingRows.\(word).id must be UUID")
                for key in ["wordTone", "actionTone"] {
                    let tone = row[key] as? String ?? "<missing-tone>"
                    #expect(
                        validTones.contains(tone),
                        "\(dataset): syncPresenter.\(fixtureKey).pendingRows.\(word).\(key) is invalid"
                    )
                }
            }
        }
    }

    private func expectNotebookEditStateKeys(_ editState: [String: Any], document: FixtureDatasetDocument, dataset: String, owner: String) {
        for key in ["id", "mode", "name", "color", "coverPattern", "coverImageAssetRef"] {
            #expect(editState.keys.contains(key), "\(dataset): \(owner) must explicitly declare \(key)")
        }
        let mode = editState["mode"] as? String ?? "<missing-mode>"
        #expect(["create", "edit"].contains(mode), "\(dataset): \(owner).mode must be create or edit")
        if mode == "create" {
            #expect((editState["name"] as? String ?? "<missing-name>").isEmpty, "\(dataset): \(owner) create mode must have an empty name")
            #expect(editState["color"] is NSNull, "\(dataset): \(owner) create mode color must be null")
            #expect(editState["coverPattern"] is NSNull, "\(dataset): \(owner) create mode coverPattern must be null")
            #expect(editState["coverImageAssetRef"] is NSNull, "\(dataset): \(owner) create mode coverImageAssetRef must be null")
        }
        if let coverPattern = editState["coverPattern"] as? String {
            #expect(!coverPattern.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "\(dataset): \(owner).coverPattern must not be blank")
        }
        if let coverImageAssetRef = editState["coverImageAssetRef"] as? String {
            expectAssetRef(
                coverImageAssetRef,
                document: document,
                expectedPrefix: "images.",
                dataset: dataset,
                owner: "\(owner).coverImageAssetRef"
            )
        }
    }

    private func expectNotebookCardStateKeys(_ cardState: [String: Any], dataset: String, owner: String) {
        for key in ["cardCount", "dueCount", "unlearnedCount", "reviewedCount", "pendingCount", "lastActivity", "isActive"] {
            #expect(cardState.keys.contains(key), "\(dataset): \(owner) must explicitly declare \(key)")
        }
        let cardCount = cardState["cardCount"] as? Int ?? -1
        let dueCount = cardState["dueCount"] as? Int ?? -1
        let unlearnedCount = cardState["unlearnedCount"] as? Int ?? -1
        let reviewedCount = cardState["reviewedCount"] as? Int ?? -1
        let pendingCount = cardState["pendingCount"] as? Int ?? -1
        #expect(cardCount >= 0, "\(dataset): \(owner).cardCount must be non-negative")
        #expect(dueCount >= 0, "\(dataset): \(owner).dueCount must be non-negative")
        #expect(unlearnedCount >= 0, "\(dataset): \(owner).unlearnedCount must be non-negative")
        #expect(reviewedCount >= 0, "\(dataset): \(owner).reviewedCount must be non-negative")
        #expect(pendingCount >= 0, "\(dataset): \(owner).pendingCount must be non-negative")
        #expect(
            cardCount == dueCount + unlearnedCount + reviewedCount,
            "\(dataset): \(owner).cardCount must equal dueCount + unlearnedCount + reviewedCount"
        )
        if cardState["isActive"] as? Bool == true {
            #expect(cardCount > 0, "\(dataset): \(owner) active card must not be empty")
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
        if seed.isLoggedIn {
            #expect(!seed.isAuthenticating, "\(dataset): \(owner) logged-in auth seed must not also be authenticating")
            #expect(seed.authError == nil, "\(dataset): \(owner) logged-in auth seed must not carry login error copy")
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

    private func expectAssetRef(
        _ ref: String,
        document: FixtureDatasetDocument,
        expectedPrefix: String,
        dataset: String,
        owner: String
    ) {
        #expect(ref.hasPrefix(expectedPrefix), "\(dataset): \(owner) must point into assets.\(expectedPrefix), got \(ref)")
        guard document.assets.asset(for: ref) != nil else {
            Issue.record("\(dataset): \(owner) \(ref) is not declared")
            return
        }
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
        fileName: String,
        format: BookFormat
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
        let expectedContentType: String
        switch format {
        case .epub:
            expectedContentType = "application/epub+zip"
        case .pdf:
            expectedContentType = "application/pdf"
        case .md:
            expectedContentType = "text/markdown; charset=utf-8"
        case .txt:
            expectedContentType = "text/plain; charset=utf-8"
        }
        #expect(
            asset.contentType == expectedContentType,
            "\(dataset): \(owner) format \(format.rawValue) requires \(expectedContentType), got \(asset.contentType)"
        )
    }
}
#endif
