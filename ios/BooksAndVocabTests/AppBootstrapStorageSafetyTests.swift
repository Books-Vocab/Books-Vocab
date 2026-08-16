import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct AppBootstrapStorageSafetyTests {
    private struct InjectedPersistentStoreFailure: Error {}

    @Test @MainActor func persistentInitializationFailurePreservesStoreAndEntersRecovery() throws {
        let previous = AuthManager.shared.modelContainer
        defer { AuthManager.shared.modelContainer = previous }

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("app-bootstrap-failure-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let locations = AppBootstrap.PersistentStoreLocations(
            local: directory.appendingPathComponent("LocalStore.store"),
            cloud: directory.appendingPathComponent("CloudStore.store")
        )
        let artifacts = [locations.local, locations.cloud]
            .flatMap { AppBootstrap.storeArtifactURLs(for: $0) }
        var originalData: [URL: Data] = [:]
        for (index, artifact) in artifacts.enumerated() {
            let data = Data("store-sentinel-\(index)".utf8)
            try data.write(to: artifact)
            originalData[artifact] = data
        }

        let outcome = AppBootstrap.run(
            arguments: [],
            persistentStoreLocations: locations,
            persistentContainerFactory: { throw InjectedPersistentStoreFailure() }
        )

        if outcome.failure == nil {
            Issue.record("persistent initialization failure must enter startup recovery")
        }
        let allInMemory = outcome.container.configurations.allSatisfy(\.isStoredInMemoryOnly)
        #expect(allInMemory)
        for artifact in artifacts {
            #expect(FileManager.default.fileExists(atPath: artifact.path))
            #expect(try Data(contentsOf: artifact) == originalData[artifact])
        }
    }

    @Test func explicitPurgeRemovesSQLiteStoreAndRealSidecars() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("app-bootstrap-purge-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }

        let storeURL = directory.appendingPathComponent("LocalStore.store")
        let artifacts = AppBootstrap.storeArtifactURLs(for: storeURL)
        #expect(artifacts.map(\.lastPathComponent) == [
            "LocalStore.store",
            "LocalStore.store-shm",
            "LocalStore.store-wal",
        ])
        for artifact in artifacts {
            try Data("sentinel".utf8).write(to: artifact)
        }

        #expect(AppBootstrap.purgeStoreFiles(at: [storeURL]))
        #expect(artifacts.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }
}
