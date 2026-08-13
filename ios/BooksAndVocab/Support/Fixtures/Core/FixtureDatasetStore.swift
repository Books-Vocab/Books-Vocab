import Foundation
import CryptoKit
import AVFoundation
import AVFAudio
import UniformTypeIdentifiers

private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
private let fixtureAssetRootEnvKey = "KG_FIXTURE_ASSET_ROOT"
// base64(raw DEFLATE(JSON)) — preferred injection key. Plaintext base64 of a
// multi-MB UI World overflows the ~1MB posix_spawn env block and the app then
// silently sees *no* dataset; compressing keeps large worlds under the limit.
// Apple `.zlib` decompression expects a raw DEFLATE stream (no zlib/gzip
// container) — producers must use e.g. Python `zlib.compressobj(wbits=-15)`.
private let fixtureDatasetDeflateEnvKey = "KG_FIXTURE_DATASET_DEFLATE_B64"
private let installedFixtureProofRelativePathEnvKey = "KG_P9_INSTALLED_FIXTURE_PROOF_RELATIVE_PATH"
private let uiTestSourceCommitEnvKey = "KG_UI_TEST_SOURCE_COMMIT"

struct FixtureInstalledAssetProof: Equatable {
    let assetID: String
    let installedPath: String
    let expectedSHA256: String
    let expectedByteSize: Int
    let actualSHA256: String
    let actualByteSize: Int

    var accessibilityDescriptor: String {
        [
            assetID,
            installedPath,
            expectedSHA256,
            String(expectedByteSize),
            actualSHA256,
            String(actualByteSize),
        ].joined(separator: "|")
    }
}

struct UIWorldInstalledAsset: Equatable {
    let ref: String
    let url: URL
    let sha256: String
    let byteSize: Int
    let contentType: String
    /// 僅記錄安裝副本的 filesystem identity；manifest 不依賴 source inode。
    let fileSystemInode: UInt64
}

enum FixtureDatasetStore {
    @TaskLocal static var testingOverrideData: Data?
    @TaskLocal static var testingAssetRoot: URL?

    private typealias PreparedEvidenceFixtureProof = (
        proof: UIWorldInstalledFixtureProof,
        value: String
    )
    private static let evidenceCacheLock = NSLock()
    private static var evidenceProofCache: [String: PreparedEvidenceFixtureProof] = [:]
    private static var latestEvidenceCacheKey: String?

    /// The active domain fixture selected by the canonical `-seedFixture`
    /// router. Production code reads this provenance instead of inspecting raw
    /// launch arguments or maintaining a second fixture counter.
    @MainActor private(set) static var activeSettingsFixtureID: SettingsFixtureID?

    @MainActor
    static func activateSettingsFixture(_ fixtureID: SettingsFixtureID) {
        guard settingsSeed(for: fixtureID) != nil else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "settings.\(fixtureID.rawValue)"))
        }
        activeSettingsFixtureID = fixtureID
    }

    static func withTestingData<T>(_ data: Data?, perform: () throws -> T) rethrows -> T {
        try $testingOverrideData.withValue(data) {
            try perform()
        }
    }

    static func withTestingData<T>(_ data: Data?, perform: () async throws -> T) async rethrows -> T {
        try await $testingOverrideData.withValue(data) {
            try await perform()
        }
    }

    static func withTestingAssetRoot<T>(_ root: URL?, perform: () throws -> T) rethrows -> T {
        try $testingAssetRoot.withValue(root?.standardizedFileURL) {
            try perform()
        }
    }

    static func withTestingAssetRoot<T>(_ root: URL?, perform: () async throws -> T) async rethrows -> T {
        try await $testingAssetRoot.withValue(root?.standardizedFileURL) {
            try await perform()
        }
    }

    static func settingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.settings[fixtureID.rawValue]
    }

    static func requireSettingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed {
        guard let seed = settingsSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "settings.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func authSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.auth[fixtureID.rawValue]
    }

    static func requireAuthSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed {
        guard let seed = authSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "auth.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func entitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.entitlements[fixtureID.rawValue]
    }

    static func requireEntitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed {
        guard let seed = entitlementsSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "entitlements.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func syncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.syncPresenter[fixtureID.rawValue]
    }

    static func requireSyncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed {
        guard let seed = syncPresenterSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "syncPresenter.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func bookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.bookshelf[fixtureID.rawValue]
    }

    static func requireBookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed {
        guard let seed = bookshelfSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "bookshelf.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func todayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.todayReview[fixtureID.rawValue]
    }

    static func requireTodayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed {
        guard let seed = todayReviewSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "todayReview.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func notebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.notebook[fixtureID.rawValue]
    }

    static func requireNotebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed {
        guard let seed = notebookSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "notebook.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func podcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.podcast[fixtureID.rawValue]
    }

    static func requirePodcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed {
        guard let seed = podcastSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "podcast.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func runtimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.runtimePodcast[fixtureID.rawValue]
    }

    static func requireRuntimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed {
        guard let seed = runtimePodcastSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "runtimePodcast.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func requireInstalledAsset(ref: String) throws -> UIWorldInstalledAsset {
        _ = try requireInstalledAssetURL(ref: ref)
        return try installedAssetSnapshot(ref: ref)
    }

    static func requireInstalledAssetURL(ref: String) throws -> URL {
        let asset = try requireAsset(ref: ref)
        let sourceURL = try validatedSourceURL(for: asset, ref: ref)
        let destination = try installURL(for: asset, ref: ref)
        let documentsRoot = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .standardizedFileURL
        // Resolve the destination before creating, deleting, or overwriting
        // anything. A pre-existing symlink in an installAs parent (or at the
        // destination itself) must never turn a fixture copy into an escape
        // from the app Documents root.
        try validateDestinationContainment(
            destination,
            in: documentsRoot,
            ref: ref
        )
        let fm = FileManager.default
        try fm.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        // Re-check after directory creation as a bounded TOCTOU defense: the
        // copy must still be inside the same real Documents root immediately
        // before any existing destination is removed or replaced.
        try validateDestinationContainment(
            destination,
            in: documentsRoot,
            ref: ref
        )
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try validateDestinationContainment(
            destination,
            in: documentsRoot,
            ref: ref
        )
        try fm.copyItem(at: sourceURL, to: destination)
        let installedSize = try byteSize(for: destination)
        guard installedSize == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(installedSize)",
            ])
        }
        let installedHash = try sha256Hex(for: destination)
        guard installedHash == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(installedHash)",
            ])
        }
        try validateInstalledAsset(destination, asset: asset, ref: ref)
        return try installedAssetSnapshot(ref: ref).url
    }

    static func installedAssetSnapshot(ref: String) throws -> UIWorldInstalledAsset {
        let asset = try requireAsset(ref: ref)
        let destination = try installURL(for: asset, ref: ref)
        let fm = FileManager.default
        guard fm.fileExists(atPath: destination.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: destination.path])
        }
        let installedSize = try byteSize(for: destination)
        guard installedSize == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(installedSize)",
            ])
        }
        let installedHash = try sha256Hex(for: destination)
        guard installedHash == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(installedHash)",
            ])
        }
        try validateContentType(asset.contentType, for: destination, ref: ref)
        return UIWorldInstalledAsset(
            ref: ref,
            url: destination,
            sha256: installedHash,
            byteSize: installedSize,
            contentType: asset.contentType,
            fileSystemInode: try fileSystemInode(for: destination)
        )
    }

    /// Returns proof for the one canonical Reader asset matching the installed
    /// file name. This is verification only: it never trusts a caller-supplied
    /// asset ID or a digest calculated by the evidence producer.
    static func readerAssetProof(forInstalledFileName fileName: String) throws -> FixtureInstalledAssetProof {
        let trimmedFileName = fileName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedFileName.isEmpty,
              URL(fileURLWithPath: trimmedFileName).lastPathComponent == trimmedFileName,
              !trimmedFileName.contains("/") else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence file name is not a single safe path component: \(fileName)",
            ])
        }
        guard case let .loaded(document, _) = loadState() else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence requires a valid UI World dataset for \(trimmedFileName)",
            ])
        }
        let matches = document.reader.values.filter { $0.bookFileName == trimmedFileName }
        guard matches.count == 1, let seed = matches.first else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence file name must resolve to exactly one reader fixture asset: \(trimmedFileName)",
            ])
        }
        let ref = seed.bookAssetRef.trimmingCharacters(in: .whitespacesAndNewlines)
        guard ref.hasPrefix("books."), !ref.isEmpty else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader fixture \(trimmedFileName) has an invalid book asset ref: \(seed.bookAssetRef)",
            ])
        }
        guard let asset = document.assets.asset(for: ref) else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence asset ref is absent from the UI World manifest: \(ref)",
            ])
        }
        let installedURL = try installURL(for: asset, ref: ref).standardizedFileURL
        let booksURL = Book.localBooksDirectory.standardizedFileURL
        guard installedURL.lastPathComponent == trimmedFileName,
              installedURL.deletingLastPathComponent().path == booksURL.path else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence asset \(ref) does not install the expected file \(trimmedFileName) directly under Books/",
            ])
        }
        guard FileManager.default.fileExists(atPath: installedURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: installedURL.path])
        }
        let resolvedBooksURL = booksURL.resolvingSymlinksInPath().standardizedFileURL
        let resolvedInstalledURL = installedURL.resolvingSymlinksInPath().standardizedFileURL
        guard resolvedBooksURL.path == booksURL.path,
              resolvedInstalledURL.deletingLastPathComponent().path == resolvedBooksURL.path,
              resolvedInstalledURL.lastPathComponent == trimmedFileName else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: installedURL.path,
                NSLocalizedDescriptionKey: "Reader evidence asset \(ref) escapes the canonical Books/ directory through a symlink",
            ])
        }
        let actualByteSize = try byteSize(for: installedURL)
        let actualSHA256 = try sha256Hex(for: installedURL)
        guard actualByteSize == asset.byteSize,
              actualSHA256 == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: installedURL.path,
                NSLocalizedDescriptionKey: "Reader evidence asset \(ref) installed copy does not match manifest metadata",
            ])
        }
        return FixtureInstalledAssetProof(
            assetID: ref,
            installedPath: installedURL.path,
            expectedSHA256: asset.sha256,
            expectedByteSize: asset.byteSize,
            actualSHA256: actualSHA256,
            actualByteSize: actualByteSize
        )
    }

    /// Decode, canonicalize, re-decode, and write the app's materialized UI
    /// World state once at fixture seed/install time. The relative proof path
    /// is supplied by the UI test; the outer runner later reads that
    /// app-container file without synthesizing its contents.
    static func materializeEvidenceFixture() throws -> UIWorldInstalledFixtureProof {
        guard case let .data(data, _) = loadSource() else {
            throw CocoaError(.fileReadNoSuchFile, userInfo: [
                NSLocalizedDescriptionKey: "UI World dataset is unavailable for evidence materialization",
            ])
        }
        let document = try decode(data)
        let sourceHash = SHA256.hash(data: data)
            .map { String(format: "%02x", $0) }
            .joined()
        let sourceCommit = ProcessInfo.processInfo.environment[uiTestSourceCommitEnvKey]
            ?? "testing"
        let jsonObject = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        guard JSONSerialization.isValidJSONObject(jsonObject) else {
            throw CocoaError(.propertyListWriteInvalid)
        }
        let canonical = try JSONSerialization.data(withJSONObject: jsonObject, options: [.sortedKeys])
        // Re-decode the bytes emitted by the app's canonicalization path. This
        // proves the installed representation still satisfies the app schema.
        let materializedDocument = try decode(canonical)
        guard materializedDocument.datasetID == document.datasetID else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "materialized UI World dataset identity drifted",
            ])
        }

        let environment = ProcessInfo.processInfo.environment
        let relativePath = environment[installedFixtureProofRelativePathEnvKey]
            .flatMap { $0.isEmpty ? nil : $0 }
            ?? "Evidence/\(document.datasetID).json"
        guard !relativePath.hasPrefix("/"),
              relativePath.split(separator: "/").allSatisfy({ $0 != "." && $0 != ".." })
        else {
            throw CocoaError(.fileWriteInvalidFileName, userInfo: [
                NSLocalizedDescriptionKey: "installed fixture proof path must be portable",
            ])
        }
        let destination = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(relativePath)
        let cacheKey = "\(document.datasetID)|\(sourceHash)|\(sourceCommit)|\(destination.standardizedFileURL.path)"
        evidenceCacheLock.lock()
        if let cached = evidenceProofCache[cacheKey] {
            latestEvidenceCacheKey = cacheKey
            evidenceCacheLock.unlock()
            return cached.proof
        }
        evidenceCacheLock.unlock()

        try FileManager.default.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try canonical.write(to: destination, options: .atomic)
        let installedBytes = try Data(contentsOf: destination)
        guard installedBytes == canonical else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "installed fixture proof bytes differ from app materialization",
            ])
        }
        let proof = UIWorldInstalledFixtureProof(
            datasetID: document.datasetID,
            path: relativePath,
            bytes: installedBytes.count,
            sha256: SHA256.hash(data: installedBytes)
                .map { String(format: "%02x", $0) }
                .joined(),
            type: "application/json",
            sourceCommit: sourceCommit,
            datasetSHA256: sourceHash
        )
        let encodedProof = String(decoding: try JSONEncoder().encode(proof), as: UTF8.self)
        evidenceCacheLock.lock()
        evidenceProofCache[cacheKey] = (proof: proof, value: encodedProof)
        latestEvidenceCacheKey = cacheKey
        evidenceCacheLock.unlock()
        return proof
    }

    /// Render-time accessor: only returns the proof prepared by fixture seed.
    /// It intentionally performs no file reads, decoding, encoding, or hashing.
    static func preparedEvidenceFixtureProofValue() -> String? {
        evidenceCacheLock.lock()
        defer { evidenceCacheLock.unlock() }
        guard let key = latestEvidenceCacheKey,
              let prepared = evidenceProofCache[key] else { return nil }
        return prepared.value
    }

    private static func requireAsset(ref: String) throws -> UIWorldAsset {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "asset \(ref)"))
        }
        guard let asset = document.assets.asset(for: ref) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "asset \(ref)"))
        }
        return asset
    }

    private static func validatedSourceURL(for asset: UIWorldAsset, ref: String) throws -> URL {
        let sourcePath = asset.sourcePath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !(!sourcePath.isEmpty && isReaderBookAsset(ref: ref) && sourcePath.hasPrefix("/")) else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: sourcePath,
                NSLocalizedDescriptionKey: "Reader asset \(ref) sourcePath must be repo-relative, not absolute",
            ])
        }
        let url = try resolveSourceURL(for: asset)
        let size = try byteSize(for: url)
        guard size == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(size)",
            ])
        }
        let actual = try sha256Hex(for: url)
        guard actual == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(actual)",
            ])
        }
        try validateContentType(asset.contentType, for: url, ref: ref)
        return url
    }

    /// Resolve a canonical repo-relative manifest source against the checkout
    /// that compiled this app. Installed filesystem identity is observed only
    /// after copying and is never used to resolve a checked-in fixture.
    static func resolveSourceURL(for asset: UIWorldAsset) throws -> URL {
        let root = try assetRootURL().standardizedFileURL
        let rawPath = asset.sourcePath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !rawPath.isEmpty else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "UI World asset sourcePath must not be empty",
            ])
        }
        let components = rawPath.split(separator: "/").map(String.init)
        guard !rawPath.hasPrefix("/"),
              components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            throw CocoaError(.fileReadNoPermission, userInfo: [
                NSFilePathErrorKey: rawPath,
                NSLocalizedDescriptionKey: "UI World asset sourcePath must be repo-relative without traversal",
            ])
        }
        let candidate = root.appendingPathComponent(rawPath)
        let lexical = candidate.standardizedFileURL
        guard isContained(lexical, in: root) else {
            throw CocoaError(.fileReadNoPermission, userInfo: [
                NSFilePathErrorKey: lexical.path,
                NSLocalizedDescriptionKey: "UI World asset sourcePath must resolve inside the current checkout",
            ])
        }
        guard FileManager.default.fileExists(atPath: lexical.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: lexical.path])
        }
        let resolvedRoot = root.resolvingSymlinksInPath().standardizedFileURL
        let resolved = lexical.resolvingSymlinksInPath().standardizedFileURL
        guard isContained(resolved, in: resolvedRoot) else {
            throw CocoaError(.fileReadNoPermission, userInfo: [
                NSFilePathErrorKey: resolved.path,
                NSLocalizedDescriptionKey: "UI World asset sourcePath escapes the current checkout through a symlink",
            ])
        }
        return resolved
    }

    private static func isReaderBookAsset(ref: String) -> Bool {
        guard case let .loaded(document, _) = loadState() else { return false }
        return document.reader.values.contains { $0.bookAssetRef == ref }
    }

    private static func isContained(_ candidate: URL, in root: URL) -> Bool {
        let rootPath = root.standardizedFileURL.path
        let candidatePath = candidate.standardizedFileURL.path
        return candidatePath == rootPath || candidatePath.hasPrefix(rootPath + "/")
    }

    private static var repositoryRootURL: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // Core
            .deletingLastPathComponent() // Fixtures
            .deletingLastPathComponent() // Support
            .deletingLastPathComponent() // BooksAndVocab
            .deletingLastPathComponent() // ios
    }

    private static func validateDestinationContainment(
        _ destination: URL,
        in root: URL,
        ref: String
    ) throws {
        let lexicalRoot = root.standardizedFileURL
        let lexicalDestination = destination.standardizedFileURL
        guard isContained(lexicalDestination, in: lexicalRoot) else {
            throw CocoaError(.fileWriteNoPermission, userInfo: [
                NSFilePathErrorKey: lexicalDestination.path,
                NSLocalizedDescriptionKey: "UI World asset (ref) installAs escapes the app Documents root",
            ])
        }

        let resolvedRoot = lexicalRoot.resolvingSymlinksInPath().standardizedFileURL
        let resolvedDestination = lexicalDestination.resolvingSymlinksInPath().standardizedFileURL
        let resolvedParent = lexicalDestination
            .deletingLastPathComponent()
            .resolvingSymlinksInPath()
            .standardizedFileURL
        guard isContained(resolvedDestination, in: resolvedRoot),
              isContained(resolvedParent, in: resolvedRoot) else {
            throw CocoaError(.fileWriteNoPermission, userInfo: [
                NSFilePathErrorKey: resolvedDestination.path,
                NSLocalizedDescriptionKey: "UI World asset (ref) installAs escapes the app Documents root through a symlink",
            ])
        }
    }

    private static func assetRootURL() throws -> URL {
        let rawRoot = testingAssetRoot?.path
            ?? ProcessInfo.processInfo.environment[fixtureAssetRootEnvKey]
        let root: URL
        if let rawRoot, !rawRoot.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            root = URL(fileURLWithPath: rawRoot, isDirectory: true).standardizedFileURL
        } else {
            root = repositoryRootURL.standardizedFileURL
        }
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: root.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            throw CocoaError(.fileNoSuchFile, userInfo: [
                NSFilePathErrorKey: root.path,
                NSLocalizedDescriptionKey: "UI World asset root does not exist: \(root.path)",
            ])
        }
        return root
    }

    private static func validateInstalledAsset(_ url: URL, asset: UIWorldAsset, ref: String) throws {
        let declaredType = asset.contentType.split(separator: ";", maxSplits: 1).first.map(String.init) ?? asset.contentType
        guard declaredType == "audio/mpeg" || declaredType == "audio/mp4" else { return }

        let extensionName = url.pathExtension.lowercased()
        let expectedExtension = declaredType == "audio/mpeg" ? "mp3" : "m4a"
        guard extensionName == expectedExtension,
              let type = UTType(filenameExtension: extensionName),
              type.preferredMIMEType == declaredType else {
            throw assetFormatError(
                ref: ref,
                url: url,
                reason: "extension/UTType mismatch for declared \(declaredType)"
            )
        }

        let data = try Data(contentsOf: url)
        guard audioContainerType(for: data) == declaredType else {
            throw assetFormatError(ref: ref, url: url, reason: "magic/container mismatch")
        }

        let avAsset = AVURLAsset(url: url)
        guard avAsset.isPlayable else {
            throw assetFormatError(ref: ref, url: url, reason: "AVFoundation reports the installed asset is not playable")
        }
        do {
            _ = try AVAudioFile(forReading: url)
        } catch {
            throw assetFormatError(
                ref: ref,
                url: url,
                reason: "AVAudioFile could not read the installed asset: \(error.localizedDescription)"
            )
        }
    }

    private static func assetFormatError(ref: String, url: URL, reason: String) -> CocoaError {
        CocoaError(.fileReadCorruptFile, userInfo: [
            NSFilePathErrorKey: url.path,
            NSLocalizedDescriptionKey: "UI World installed audio asset \(ref) is invalid: \(reason)",
        ])
    }

    private static func audioContainerType(for data: Data) -> String? {
        if data.count >= 8,
           data[4] == 0x66, data[5] == 0x74, data[6] == 0x79, data[7] == 0x70 {
            return "audio/mp4"
        }

        var offset = 0
        if data.count >= 10,
           data[0] == 0x49, data[1] == 0x44, data[2] == 0x33 {
            let tagSize = (Int(data[6] & 0x7F) << 21)
                | (Int(data[7] & 0x7F) << 14)
                | (Int(data[8] & 0x7F) << 7)
                | Int(data[9] & 0x7F)
            offset = 10 + tagSize + ((data[5] & 0x10) != 0 ? 10 : 0)
        }

        let upperBound = max(offset, data.count - 2)
        for index in offset..<upperBound {
            guard index + 2 < data.count else { break }
            let first = data[index]
            let second = data[index + 1]
            let third = data[index + 2]
            guard first == 0xFF, second & 0xE0 == 0xE0 else { continue }
            let version = (second >> 3) & 0x03
            let layer = (second >> 1) & 0x03
            let bitrateIndex = (third >> 4) & 0x0F
            let sampleRateIndex = (third >> 2) & 0x03
            if version != 0x01, layer == 0x01, bitrateIndex != 0x00, bitrateIndex != 0x0F, sampleRateIndex != 0x03 {
                return "audio/mpeg"
            }
        }
        return nil
        }
    private static func installURL(for asset: UIWorldAsset, ref: String) throws -> URL {
        let installAs = asset.installAs.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !installAs.hasPrefix("/") else {
            preconditionFailure("UI World asset \(ref) installAs must be relative: \(installAs)")
        }
        let components = installAs.split(separator: "/").map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            preconditionFailure("UI World asset \(ref) installAs contains an unsafe path component: \(installAs)")
        }
        let root = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let destination = root.appendingPathComponent(installAs).standardizedFileURL
        guard isContained(destination, in: root.standardizedFileURL) else {
            preconditionFailure("UI World asset \(ref) installAs escaped the document directory: \(installAs)")
        }
        return destination
    }

    private static func validateContentType(_ contentType: String, for url: URL, ref: String) throws {
        let expected = contentType.split(separator: ";", maxSplits: 1).first.map(String.init) ?? contentType
        guard let actual = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType,
              actual == expected else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) contentType mismatch: expected \(expected)",
            ])
        }
    }

    private static func fileSystemInode(for url: URL) throws -> UInt64 {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let number = attributes[.systemFileNumber] as? NSNumber else {
            throw CocoaError(.fileReadUnknown, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World installed asset has no filesystem inode snapshot",
            ])
        }
        return number.uint64Value
    }

    static func sha256Hex(for url: URL) throws -> String {
        let data = try Data(contentsOf: url)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func byteSize(for url: URL) throws -> Int {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let size = values.fileSize else {
            throw CocoaError(.fileReadUnknown, userInfo: [NSFilePathErrorKey: url.path])
        }
        return size
    }

    static func readerSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.reader[fixtureID.rawValue]
    }

    static func requireReaderSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed {
        guard let seed = readerSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "reader.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func vocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.vocabulary[fixtureID.rawValue]
    }

    static func requireVocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed {
        guard let seed = vocabularySeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "vocabulary.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func reviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.reviewDeck[fixtureID.rawValue]
    }

    static func requireReviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed {
        guard let seed = reviewDeckSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "reviewDeck.\(fixtureID.rawValue)"))
        }
        return seed
    }

    /// Decode a dataset document without going through the ambient load chain.
    /// Used by contract tests (and any tooling) to fail loudly on malformed
    /// UI World files.
    static func decode(_ data: Data) throws -> FixtureDatasetDocument {
        let document = try makeDecoder().decode(FixtureDatasetDocument.self, from: data)
        return try materializingVocabularyInheritance(in: document)
    }

    private static func materializingVocabularyInheritance(
        in document: FixtureDatasetDocument
    ) throws -> FixtureDatasetDocument {
        var resolved: [String: UIWorldVocabularySeed] = [:]

        func resolve(_ fixtureID: String, visiting: [String]) throws -> UIWorldVocabularySeed {
            if let seed = resolved[fixtureID] { return seed }
            guard !visiting.contains(fixtureID) else {
                throw DecodingError.dataCorrupted(
                    .init(
                        codingPath: [],
                        debugDescription: "UI World vocabulary inheritance cycle: \((visiting + [fixtureID]).joined(separator: " -> "))"
                    )
                )
            }
            guard let seed = document.vocabulary[fixtureID] else {
                throw DecodingError.dataCorrupted(
                    .init(codingPath: [], debugDescription: "UI World vocabulary inheritance is missing base fixture \(fixtureID)")
                )
            }

            let base: UIWorldVocabularySeed?
            if let baseFixture = seed.baseFixture {
                guard UIWorldVocabularyFixtureID(rawValue: baseFixture) != nil else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: [],
                            debugDescription: "UI World vocabulary.\(fixtureID).baseFixture is unknown: \(baseFixture)"
                        )
                    )
                }
                guard seed.entries.isEmpty else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: [],
                            debugDescription: "UI World vocabulary.\(fixtureID) must not declare entries when baseFixture is present"
                        )
                    )
                }
                base = try resolve(baseFixture, visiting: visiting + [fixtureID])
            } else {
                base = nil
            }

            let entries = base?.entries ?? seed.entries
            var overridesByWord = Dictionary(
                uniqueKeysWithValues: (base?.entryOverrides ?? []).map { ($0.word, $0) }
            )
            var localOverrideWords: Set<String> = []
            for override in seed.entryOverrides {
                guard localOverrideWords.insert(override.word).inserted else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: [],
                            debugDescription: "UI World vocabulary.\(fixtureID).entryOverrides duplicates word \(override.word)"
                        )
                    )
                }
                guard overridesByWord[override.word] == nil else {
                    throw DecodingError.dataCorrupted(
                        .init(
                            codingPath: [],
                            debugDescription: "UI World vocabulary.\(fixtureID).entryOverrides duplicates inherited word \(override.word)"
                        )
                    )
                }
                overridesByWord[override.word] = override
            }

            let entryWords = Set(entries.map(\.word))
            let missingWords = Set(overridesByWord.keys).subtracting(entryWords)
            guard missingWords.isEmpty else {
                throw DecodingError.dataCorrupted(
                    .init(
                        codingPath: [],
                        debugDescription: "UI World vocabulary.\(fixtureID).entryOverrides references missing words \(missingWords.sorted())"
                    )
                )
            }
            for record in seed.reviewHistory where !entryWords.contains(record.word) {
                throw DecodingError.dataCorrupted(
                    .init(
                        codingPath: [],
                        debugDescription: "UI World vocabulary.\(fixtureID).reviewHistory.\(record.word) must reference a resolved entry"
                    )
                )
            }

            let materialized = UIWorldVocabularySeed(
                notebookRemoteId: seed.notebookRemoteId,
                notebookName: seed.notebookName,
                notebookSyncStatus: seed.notebookSyncStatus,
                bookTitle: seed.bookTitle,
                entries: entries,
                reviewHistory: seed.reviewHistory,
                entryOverrides: entries.compactMap { overridesByWord[$0.word] }
            )
            resolved[fixtureID] = materialized
            return materialized
        }

        for fixtureID in document.vocabulary.keys {
            _ = try resolve(fixtureID, visiting: [])
        }

        return FixtureDatasetDocument(
            schema: document.schema,
            datasetID: document.datasetID,
            assets: document.assets,
            preferences: document.preferences,
            auth: document.auth,
            entitlements: document.entitlements,
            settings: document.settings,
            bookshelf: document.bookshelf,
            todayReview: document.todayReview,
            notebook: document.notebook,
            podcast: document.podcast,
            runtimePodcast: document.runtimePodcast,
            reader: document.reader,
            vocabulary: resolved,
            reviewDeck: document.reviewDeck,
            syncPresenter: document.syncPresenter,
            scenarioContext: document.scenarioContext
        )
    }

    static func requireDocument() -> FixtureDatasetDocument {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "the UI World document"))
        }
        return document
    }

    static func sharedDeckCatalogSeed() -> UIWorldSharedDeckCatalogSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.sharedDecks
    }

    static func requireSharedDeckCatalogSeed() -> UIWorldSharedDeckCatalogSeed {
        guard let seed = sharedDeckCatalogSeed() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "sharedDecks"))
        }
        return seed
    }

    /// Safe (non-`require`) accessor for optional scenario context. Returns
    /// nil when the UI World is absent/invalid or omits `scenarioContext`, so
    /// independent scenarios can fall back gracefully without a
    /// `preconditionFailure`.
    static func scenarioContext() -> UIWorldScenarioContextSeed? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return document.scenarioContext
    }

    /// Diagnostic for `require*Seed` / asset resolution failures. When the UI
    /// World never loaded (missing env, invalid base64, decompress failure,
    /// decode error) the message must surface that root cause — reporting
    /// "missing <fixture key>" against a world that was never injected sends
    /// the investigation down the wrong path.
    static func seedResolutionFailureDescription(resolving reference: String) -> String {
        switch loadState() {
        case .loaded:
            return "UI World is missing \(reference)"
        case .absent:
            return "UI World is not loaded — neither \(fixtureDatasetDeflateEnvKey) nor \(fixtureDatasetEnvKey) is set (and no testing override); cannot resolve \(reference)"
        case let .invalid(source, error):
            return "UI World failed to load from \(source): \(error); cannot resolve \(reference)"
        }
    }

    static func debugSummary() -> String {
        switch loadState() {
        case .absent:
            return "absent"
        case let .invalid(source, error):
            return "invalid @ \(source) (\(error))"
        case let .loaded(document, source):
            return "\(document.datasetID) @ \(source)"
        }
    }

    static func readerProvenance() -> ReaderFixtureDatasetProvenance? {
        guard case let .loaded(document, source) = loadState() else { return nil }
        return ReaderFixtureDatasetProvenance(datasetID: document.datasetID, source: source)
    }

    private enum LoadState {
        case absent
        case invalid(source: String, error: String)
        case loaded(FixtureDatasetDocument, source: String)
    }

    private enum LoadSource {
        case absent
        case invalid(source: String, error: String)
        case data(Data, description: String)
    }

    private static func loadState() -> LoadState {
        let source = loadSource()
        switch source {
        case .absent:
            return .absent
        case let .invalid(source, error):
            return .invalid(source: source, error: error)
        case let .data(data, description):
            do {
                let document = try decode(data)
                return .loaded(document, source: description)
            } catch {
                return .invalid(source: description, error: String(reflecting: error))
            }
        }
    }

    private static func loadSource() -> LoadSource {
        if let testingOverrideData {
            return .data(testingOverrideData, description: "testing-override")
        }

        let environment = ProcessInfo.processInfo.environment
        let deflateRawValue = environment[fixtureDatasetDeflateEnvKey]
        let plainRawValue = environment[fixtureDatasetEnvKey]

        if deflateRawValue != nil, plainRawValue != nil {
            // Two sources could describe two different worlds; picking one
            // silently would hide exactly the kind of tooling drift this
            // fail-loud chain exists to expose.
            return .invalid(
                source: "env:\(fixtureDatasetDeflateEnvKey)+\(fixtureDatasetEnvKey)",
                error: "both \(fixtureDatasetDeflateEnvKey) and \(fixtureDatasetEnvKey) are set; the UI World source is ambiguous — unset one"
            )
        }

        if let deflateRawValue {
            let envDescription = "env:\(fixtureDatasetDeflateEnvKey)"
            guard !deflateRawValue.isEmpty else {
                return .invalid(source: envDescription, error: "\(fixtureDatasetDeflateEnvKey) must not be empty")
            }
            guard let compressed = Data(base64Encoded: deflateRawValue) else {
                return .invalid(source: envDescription, error: "\(fixtureDatasetDeflateEnvKey) is not valid base64")
            }
            do {
                let data = try (compressed as NSData).decompressed(using: .zlib) as Data
                return .data(data, description: envDescription)
            } catch {
                return .invalid(
                    source: envDescription,
                    error: "\(fixtureDatasetDeflateEnvKey) is not a raw DEFLATE stream (decompress failed: \(error.localizedDescription))"
                )
            }
        }

        let envDescription = "env:\(fixtureDatasetEnvKey)"
        guard let rawValue = plainRawValue else {
            return .absent
        }

        guard !rawValue.isEmpty else {
            return .invalid(source: envDescription, error: "\(fixtureDatasetEnvKey) must not be empty")
        }

        guard let data = Data(base64Encoded: rawValue) else {
            return .invalid(source: envDescription, error: "\(fixtureDatasetEnvKey) is not valid base64")
        }

        return .data(data, description: envDescription)
    }

    private static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            if let rawValue = try? container.decode(String.self) {
                if let date = AppDateFormatters.parseISO8601(rawValue) {
                    return date
                }
                throw DecodingError.dataCorruptedError(
                    in: container,
                    debugDescription: "Expected ISO8601 date string, got \(rawValue)"
                )
            }
            if let rawValue = try? container.decode(Double.self) {
                return Date(timeIntervalSince1970: rawValue)
            }
            if let rawValue = try? container.decode(Int.self) {
                return Date(timeIntervalSince1970: TimeInterval(rawValue))
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Expected ISO8601 string or epoch seconds for Date"
            )
        }
        return decoder
    }
}

extension SubscriptionBadgeTone: Codable {
    private enum EncodedValue: String, Codable {
        case neutral
        case accent
        case success
    }

    init(from decoder: Decoder) throws {
        switch try EncodedValue(from: decoder) {
        case .neutral:
            self = .neutral
        case .accent:
            self = .accent
        case .success:
            self = .success
        }
    }

    func encode(to encoder: Encoder) throws {
        let encodedValue: EncodedValue
        switch self {
        case .neutral:
            encodedValue = .neutral
        case .accent:
            encodedValue = .accent
        case .success:
            encodedValue = .success
        }
        try encodedValue.encode(to: encoder)
    }
}

extension AutoplaySpeed: Codable {}

extension TodayReviewRevealStage: Codable {
    private enum EncodedValue: String, Codable {
        case front
        case back
    }

    init(from decoder: Decoder) throws {
        switch try EncodedValue(from: decoder) {
        case .front:
            self = .front
        case .back:
            self = .back
        }
    }

    func encode(to encoder: Encoder) throws {
        let encodedValue: EncodedValue = self == .front ? .front : .back
        try encodedValue.encode(to: encoder)
    }
}
