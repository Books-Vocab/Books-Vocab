#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite(.serialized) struct NotebookFixturesTests {
    private static var marketingDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
            return try Data(contentsOf: url)
        }
    }

    private static var generatedDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/demo/generated/ios_fixture_dataset.json")
            return try Data(contentsOf: url)
        }
    }

    @Test func notebookFixtureRegistryExposesPreviewAndCatalogScenarios() async throws {
        let previewKeys = NotebookFixtures.recipes(for: .preview).map(\.key.rawValue)
        let catalogKeys = NotebookFixtures.recipes(for: .catalog).map(\.key.rawValue)

        #expect(previewKeys == [
            "notebook.empty",
            "notebook.populated",
            "notebook.readerPickerMany",
            "notebook.readerPickerPopulated",
            "notebook.single",
        ])

        #expect(catalogKeys == [
            "notebook.cardGallery",
            "notebook.coverGallery",
            "notebook.editGallery",
            "notebook.empty",
            "notebook.populated",
            "notebook.readerPickerMany",
            "notebook.readerPickerPopulated",
            "notebook.single",
        ])
    }

    @Test func notebookFixtureRegistryIsManifestOnly() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BooksAndVocabTests
            .deletingLastPathComponent() // ios
            .appendingPathComponent("BooksAndVocab/Support/Fixtures/Notebook/NotebookFixtures.swift")
        let source = try String(contentsOf: url, encoding: .utf8)
        let registryStart = try #require(source.range(of: "private static let registry"))
        let registryEnd = try #require(source.range(of: "static func recipes", range: registryStart.upperBound..<source.endIndex))
        let registrySource = String(source[registryStart.lowerBound..<registryEnd.lowerBound])

        #expect(registrySource.contains("NotebookFixtureID.allCases.map"))
        #expect(registrySource.contains("FixtureDatasetStore.requireNotebookSeed(for: fixtureID)"))
        #expect(!registrySource.contains(".init("), "Notebook fixture registry must not construct local seed data")
    }

    @Test func repoAndGeneratedDatasetsDeclareNoUnknownNotebookFixtureKey() throws {
        let expected = Set(NotebookFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        // FROZEN 2026-08-05 — 凍結前這兩行是雙向 `==`（world keys 必須等於 allCases），
        // 那是「加一個 FixtureID 就得回填兩份 world」的稅源。現只驗單向：world 不得含
        // app 不認識的 key（那種 key 永遠不會 render）。兩行各配一個 non-empty 正控——
        // 沒有正控的 subset 對空集合恆真（假綠）。復業第一步＝改回 `==`，完整配方見正本。
        // 正本 docs/reference/catalog_scope.md §FROZEN。
        #expect(!repoDocument.notebook.isEmpty)
        #expect(Set(repoDocument.notebook.keys).isSubset(of: expected))
        #expect(!generatedDocument.notebook.isEmpty)
        #expect(Set(generatedDocument.notebook.keys).isSubset(of: expected))
    }

    @MainActor
    @Test func cardGalleryMaterializesManifestCardState() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let seed = try #require(document.notebook[NotebookFixtureID.cardGallery.rawValue])
        #expect(seed.notebooks.count >= 4)
        #expect(seed.notebooks.allSatisfy { $0.cardState != nil })

        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let cards = NotebookFixtures.cardData(for: .cardGallery)
            #expect(cards.contains { $0.cardCount > 500 && $0.dueCount > 0 && $0.isActive })
            #expect(cards.contains { $0.cardCount == 0 && $0.lastActivity == nil })
            #expect(cards.contains { $0.name.count > 24 })
            for card in cards {
                #expect(card.cardCount == card.dueCount + card.unlearnedCount + card.reviewedCount)
            }
        }
    }

    @MainActor
    @Test func editGalleryMaterializesManifestEditStates() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let seed = try #require(document.notebook[NotebookFixtureID.editGallery.rawValue])
        let ids = Set(seed.editStates.map(\.id))
        #expect(ids == [
            "create_blank",
            "edit_color_pattern",
            "edit_color_only",
            "edit_long_name",
            "edit_custom_image",
            "edit_empty_name",
        ])
        #expect(seed.editStates.contains { $0.mode == "create" && $0.name.isEmpty })
        #expect(seed.editStates.contains { $0.mode == "edit" && $0.name.isEmpty })
        #expect(seed.editStates.contains { $0.coverImageAssetRef == "images.notebook_cover_app_icon" })

        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            if case .create = NotebookFixtures.editSheetMode(id: "create_blank", for: .editGallery) {
                #expect(Bool(true))
            } else {
                Issue.record("create_blank must materialize create mode")
            }

            if case let .edit(name, color, coverPattern, coverImagePath) = NotebookFixtures.editSheetMode(id: "edit_custom_image", for: .editGallery) {
                #expect(name == "旅行閱讀詞庫")
                #expect(color == "#6F8EA3")
                #expect(coverPattern == nil)
                let path = try #require(coverImagePath)
                #expect(FileManager.default.fileExists(atPath: path))
            } else {
                Issue.record("edit_custom_image must materialize edit mode")
            }
        }
    }

    @MainActor
    @Test func singleNotebookFixtureComesFromUIWorld() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedNotebook = try #require(document.notebook[NotebookFixtureID.single.rawValue]?.notebooks.first)
        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let model = NotebookFixtures.renderModel(for: .single)
            #expect(model.notebooks.count == 1)
            #expect(model.notebooks.first?.remoteId == expectedNotebook.remoteId)
        }
    }

    @MainActor
    @Test func emptyNotebookFixtureIsExplicitlyDeclaredByUIWorld() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let expectedSeed = try #require(document.notebook[NotebookFixtureID.empty.rawValue])
        #expect(expectedSeed.notebooks.isEmpty)
        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let model = NotebookFixtures.renderModel(for: .empty)
            #expect(model.notebooks.isEmpty)
        }
    }

    @MainActor
    @Test func notebookEntriesApplyOptionalReviewSchedulingSeed() async throws {
        // Data-plane fix: notebook entry 可帶 optional review scheduling 欄位，
        // materialize 進 VocabularyEntry 後 NotebookStatsCalculator 才能算出
        // due/unlearned/reviewed 徽章與進度條；不帶欄位的 entry 行為不變。
        var topLevel = try #require(try JSONSerialization.jsonObject(with: Self.marketingDemoData) as? [String: Any])
        var notebookDomain = try #require(topLevel["notebook"] as? [String: Any])

        // 先把所有 notebook entry 的 review 欄位拔掉（確定性 baseline），
        // 再只給 populated.notebooks[0].entries[0] 注入 review scheduling。
        for (fixtureID, rawSeed) in notebookDomain {
            var seed = try #require(rawSeed as? [String: Any])
            var notebooks = try #require(seed["notebooks"] as? [[String: Any]])
            for rowIndex in notebooks.indices {
                var entries = try #require(notebooks[rowIndex]["entries"] as? [[String: Any]])
                for entryIndex in entries.indices {
                    for key in ["reviewIntervalHours", "nextReviewAt", "lastReviewedAt", "reviewCount"] {
                        entries[entryIndex].removeValue(forKey: key)
                    }
                }
                notebooks[rowIndex]["entries"] = entries
            }
            seed["notebooks"] = notebooks
            notebookDomain[fixtureID] = seed
        }

        var populated = try #require(notebookDomain[NotebookFixtureID.populated.rawValue] as? [String: Any])
        var notebooks = try #require(populated["notebooks"] as? [[String: Any]])
        var entries = try #require(notebooks[0]["entries"] as? [[String: Any]])
        let word = try #require(entries[0]["word"] as? String)
        let remoteId = try #require(notebooks[0]["remoteId"] as? String)
        entries[0]["reviewCount"] = 4
        entries[0]["reviewIntervalHours"] = 48.0
        entries[0]["nextReviewAt"] = "2026-07-08T00:00:00Z"
        entries[0]["lastReviewedAt"] = "2026-07-06T12:00:00Z"
        notebooks[0]["entries"] = entries
        populated["notebooks"] = notebooks
        notebookDomain[NotebookFixtureID.populated.rawValue] = populated
        topLevel["notebook"] = notebookDomain
        let mutated = try JSONSerialization.data(withJSONObject: topLevel)

        try await FixtureDatasetStore.withTestingData(mutated) {
            let model = NotebookFixtures.renderModel(for: .populated)
            let allEntries = try model.container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
            let target = try #require(allEntries.first { $0.word == word && $0.notebookId == remoteId })

            #expect(target.reviewCount == 4)
            #expect(target.reviewIntervalHours == 48.0)
            #expect(target.nextReviewAt == AppDateFormatters.parseISO8601("2026-07-08T00:00:00Z"))
            #expect(target.lastReviewedAt == AppDateFormatters.parseISO8601("2026-07-06T12:00:00Z"))

            // review 欄位缺席的 entry 行為不變：reviewCount 0 / lastReviewedAt nil。
            let untouched = try #require(allEntries.first { $0.word != word && $0.notebookId == remoteId })
            #expect(untouched.reviewCount == 0)
            #expect(untouched.lastReviewedAt == nil)

            // NotebookStatsCalculator 對 seeded scheduling 的判定：唯一 due 卡
            // （其餘 entry reviewCount == 0 → unlearned，不吃牆鐘）。
            let now = try #require(AppDateFormatters.parseISO8601("2026-07-09T00:00:00Z"))
            let stats = NotebookStatsCalculator.compute(allEntries, pendingEntries: [], now: now)
            #expect(stats[remoteId]?.dueCount == 1)
        }
    }

    @MainActor
    @Test func coverGalleryMaterializesManifestImageAsset() async throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let seed = try #require(document.notebook[NotebookFixtureID.coverGallery.rawValue])
        #expect(seed.notebooks.contains { $0.coverImageAssetRef == "images.notebook_cover_app_icon" })

        try await FixtureDatasetStore.withTestingData(Self.marketingDemoData) {
            let notebooks = NotebookFixtures.notebooks(for: .coverGallery)
            let imageBacked = notebooks.filter { $0.coverImagePath != nil }
            #expect(!imageBacked.isEmpty)
            for notebook in imageBacked {
                let path = try #require(notebook.coverImagePath)
                #expect(FileManager.default.fileExists(atPath: path))
            }
        }
    }
}
#endif
