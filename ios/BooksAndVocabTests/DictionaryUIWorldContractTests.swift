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

        let required = try #require(dictionary.coverage["required"])
        let counterexamples = try #require(dictionary.coverage["counterexamples"])
        #expect(Set(required.fixtureIDs).isDisjoint(with: counterexamples.fixtureIDs))
        #expect(Set(required.stepLabels).isDisjoint(with: counterexamples.stepLabels))
        #expect(Set(required.assetIDs).isDisjoint(with: counterexamples.assetIDs))
        #expect(Set(required.assetInodes).isDisjoint(with: counterexamples.assetInodes))

        for coverage in [required, counterexamples] {
            #expect(coverage.assetIDs.count == coverage.assetInodes.count)
            for (assetID, inode) in zip(coverage.assetIDs, coverage.assetInodes) {
                #expect(inode == "inode:\(assetID)")
                #expect(marketing.assets.typeByID[assetID] != nil)
            }
        }

        #expect(required.fixtureIDs.contains("dictionary.lookup.result"))
        #expect(required.fixtureIDs.contains("dictionary.detail.senses"))
        #expect(required.stepLabels == ["idle", "loading", "result", "partial", "offline", "error", "retry"])
        #expect(counterexamples.fixtureIDs == [
            "dictionary.lookup.error",
            "dictionary.p2.missing-example",
            "dictionary.p2.materialize-error",
        ])
        #expect(counterexamples.stepLabels == [
            "error-counterexample",
            "missing-example-counterexample",
            "materialize-error-counterexample",
        ])
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

    private static func data(at relativePath: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent(relativePath))
    }
}
