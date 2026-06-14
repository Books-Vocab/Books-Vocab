#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

// .serialized: tests exercise process-level fixture environment loading.
@Suite(.serialized)
struct FixtureDatasetStoreTests {
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

    @Test func settingsSeedFailsWhenNullableStateKeysAreMissing() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "missing-settings-nullable-state",
          "settings": {
            "logged_out": {
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

            let subscriptionManager = UITestSubscriptionManager.proAccess()
            #expect(subscriptionManager.entitlements.pro.is_active == true)
            #expect(subscriptionManager.entitlements.pro.plan_name == "Books & Vocab Pro")
            #expect(subscriptionManager.entitlements.pro.last_synced_at == "2026-06-10T00:00:00Z")
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

    @Test @MainActor func externalDatasetDeclaresRuntimeWorlds() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-runtime-worlds",
          "assets": {
            "books": {},
            "audio": {
              "runtime-audio": {
                "sourcePath": "/tmp/audio.m4a",
                "sha256": "unused-in-decode-test",
                "byteSize": 0,
                "installAs": null,
                "contentType": "audio/mp4"
              }
            },
            "subtitles": {
              "runtime-subtitle": {
                "sourcePath": "/tmp/audio.srt",
                "sha256": "unused-in-decode-test",
                "byteSize": 0,
                "installAs": null,
                "contentType": "application/x-subrip; charset=utf-8"
              }
            },
            "text": {
              "reader-source": {
                "sourcePath": "/tmp/source.md",
                "sha256": "unused-in-decode-test",
                "byteSize": 0,
                "installAs": null,
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
                    "subtitleAssetRef": "subtitles.runtime-subtitle"
                  }
                }
              ]
            }
          },
          "reader": {
            "realBookLibrary": {
              "textAssetRef": "text.reader-source",
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
            let runtimeSeed = FixtureDatasetStore.runtimePodcastSeed(for: .playablePreview)
            #expect(runtimeSeed?.seriesTitle == "Runtime Series")
            #expect(runtimeSeed?.episodes.first?.download?.audioAssetRef == "audio.runtime-audio")
            #expect(runtimeSeed?.episodes.first?.download?.subtitleAssetRef == "subtitles.runtime-subtitle")
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
          "settings": {
            "subscribed_active": {
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
                "summaryText": "已連線 · 240 張 · 剛剛"
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
                  "progression": 0.5,
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
                { "episodeNumber": 2, "title": "Unstarted Episode", "durationSec": 1200 }
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

}
#endif
