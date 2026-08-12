#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

extension FixtureDatasetStoreTests {
    static var repoRootURL: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repo root
    }

    static var readerRealBookAssetPath: String {
        repoRootURL
            .appendingPathComponent("ops/fixtures/assets/reader-real-book.epub")
            .path
    }

    static func withEnv<T>(_ key: String, _ value: String?, perform: () throws -> T) rethrows -> T {
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

    static func withFixtureDatasetEnv<T>(_ value: String?, perform: () throws -> T) rethrows -> T {
        try withEnv("KG_FIXTURE_DATASET_B64", value, perform: perform)
    }

    static func withFixtureDatasetDeflateEnv<T>(_ value: String?, perform: () throws -> T) rethrows -> T {
        try withEnv("KG_FIXTURE_DATASET_DEFLATE_B64", value, perform: perform)
    }

    /// base64(raw DEFLATE) — the exact payload shape ops stages into
    /// `KG_FIXTURE_DATASET_DEFLATE_B64` (Apple `.zlib` == raw DEFLATE stream).
    static func deflateBase64(_ data: Data) throws -> String {
        let compressed = try (data as NSData).compressed(using: .zlib) as Data
        return compressed.base64EncodedString()
    }

    static func completeV2DatasetData(_ json: String) throws -> Data {
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
    static func settingsDataset(
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

    static func vocabularyDataset(
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

    static func reviewDeckDataset(
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

    static func notebookDataset(
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

    static func bookshelfDataset(
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

    static func syncPresenterDataset(
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

    static func fullVocabularyEntryJSON(word: String) -> String {
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

    static func readerSeedJSON(extraFields: String = "") -> String {
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

    static func todayReviewCardJSON(
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
