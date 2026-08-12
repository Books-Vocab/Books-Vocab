#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

// Schema/domain tests remain parallel; process-level environment tests live in FixtureDatasetEnvironmentTests.
@Suite
struct FixtureDatasetStoreTests {
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

}
#endif
