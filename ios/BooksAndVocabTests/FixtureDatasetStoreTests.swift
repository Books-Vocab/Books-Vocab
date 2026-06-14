#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

// .serialized: tests mutate FixtureDatasetStore.testingOverrideData singleton.
@Suite(.serialized)
struct FixtureDatasetStoreTests {
    @Test @MainActor func externalDatasetDeclaresAuthAndEntitlementWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v1",
          "datasetID": "test-ui-world",
          "auth": {
            "signedIn": {
              "isLoggedIn": true,
              "userId": "world-user",
              "token": "world-token",
              "displayName": "World User",
              "email": "world@example.com",
              "provider": "apple",
              "providerUserId": "apple:world-user"
            },
            "guest": {
              "isLoggedIn": false,
              "userId": null,
              "token": null,
              "displayName": null,
              "email": null,
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

        try FixtureDatasetStore.withTestingData(Data(dataset.utf8)) {
            #expect(FixtureDatasetStore.debugSummary() == "test-ui-world @ testing-override")

            let auth = try #require(FixtureDatasetStore.authSeed(for: .signedIn))
            #expect(auth.isLoggedIn == true)
            #expect(auth.userId == "world-user")
            #expect(auth.token == "world-token")
            #expect(auth.displayName == "World User")
            #expect(auth.email == "world@example.com")

            let guest = try #require(FixtureDatasetStore.authSeed(for: .guest))
            #expect(guest.isLoggedIn == false)
            #expect(guest.userId == nil)

            let entitlements = try #require(FixtureDatasetStore.entitlementsSeed(for: .pro))
            #expect(entitlements.pro.is_active == true)
            #expect(entitlements.pro.status == "active")

            let subscriptionManager = UITestSubscriptionManager.proAccess()
            #expect(subscriptionManager.entitlements.pro.is_active == true)
            #expect(subscriptionManager.entitlements.pro.plan_name == "Books & Vocab Pro")
            #expect(subscriptionManager.entitlements.pro.last_synced_at == "2026-06-10T00:00:00Z")
        }
    }

    @Test @MainActor func externalDatasetDeclaresRuntimeWorlds() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v1",
          "datasetID": "test-runtime-worlds",
          "runtimePodcast": {
            "playablePreview": {
              "audioPath": "/tmp/audio.m4a",
              "subtitlePath": "/tmp/audio.srt",
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
                  "subtitleAvailable": true
                }
              ]
            }
          },
          "reader": {
            "realBookLibrary": {
              "textPath": "/tmp/source.md",
              "title": "Reader Source",
              "author": "KG",
              "bookFileName": "reader.epub",
              "notebookRemoteId": "reader-notebook",
              "notebookName": "Reader Notebook",
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
              "notebookName": null,
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

        try FixtureDatasetStore.withTestingData(Data(dataset.utf8)) {
            #expect(FixtureDatasetStore.runtimePodcastSeed(for: .playablePreview)?.seriesTitle == "Runtime Series")
            #expect(FixtureDatasetStore.readerSeed(for: .realBookLibrary)?.entry.word == "introduction")
            #expect(FixtureDatasetStore.vocabularySeed(for: .searchVocabNotebook)?.entries.first?.word == "affect")
            #expect(FixtureDatasetStore.reviewDeckSeed(for: .probe)?.entries.first?.word == "probeword001")
        }
    }

    @Test @MainActor func externalDatasetOverridesFixtureSeeds() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v1",
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

        try FixtureDatasetStore.withTestingData(Data(dataset.utf8)) {
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
          "schema": "kg.fixture.dataset.v1",
          "datasetID": "test-notebook-podcast",
          "notebook": {
            "populated": {
              "notebooks": [
                {
                  "remoteId": "default",
                  "name": "外部單字本",
                  "isDefault": true,
                  "sortOrder": 0,
                  "entries": [
                    { "word": "serendipity", "translation": "機緣巧合" }
                  ]
                },
                {
                  "remoteId": "nb-external",
                  "name": "外部第二本",
                  "sortOrder": 1,
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
                { "episodeNumber": 2, "title": "Unstarted Episode" }
              ]
            }
          }
        }
        """

        try FixtureDatasetStore.withTestingData(Data(dataset.utf8)) {
            #expect(FixtureDatasetStore.debugSummary() == "test-notebook-podcast @ testing-override")

            let notebookSeed = FixtureDatasetStore.notebookSeed(for: .populated)
            #expect(notebookSeed?.notebooks.count == 2)
            #expect(notebookSeed?.notebooks.first?.name == "外部單字本")

            let notebookModel = NotebookFixtures.renderModel(for: .populated)
            #expect(notebookModel.notebooks.map(\.name) == ["外部單字本", "外部第二本"])
            #expect(notebookModel.container != nil)

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
