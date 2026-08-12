import Foundation
import CryptoKit

private let fixtureDatasetEnvKey = "KG_FIXTURE_DATASET_B64"
// base64(raw DEFLATE(JSON)) — preferred injection key. Plaintext base64 of a
// multi-MB UI World overflows the ~1MB posix_spawn env block and the app then
// silently sees *no* dataset; compressing keeps large worlds under the limit.
// Apple `.zlib` decompression expects a raw DEFLATE stream (no zlib/gzip
// container) — producers must use e.g. Python `zlib.compressobj(wbits=-15)`.
private let fixtureDatasetDeflateEnvKey = "KG_FIXTURE_DATASET_DEFLATE_B64"
enum FixtureDatasetStore {
    @TaskLocal static var testingOverrideData: Data?

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

    static func requireInstalledAssetURL(ref: String) throws -> URL {
        let asset = try requireAsset(ref: ref)
        let sourceURL = try validatedSourceURL(for: asset, ref: ref)
        let destination = try installURL(for: asset, ref: ref)
        let fm = FileManager.default
        try fm.createDirectory(
            at: destination.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
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
        return destination
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
        let url = URL(fileURLWithPath: asset.sourcePath)
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: url.path])
        }
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
        return url
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
        return FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(installAs)
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
        try makeDecoder().decode(FixtureDatasetDocument.self, from: data)
    }

    static func requireDocument() -> FixtureDatasetDocument {
        guard case let .loaded(document, _) = loadState() else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "the UI World document"))
        }
        return document
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
