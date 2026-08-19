import Foundation

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
    enum RuntimeMaterializationError: Error, Equatable {
        case unavailable(fixtureID: String)
        case missingSourceAsset(assetID: String)
        case invalidSourceAsset(ref: String, reason: String)
    }

    enum Availability: Equatable {
        case absent
        case loaded
        case invalid(String)
    }

    @TaskLocal static var testingOverrideData: Data?
    @TaskLocal static var testingOverrideIsActive = false
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
        try $testingOverrideIsActive.withValue(true) {
            try $testingOverrideData.withValue(data) {
                try perform()
            }
        }
    }

    static func withTestingData<T>(_ data: Data?, perform: () async throws -> T) async rethrows -> T {
        try await $testingOverrideIsActive.withValue(true) {
            try await $testingOverrideData.withValue(data) {
                try await perform()
            }
        }
    }

    static var isFixtureDriven: Bool {
        if testingOverrideIsActive || AppRuntimeOptions.isUITesting() {
            return true
        }
        let environment = ProcessInfo.processInfo.environment
        return environment.keys.contains {
            $0 == FixtureDatasetLoader.deflateEnvironmentKey
                || $0 == FixtureDatasetLoader.datasetEnvironmentKey
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

    private static func loadedResolver() -> FixtureDatasetResolver? {
        guard case let .loaded(document, _) = loadState() else { return nil }
        return FixtureDatasetResolver(document: document)
    }

    private static func loadedAssetResolver(for ref: String) throws -> FixtureDatasetResolver {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "asset \(ref)"))
        }
        return FixtureDatasetResolver(
            document: document,
            assetRoot: try FixtureDatasetResolver.assetRootURL(testingRoot: testingAssetRoot)
        )
    }

    static func settingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed? {
        loadedResolver()?.settingsSeed(for: fixtureID)
    }

    static func requireSettingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed {
        guard let seed = settingsSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "settings.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func authSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed? {
        loadedResolver()?.authSeed(for: fixtureID)
    }

    static func requireAuthSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed {
        guard let seed = authSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "auth.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func entitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed? {
        loadedResolver()?.entitlementsSeed(for: fixtureID)
    }

    static func requireEntitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed {
        guard let seed = entitlementsSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "entitlements.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func syncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed? {
        loadedResolver()?.syncPresenterSeed(for: fixtureID)
    }

    static func requireSyncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed {
        guard let seed = syncPresenterSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "syncPresenter.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func bookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed? {
        loadedResolver()?.bookshelfSeed(for: fixtureID)
    }

    static func requireBookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed {
        guard let seed = bookshelfSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "bookshelf.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func todayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed? {
        loadedResolver()?.todayReviewSeed(for: fixtureID)
    }

    static func requireTodayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed {
        guard let seed = todayReviewSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "todayReview.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func notebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed? {
        loadedResolver()?.notebookSeed(for: fixtureID)
    }

    static func requireNotebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed {
        guard let seed = notebookSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "notebook.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func podcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed? {
        loadedResolver()?.podcastSeed(for: fixtureID)
    }

    static func requirePodcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed {
        guard let seed = podcastSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "podcast.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func runtimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed? {
        loadedResolver()?.runtimePodcastSeed(for: fixtureID)
    }

    static func requireRuntimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed {
        guard let seed = runtimePodcastSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "runtimePodcast.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func requireInstalledAsset(ref: String) throws -> UIWorldInstalledAsset {
        let resolver = try loadedAssetResolver(for: ref)
        _ = try resolver.requireInstalledAssetURL(ref: ref)
        return try resolver.installedAssetSnapshot(ref: ref)
    }

    static func requireInstalledAssetURL(ref: String) throws -> URL {
        try loadedAssetResolver(for: ref).requireInstalledAssetURL(ref: ref)
    }

    static func installedAssetSnapshot(ref: String) throws -> UIWorldInstalledAsset {
        guard let resolver = loadedResolver() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "asset \(ref)"))
        }
        return try resolver.installedAssetSnapshot(ref: ref)
    }

    /// Returns proof for the one canonical Reader asset matching the installed
    /// file name. This is verification only: it never trusts a caller-supplied
    /// asset ID or a digest calculated by the evidence producer.
    static func readerAssetProof(forInstalledFileName fileName: String) throws -> FixtureInstalledAssetProof {
        let trimmedFileName = fileName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let resolver = loadedResolver() else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence requires a valid UI World dataset for \(trimmedFileName)",
            ])
        }
        return try resolver.readerAssetProof(forInstalledFileName: fileName)
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
        let sourceHash = FixtureDatasetResolver.sha256Hex(for: data)
        let sourceCommit = ProcessInfo.processInfo.environment[uiTestSourceCommitEnvKey]
            ?? "testing"
        let environment = ProcessInfo.processInfo.environment
        let relativePath = environment[installedFixtureProofRelativePathEnvKey]
            .flatMap { $0.isEmpty ? nil : $0 }
            ?? "Evidence/\(document.datasetID).json"
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

        let materialized = try FixtureDatasetResolver(document: document).materializeEvidenceFixture(
            sourceData: data,
            sourceCommit: sourceCommit,
            relativePath: relativePath
        )
        let proof = materialized.proof
        let encodedProof = materialized.encodedProof
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

    /// Resolve a canonical repo-relative manifest source against the checkout
    /// that compiled this app. Installed filesystem identity is observed only
    /// after copying and is never used to resolve a checked-in fixture.
    static func resolveSourceURL(for asset: UIWorldAsset) throws -> URL {
        let root = try FixtureDatasetResolver.assetRootURL(testingRoot: testingAssetRoot)
        return try FixtureDatasetResolver.resolveSourceURL(for: asset, assetRoot: root)
    }

    static func sha256Hex(for url: URL) throws -> String {
        try FixtureDatasetResolver.sha256Hex(for: url)
    }

    static func byteSize(for url: URL) throws -> Int {
        try FixtureDatasetResolver.byteSize(for: url)
    }

    static func readerSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed? {
        loadedResolver()?.readerSeed(for: fixtureID)
    }

    static func requireReaderSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed {
        guard let seed = readerSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "reader.\(fixtureID.rawValue)"))
        }
        return seed
    }

    static func vocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed? {
        loadedResolver()?.vocabularySeed(for: fixtureID)
    }

    static func requireVocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed {
        guard let resolver = loadedResolver(), resolver.vocabularySeed(for: fixtureID) != nil else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "vocabulary.\(fixtureID.rawValue)"))
        }
        return resolver.requireVocabularySeed(for: fixtureID)
    }

    static func reviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed? {
        loadedResolver()?.reviewDeckSeed(for: fixtureID)
    }

    static func requireReviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed {
        guard let seed = reviewDeckSeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "reviewDeck.\(fixtureID.rawValue)"))
        }
        return seed
    }

    /// UI World files.
    static func decode(_ data: Data) throws -> FixtureDatasetDocument {
        let document = try FixtureDatasetLoader.decode(data)
        return try FixtureDatasetResolver.materializeVocabularyInheritance(in: document)
    }

    static func requireDocument() -> FixtureDatasetDocument {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "the UI World document"))
        }
        return document
    }

    static func sharedDeckCatalogSeed() -> UIWorldSharedDeckCatalogSeed? {
        loadedResolver()?.sharedDeckCatalogSeed()
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
        loadedResolver()?.scenarioContext()
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
            return "UI World is not loaded — neither \(FixtureDatasetLoader.deflateEnvironmentKey) nor \(FixtureDatasetLoader.datasetEnvironmentKey) is set (and no testing override); cannot resolve \(reference)"
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

    static var availability: Availability {
        switch loadState() {
        case .absent: return .absent
        case .loaded: return .loaded
        case let .invalid(_, error): return .invalid(error)
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
        switch FixtureDatasetLoader.loadSource(testingOverrideData: testingOverrideData) {
        case .absent:
            return .absent
        case let .invalid(source, error):
            return .invalid(source: source, error: error)
        case let .data(data, description):
            return .data(data, description: description)
        }
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
