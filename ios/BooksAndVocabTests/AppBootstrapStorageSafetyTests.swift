import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct AppBootstrapStorageSafetyTests {
    private struct InjectedPersistentStoreFailure: Error {}

    @Test @MainActor func persistentInitializationFailurePreservesStoreAndEntersRecovery() {
        let previous = AuthManager.shared.modelContainer
        defer { AuthManager.shared.modelContainer = previous }

        let outcome = AppBootstrap.run(
            arguments: [],
            persistentContainerFactory: { throw InjectedPersistentStoreFailure() }
        )

        if outcome.failure == nil {
            Issue.record("persistent initialization failure must enter startup recovery")
        }
        let allInMemory = outcome.container.configurations.allSatisfy(\.isStoredInMemoryOnly)
        #expect(allInMemory)
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
