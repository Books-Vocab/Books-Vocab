#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

// .serialized: tests exercise process-level fixture environment loading.
@Suite(.serialized)
struct FixtureDatasetStoreTests {
    private static var repoRootURL: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repo root
    }

    private static var readerRealBookAssetPath: String {
        repoRootURL
            .appendingPathComponent("ops/fixtures/assets/reader-real-book.epub")
            .path
    }

    private static func withEnv<T>(_ key: String, _ value: String?, perform: () throws -> T) rethrows -> T {
        let previous = getenv(key).map { String(cString: $0) }
        if let value {
            setenv(key, value, 1)
        } else {
            unsetenv(key)
        }
        defer {
            if let previous {
                setenv(key, previous, 1)
            } else {
                unsetenv(key)
            }
        }
        return try perform()
    }

    private static func withFixtureDatasetEnv<T>(_ value: String?, perform: () throws -> T) rethrows -> T {
        try withEnv("KG_FIXTURE_DATASET_B64", value, perform: perform)
    }

    private static func withFixtureDatasetDeflateEnv<T>(_ value: String?, perform: () throws -> T) rethrows -> T {
        try withEnv("KG_FIXTURE_DATASET_DEFLATE_B64", value, perform: perform)
    }

    /// base64(raw DEFLATE) — the exact payload shape ops stages into
    /// `KG_FIXTURE_DATASET_DEFLATE_B64` (Apple `.zlib` == raw DEFLATE stream).
    private static func deflateBase64(_ data: Data) throws -> String {
        let compressed = try (data as NSData).compressed(using: .zlib) as Data
        return compressed.base64EncodedString()
    }

    private static func completeV2DatasetData(_ json: String) throws -> Data {
        var object = try #require(try JSONSerialization.jsonObject(with: Data(json.utf8)) as? [String: Any])
        object["assets"] = object["assets"] ?? [
            "books": [:],
            "audio": [:],
            "subtitles": [:],
            "text": [:],
            "images": [:],
        ]
        object["preferences"] = object["preferences"] ?? [
            "userDefaults": [:],
            "ubiquitousKeyValueStore": [:],
        ]
        for key in [
            "auth",
            "entitlements",
            "settings",
            "bookshelf",
            "todayReview",
            "notebook",
            "podcast",
            "runtimePodcast",
            "reader",
            "vocabulary",
            "reviewDeck",
            "syncPresenter",
        ] where object[key] == nil {
            object[key] = [:]
        }
        return try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    }

    @Test func datasetFailsWhenSchemaIsMissing() throws {
        let dataset = """
        {
          "datasetID": "missing-schema"
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Data(dataset.utf8))
        }
    }

    @Test func datasetFailsWhenSchemaIsNotV2() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v1",
          "datasetID": "legacy-schema"
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Data(dataset.utf8))
        }
    }

    @Test func datasetFailsWhenDatasetIDIsMissingOrEmpty() throws {
        let missingID = """
        {
          "schema": "kg.fixture.dataset.v2"
        }
        """
        let emptyID = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "   "
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Data(missingID.utf8))
        }
        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(emptyID))
        }
    }

    @Test func fixtureDatasetEnvFailsWhenPresentButEmptyOrMalformed() throws {
        try Self.withFixtureDatasetEnv("") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("must not be empty"))
            }
        }

        try Self.withFixtureDatasetEnv("not-base64") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("not valid base64"))
            }
        }
    }

    @Test func fixtureDatasetTestingOverrideTakesPrecedenceOverMalformedEnv() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "override-world"
        }
        """

        try Self.withFixtureDatasetEnv("not-base64") {
            try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
                #expect(FixtureDatasetStore.debugSummary() == "override-world @ testing-override")
            }
        }
    }

    @Test func fixtureDatasetDeflateEnvLoadsCompressedWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "deflate-world"
        }
        """
        let deflateB64 = try Self.deflateBase64(Self.completeV2DatasetData(dataset))

        try Self.withFixtureDatasetDeflateEnv(deflateB64) {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary() == "deflate-world @ env:KG_FIXTURE_DATASET_DEFLATE_B64")
            }
        }
    }

    @Test func fixtureDatasetDeflateEnvFailsWhenEmptyMalformedOrNotDeflate() throws {
        try Self.withFixtureDatasetDeflateEnv("") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_DEFLATE_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("must not be empty"))
            }
        }

        try Self.withFixtureDatasetDeflateEnv("not-base64") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_DEFLATE_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("not valid base64"))
            }
        }

        // Valid base64 of plaintext JSON — not a raw DEFLATE stream.
        let plaintextBase64 = Data("{\"schema\":\"kg.fixture.dataset.v2\"}".utf8).base64EncodedString()
        try Self.withFixtureDatasetDeflateEnv(plaintextBase64) {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_DEFLATE_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("decompress failed"))
            }
        }
    }

    @Test func fixtureDatasetEnvFailsWhenBothPlainAndDeflateArePresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "ambiguous-world"
        }
        """
        let data = try Self.completeV2DatasetData(dataset)
        let plainB64 = data.base64EncodedString()
        let deflateB64 = try Self.deflateBase64(data)

        try Self.withFixtureDatasetEnv(plainB64) {
            try Self.withFixtureDatasetDeflateEnv(deflateB64) {
                try FixtureDatasetStore.withTestingData(nil) {
                    let summary = FixtureDatasetStore.debugSummary()
                    #expect(summary.contains("invalid @"))
                    #expect(summary.contains("both KG_FIXTURE_DATASET_DEFLATE_B64 and KG_FIXTURE_DATASET_B64 are set"))
                }
            }
        }
    }

    @Test func fixtureDatasetPlaintextEnvStillLoadsWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "plaintext-world"
        }
        """
        let plainB64 = try Self.completeV2DatasetData(dataset).base64EncodedString()

        try Self.withFixtureDatasetEnv(plainB64) {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary() == "plaintext-world @ env:KG_FIXTURE_DATASET_B64")
            }
        }
    }

    @Test func seedResolutionFailureDescriptionExplainsWhyWorldIsNotLoaded() throws {
        // Absent: neither env key set, no testing override.
        try Self.withFixtureDatasetEnv(nil) {
            try Self.withFixtureDatasetDeflateEnv(nil) {
                try FixtureDatasetStore.withTestingData(nil) {
                    let message = FixtureDatasetStore.seedResolutionFailureDescription(resolving: "notebook.demo")
                    #expect(message.contains("UI World is not loaded"))
                    #expect(message.contains("KG_FIXTURE_DATASET_DEFLATE_B64"))
                    #expect(message.contains("KG_FIXTURE_DATASET_B64"))
                    #expect(message.contains("notebook.demo"))
                }
            }
        }

        // Invalid: env present but broken — must surface the real load failure,
        // never masquerade as "missing <fixture key>".
        try Self.withFixtureDatasetEnv("not-base64") {
            try Self.withFixtureDatasetDeflateEnv(nil) {
                try FixtureDatasetStore.withTestingData(nil) {
                    let message = FixtureDatasetStore.seedResolutionFailureDescription(resolving: "notebook.demo")
                    #expect(message.contains("UI World failed to load"))
                    #expect(message.contains("env:KG_FIXTURE_DATASET_B64"))
                    #expect(message.contains("not valid base64"))
                    #expect(message.contains("notebook.demo"))
                }
            }
        }

        // Loaded but key genuinely missing: keep the classic message.
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "loaded-world"
        }
        """
        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let message = FixtureDatasetStore.seedResolutionFailureDescription(resolving: "notebook.demo")
            #expect(message == "UI World is missing notebook.demo")
        }
    }

    @Test func v2DatasetFailsWhenTopLevelDomainIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-domains"
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Data(dataset.utf8))
        }
    }

    @Test func datasetFailsWhenTopLevelDomainIsUnknown() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-top-level-domain",
          "podcasts": {}
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenAssetManifestContainsUnknownBucket() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-asset-bucket",
          "assets": {
            "books": {},
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {},
            "videos": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenAssetContainsUnknownProperty() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-asset-property",
          "assets": {
            "books": {},
            "audio": {},
            "subtitles": {},
            "text": {
              "source": {
                "sourcePath": "/tmp/source.md",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "UITestAssets/source.md",
                "contentType": "text/markdown; charset=utf-8",
                "encoding": "utf-8"
              }
            },
            "images": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenAssetInstallPathIsInvalid() throws {
        let installPaths = [
            "   ",
            "/tmp/payload.txt",
            "Books/../payload.txt",
        ]

        for installAs in installPaths {
            let dataset = """
            {
              "schema": "kg.fixture.dataset.v2",
              "datasetID": "invalid-asset-install-path",
              "assets": {
                "books": {},
                "audio": {},
                "subtitles": {},
                "text": {
                  "source": {
                    "sourcePath": "/tmp/source.md",
                    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "byteSize": 1,
                    "installAs": "\(installAs)",
                    "contentType": "text/markdown; charset=utf-8"
                  }
                },
                "images": {}
              }
            }
            """

            #expect(throws: DecodingError.self) {
                _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
            }
        }
    }

    @Test func datasetFailsWhenAssetInstallPathIsNull() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "null-asset-install-path",
          "assets": {
            "books": {},
            "audio": {},
            "subtitles": {},
            "text": {
              "source": {
                "sourcePath": "/tmp/source.md",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": null,
                "contentType": "text/markdown; charset=utf-8"
              }
            },
            "images": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenAssetInstallPathIsDuplicated() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "duplicate-asset-install-path",
          "assets": {
            "books": {
              "book": {
                "sourcePath": "/tmp/book.epub",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "Books/shared.epub",
                "contentType": "application/epub+zip"
              }
            },
            "audio": {},
            "subtitles": {},
            "text": {
              "source": {
                "sourcePath": "/tmp/source.md",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "Books/shared.epub",
                "contentType": "text/markdown; charset=utf-8"
              }
            },
            "images": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenAssetContentTypeDoesNotBelongToBucket() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "wrong-asset-content-type-bucket",
          "assets": {
            "books": {},
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {
              "cover": {
                "sourcePath": "/tmp/cover.png",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "NotebookCovers/cover.png",
                "contentType": "application/pdf"
              }
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenAssetContentTypeDoesNotMatchExtension() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "wrong-asset-content-type-extension",
          "assets": {
            "books": {
              "book": {
                "sourcePath": "/tmp/book.epub",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "Books/book.epub",
                "contentType": "application/pdf"
              }
            },
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenFixtureDomainContainsUnknownFixtureID() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-fixture-id",
          "auth": {
            "guest": {
              "isLoggedIn": false,
              "userId": null,
              "token": null,
              "keychainTokenState": "absent",
              "displayName": null,
              "email": null,
              "authError": null,
              "isAuthenticating": false,
              "provider": null,
              "providerUserId": null
            }
          },
          "settings": {
            "subscribed_typo": {
              "authFixtureRef": "auth.guest",
              "entitlementsFixtureRef": null,
              "auth": {
                "isLoggedIn": false,
                "userInitials": null,
                "avatarURL": null,
                "displayName": "未登入",
                "email": null,
                "authError": null,
                "isAuthenticating": false,
                "iconBreathing": false,
                "manualLoginHint": null
              },
              "preferences": {
                "selectedLanguage": "繁體中文",
                "selectedAppearance": "跟隨系統",
                "translationSource": "English",
                "translationTarget": "繁體中文",
                "selectedReviewMode": "寬鬆",
                "autoSyncEnabled": false,
                "showAutoSync": false
              },
              "kg": null,
              "subscription": null,
              "syncSummary": null,
              "reviewSettings": null,
              "bookSync": null,
              "about": {
                "version": "1.0 (1)",
                "developerName": "MPSO"
              },
              "danger": null,
              "manualLoginUserId": null,
              "debugLocalServerURL": null
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func datasetFailsWhenNotebookCardStateOmitsNullableField() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "notebook-card-state-missing-nullable",
          "notebook": {
            "populated": {
              "notebooks": [
                {
                  "remoteId": "nb-card-state",
                  "name": "Card state",
                  "color": null,
                  "coverPattern": null,
                  "coverImageAssetRef": null,
                  "cardState": {
                    "cardCount": 0,
                    "dueCount": 0,
                    "unlearnedCount": 0,
                    "reviewedCount": 0,
                    "pendingCount": 0,
                    "isActive": true
                  },
                  "syncStatus": 2,
                  "isDefault": false,
                  "sortOrder": 0,
                  "entries": []
                }
              ],
              "editStates": []
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookEntryFailsWhenMetadataKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-notebook-entry-metadata",
          "notebook": {
            "populated": {
              "editStates": [],
              "notebooks": [
                {
                  "remoteId": "default",
                  "name": "Default",
                  "syncStatus": 1,
                  "entries": [
                    {
                      "word": "partial",
                      "translation": "局部",
                      "syncStatus": 1,
                      "actionType": "add",
                      "isArchived": false,
                      "isExcludedFromReader": false
                    }
                  ]
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookRowFailsWhenMetadataKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-notebook-row-metadata",
          "notebook": {
            "populated": {
              "editStates": [],
              "notebooks": [
                {
                  "remoteId": "default",
                  "name": "Default",
                  "syncStatus": 1,
                  "entries": []
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookFixtureFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.notebookDataset(
            datasetID: "unknown-notebook-fixture-key",
            fixtureExtraFields: ",\"layout\": \"grid\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookRowFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.notebookDataset(
            datasetID: "unknown-notebook-row-key",
            notebookExtraFields: ",\"localOnly\": true"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookEntryFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.notebookDataset(
            datasetID: "unknown-notebook-entry-key",
            entryExtraFields: ",\"legacySource\": \"csv\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookCardStateFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.notebookDataset(
            datasetID: "unknown-notebook-card-state-key",
            cardStateExtraFields: ",\"isStale\": false"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func notebookEditStateFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.notebookDataset(
            datasetID: "unknown-notebook-edit-state-key",
            editStateExtraFields: ",\"source\": \"draft\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenSeriesSortOrderIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-series-sort-order",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "subtitleAvailable": true,
                  "download": null
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenNullableSeriesStateKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-nullable-series-state",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": []
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenPreferredNotebookKeyIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-preferred-notebook-key",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": []
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenSeriesUnknownKeyIsPresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-runtime-podcast-series-key",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [],
              "cached": true
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenEpisodePlaybackMetadataKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-episode-playback-metadata",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "subtitleAvailable": true,
                  "download": null
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenEpisodeUnknownKeyIsPresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-runtime-podcast-episode-key",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "durationSec": 120.5,
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "previewDurationSec": 60,
                  "subtitleAvailable": true,
                  "download": null,
                  "downloaded": true
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenEpisodeDownloadStateKeyIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-episode-download-state",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "durationSec": 120.5,
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "previewDurationSec": 60,
                  "subtitleAvailable": true
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenDownloadUnknownKeyIsPresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-runtime-podcast-download-key",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "durationSec": 120.5,
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "previewDurationSec": 60,
                  "subtitleAvailable": true,
                  "download": {
                    "audioAssetRef": "audio.runtime-audio",
                    "subtitleAssetRef": null,
                    "localAudioPath": "podcast-downloads/audio.m4a",
                    "localSubtitlePath": null,
                    "downloaded": true
                  }
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenDownloadNullableStateKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-download-nullable-state",
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "durationSec": 120.5,
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "previewDurationSec": 60,
                  "subtitleAvailable": true,
                  "download": {
                    "audioAssetRef": "audio.runtime-audio",
                    "subtitleAssetRef": null,
                    "localAudioPath": "podcast-downloads/audio.m4a"
                  }
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenSeriesAudioAssetRefIsMissingFromManifest() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-audio-asset-ref",
          "assets": {
            "books": {},
            "audio": {},
            "subtitles": {
              "runtime-subtitle": {
                "sourcePath": "/tmp/audio.srt",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-subtitles/audio.srt",
                "contentType": "application/x-subrip; charset=utf-8"
              }
            },
            "text": {},
            "images": {}
          },
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": []
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func runtimePodcastFailsWhenDownloadSubtitleAssetRefIsMissingFromManifest() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-download-subtitle-asset-ref",
          "assets": {
            "books": {},
            "audio": {
              "runtime-audio": {
                "sourcePath": "/tmp/audio.m4a",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-downloads/audio.m4a",
                "contentType": "audio/mp4"
              }
            },
            "subtitles": {
              "runtime-subtitle": {
                "sourcePath": "/tmp/audio.srt",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-subtitles/audio.srt",
                "contentType": "application/x-subrip; charset=utf-8"
              }
            },
            "text": {},
            "images": {}
          },
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": null,
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "durationSec": 120.5,
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "previewDurationSec": 60,
                  "subtitleAvailable": true,
                  "download": {
                    "audioAssetRef": "audio.runtime-audio",
                    "subtitleAssetRef": "subtitles.missing-runtime-subtitle",
                    "localAudioPath": "podcast-downloads/audio.m4a",
                    "localSubtitlePath": "podcast-subtitles/audio.srt"
                  }
                }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularyEntryFailsWhenNullableRowStateKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-vocabulary-entry-nullable-row-state",
          "vocabulary": {
            "searchVocabNotebook": {
              "notebookRemoteId": "search-notebook",
              "notebookName": "Search Notebook",
              "notebookSyncStatus": 1,
              "bookTitle": "Search Book",
              "entries": [
                {
                  "word": "partial",
                  "translation": "局部",
                  "context": "Partial context.",
                  "bookTitle": "Search Book",
                  "reviewMode": "recognition",
                  "reviewExamples": [],
                  "syncStatus": 1,
                  "actionType": "add",
                  "isArchived": false,
                  "isExcludedFromReader": false,
                  "graphLinksByKind": {}
                }
              ],
              "reviewHistory": []
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularySeedFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.vocabularyDataset(
            datasetID: "unknown-vocabulary-seed-key",
            entriesJSON: Self.fullVocabularyEntryJSON(word: "anchored"),
            reviewHistoryJSON: "[]",
            extraFields: #","cachedCount": 1"#
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularyEntryFailsWhenUnknownKeyIsPresent() throws {
        let entry = Self.fullVocabularyEntryJSON(word: "unexpected")
            .replacingOccurrences(of: "\"graphLinksByKind\": {}", with: "\"graphLinksByKind\": {}, \"legacyEase\": 2.5")
        let dataset = Self.vocabularyDataset(
            datasetID: "unknown-vocabulary-entry-key",
            entriesJSON: entry,
            reviewHistoryJSON: "[]"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularyReviewHistoryFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.vocabularyDataset(
            datasetID: "unknown-review-history-key",
            entriesJSON: Self.fullVocabularyEntryJSON(word: "anchored"),
            reviewHistoryJSON: """
            [
              {
                "word": "anchored",
                "feedback": 1,
                "reviewedAt": "2026-01-02T00:00:00Z",
                "source": "legacy"
              }
            ]
            """
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularyEntryFailsWhenRowStateValuesAreInvalid() throws {
        let entry = Self.fullVocabularyEntryJSON(word: "invalid-state")
            .replacingOccurrences(of: "\"syncStatus\": 1", with: "\"syncStatus\": 9")
            .replacingOccurrences(of: "\"actionType\": \"add\"", with: "\"actionType\": \"merge\"")
        let dataset = Self.vocabularyDataset(
            datasetID: "invalid-vocabulary-row-state",
            entriesJSON: entry,
            reviewHistoryJSON: "[]"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularySeedFailsWhenReviewHistoryReferencesMissingEntry() throws {
        let dataset = Self.vocabularyDataset(
            datasetID: "review-history-missing-entry",
            entriesJSON: Self.fullVocabularyEntryJSON(word: "anchored"),
            reviewHistoryJSON: """
            [
              {
                "word": "orphaned",
                "feedback": 1,
                "reviewedAt": "2026-01-02T00:00:00Z"
              }
            ]
            """
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func vocabularySeedFailsWhenEntryWordsAreDuplicated() throws {
        let entry = Self.fullVocabularyEntryJSON(word: "duplicated")
        let dataset = Self.vocabularyDataset(
            datasetID: "duplicate-vocabulary-entry-word",
            entriesJSON: "\(entry),\(entry)",
            reviewHistoryJSON: "[]"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func reviewDeckSeedFailsWhenEntryWordsAreDuplicated() throws {
        let entry = Self.fullVocabularyEntryJSON(word: "duplicated")
        let dataset = Self.reviewDeckDataset(
            datasetID: "duplicate-review-deck-entry-word",
            entriesJSON: "\(entry),\(entry)"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func reviewDeckSeedFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.reviewDeckDataset(
            datasetID: "unknown-review-deck-key",
            entriesJSON: Self.fullVocabularyEntryJSON(word: "anchored"),
            extraFields: #","sessionSeed": true"#
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func syncPresenterSeedFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.syncPresenterDataset(
            datasetID: "unknown-sync-presenter-seed-key",
            extraFields: ",\"lastRunAt\": \"2026-01-01T00:00:00Z\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func syncPresenterStepFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.syncPresenterDataset(
            datasetID: "unknown-sync-presenter-step-key",
            stepExtraFields: ",\"retryAfterSec\": 5"
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func syncPresenterPendingRowFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.syncPresenterDataset(
            datasetID: "unknown-sync-presenter-pending-row-key",
            pendingRowExtraFields: ",\"remoteStatus\": \"queued\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func catalogPodcastFailsWhenEpisodeDurationIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-catalog-podcast-duration",
          "podcast": {
            "shelf_continue": {
              "series": {
                "remoteId": "s-external",
                "title": "External Series",
                "hostNames": ["Ava Chen"],
                "colorHex": "#112233",
                "coverPattern": "waves"
              },
              "episodes": [
                { "episodeNumber": 1, "title": "External Episode", "lastPlayedTime": 300 }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func catalogPodcastFailsWhenEpisodeNullableProgressIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-catalog-podcast-nullable-progress",
          "podcast": {
            "shelf_continue": {
              "series": {
                "remoteId": "s-external",
                "title": "External Series",
                "hostNames": ["Ava Chen"],
                "colorHex": "#112233",
                "coverPattern": "waves"
              },
              "episodes": [
                { "episodeNumber": 1, "title": "External Episode", "durationSec": 900 }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func catalogPodcastFailsWhenSeedContainsUnknownKey() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-catalog-podcast-key",
          "podcast": {
            "shelf_continue": {
              "series": {
                "remoteId": "s-external",
                "title": "External Series",
                "hostNames": ["Ava Chen"],
                "colorHex": "#112233",
                "coverPattern": "waves",
                "artworkURL": null
              },
              "episodes": [
                { "episodeNumber": 1, "title": "External Episode", "durationSec": 900, "lastPlayedTime": null }
              ]
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func todayReviewFailsWhenNullableCardKeyIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-today-review-nullable-card-key",
          "todayReview": {
            "front": {
              "progressText": "1 / 3",
              "currentCard": null,
              "revealStage": "front",
              "canShuffle": true,
              "canGoPrevious": false,
              "canGoNext": true,
              "remainingCount": 2,
              "forgotCount": 0,
              "rememberedCount": 1,
              "rememberedFeedbackTrigger": 0,
              "forgotFeedbackTrigger": 0,
              "isAutoPlaying": false,
              "isAutoPlayPaused": false,
              "autoplayProgress": 0,
              "autoplaySpeed": "normal",
              "autoplaySoundEnabled": true,
              "showFirstRunHint": false
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func todayReviewFailsWhenNestedLinkContainsUnknownKey() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-today-review-link-key",
          "todayReview": {
            "front": {
              "progressText": "1 / 3",
              "currentCard": \(Self.todayReviewCardJSON(extraLinkFields: #","rank": 1"#)),
              "nextCard": null,
              "revealStage": "front",
              "canShuffle": true,
              "canGoPrevious": false,
              "canGoNext": true,
              "remainingCount": 2,
              "forgotCount": 0,
              "rememberedCount": 1,
              "rememberedFeedbackTrigger": 0,
              "forgotFeedbackTrigger": 0,
              "isAutoPlaying": false,
              "isAutoPlayPaused": false,
              "autoplayProgress": 0,
              "autoplaySpeed": "normal",
              "autoplaySoundEnabled": true,
              "showFirstRunHint": false
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func settingsSeedFailsWhenNullableStateKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-settings-nullable-state",
          "settings": {
            "logged_out": {
              "authFixtureRef": "auth.guest",
              "entitlementsFixtureRef": null,
              "auth": {
                "isLoggedIn": false,
                "userInitials": null,
                "avatarURL": null,
                "displayName": "未登入",
                "email": null,
                "authError": null,
                "isAuthenticating": false,
                "iconBreathing": false,
                "manualLoginHint": null
              },
              "preferences": {
                "selectedLanguage": "繁體中文",
                "selectedAppearance": "跟隨系統",
                "translationSource": "English",
                "translationTarget": "繁體中文",
                "selectedReviewMode": "寬鬆",
                "autoSyncEnabled": false,
                "showAutoSync": false
              },
              "kg": null,
              "subscription": null,
              "syncSummary": null,
              "about": {
                "version": "1.0 (1)",
                "developerName": "MPSO"
              },
              "danger": null,
              "manualLoginUserId": null,
              "debugLocalServerURL": null
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func settingsSeedFailsWhenAuthFixtureRefIsMissingFromWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-settings-auth-ref",
          "auth": {
            "guest": {
              "isLoggedIn": false,
              "userId": null,
              "token": null,
              "keychainTokenState": "absent",
              "displayName": null,
              "email": null,
              "authError": null,
              "isAuthenticating": false,
              "provider": null,
              "providerUserId": null
            }
          },
          "settings": {
            "logged_out": {
              "authFixtureRef": "auth.missing",
              "entitlementsFixtureRef": null,
              "auth": {
                "isLoggedIn": false,
                "userInitials": null,
                "avatarURL": null,
                "displayName": "未登入",
                "email": null,
                "authError": null,
                "isAuthenticating": false,
                "iconBreathing": false,
                "manualLoginHint": null
              },
              "preferences": {
                "selectedLanguage": "繁體中文",
                "selectedAppearance": "跟隨系統",
                "translationSource": "English",
                "translationTarget": "繁體中文",
                "selectedReviewMode": "寬鬆",
                "autoSyncEnabled": false,
                "showAutoSync": false
              },
              "kg": null,
              "subscription": null,
              "syncSummary": null,
              "reviewSettings": null,
              "bookSync": null,
              "about": {
                "version": "1.0 (1)",
                "developerName": "MPSO"
              },
              "danger": null,
              "manualLoginUserId": null,
              "debugLocalServerURL": null
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func settingsSeedFailsWhenSubscriptionStateHasNoEntitlementsRef() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "settings-subscription-without-entitlements-ref",
          "auth": {
            "guest": {
              "isLoggedIn": false,
              "userId": null,
              "token": null,
              "keychainTokenState": "absent",
              "displayName": null,
              "email": null,
              "authError": null,
              "isAuthenticating": false,
              "provider": null,
              "providerUserId": null
            }
          },
          "settings": {
            "logged_out": {
              "authFixtureRef": "auth.guest",
              "entitlementsFixtureRef": null,
              "auth": {
                "isLoggedIn": false,
                "userInitials": null,
                "avatarURL": null,
                "displayName": "未登入",
                "email": null,
                "authError": null,
                "isAuthenticating": false,
                "iconBreathing": false,
                "manualLoginHint": null
              },
              "preferences": {
                "selectedLanguage": "繁體中文",
                "selectedAppearance": "跟隨系統",
                "translationSource": "English",
                "translationTarget": "繁體中文",
                "selectedReviewMode": "寬鬆",
                "autoSyncEnabled": false,
                "showAutoSync": false
              },
              "kg": null,
              "subscription": {
                "isActive": true,
                "planName": "Pro",
                "badgeText": "啟用中",
                "badgeTone": "success",
                "summary": "年度方案",
                "detail": "已解鎖全部功能",
                "sourceLabel": "App Store",
                "managementNote": "由 App Store 管理",
                "pricingUnavailableMessage": null,
                "restoreLabel": "恢復購買",
                "restoreDescription": "如果曾購買過訂閱",
                "isRestoreAvailable": true,
                "ctaTitle": "管理訂閱",
                "isRefreshing": false
              },
              "syncSummary": null,
              "reviewSettings": null,
              "bookSync": null,
              "about": {
                "version": "1.0 (1)",
                "developerName": "MPSO"
              },
              "danger": null,
              "manualLoginUserId": null,
              "debugLocalServerURL": null
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func settingsSeedFailsWhenUnknownKeysArePresent() throws {
        let datasets = [
            Self.settingsDataset(datasetID: "unknown-settings-seed-key", seedExtraFields: ",\"legacyMode\": true"),
            Self.settingsDataset(datasetID: "unknown-settings-auth-key", authExtraFields: ",\"legacyUserId\": \"u\""),
            Self.settingsDataset(datasetID: "unknown-settings-preferences-key", preferencesExtraFields: ",\"legacyAutoSync\": true"),
            Self.settingsDataset(datasetID: "unknown-settings-kg-key", kgExtraFields: ",\"legacyServer\": true"),
            Self.settingsDataset(datasetID: "unknown-settings-kg-observation-key", observationExtraFields: ",\"sampledAt\": \"2026-01-01T00:00:00Z\""),
            Self.settingsDataset(datasetID: "unknown-settings-subscription-key", subscriptionExtraFields: ",\"legacyProductId\": \"pro\""),
            Self.settingsDataset(datasetID: "unknown-settings-review-key", reviewExtraFields: ",\"legacyInterval\": 24"),
            Self.settingsDataset(datasetID: "unknown-settings-sync-summary-key", syncSummaryExtraFields: ",\"lastSyncedAt\": \"now\""),
            Self.settingsDataset(datasetID: "unknown-settings-about-key", aboutExtraFields: ",\"buildChannel\": \"debug\""),
            Self.settingsDataset(datasetID: "unknown-settings-danger-key", dangerExtraFields: ",\"pendingReason\": \"test\""),
            Self.settingsDataset(datasetID: "unknown-settings-book-sync-key", bookSyncExtraFields: ",\"queuedCount\": 1"),
        ]

        for dataset in datasets {
            #expect(throws: DecodingError.self) {
                _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
            }
        }
    }

    @Test func bookshelfBookFailsWhenNullableStateKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-bookshelf-nullable-state",
          "bookshelf": {
            "with_books_library": {
              "books": [
                {
                  "title": "Editorial English",
                  "author": "KG Studio",
                  "fileName": "editorial-english.epub",
                  "format": "epub",
                  "progression": 0.5,
                  "dateAdded": "2026-01-01T00:00:00Z",
                  "dateLastRead": "2026-01-06T00:00:00Z"
                }
              ],
              "referenceDate": "2026-01-07T00:00:00Z"
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test @MainActor func externalDatasetDeclaresAuthAndEntitlementWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-ui-world",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "world-user",
              "token": "world-token",
              "keychainTokenState": "available",
              "displayName": "World User",
              "email": "world@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:world-user"
            },
            "guest": {
              "isLoggedIn": false,
              "userId": null,
              "token": null,
              "keychainTokenState": "absent",
              "displayName": null,
              "email": null,
              "authError": null,
              "isAuthenticating": false,
              "provider": null,
              "providerUserId": null
            }
          },
          "entitlements": {
            "pro": {
              "pro": {
                "is_active": true,
                "product_id": "com.wordnexus.pro.monthly",
                "plan_name": "Books & Vocab Pro",
                "price_display": "NT$90 / month",
                "status": "active",
                "is_trial": false,
                "trial_days": 7,
                "will_renew": true,
                "expires_at": "2099-12-31T23:59:59Z",
                "source": "app_store",
                "last_synced_at": "2026-06-10T00:00:00Z"
              }
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            #expect(FixtureDatasetStore.debugSummary() == "test-ui-world @ testing-override")

            let auth = try #require(FixtureDatasetStore.authSeed(for: .signedIn))
            #expect(auth.isLoggedIn == true)
            #expect(auth.userId == "world-user")
            #expect(auth.token == "world-token")
            #expect(auth.keychainTokenState == .available)
            #expect(auth.displayName == "World User")
            #expect(auth.email == "world@example.com")
            #expect(auth.authError == nil)
            #expect(auth.isAuthenticating == false)

            let guest = try #require(FixtureDatasetStore.authSeed(for: .guest))
            #expect(guest.isLoggedIn == false)
            #expect(guest.userId == nil)
            #expect(guest.keychainTokenState == .absent)
            #expect(guest.authError == nil)
            #expect(guest.isAuthenticating == false)

            let entitlements = try #require(FixtureDatasetStore.entitlementsSeed(for: .pro))
            #expect(entitlements.pro.is_active == true)
            #expect(entitlements.pro.status == "active")

            #if targetEnvironment(simulator)
            let subscriptionManager = UITestSubscriptionManager.proAccess()
            #expect(subscriptionManager.entitlements.pro.is_active == true)
            #expect(subscriptionManager.entitlements.pro.plan_name == "Books & Vocab Pro")
            #expect(subscriptionManager.entitlements.pro.last_synced_at == "2026-06-10T00:00:00Z")
            #endif
        }
    }

    @Test func authSeedFailsWhenNullableIdentityKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-nullable-auth-keys",
          "auth": {
            "guest": {
              "isLoggedIn": false,
              "keychainTokenState": "absent",
              "authError": null,
              "isAuthenticating": false
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func authSeedFailsWhenUnknownKeyIsPresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-auth-key",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "world-user",
              "token": "world-token",
              "keychainTokenState": "available",
              "displayName": "World User",
              "email": "world@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:world-user",
              "staleSession": true
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func authSeedFailsWhenReadableTokenIsMissingForAvailableKeychain() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "invalid-auth-keychain-token",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "world-user",
              "token": null,
              "keychainTokenState": "available",
              "displayName": "World User",
              "email": "world@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:world-user"
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func authSeedFailsWhenLoggedInUserIdIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "invalid-auth-missing-user-id",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": null,
              "token": "world-token",
              "keychainTokenState": "available",
              "displayName": "World User",
              "email": "world@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:world-user"
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func entitlementsSeedFailsWhenNullableProKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-nullable-entitlement-keys",
          "entitlements": {
            "pro": {
              "pro": {
                "is_active": true,
                "product_id": "com.wordnexus.pro.monthly",
                "plan_name": "Books & Vocab Pro",
                "price_display": "NT$90 / month",
                "status": "active",
                "is_trial": false,
                "trial_days": 7,
                "will_renew": true,
                "expires_at": null,
                "source": "app_store"
              }
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func entitlementsSeedFailsWhenWrapperContainsUnknownKey() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-entitlement-wrapper-key",
          "entitlements": {
            "pro": {
              "pro": {
                "is_active": true,
                "product_id": "com.wordnexus.pro.monthly",
                "plan_name": "Books & Vocab Pro",
                "price_display": "NT$90 / month",
                "status": "active",
                "is_trial": false,
                "trial_days": 7,
                "will_renew": true,
                "expires_at": null,
                "source": "app_store",
                "last_synced_at": "2026-06-10T00:00:00Z"
              },
              "source": "legacy"
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func entitlementsSeedFailsWhenProStatusContainsUnknownKey() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-entitlement-pro-key",
          "entitlements": {
            "pro": {
              "pro": {
                "is_active": true,
                "product_id": "com.wordnexus.pro.monthly",
                "plan_name": "Books & Vocab Pro",
                "price_display": "NT$90 / month",
                "status": "active",
                "is_trial": false,
                "trial_days": 7,
                "will_renew": true,
                "expires_at": null,
                "source": "app_store",
                "last_synced_at": "2026-06-10T00:00:00Z",
                "is_admin_granted": false
              }
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test @MainActor func externalDatasetCanDeclareLockedKeychainSession() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-locked-keychain",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "locked-user",
              "token": null,
              "keychainTokenState": "readFailed",
              "displayName": "Locked User",
              "email": "locked@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:locked-user"
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let auth = try #require(FixtureDatasetStore.authSeed(for: .signedIn))
            #expect(auth.isLoggedIn == true)
            #expect(auth.userId == "locked-user")
            #expect(auth.token == nil)
            #expect(auth.keychainTokenState == .readFailed)
            #expect(auth.authError == nil)
            #expect(auth.isAuthenticating == false)
        }
    }

    #if targetEnvironment(simulator)
    @Test @MainActor func lockedKeychainAuthSeedRestoresPendingSessionState() throws {
        let auth = AuthManager.shared
        let previous = PersistedAuthSession(
            userId: auth.userId,
            displayName: auth.displayName,
            userEmail: auth.userEmail,
            avatarURL: auth.avatarURL,
            token: auth.token,
            keychainReadFailed: auth.keychainReadPending
        )
        defer {
            auth.applyUITestPersistedSession(previous)
        }

        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-locked-keychain-seed",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "locked-user",
              "token": null,
              "keychainTokenState": "readFailed",
              "displayName": "Locked User",
              "email": "locked@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:locked-user"
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            UITestFixtureSeed.seedSignedInLoginFromWorld()
            #expect(auth.isLoggedIn == true)
            #expect(auth.userId == "locked-user")
            #expect(auth.token == nil)
            #expect(auth.keychainReadPending == true)
            #expect(auth.displayName == "Locked User")
            #expect(auth.userEmail == "locked@example.com")
        }
    }
    #endif

    @Test @MainActor func externalDatasetDeclaresAndAppliesPreferenceWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-preferences",
          "preferences": {
            "userDefaults": {
              "app_language_selection": "traditionalChinese",
              "translation_source_lang": "en",
              "translation_source_lang_updated_at": 1781424000,
              "auto_sync_enabled": true,
              "podcast.subtitleSize": "large"
            },
            "ubiquitousKeyValueStore": {
              "app_language_selection": "traditionalChinese",
              "translation_source_lang": "en",
              "translation_source_lang_updated_at": 1781424000,
              "review_settings_progress_paused": false
            }
          }
        }
        """

        let suite = "test.ui-world.preferences.\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defaults.removePersistentDomain(forName: suite)
        let cloud = FakeCloudKVStore()

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let document = FixtureDatasetStore.requireDocument()
            document.preferences.apply(to: defaults, cloud: cloud)

            #expect(defaults.string(forKey: "app_language_selection") == "traditionalChinese")
            #expect(defaults.string(forKey: "translation_source_lang") == "en")
            #expect(defaults.object(forKey: "translation_source_lang_updated_at") as? Double == 1_781_424_000)
            #expect(defaults.bool(forKey: "auto_sync_enabled") == true)
            #expect(defaults.string(forKey: "podcast.subtitleSize") == "large")
            #expect(cloud.string(forKey: "app_language_selection") == "traditionalChinese")
            #expect(cloud.string(forKey: "translation_source_lang") == "en")
            #expect(cloud.double(forKey: "translation_source_lang_updated_at") == 1_781_424_000)
            #expect(cloud.double(forKey: "review_settings_progress_paused") == 0.0)
        }
    }

    @Test func preferenceWorldFailsWhenUserDefaultsKeyIsEmpty() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "empty-user-defaults-preference-key",
          "preferences": {
            "userDefaults": {
              "   ": "traditionalChinese"
            },
            "ubiquitousKeyValueStore": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func preferenceWorldFailsWhenUserDefaultsKeyIsUnknown() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-user-defaults-preference-key",
          "preferences": {
            "userDefaults": {
              "translation_source_lagn": "en"
            },
            "ubiquitousKeyValueStore": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func preferenceWorldFailsWhenUnknownWrapperKeyIsPresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-preference-wrapper-key",
          "preferences": {
            "userDefaults": {},
            "ubiquitousKeyValueStore": {},
            "keychain": {}
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func preferenceWorldFailsWhenLocalOnlyKeyIsDeclaredInUbiquitousKeyValueStore() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "local-only-preference-in-icloud-kvs",
          "preferences": {
            "userDefaults": {},
            "ubiquitousKeyValueStore": {
              "auto_sync_enabled": true
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func preferenceWorldFailsWhenUbiquitousKeyValueStoreKeyIsEmpty() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "empty-ubiquitous-preference-key",
          "preferences": {
            "userDefaults": {},
            "ubiquitousKeyValueStore": {
              "": false
            }
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test @MainActor func externalDatasetDeclaresRuntimeWorlds() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-runtime-worlds",
          "assets": {
            "books": {
              "reader-book": {
                "sourcePath": "/tmp/reader.epub",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "Books/reader.epub",
                "contentType": "application/epub+zip"
              }
            },
            "audio": {
              "runtime-audio": {
                "sourcePath": "/tmp/audio.m4a",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-downloads/audio.m4a",
                "contentType": "audio/mp4"
              }
            },
            "subtitles": {
              "runtime-subtitle": {
                "sourcePath": "/tmp/audio.srt",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-subtitles/audio.srt",
                "contentType": "application/x-subrip; charset=utf-8"
              }
            },
            "text": {
              "reader-source": {
                "sourcePath": "/tmp/source.md",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "Books/sources/source.md",
                "contentType": "text/markdown; charset=utf-8"
              }
            },
            "images": {}
          },
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": "runtime-notebook",
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": [
                {
                  "remoteId": "series-runtime_ep_01",
                  "episodeNumber": 1,
                  "title": "Runtime Episode",
                  "durationSec": 120.5,
                  "audioAvailable": true,
                  "previewAvailable": true,
                  "previewDurationSec": 60,
                  "subtitleAvailable": true,
                  "download": {
                    "audioAssetRef": "audio.runtime-audio",
                    "subtitleAssetRef": "subtitles.runtime-subtitle",
                    "localAudioPath": "podcast-downloads/audio.m4a",
                    "localSubtitlePath": "podcast-subtitles/audio.srt"
                  }
                }
              ]
            }
          },
          "notebook": {
            "populated": {
              "editStates": [],
              "notebooks": [
                {
                  "remoteId": "runtime-notebook",
                  "name": "Runtime Notebook",
                  "color": null,
                  "syncStatus": 1,
                  "isDefault": true,
                  "sortOrder": 0,
                  "coverPattern": null,
                  "coverImageAssetRef": null,
                  "cardState": null,
                  "entries": []
                }
              ]
            }
          },
          "reader": {
            "realBookLibrary": {
              "textAssetRef": "text.reader-source",
              "bookAssetRef": "books.reader-book",
              "title": "Reader Source",
              "author": "KG",
              "bookFileName": "reader.epub",
              "notebookRemoteId": "reader-notebook",
              "notebookName": "Reader Notebook",
              "notebookSyncStatus": 1,
              "entry": {
                "word": "introduction",
                "translation": "引言",
                "context": "Introduction",
                "explanation": null,
                "partOfSpeech": "n.",
                "bookTitle": "Reader Source",
                "chapterTitle": "Intro",
                "kgCardId": "reader-card",
                "difficultyTier": "core",
                "reviewMode": "recognition",
                "reviewExamples": ["Introduction"],
                "collocations": null,
                "rootForm": null,
                "inflections": null,
                "syncStatus": 1,
                "actionType": "add",
                "isArchived": false,
                "isExcludedFromReader": false,
                "reviewIntervalHours": 24,
                "nextReviewAt": "2026-01-01T00:00:00Z",
                "lastReviewedAt": null,
                "reviewCount": 0,
                "reviewStreak": 0,
                "lastReviewFeedbackRaw": -1,
                "graphLinksByKind": {}
              }
            }
          },
          "vocabulary": {
            "searchVocabNotebook": {
              "notebookRemoteId": "search-notebook",
              "notebookName": "Search Notebook",
              "notebookSyncStatus": 0,
              "bookTitle": "Search Book",
              "entries": [
                {
                  "word": "affect",
                  "translation": "影響",
                  "context": "Sleep can affect memory.",
                  "explanation": "動詞。",
                  "partOfSpeech": "v.",
                  "bookTitle": "Search Book",
                  "chapterTitle": "Usage",
                  "kgCardId": "demo-affect",
                  "difficultyTier": "core",
                  "reviewMode": "recognition",
                  "reviewExamples": ["Sleep can affect memory."],
                  "collocations": null,
                  "rootForm": null,
                  "inflections": null,
                  "syncStatus": 2,
                  "actionType": "edit",
                  "isArchived": true,
                  "isExcludedFromReader": true,
                  "reviewIntervalHours": 24,
                  "nextReviewAt": "2026-01-01T00:00:00Z",
                  "lastReviewedAt": null,
                  "reviewCount": 1,
                  "reviewStreak": 1,
                  "lastReviewFeedbackRaw": 1,
                  "graphLinksByKind": {}
                }
              ],
              "reviewHistory": []
            }
          },
          "reviewDeck": {
            "probe": {
              "notebookRemoteId": "default",
              "notebookName": "Review Probe Fixture",
              "notebookSyncStatus": 1,
              "entries": [
                {
                  "word": "probeword001",
                  "translation": "量測卡片 1",
                  "context": "Probe context.",
                  "explanation": "Probe explanation.",
                  "partOfSpeech": "n.",
                  "bookTitle": "Review Probe Fixture",
                  "chapterTitle": "Probe",
                  "kgCardId": "probe-001",
                  "difficultyTier": "intermediate",
                  "reviewMode": "recognition",
                  "reviewExamples": ["Probe context."],
                  "collocations": null,
                  "rootForm": null,
                  "inflections": null,
                  "syncStatus": 1,
                  "actionType": "add",
                  "isArchived": false,
                  "isExcludedFromReader": false,
                  "reviewIntervalHours": 12,
                  "nextReviewAt": "2026-01-01T00:00:00Z",
                  "lastReviewedAt": null,
                  "reviewCount": 0,
                  "reviewStreak": 0,
                  "lastReviewFeedbackRaw": -1,
                  "graphLinksByKind": {}
                }
              ]
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let document = FixtureDatasetStore.requireDocument()
            let runtimeSeed = FixtureDatasetStore.runtimePodcastSeed(for: .playablePreview)
            #expect(runtimeSeed?.seriesTitle == "Runtime Series")
            #expect(runtimeSeed?.preferredNotebookId == "runtime-notebook")
            #expect(runtimeSeed?.episodes.first?.download?.audioAssetRef == "audio.runtime-audio")
            #expect(runtimeSeed?.episodes.first?.download?.subtitleAssetRef == "subtitles.runtime-subtitle")
            #expect(runtimeSeed?.episodes.first?.download?.localAudioPath == "podcast-downloads/audio.m4a")
            #expect(runtimeSeed?.episodes.first?.download?.localSubtitlePath == "podcast-subtitles/audio.srt")
            let series = try UITestFixtureSeed.makeRuntimePodcastSeries(
                from: try #require(runtimeSeed),
                document: document,
                owner: "runtimePodcast.playablePreview"
            )
            #expect(series.preferredNotebookId == "runtime-notebook")
            #expect(FixtureDatasetStore.readerSeed(for: .realBookLibrary)?.entry.word == "introduction")
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.entries.first?.word == "affect")
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.notebookSyncStatus == 0)
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.entries.first?.syncStatus == 2)
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.entries.first?.actionType == "edit")
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.entries.first?.isArchived == true)
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.entries.first?.isExcludedFromReader == true)
            #expect(FixtureDatasetStore.reviewDeckSeed(for: .probe)?.entries.first?.word == "probeword001")
        }
    }

    @Test func readerSeedFailsWhenUnknownKeyIsPresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "unknown-reader-key",
          "reader": {
            "realBookLibrary": \(Self.readerSeedJSON(extraFields: ",\"selectionWord\": \"introduction\""))
          }
        }
        """

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test @MainActor func runtimePodcastMaterializationFailsWhenPreferredNotebookIsMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-runtime-podcast-preferred-notebook-ref",
          "assets": {
            "books": {},
            "audio": {
              "runtime-audio": {
                "sourcePath": "/tmp/audio.m4a",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-downloads/audio.m4a",
                "contentType": "audio/mp4"
              }
            },
            "subtitles": {
              "runtime-subtitle": {
                "sourcePath": "/tmp/audio.srt",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "podcast-subtitles/audio.srt",
                "contentType": "application/x-subrip; charset=utf-8"
              }
            },
            "text": {},
            "images": {}
          },
          "runtimePodcast": {
            "playablePreview": {
              "audioAssetRef": "audio.runtime-audio",
              "subtitleAssetRef": "subtitles.runtime-subtitle",
              "seriesRemoteId": "series-runtime",
              "seriesTitle": "Runtime Series",
              "hostNames": ["Lab Host"],
              "preferredNotebookId": "ghost-notebook",
              "color": "sunset",
              "coverPattern": "waves",
              "sortOrder": -100,
              "durationSec": 120.5,
              "episodes": []
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let document = FixtureDatasetStore.requireDocument()
            let seed = try #require(FixtureDatasetStore.runtimePodcastSeed(for: .playablePreview))

            #expect(throws: UIWorldRuntimePodcastMaterializationError.preferredNotebookMissing(
                owner: "runtimePodcast.playablePreview",
                notebookId: "ghost-notebook"
            )) {
                _ = try UITestFixtureSeed.makeRuntimePodcastSeries(
                    from: seed,
                    document: document,
                    owner: "runtimePodcast.playablePreview"
                )
            }
        }
    }

    @Test @MainActor func assetInstallPlanCopiesIntoAppContainerAndVerifiesHash() throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-ui-world-asset-source-\(UUID().uuidString).txt")
        try Data("asset payload".utf8).write(to: source)
        let hash = try FixtureDatasetStore.sha256Hex(for: source)
        let byteSize = try FixtureDatasetStore.byteSize(for: source)
        let installAs = "UITestAssets/\(UUID().uuidString)/payload.txt"
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-asset-install-plan",
          "assets": {
            "books": {},
            "audio": {},
            "subtitles": {},
            "text": {
              "payload": {
                "sourcePath": "\(source.path)",
                "sha256": "\(hash)",
                "byteSize": \(byteSize),
                "installAs": "\(installAs)",
                "contentType": "text/plain; charset=utf-8"
              }
            },
            "images": {}
          }
        }
        """

        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let expected = documents.appendingPathComponent(installAs)
        defer {
            try? FileManager.default.removeItem(at: source)
            try? FileManager.default.removeItem(at: expected.deletingLastPathComponent())
        }

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let installed = try FixtureDatasetStore.requireInstalledAssetURL(ref: "text.payload")
            #expect(installed == expected)
            #expect(FileManager.default.fileExists(atPath: installed.path))
            #expect(try Data(contentsOf: installed) == Data("asset payload".utf8))
            #expect(try FixtureDatasetStore.byteSize(for: installed) == byteSize)
            #expect(try FixtureDatasetStore.sha256Hex(for: installed) == hash)
        }
    }

    @Test @MainActor func externalDatasetOverridesFixtureSeeds() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-marketing",
          "assets": {
            "books": {
              "editorial_english_epub": {
                "sourcePath": "\(Self.readerRealBookAssetPath)",
                "sha256": "1c903a07f1e75ec48b472062207d543698fe8a8d381348be0f8110953776bb2f",
                "byteSize": 2236,
                "installAs": "Books/editorial-english.epub",
                "contentType": "application/epub+zip"
              }
            },
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {}
          },
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "marketing-user",
              "token": "marketing-token",
              "keychainTokenState": "available",
              "displayName": "Max Chen",
              "email": "max@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:marketing-user"
            }
          },
          "entitlements": {
            "pro": {
              "pro": {
                "is_active": true,
                "product_id": "com.wordnexus.pro.monthly",
                "plan_name": "Books & Vocab Pro",
                "price_display": "NT$90 / month",
                "status": "active",
                "is_trial": false,
                "trial_days": 7,
                "will_renew": true,
                "expires_at": "2099-12-31T23:59:59Z",
                "source": "app_store",
                "last_synced_at": "2026-06-10T00:00:00Z"
              }
            }
          },
          "settings": {
            "subscribed_active": {
              "authFixtureRef": "auth.signedIn",
              "entitlementsFixtureRef": "entitlements.pro",
              "auth": {
                "isLoggedIn": true,
                "userInitials": "MC",
                "avatarURL": null,
                "displayName": "Max Chen",
                "email": "max@example.com",
                "authError": null,
                "isAuthenticating": false,
                "iconBreathing": false,
                "manualLoginHint": null
              },
              "preferences": {
                "selectedLanguage": "繁體中文",
                "selectedAppearance": "跟隨系統",
                "translationSource": "English",
                "translationTarget": "繁體中文",
                "selectedReviewMode": "寬鬆",
                "autoSyncEnabled": true,
                "showAutoSync": true
              },
              "kg": {
                "serverURL": "\(TestBrandIdentity.publicBaseURL)",
                "isConnected": true,
                "connectionPulse": false,
                "serverCardCount": 240,
                "lastSyncDescription": "剛剛",
                "isUsingLocalServer": false,
                "localServerURL": null,
                "observation": null
              },
              "subscription": {
                "isActive": true,
                "planName": "Pro",
                "badgeText": "啟用中",
                "badgeTone": "success",
                "summary": "年度方案",
                "detail": "已解鎖全部功能",
                "sourceLabel": "App Store",
                "managementNote": "由 App Store 管理",
                "pricingUnavailableMessage": null,
                "restoreLabel": "恢復購買",
                "restoreDescription": "如果曾購買過訂閱",
                "isRestoreAvailable": true,
                "ctaTitle": "管理訂閱",
                "isRefreshing": false
              },
              "syncSummary": {
                "isConnected": true,
                "isSyncing": false,
                "summaryText": "已連線 · 240 張",
                "lastSyncedText": "上次同步 剛剛"
              },
              "reviewSettings": null,
              "bookSync": null,
              "about": {
                "version": "9.9.9 (999)",
                "developerName": "MPSO"
              },
              "danger": {
                "isDeletingAccount": false
              },
              "manualLoginUserId": null,
              "debugLocalServerURL": null
            }
          },
          "bookshelf": {
            "with_books_library": {
              "books": [
                {
                  "title": "Editorial English",
                  "author": "KG Studio",
                  "fileName": "editorial-english.epub",
                  "format": "epub",
                  "bookAssetRef": "books.editorial_english_epub",
                  "progression": 0.5,
                  "preferredNotebookId": null,
                  "dateAdded": "2026-01-01T00:00:00Z",
                  "dateLastRead": "2026-01-06T00:00:00Z"
                }
              ],
              "referenceDate": "2026-01-07T00:00:00Z"
            }
          },
          "todayReview": {
            "front": {
              "progressText": "4 / 12",
              "currentCard": {
                "word": "discerning",
                "translation": "有鑑別力的",
                "context": "She is discerning about what deserves her focus.",
                "explanation": "形容人判斷細膩、有眼光。",
                "partOfSpeech": "adj.",
                "bookTitle": "Editorial English",
                "chapterTitle": "Tone",
                "dateAdded": "2026-01-01T00:00:00Z",
                "difficultyTier": "advanced",
                "reviewMode": "recognition",
                "reviewExamples": [
                  "She is discerning about what deserves her focus."
                ],
                "rootForm": "discerning",
                "inflections": [
                  "discernment"
                ],
                "graphLinksByKind": {}
              },
              "nextCard": null,
              "revealStage": "front",
              "canShuffle": true,
              "canGoPrevious": true,
              "canGoNext": true,
              "remainingCount": 8,
              "forgotCount": 1,
              "rememberedCount": 3,
              "rememberedFeedbackTrigger": 0,
              "forgotFeedbackTrigger": 0,
              "isAutoPlaying": false,
              "isAutoPlayPaused": false,
              "autoplayProgress": 0.25,
              "autoplaySpeed": "normal",
              "autoplaySoundEnabled": true,
              "showFirstRunHint": false
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            #expect(FixtureDatasetStore.debugSummary() == "test-marketing @ testing-override")
            #expect(FixtureDatasetStore.settingsSeed(for: .subscribedActive)?.auth.displayName == "Max Chen")
            #expect(FixtureDatasetStore.bookshelfSeed(for: .withBooksLibrary)?.books.first?.title == "Editorial English")
            #expect(FixtureDatasetStore.todayReviewSeed(for: .front)?.currentCard?.word == "discerning")

            let settingsModel = SettingsFixtures.renderModel(for: .subscribedActive)
            #expect(settingsModel.state.auth.displayName == "Max Chen")
            #expect(settingsModel.state.about.version == "9.9.9 (999)")

            let bookshelfModel = BookshelfFixtures.renderModel(for: .withBooksLibrary)
            #expect(bookshelfModel.books.first?.title == "Editorial English")

            let todayReviewModel = TodayReviewFixtures.renderModel(for: .front)
            #expect(todayReviewModel.state.currentCard?.card.word == "discerning")
            #expect(todayReviewModel.state.progressText == "4 / 12")
        }
    }

    @Test @MainActor func externalDatasetOverridesNotebookAndPodcastSeeds() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-notebook-podcast",
          "notebook": {
            "populated": {
              "editStates": [],
              "notebooks": [
                {
                  "remoteId": "default",
                  "name": "外部單字本",
                  "color": null,
                  "syncStatus": 0,
                  "isDefault": true,
                  "sortOrder": 0,
                  "coverPattern": null,
                  "coverImageAssetRef": null,
                  "cardState": null,
                  "entries": [
                    {
                      "word": "serendipity",
                      "translation": "機緣巧合",
                      "context": "Serendipity changed the plan.",
                      "explanation": "A fortunate discovery by chance.",
                      "partOfSpeech": "n.",
                      "bookTitle": "外部單字本範例",
                      "chapterTitle": "第一章",
                      "syncStatus": 2,
                      "actionType": "delete",
                      "isArchived": true,
                      "isExcludedFromReader": true
                    }
                  ]
                },
                {
                  "remoteId": "nb-external",
                  "name": "外部第二本",
                  "color": null,
                  "syncStatus": 1,
                  "isDefault": false,
                  "sortOrder": 1,
                  "coverPattern": null,
                  "coverImageAssetRef": null,
                  "cardState": null,
                  "entries": []
                }
              ]
            }
          },
          "podcast": {
            "shelf_continue": {
              "series": {
                "remoteId": "s-external",
                "title": "External Series",
                "hostNames": ["Ava Chen"],
                "colorHex": "#112233",
                "coverPattern": "waves"
              },
              "episodes": [
                { "episodeNumber": 1, "title": "External Episode", "durationSec": 900, "lastPlayedTime": 300 },
                { "episodeNumber": 2, "title": "Unstarted Episode", "durationSec": 1200, "lastPlayedTime": null }
              ]
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            #expect(FixtureDatasetStore.debugSummary() == "test-notebook-podcast @ testing-override")

            let notebookSeed = FixtureDatasetStore.notebookSeed(for: .populated)
            #expect(notebookSeed?.notebooks.count == 2)
            #expect(notebookSeed?.notebooks.first?.name == "外部單字本")
            #expect(notebookSeed?.notebooks.first?.syncStatus == 0)
            #expect(notebookSeed?.notebooks.first?.entries.first?.syncStatus == 2)
            #expect(notebookSeed?.notebooks.first?.entries.first?.actionType == "delete")

            let notebookModel = NotebookFixtures.renderModel(for: .populated)
            #expect(notebookModel.notebooks.map(\.name) == ["外部單字本", "外部第二本"])
            #expect(notebookModel.notebooks.first?.syncStatus == 0)
            let context = notebookModel.container.mainContext
            let entries = try context.fetch(FetchDescriptor<VocabularyEntry>())
            #expect(entries.first?.syncStatus == 2)
            #expect(entries.first?.actionType == "delete")
            #expect(entries.first?.isArchived == true)
            #expect(entries.first?.isExcludedFromReader == true)

            let podcastSeed = FixtureDatasetStore.podcastSeed(for: .shelfContinue)
            #expect(podcastSeed?.series.title == "External Series")

            let podcastModel = PodcastFixtures.renderModel(for: .shelfContinue)
            #expect(podcastModel.series.title == "External Series")
            #expect(podcastModel.items.count == 2)
            #expect(podcastModel.items[0].progress?.lastPlayedTime == 300)
            #expect(podcastModel.items[1].progress == nil)
        }
    }

    @Test func bookshelfSeedFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.bookshelfDataset(
            datasetID: "unknown-bookshelf-seed-key",
            extraFields: ",\"layout\": \"grid\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    @Test func bookshelfBookFailsWhenUnknownKeyIsPresent() throws {
        let dataset = Self.bookshelfDataset(
            datasetID: "unknown-bookshelf-book-key",
            bookExtraFields: ",\"localPath\": \"Books/editorial-english.epub\""
        )

        #expect(throws: DecodingError.self) {
            _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
        }
    }

    private static func settingsDataset(
        datasetID: String,
        seedExtraFields: String = "",
        authExtraFields: String = "",
        preferencesExtraFields: String = "",
        kgExtraFields: String = "",
        observationExtraFields: String = "",
        subscriptionExtraFields: String = "",
        reviewExtraFields: String = "",
        syncSummaryExtraFields: String = "",
        aboutExtraFields: String = "",
        dangerExtraFields: String = "",
        bookSyncExtraFields: String = ""
    ) -> String {
        """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "\(datasetID)",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "settings-user",
              "token": "settings-token",
              "keychainTokenState": "available",
              "displayName": "Settings User",
              "email": "settings@example.com",
              "authError": null,
              "isAuthenticating": false,
              "provider": "apple",
              "providerUserId": "apple:settings-user"
            }
          },
          "entitlements": {
            "pro": {
              "pro": {
                "is_active": true,
                "product_id": "com.wordnexus.pro.monthly",
                "plan_name": "Books & Vocab Pro",
                "price_display": "NT$90 / month",
                "status": "active",
                "is_trial": false,
                "trial_days": 7,
                "will_renew": true,
                "expires_at": "2099-12-31T23:59:59Z",
                "source": "app_store",
                "last_synced_at": "2026-06-10T00:00:00Z"
              }
            }
          },
          "settings": {
            "subscribed_active": {
              "authFixtureRef": "auth.signedIn",
              "entitlementsFixtureRef": "entitlements.pro",
              "auth": {
                "isLoggedIn": true,
                "userInitials": "SU",
                "avatarURL": null,
                "displayName": "Settings User",
                "email": "settings@example.com",
                "authError": null,
                "isAuthenticating": false,
                "iconBreathing": false,
                "manualLoginHint": null\(authExtraFields)
              },
              "preferences": {
                "selectedLanguage": "繁體中文",
                "selectedAppearance": "跟隨系統",
                "translationSource": "English",
                "translationTarget": "繁體中文",
                "selectedReviewMode": "寬鬆",
                "autoSyncEnabled": true,
                "showAutoSync": true\(preferencesExtraFields)
              },
              "kg": {
                "serverURL": "\(TestBrandIdentity.publicBaseURL)",
                "isConnected": true,
                "connectionPulse": false,
                "serverCardCount": 240,
                "lastSyncDescription": "剛剛",
                "isUsingLocalServer": true,
                "localServerURL": "http://127.0.0.1:8000",
                "observation": {
                  "previewLines": ["ok"],
                  "totalCount": 1\(observationExtraFields)
                }\(kgExtraFields)
              },
              "subscription": {
                "isActive": true,
                "planName": "Pro",
                "badgeText": "啟用中",
                "badgeTone": "success",
                "summary": "年度方案",
                "detail": "已解鎖全部功能",
                "sourceLabel": "App Store",
                "managementNote": "由 App Store 管理",
                "pricingUnavailableMessage": null,
                "restoreLabel": "恢復購買",
                "restoreDescription": "如果曾購買過訂閱",
                "isRestoreAvailable": true,
                "ctaTitle": "管理訂閱",
                "isRefreshing": false\(subscriptionExtraFields)
              },
              "syncSummary": {
                "isConnected": true,
                "isSyncing": false,
                "summaryText": "已連線",
                "lastSyncedText": null\(syncSummaryExtraFields)
              },
              "reviewSettings": {
                "mode": "lenient",
                "customInitialIntervalHours": 24,
                "customRememberedMultiplier": 2,
                "customForgotMultiplier": 0.5,
                "customMinimumIntervalHours": 1,
                "customMaximumIntervalHours": 720,
                "isProgressPaused": false,
                "progressPausedAt": null,
                "autoplaySpeed": "normal",
                "autoplaySoundEnabled": true\(reviewExtraFields)
              },
              "bookSync": {
                "text": "同步完成",
                "detail": null,
                "tone": "success"\(bookSyncExtraFields)
              },
              "about": {
                "version": "1.0 (1)",
                "developerName": "MPSO"\(aboutExtraFields)
              },
              "danger": {
                "isDeletingAccount": false\(dangerExtraFields)
              },
              "manualLoginUserId": null,
              "debugLocalServerURL": null\(seedExtraFields)
            }
          }
        }
        """
    }

    private static func vocabularyDataset(
        datasetID: String,
        entriesJSON: String,
        reviewHistoryJSON: String,
        extraFields: String = ""
    ) -> String {
        """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "\(datasetID)",
          "vocabulary": {
            "searchVocabNotebook": {
              "notebookRemoteId": "search-notebook",
              "notebookName": "Search Notebook",
              "notebookSyncStatus": 1,
              "bookTitle": "Search Book",
              "entries": [
                \(entriesJSON)
              ]\(extraFields),
              "reviewHistory": \(reviewHistoryJSON)
            }
          }
        }
        """
    }

    private static func reviewDeckDataset(
        datasetID: String,
        entriesJSON: String,
        extraFields: String = ""
    ) -> String {
        """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "\(datasetID)",
          "reviewDeck": {
            "phaseSingle": {
              "notebookRemoteId": "review-deck-notebook",
              "notebookName": "Review Deck Notebook",
              "notebookSyncStatus": 1,
              "entries": [
                \(entriesJSON)
              ]\(extraFields)
            }
          }
        }
        """
    }

    private static func notebookDataset(
        datasetID: String,
        fixtureExtraFields: String = "",
        notebookExtraFields: String = "",
        cardStateExtraFields: String = "",
        entryExtraFields: String = "",
        editStateExtraFields: String = ""
    ) -> String {
        """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "\(datasetID)",
          "notebook": {
            "populated": {
              "editStates": [
                {
                  "id": "edit-default",
                  "mode": "edit",
                  "name": "Default",
                  "color": null,
                  "coverPattern": null,
                  "coverImageAssetRef": null\(editStateExtraFields)
                }
              ],
              "notebooks": [
                {
                  "remoteId": "default",
                  "name": "Default",
                  "color": null,
                  "coverPattern": null,
                  "coverImageAssetRef": null,
                  "cardState": {
                    "cardCount": 1,
                    "dueCount": 1,
                    "unlearnedCount": 0,
                    "reviewedCount": 0,
                    "pendingCount": 0,
                    "lastActivity": null,
                    "isActive": true\(cardStateExtraFields)
                  },
                  "syncStatus": 1,
                  "isDefault": true,
                  "sortOrder": 0,
                  "entries": [
                    {
                      "word": "anchored",
                      "translation": "固定",
                      "syncStatus": 1,
                      "actionType": "add",
                      "isArchived": false,
                      "isExcludedFromReader": false,
                      "context": "A deterministic context.",
                      "explanation": null,
                      "partOfSpeech": "v.",
                      "bookTitle": "Notebook Book",
                      "chapterTitle": null\(entryExtraFields)
                    }
                  ]\(notebookExtraFields)
                }
              ]\(fixtureExtraFields)
            }
          }
        }
        """
    }

    private static func bookshelfDataset(
        datasetID: String,
        extraFields: String = "",
        bookExtraFields: String = ""
    ) -> String {
        """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "\(datasetID)",
          "assets": {
            "books": {
              "editorial_english_epub": {
                "sourcePath": "/tmp/editorial.epub",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "byteSize": 1,
                "installAs": "Books/editorial-english.epub",
                "contentType": "application/epub+zip"
              }
            },
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {}
          },
          "bookshelf": {
            "with_books_library": {
              "books": [
                {
                  "title": "Editorial English",
                  "author": "KG Studio",
                  "fileName": "editorial-english.epub",
                  "format": "epub",
                  "bookAssetRef": "books.editorial_english_epub",
                  "progression": 0.5,
                  "preferredNotebookId": null,
                  "dateAdded": "2026-01-01T00:00:00Z",
                  "dateLastRead": "2026-01-06T00:00:00Z"\(bookExtraFields)
                }
              ],
              "referenceDate": "2026-01-07T00:00:00Z"\(extraFields)
            }
          }
        }
        """
    }

    private static func syncPresenterDataset(
        datasetID: String,
        extraFields: String = "",
        stepExtraFields: String = "",
        pendingRowExtraFields: String = ""
    ) -> String {
        """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "\(datasetID)",
          "syncPresenter": {
            "ready": {
              "isLoggedIn": true,
              "isConnected": true,
              "phase": "ready",
              "failureKind": null,
              "pendingCount": 1,
              "addCount": 1,
              "deleteCount": 0,
              "steps": [
                {
                  "id": "push",
                  "label": "Push local changes",
                  "status": "waiting",
                  "current": 0,
                  "total": 1,
                  "detail": "Waiting"\(stepExtraFields)
                }
              ],
              "summaryText": "1 pending",
              "pendingRows": [
                {
                  "id": "11111111-1111-1111-1111-111111111111",
                  "word": "anchored",
                  "partOfSpeech": "v.",
                  "translation": "固定",
                  "wordTone": "primary",
                  "isStrikethrough": false,
                  "actionSystemImage": "plus.circle",
                  "actionTone": "primary",
                  "actionAccessibilityLabel": "新增 anchored"\(pendingRowExtraFields)
                }
              ]\(extraFields)
            }
          }
        }
        """
    }

    private static func fullVocabularyEntryJSON(word: String) -> String {
        """
        {
          "word": "\(word)",
          "translation": "測試",
          "context": "A deterministic test context.",
          "explanation": null,
          "partOfSpeech": "n.",
          "bookTitle": "Search Book",
          "chapterTitle": null,
          "kgCardId": "\(word)-card",
          "difficultyTier": "core",
          "reviewMode": "recognition",
          "reviewExamples": [],
          "collocations": null,
          "rootForm": null,
          "inflections": null,
          "syncStatus": 1,
          "actionType": "add",
          "isArchived": false,
          "isExcludedFromReader": false,
          "reviewIntervalHours": 24,
          "nextReviewAt": "2026-01-03T00:00:00Z",
          "lastReviewedAt": null,
          "reviewCount": 0,
          "reviewStreak": 0,
          "lastReviewFeedbackRaw": -1,
          "graphLinksByKind": {}
        }
        """
    }

    private static func readerSeedJSON(extraFields: String = "") -> String {
        """
        {
          "textAssetRef": "text.reader-source",
          "bookAssetRef": "books.reader-book",
          "title": "Reader Source",
          "author": "KG",
          "bookFileName": "reader.epub",
          "notebookRemoteId": "reader-notebook",
          "notebookName": "Reader Notebook",
          "notebookSyncStatus": 1,
          "entry": \(Self.fullVocabularyEntryJSON(word: "introduction"))\(extraFields)
        }
        """
    }

    private static func todayReviewCardJSON(
        extraCardFields: String = "",
        extraLinkFields: String = ""
    ) -> String {
        """
        {
          "word": "discerning",
          "translation": "有鑑別力的",
          "context": "She is discerning about what deserves her focus.",
          "explanation": "形容人判斷細膩、有眼光。",
          "partOfSpeech": "adj.",
          "bookTitle": "Editorial English",
          "chapterTitle": "Tone",
          "dateAdded": "2026-01-01T00:00:00Z",
          "difficultyTier": "advanced",
          "reviewMode": "recognition",
          "reviewExamples": [
            "She is discerning about what deserves her focus."
          ],
          "rootForm": "discerning",
          "inflections": [
            "discernment"
          ],
          "graphLinksByKind": {
            "shares_usage": [
              {
                "id": "link-1",
                "cardId": "card-1",
                "word": "perceptive",
                "kind": "shares_usage",
                "label": "相關",
                "confidence": 0.9,
                "reason": "both describe careful judgment",
                "hidden": false\(extraLinkFields)
              }
            ]
          }\(extraCardFields)
        }
        """
    }

}
#endif
