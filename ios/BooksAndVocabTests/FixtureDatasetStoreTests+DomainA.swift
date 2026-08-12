#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

extension FixtureDatasetStoreTests {
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

}
#endif
