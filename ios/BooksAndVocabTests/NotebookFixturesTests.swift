#if DEBUG
import Foundation
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
            "notebook.single",
        ])

        #expect(catalogKeys == previewKeys)
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

    @Test func repoAndGeneratedDatasetsDeclareEveryNotebookFixture() throws {
        let expected = Set(NotebookFixtureID.allCases.map(\.rawValue))
        let repoDocument = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let generatedDocument = try FixtureDatasetStore.decode(Self.generatedDemoData)

        #expect(Set(repoDocument.notebook.keys) == expected)
        #expect(Set(generatedDocument.notebook.keys) == expected)
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
}
#endif
