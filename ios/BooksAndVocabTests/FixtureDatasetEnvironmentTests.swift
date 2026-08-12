#if DEBUG
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@Suite(.serialized)
struct FixtureDatasetEnvironmentTests {
    @Test func seedResolutionFailureDescriptionExplainsWhyWorldIsNotLoaded() throws {
        // Absent: neither env key set, no testing override.
        try FixtureDatasetStoreTests.withFixtureDatasetEnv(nil) {
            try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv(nil) {
                try FixtureDatasetStore.withTestingData(nil) {
                    let message = FixtureDatasetStore.seedResolutionFailureDescription(resolving: "notebook.demo")
                    #expect(message.contains("UI World is not loaded"))
                    #expect(message.contains("KG_FIXTURE_DATASET_DEFLATE_B64"))
                    #expect(message.contains("KG_FIXTURE_DATASET_B64"))
                    #expect(message.contains("notebook.demo"))
                }
            }
        }

        // Invalid: env present but broken — must surface the real load failure,
        // never masquerade as "missing <fixture key>".
        try FixtureDatasetStoreTests.withFixtureDatasetEnv("not-base64") {
            try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv(nil) {
                try FixtureDatasetStore.withTestingData(nil) {
                    let message = FixtureDatasetStore.seedResolutionFailureDescription(resolving: "notebook.demo")
                    #expect(message.contains("UI World failed to load"))
                    #expect(message.contains("env:KG_FIXTURE_DATASET_B64"))
                    #expect(message.contains("not valid base64"))
                    #expect(message.contains("notebook.demo"))
                }
            }
        }

        // Loaded but key genuinely missing: keep the classic message.
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "loaded-world"
        }
        """
        try FixtureDatasetStore.withTestingData(FixtureDatasetStoreTests.completeV2DatasetData(dataset)) {
            let message = FixtureDatasetStore.seedResolutionFailureDescription(resolving: "notebook.demo")
            #expect(message == "UI World is missing notebook.demo")
        }
    }

    @Test func fixtureDatasetEnvFailsWhenPresentButEmptyOrMalformed() throws {
        try FixtureDatasetStoreTests.withFixtureDatasetEnv("") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("must not be empty"))
            }
        }

        try FixtureDatasetStoreTests.withFixtureDatasetEnv("not-base64") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("not valid base64"))
            }
        }
    }

    @Test func fixtureDatasetTestingOverrideTakesPrecedenceOverMalformedEnv() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "override-world"
        }
        """

        try FixtureDatasetStoreTests.withFixtureDatasetEnv("not-base64") {
            try FixtureDatasetStore.withTestingData(FixtureDatasetStoreTests.completeV2DatasetData(dataset)) {
                #expect(FixtureDatasetStore.debugSummary() == "override-world @ testing-override")
            }
        }
    }

    @Test func fixtureDatasetDeflateEnvLoadsCompressedWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "deflate-world"
        }
        """
        let deflateB64 = try FixtureDatasetStoreTests.deflateBase64(FixtureDatasetStoreTests.completeV2DatasetData(dataset))

        try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv(deflateB64) {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary() == "deflate-world @ env:KG_FIXTURE_DATASET_DEFLATE_B64")
            }
        }
    }

    @Test func fixtureDatasetDeflateEnvFailsWhenEmptyMalformedOrNotDeflate() throws {
        try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv("") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_DEFLATE_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("must not be empty"))
            }
        }

        try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv("not-base64") {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_DEFLATE_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("not valid base64"))
            }
        }

        // Valid base64 of plaintext JSON — not a raw DEFLATE stream.
        let plaintextBase64 = Data("{\"schema\":\"kg.fixture.dataset.v2\"}".utf8).base64EncodedString()
        try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv(plaintextBase64) {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary().contains("invalid @ env:KG_FIXTURE_DATASET_DEFLATE_B64"))
                #expect(FixtureDatasetStore.debugSummary().contains("decompress failed"))
            }
        }
    }

    @Test func fixtureDatasetEnvFailsWhenBothPlainAndDeflateArePresent() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "ambiguous-world"
        }
        """
        let data = try FixtureDatasetStoreTests.completeV2DatasetData(dataset)
        let plainB64 = data.base64EncodedString()
        let deflateB64 = try FixtureDatasetStoreTests.deflateBase64(data)

        try FixtureDatasetStoreTests.withFixtureDatasetEnv(plainB64) {
            try FixtureDatasetStoreTests.withFixtureDatasetDeflateEnv(deflateB64) {
                try FixtureDatasetStore.withTestingData(nil) {
                    let summary = FixtureDatasetStore.debugSummary()
                    #expect(summary.contains("invalid @"))
                    #expect(summary.contains("both KG_FIXTURE_DATASET_DEFLATE_B64 and KG_FIXTURE_DATASET_B64 are set"))
                }
            }
        }
    }

    @Test func fixtureDatasetPlaintextEnvStillLoadsWorld() throws {
        let dataset = """
        {
          "schema": "kg.fixture.dataset.v2",
          "datasetID": "plaintext-world"
        }
        """
        let plainB64 = try FixtureDatasetStoreTests.completeV2DatasetData(dataset).base64EncodedString()

        try FixtureDatasetStoreTests.withFixtureDatasetEnv(plainB64) {
            try FixtureDatasetStore.withTestingData(nil) {
                #expect(FixtureDatasetStore.debugSummary() == "plaintext-world @ env:KG_FIXTURE_DATASET_B64")
            }
        }
    }
}
#endif
