import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

/// #2107：啟動路徑的 ubiquity lookup 與 EPUB→iCloud 複製必須 off-main、可續跑、不重複。
@Suite("ICloudEPUBMigration — off-main, resumable launch migration")
struct ICloudEPUBMigrationTests {

    // MARK: - Helpers

    private final class Locked<Value>: @unchecked Sendable {
        private let lock = NSLock()
        private var stored: Value
        init(_ value: Value) { stored = value }
        var value: Value { lock.withLock { stored } }
        func set(_ value: Value) { lock.withLock { stored = value } }
        func mutate(_ body: (inout Value) -> Void) { lock.withLock { body(&stored) } }
    }

    private struct InjectedInterruption: Error {}

    private struct Sandbox {
        let root: URL
        var local: URL { root.appendingPathComponent("local", isDirectory: true) }
        var iCloud: URL { root.appendingPathComponent("icloud", isDirectory: true) }
        var staging: URL { root.appendingPathComponent("staging", isDirectory: true) }

        init() throws {
            root = FileManager.default.temporaryDirectory
                .appendingPathComponent("icloud-epub-migration-\(UUID().uuidString)", isDirectory: true)
            for dir in [local, iCloud] {
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            }
        }

        func remove() { try? FileManager.default.removeItem(at: root) }

        func names(in dir: URL) -> [String] {
            ((try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []).sorted()
        }
    }

    /// Real file system under the sandbox + in-memory completion flag (never touches
    /// UserDefaults.standard, so the hosted app's real key is unaffected).
    private static func fileOps(
        _ sandbox: Sandbox,
        completed: Locked<Bool>,
        iCloudAvailable: Bool = true
    ) -> ICloudEPUBMigration.FileOps {
        let local = sandbox.local
        let iCloud = sandbox.iCloud
        let staging = sandbox.staging
        return ICloudEPUBMigration.FileOps(
            lockKey: "test-\(UUID().uuidString)",
            iCloudBooksDirectory: { iCloudAvailable ? iCloud : nil },
            localBooksDirectory: { local },
            stagingDirectory: { staging },
            contentsOfDirectory: {
                try FileManager.default.contentsOfDirectory(at: $0, includingPropertiesForKeys: nil)
            },
            fileExists: { FileManager.default.fileExists(atPath: $0.path) },
            createDirectory: {
                try FileManager.default.createDirectory(at: $0, withIntermediateDirectories: true)
            },
            copyItem: { try FileManager.default.copyItem(at: $0, to: $1) },
            moveItem: { try FileManager.default.moveItem(at: $0, to: $1) },
            removeItem: { try FileManager.default.removeItem(at: $0) },
            isCompleted: { completed.value },
            markCompleted: { completed.set(true) }
        )
    }

    private static func inMemoryContainer() throws -> ModelContainer {
        try ModelContainer(
            for: Schema(AppBootstrap.fullModelTypes),
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
    }

    // MARK: - AppBootstrap.run does not wait on the migration

    @Test @MainActor func appBootstrapRunReturnsWithoutWaitingOnSlowMigrationSeam() throws {
        let previous = AuthManager.shared.modelContainer
        defer { AuthManager.shared.modelContainer = previous }
        let sandbox = try Sandbox()
        defer { sandbox.remove() }

        let release = DispatchSemaphore(value: 0)
        let finished = DispatchSemaphore(value: 0)
        let seamFinished = Locked(false)
        let seamRanOnMain = Locked<Bool?>(nil)
        var ops = Self.fileOps(sandbox, completed: Locked(false))
        ops.iCloudBooksDirectory = {
            seamRanOnMain.set(Thread.isMainThread)
            // Slow ubiquity lookup: blocks until the test releases it (bounded).
            _ = release.wait(timeout: .now() + 3)
            seamFinished.set(true)
            finished.signal()
            return nil
        }

        let outcome = AppBootstrap.run(
            arguments: [],
            persistentContainerFactory: { try Self.inMemoryContainer() },
            iCloudMigrationFileOps: ops
        )
        let returnedBeforeSeamFinished = !seamFinished.value
        release.signal()

        #expect(outcome.failure == nil)
        #expect(returnedBeforeSeamFinished, "AppBootstrap.run blocked on the slow migration seam")
        #expect(finished.wait(timeout: .now() + 5) == .success, "migration seam never ran")
        #expect(seamRanOnMain.value == false, "migration seam ran on the main thread")
    }

    // MARK: - Resumable, idempotent, done-key semantics

    @Test func interruptedMigrationResumesWithoutDuplicatingFiles() async throws {
        let sandbox = try Sandbox()
        defer { sandbox.remove() }
        let sources: [String: Data] = [
            "a.epub": Data(repeating: 0xA1, count: 4096),
            "b.epub": Data(repeating: 0xB2, count: 4096),
            "c.epub": Data(repeating: 0xC3, count: 4096),
        ]
        for (name, data) in sources {
            try data.write(to: sandbox.local.appendingPathComponent(name))
        }
        try Data("not a book".utf8).write(to: sandbox.local.appendingPathComponent("notes.txt"))
        let completed = Locked(false)

        // Run 1: copying b.epub is interrupted after writing a partial file to its
        // copy target (simulates a kill/disk error mid-copy).
        var interrupted = Self.fileOps(sandbox, completed: completed)
        interrupted.copyItem = { from, to in
            if from.lastPathComponent == "b.epub" {
                try Data(repeating: 0xB2, count: 100).write(to: to)
                throw InjectedInterruption()
            }
            try FileManager.default.copyItem(at: from, to: to)
        }
        let first = await ICloudEPUBMigration.schedule(fileOps: interrupted).value
        #expect(first == .incomplete(failed: 1, total: 3))
        #expect(completed.value == false, "done key must not be set while a book is missing")
        // Leftover of a crash between copy and commit on a previous launch.
        try FileManager.default.createDirectory(at: sandbox.staging, withIntermediateDirectories: true)
        try Data(repeating: 0xB2, count: 7).write(to: sandbox.staging.appendingPathComponent("b.epub"))

        // Run 2: resumes, copies only what is missing.
        let copies = Locked<[String]>([])
        var resumed = Self.fileOps(sandbox, completed: completed)
        resumed.copyItem = { from, to in
            copies.mutate { $0.append(from.lastPathComponent) }
            try FileManager.default.copyItem(at: from, to: to)
        }
        let progress = Locked<[String]>([])
        let second = await ICloudEPUBMigration.schedule(
            fileOps: resumed,
            progress: { done, total in progress.mutate { $0.append("\(done)/\(total)") } }
        ).value

        #expect(second == .completed(copied: 1, total: 3))
        #expect(copies.value == ["b.epub"], "already-migrated books were copied again")
        #expect(progress.value == ["1/3", "2/3", "3/3"])
        #expect(completed.value == true)
        #expect(sandbox.names(in: sandbox.iCloud) == ["a.epub", "b.epub", "c.epub"])
        for (name, data) in sources {
            let migrated = try Data(contentsOf: sandbox.iCloud.appendingPathComponent(name))
            #expect(migrated == data, "\(name) in iCloud is not a complete copy")
        }
        #expect(sandbox.names(in: sandbox.staging).isEmpty, "staging leftovers were not cleaned")

        // Run 3: done key short-circuits; nothing is copied.
        copies.set([])
        let third = await ICloudEPUBMigration.schedule(fileOps: resumed).value
        #expect(third == .alreadyCompleted)
        #expect(copies.value.isEmpty)
    }

    @Test func iCloudUnavailableDefersWithoutSettingDoneKey() async throws {
        let sandbox = try Sandbox()
        defer { sandbox.remove() }
        try Data(repeating: 1, count: 16).write(to: sandbox.local.appendingPathComponent("a.epub"))
        let completed = Locked(false)

        let result = await ICloudEPUBMigration.schedule(
            fileOps: Self.fileOps(sandbox, completed: completed, iCloudAvailable: false)
        ).value

        #expect(result == .deferredICloudUnavailable)
        #expect(completed.value == false)
        #expect(sandbox.names(in: sandbox.iCloud).isEmpty)
    }

    @Test func migrationSeamNeverRunsOnMainThread() async throws {
        let sandbox = try Sandbox()
        defer { sandbox.remove() }
        try Data(repeating: 1, count: 16).write(to: sandbox.local.appendingPathComponent("a.epub"))
        let mainThreadCalls = Locked(0)
        var ops = Self.fileOps(sandbox, completed: Locked(false))
        let copy = ops.copyItem
        let lookup = ops.iCloudBooksDirectory
        ops.copyItem = { from, to in
            if Thread.isMainThread { mainThreadCalls.mutate { $0 += 1 } }
            try copy(from, to)
        }
        ops.iCloudBooksDirectory = {
            if Thread.isMainThread { mainThreadCalls.mutate { $0 += 1 } }
            return lookup()
        }

        let result = await ICloudEPUBMigration.schedule(fileOps: ops).value

        #expect(result == .completed(copied: 1, total: 1))
        #expect(mainThreadCalls.value == 0)
    }

    @Test func pdfIsMigratedAndV1CompletedKeyIsRetired() async throws {
        let sandbox = try Sandbox()
        defer { sandbox.remove() }
        try Data(repeating: 1, count: 16).write(to: sandbox.local.appendingPathComponent("a.epub"))
        try Data(repeating: 2, count: 16).write(to: sandbox.local.appendingPathComponent("b.pdf"))
        try Data(repeating: 3, count: 16).write(to: sandbox.local.appendingPathComponent("C.PDF"))
        try Data("x".utf8).write(to: sandbox.local.appendingPathComponent("notes.txt"))

        let result = await ICloudEPUBMigration.schedule(
            fileOps: Self.fileOps(sandbox, completed: Locked(false))
        ).value

        #expect(result == .completed(copied: 3, total: 3))
        #expect(sandbox.names(in: sandbox.iCloud) == ["C.PDF", "a.epub", "b.pdf"])
        #expect(ICloudEPUBMigration.completionKey.hasSuffix("_v2"))
    }

    // MARK: - ICloudDownloadManager.startMonitoring

    @Test @MainActor func startMonitoringResolvesContainerOffMainWithoutBlocking() async {
        let release = DispatchSemaphore(value: 0)
        let lookupFinished = Locked(false)
        let lookupRanOnMain = Locked<Bool?>(nil)
        let mgr = ICloudDownloadManager(booksDirectoryLookup: {
            lookupRanOnMain.set(Thread.isMainThread)
            _ = release.wait(timeout: .now() + 3)
            lookupFinished.set(true)
            return nil
        })

        mgr.startMonitoring()
        let returnedBeforeLookupFinished = !lookupFinished.value
        release.signal()
        await mgr.waitForPendingStartForTesting()

        #expect(returnedBeforeLookupFinished, "startMonitoring blocked on the ubiquity lookup")
        #expect(lookupRanOnMain.value == false, "ubiquity lookup ran on the main thread")
        #expect(!mgr.isMonitoringForTesting, "nil container must not start a metadata query")
    }
}
