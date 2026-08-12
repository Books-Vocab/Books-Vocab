#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

extension FixtureDatasetStoreTests {
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

}
#endif
