#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

extension FixtureDatasetStoreTests {
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

    // MARK: - Books/ containment guard (IMP-20260806-edac2b)

    /// The fixture seeders guard that an installed book asset landed directly
    /// under `Books/`. Comparing the two `URL`s naked rejects a path that
    /// satisfies the guard's own stated requirement:
    ///
    /// - `installedURL.deletingLastPathComponent()` **always** yields a
    ///   directory URL with a trailing slash.
    /// - `Book.localBooksDirectory` is `documentDirectory.appendingPathComponent("Books")`
    ///   computed *before* `createDirectory` runs — and `appendingPathComponent`
    ///   only appends a trailing slash when the directory already exists. The
    ///   result is then cached for the lifetime of the process.
    ///
    /// `standardizedFileURL` does not normalize a trailing slash away, so on a
    /// fresh container the two spellings of the same directory compare unequal
    /// and the seeder aborts. The aborting launch leaves `Books/` on disk, so
    /// every later launch passes — which is exactly how the UI suite stays
    /// green while the fixture is broken for anyone with a clean simulator.
    @Test func booksContainmentGuardsCompareNormalizedPaths() throws {
        let root = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("kg-books-guard-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        // Mirrors Book.localBooksDirectory: compute first, create second, cache.
        let cachedBooksDirectory = root.appendingPathComponent("Books")
        try FileManager.default.createDirectory(at: cachedBooksDirectory, withIntermediateDirectories: true)
        // Mirrors FixtureDatasetStore.installURL(for:ref:) for installAs "Books/<file>".
        let installedParent = root.appendingPathComponent("Books/reader-real-book.epub")
            .deletingLastPathComponent()

        #expect(
            installedParent.standardizedFileURL != cachedBooksDirectory.standardizedFileURL,
            "trailing-slash asymmetry is the trap: naked URL equality must never gate this"
        )
        #expect(
            installedParent.standardizedFileURL.path == cachedBooksDirectory.standardizedFileURL.path,
            "path comparison is what makes the two spellings of Books/ agree"
        )

        // Neither seeder may reintroduce the naked comparison.
        for relative in [
            "ios/BooksAndVocab/Support/UITestFixtureSeed+Reader.swift",
            "ios/BooksAndVocab/Support/Fixtures/Bookshelf/BookshelfFixtures.swift",
        ] {
            let source = try String(
                contentsOf: Self.repoRootURL.appendingPathComponent(relative),
                encoding: .utf8
            )
            #expect(
                !source.contains("deletingLastPathComponent().standardizedFileURL =="),
                "\(relative): Books/ containment guard must not compare URLs naked"
            )
            #expect(
                source.contains("standardizedFileURL.path =="),
                "\(relative): Books/ containment guard must compare normalized paths"
            )
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

}
#endif
