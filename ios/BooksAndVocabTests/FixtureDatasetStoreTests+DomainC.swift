#if DEBUG
import CryptoKit
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

extension FixtureDatasetStoreTests {
    @Test func reviewCalendarEvidenceRejectsNestedCheckoutIdentityKeys() throws {
        for unknownKey in ["assetInodes", "inode"] {
            let value = unknownKey == "inode" ? "\"checkout-inode\"" : "[\"checkout-inode\"]"
            // The app decoder must not silently erase checkout-local identity
            // fields before the host exact-key validator sees the same world.
            let dataset = """
            {
              "schema": "kg.fixture.dataset.v2",
              "datasetID": "nested-review-evidence-unknown-key",
              "scenarioContext": {
                "surfaceContracts": {
                  "reviewCalendar": {
                    "required": [
                      {
                        "fixtureID": "calendar",
                        "stepLabel": "calendar",
                        "index": 0,
                        "assetIDs": ["calendar-shot"],
                        "\(unknownKey)": \(value)
                      }
                    ],
                    "counterexamples": []
                  }
                }
              }
            }
            """

            #expect(throws: DecodingError.self) {
                _ = try FixtureDatasetStore.decode(Self.completeV2DatasetData(dataset))
            }
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

    @Test @MainActor func assetInstallPlanResolvesFromInjectedRootOutsideProcessCWD() throws {
        let assetRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-ui-world-asset-root-\(UUID().uuidString)", isDirectory: true)
        let relativeSourcePath = "fixture-payload-\(UUID().uuidString).txt"
        let source = assetRoot.appendingPathComponent(relativeSourcePath)
        try FileManager.default.createDirectory(at: assetRoot, withIntermediateDirectories: true)
        try Data("asset payload".utf8).write(to: source)
        #expect(
            !FileManager.default.fileExists(atPath: relativeSourcePath),
            "the relative asset must not be discoverable from the process CWD"
        )
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
                "sourcePath": "\(relativeSourcePath)",
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

        defer {
            try? FileManager.default.removeItem(at: source)
        }

        #expect(throws: (any Error).self) {
            try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
                _ = try FixtureDatasetStore.requireInstalledAssetURL(ref: "text.payload")
            }
        }
    }

    @Test @MainActor func assetInstallPlanRejectsAbsoluteSourcePath() throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-ui-world-asset-source-\(UUID().uuidString).txt")
        try Data("asset payload".utf8).write(to: source)
        let hash = try FixtureDatasetStore.sha256Hex(for: source)
        let byteSize = try FixtureDatasetStore.byteSize(for: source)
        let installAs = "UITestAssets/\(UUID().uuidString)/payload.txt"
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-asset-install-plan-absolute",
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

        defer { try? FileManager.default.removeItem(at: source) }

        #expect(throws: (any Error).self) {
            try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
                _ = try FixtureDatasetStore.requireInstalledAssetURL(ref: "text.payload")
            }
        }
    }

    @Test @MainActor func readerTOCAssetsMaterializeWithCheckedInIntegrity() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "reader-toc-asset-integrity",
          "assets": {
            "books": {
              "reader_real_book_epub": {
                "sourcePath": "ops/fixtures/assets/reader-real-book.epub",
                "sha256": "ee786150bbe89660e9aa35cd66e490734d94f5a2415267ed84a64dbb3a5d036c",
                "byteSize": 18653,
                "installAs": "Books/reader-real-book-contract.epub",
                "contentType": "application/epub+zip"
              },
              "reader_invalid_destination_epub": {
                "sourcePath": "ops/fixtures/assets/reader-invalid-destination.epub",
                "sha256": "89864813d0f197efe8f680287579d5a338f7611cdb88f2cf42ce8ea38cacc68f",
                "byteSize": 17344,
                "installAs": "Books/reader-invalid-destination-contract.epub",
                "contentType": "application/epub+zip"
              }
            },
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {}
          }
        }
        """
        let installedPaths = [
            "Books/reader-real-book-contract.epub",
            "Books/reader-invalid-destination-contract.epub",
        ].map {
            FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
                .appendingPathComponent($0)
        }
        defer {
            for path in installedPaths {
                try? FileManager.default.removeItem(at: path)
            }
        }

        try FixtureDatasetStore.withTestingData(Self.completeV2DatasetData(dataset)) {
            let contracts = [
                (
                    ref: "books.reader_real_book_epub",
                    sourcePath: "ops/fixtures/assets/reader-real-book.epub",
                    fileName: "reader-real-book-contract.epub",
                    sha256: "ee786150bbe89660e9aa35cd66e490734d94f5a2415267ed84a64dbb3a5d036c",
                    byteSize: 18653
                ),
                (
                    ref: "books.reader_invalid_destination_epub",
                    sourcePath: "ops/fixtures/assets/reader-invalid-destination.epub",
                    fileName: "reader-invalid-destination-contract.epub",
                    sha256: "89864813d0f197efe8f680287579d5a338f7611cdb88f2cf42ce8ea38cacc68f",
                    byteSize: 17344
                ),
            ]

            for contract in contracts {
                let installed = try FixtureDatasetStore.requireInstalledAssetURL(ref: contract.ref)
                let source = Self.repoRootURL.appendingPathComponent(contract.sourcePath)
                #expect(installed.lastPathComponent == contract.fileName)
                #expect(try FixtureDatasetStore.byteSize(for: installed) == contract.byteSize)
                #expect(try FixtureDatasetStore.sha256Hex(for: installed) == contract.sha256)
                #expect(try Data(contentsOf: installed) == Data(contentsOf: source))
            }
        }
    }

    @Test func readerEPUBSourcePathRejectsUnsafeLocatorsAtDecodeBoundary() throws {
        let cases = [
            Self.readerRealBookAssetPath,
            "ops/fixtures/assets/../../../../reader-real-book.epub",
            "ops/fixtures/assets/./reader-real-book.epub",
            "ops/fixtures/assets//reader-real-book.epub",
            "ops/fixtures/assets/reader-real-book.epub/",
        ]

        for sourcePath in cases {
            let data = try Self.readerAssetDatasetData(
                sourcePath: sourcePath,
                installAs: "Books/reader-source-path-" + UUID().uuidString + ".epub"
            )

            #expect(throws: DecodingError.self) {
                _ = try FixtureDatasetStore.decode(data)
            }
        }
    }

    @Test func installAsRejectsEmptyPathComponentsAtDecodeBoundary() throws {
        for installAs in [
            "",
            "   ",
            "Books//reader.epub",
            "Books/reader.epub/",
            "Books/./reader.epub",
            "Books/../reader.epub",
            "/Books/reader.epub",
        ] {
            let data = try Self.readerAssetDatasetData(
                sourcePath: "ops/fixtures/assets/reader-real-book.epub",
                installAs: installAs
            )

            #expect(throws: DecodingError.self) {
                _ = try FixtureDatasetStore.decode(data)
            }
        }
    }

    @Test @MainActor func destinationSymlinkEscapeIsRejectedBeforeCopy() throws {
        let source = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-ui-world-destination-source-\(UUID().uuidString).txt")
        let outsideRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("kg-ui-world-destination-outside-\(UUID().uuidString)", isDirectory: true)
        let outsideFile = outsideRoot.appendingPathComponent("payload.txt")
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let symlinkComponent = "kg-p3-destination-symlink-\(UUID().uuidString)"
        let symlink = documents.appendingPathComponent(symlinkComponent)
        let installAs = "\(symlinkComponent)/payload.txt"
        let sentinel = Data("outside sentinel".utf8)

        try Data("source payload".utf8).write(to: source)
        try FileManager.default.createDirectory(at: outsideRoot, withIntermediateDirectories: true)
        try sentinel.write(to: outsideFile)
        try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: outsideRoot)
        defer {
            try? FileManager.default.removeItem(at: symlink)
            try? FileManager.default.removeItem(at: outsideRoot)
            try? FileManager.default.removeItem(at: source)
        }

        let hash = try FixtureDatasetStore.sha256Hex(for: source)
        let byteSize = try FixtureDatasetStore.byteSize(for: source)
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "destination-symlink-escape",
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

        // The destination points through a symlink outside Documents. The
        // preflight must reject it before create/remove/copy can touch the
        // outside sentinel.
        // No implementation detail is trusted here: the observable contract
        // is throw + unchanged outside bytes.
        // Swift Testing cannot compare an arbitrary thrown CocoaError payload
        // portably across Foundation versions, so keep the assertion typed.
        // The source realpath guard remains covered by the test above.
        //
        // swiftlint:disable:next force_try
        let data = try Self.completeV2DatasetData(dataset)
        #expect(throws: (any Error).self) {
            try FixtureDatasetStore.withTestingData(data) {
                _ = try FixtureDatasetStore.requireInstalledAssetURL(ref: "text.payload")
            }
        }
        #expect(try Data(contentsOf: outsideFile) == sentinel)
    }

    @Test func readerEPUBSourcePathRejectsSymlinkOutsideRepository() throws {
        let source = URL(fileURLWithPath: Self.readerRealBookAssetPath)
        let outsideRoot = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent(
                "kg-reader-source-escape-" + UUID().uuidString,
                isDirectory: true
            )
        let outside = outsideRoot.appendingPathComponent("reader-real-book.epub")
        let symlinkName = ".p3-reader-source-escape-" + UUID().uuidString + ".epub"
        let symlink = Self.repoRootURL
            .appendingPathComponent("ops/fixtures/assets/" + symlinkName)
        try FileManager.default.createDirectory(at: outsideRoot, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: source, to: outside)
        try FileManager.default.createSymbolicLink(
            at: symlink,
            withDestinationURL: outside
        )
        defer {
            try? FileManager.default.removeItem(at: symlink)
            try? FileManager.default.removeItem(at: outsideRoot)
        }

        let installAs = "Books/reader-symlink-" + UUID().uuidString + ".epub"
        let data = try Self.readerAssetDatasetData(
            sourcePath: "ops/fixtures/assets/" + symlinkName,
            installAs: installAs
        )
        let installed = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(installAs)
        defer { try? FileManager.default.removeItem(at: installed) }

        _ = try FixtureDatasetStore.decode(data)
        #expect(throws: (any Error).self) {
            try FixtureDatasetStore.withTestingData(data) {
                _ = try FixtureDatasetStore.requireInstalledAssetURL(ref: "books.reader-book")
            }
        }
    }

    @Test @MainActor func evidenceFixtureProofUsesMaterializedDatasetBytes() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "test-evidence-fixture"
        }
        """
        let data = try Self.completeV2DatasetData(dataset)
        let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let expected = documents.appendingPathComponent("Evidence/test-evidence-fixture.json")
        defer { try? FileManager.default.removeItem(at: expected.deletingLastPathComponent()) }

        try FixtureDatasetStore.withTestingData(data) {
            let proof = try FixtureDatasetStore.materializeEvidenceFixture()
            let rawObject = try JSONSerialization.jsonObject(with: data)
            let canonical = try JSONSerialization.data(withJSONObject: rawObject, options: [.sortedKeys])
            let expectedHash = SHA256.hash(data: canonical)
                .map { String(format: "%02x", $0) }
                .joined()
            let sourceHash = SHA256.hash(data: data)
                .map { String(format: "%02x", $0) }
                .joined()

            #expect(proof.datasetID == "test-evidence-fixture")
            #expect(proof.path == "Evidence/test-evidence-fixture.json")
            #expect(proof.type == "application/json")
            #expect(proof.datasetSHA256 == sourceHash)
            #expect(proof.bytes == canonical.count)
            #expect(proof.sha256 == expectedHash)
            #expect(try Data(contentsOf: expected) == canonical)
            #expect(try Data(contentsOf: expected) != data)
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
                "sha256": "ee786150bbe89660e9aa35cd66e490734d94f5a2415267ed84a64dbb3a5d036c",
                "byteSize": 18653,
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
