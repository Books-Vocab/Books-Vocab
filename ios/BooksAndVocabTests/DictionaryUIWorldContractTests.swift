import Foundation
import Testing
@testable import BooksAndVocab

@Suite("P1/P2 dictionary UI World contract", .serialized)
struct DictionaryUIWorldContractTests {
    @Test("marketing_demo keeps canonical dictionary coverage disjoint and one-to-one")
    func marketingDemoDictionaryCoverageIsCanonical() throws {
        let marketing = try FixtureDatasetStore.decode(Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json"))
        let generated = try FixtureDatasetStore.decode(Self.data(at: "ops/demo/generated/ios_fixture_dataset.json"))

        #expect(marketing.schema == FixtureDatasetDocument.currentSchema)
        #expect(marketing.datasetID == "marketing_demo")
        #expect(marketing.scenarioContext?.dictionary == generated.scenarioContext?.dictionary)

        let dictionary = try #require(marketing.scenarioContext?.dictionary)
        #expect(Set(dictionary.lookup.keys) == ["idle", "loading", "result", "partial", "offline", "error", "retry"])
        #expect(dictionary.lookup["result"]?.fixtureID == "dictionary.lookup.result")
        #expect(dictionary.lookup["error"]?.fixtureID == "dictionary.lookup.error")

        let dictionaryCoverageRequired = try #require(dictionary.coverage["required"])
        let dictionaryCoverageCounterexamples = try #require(dictionary.coverage["counterexamples"])
        #expect(dictionaryCoverageRequired.fixtureIDs == [
            "dictionary.lookup.result",
            "dictionary.detail.senses",
        ])
        #expect(dictionaryCoverageCounterexamples.fixtureIDs == ["dictionary.lookup.error"])

        // `scenarioContext.dictionary.coverage` describes the typed payload;
        // the P1/P2 matrix is a separate surface contract. Keeping these
        // assertions on the matrix prevents a payload-level lookup state from
        // being mistaken for a user-facing counterexample row.
        let surfaceContract = try #require(
            marketing.scenarioContext?.surfaceContracts?["dictionary"]
        )
        #expect(
            surfaceContract == generated.scenarioContext?.surfaceContracts?["dictionary"]
        )
        let required = surfaceContract.required
        let counterexamples = surfaceContract.counterexamples
        #expect(Set(required.map(\.fixtureID)).isDisjoint(with: counterexamples.map(\.fixtureID)))
        #expect(Set(required.map(\.stepLabel)).isDisjoint(with: counterexamples.map(\.stepLabel)))
        #expect(
            Set(required.flatMap(\.assetIDs)).isDisjoint(with: counterexamples.flatMap(\.assetIDs))
        )

        for coverage in [required, counterexamples] {
            for assetID in coverage.flatMap(\.assetIDs) {
                #expect(marketing.assets.typeByID[assetID] != nil)
            }
        }

        #expect(required.map(\.fixtureID) == [
            "ui-p1-dictionary-rich",
            "ui-p2-dictionary-senses",
        ])
        #expect(required.map(\.stepLabel) == ["dictionary-rich", "dictionary-senses"])
        #expect(required.map(\.index) == [0, 1])
        #expect(required.map(\.assetIDs) == [["catalog_reader_epub"], ["catalog_reader_epub"]])
        #expect(counterexamples.map(\.fixtureID) == [
            "dictionary.lookup.partial",
            "dictionary.lookup.offline",
            "dictionary.lookup.error",
            "dictionary.lookup.retry",
            "dictionary.p2.missing-example",
            "dictionary.p2.materialize-error",
        ])
        #expect(counterexamples.map(\.stepLabel) == [
            "partial-counterexample",
            "offline-counterexample",
            "error-counterexample",
            "retry-counterexample",
            "missing-example-counterexample",
            "materialize-error-counterexample",
        ])
        #expect(counterexamples.map(\.index) == [2, 3, 4, 5, 6, 7])
        #expect(counterexamples.map(\.assetIDs) == [
            [],
            [],
            ["catalog_reader_pdf"],
            [],
            [],
            [],
        ])
    }

    @Test("P2 dictionary senses and counterexamples resolve through typed selectors")
    func p2DictionarySensesAndCounterexamplesResolveThroughTypedSelectors() throws {
        let data = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")

        try FixtureDatasetStore.withTestingData(data) {
            let fixtureID = UIWorldDictionaryFixtureID.p2DictionarySenses
            let surface = try #require(
                FixtureDatasetStore.dictionarySurfaceContract(for: fixtureID)
            )
            let dictionary = try #require(
                FixtureDatasetStore.dictionarySeed(for: fixtureID)
            )
            let missingExample = try #require(
                FixtureDatasetStore.dictionaryCounterexampleContract(
                    for: .p2MissingExample
                )
            )
            let materializeError = try #require(
                FixtureDatasetStore.dictionaryCounterexampleContract(
                    for: .p2MaterializeError
                )
            )

            #expect(fixtureID.rawValue == "ui-p2-dictionary-senses")
            #expect(surface.stepLabel == "dictionary-senses")
            #expect(surface.index == 1)
            #expect(surface.assetIDs == ["catalog_reader_epub"])
            #expect(dictionary.provenance.entryID == "engraved")
            #expect(dictionary.senses.map(\.id) == ["sense-1", "sense-2"])
            #expect(missingExample.fixtureID == UIWorldDictionaryCounterexampleID.p2MissingExample.rawValue)
            #expect(materializeError.fixtureID == UIWorldDictionaryCounterexampleID.p2MaterializeError.rawValue)
        }
    }

    @Test("P1 dictionary consumer resolves the canonical surface fixture")
    func p1DictionaryConsumerResolvesCanonicalSurfaceFixture() throws {
        let data = try Self.data(at: "ops/fixtures/ui_worlds/marketing_demo.json")

        try FixtureDatasetStore.withTestingData(data) {
            let fixtureID = UIWorldDictionaryFixtureID.p1DictionaryRich
            let surface = try #require(
                FixtureDatasetStore.dictionarySurfaceContract(for: fixtureID)
            )
            let dictionary = try #require(
                FixtureDatasetStore.dictionarySeed(for: fixtureID)
            )

            #expect(fixtureID.rawValue == "ui-p1-dictionary-rich")
            #expect(surface.stepLabel == "dictionary-rich")
            #expect(surface.index == 0)
            #expect(surface.assetIDs == ["catalog_reader_epub"])
            #expect(dictionary.provenance.entryID == "engraved")
            #expect(dictionary.senses.count == 2)
            #expect(dictionary.examples.count == 2)
        }
    }

    private static func data(at relativePath: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent(relativePath))
    }
}
