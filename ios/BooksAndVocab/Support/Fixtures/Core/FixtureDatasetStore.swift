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
            $0 == fixtureDatasetDeflateEnvKey || $0 == fixtureDatasetEnvKey
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
            .standardizedFileURL
            .resolvingSymlinksInPath()
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
        return sha256Hex(for: data)
    }

    private static func sha256Hex(for data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func rawDatasetData() -> Data? {
        switch loadSource() {
        case let .data(data, _): return data
        case .absent, .invalid: return nil
        }
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
        guard case let .loaded(document, _) = loadState(), document.vocabulary[fixtureID.rawValue] != nil else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "vocabulary.\(fixtureID.rawValue)"))
        }
        return resolveVocabularySeed(
            fixtureID,
            in: document,
            visiting: []
        )
    }

    private static func resolveVocabularySeed(
        _ fixtureID: UIWorldVocabularyFixtureID,
        in document: FixtureDatasetDocument,
        visiting: Set<String>
    ) -> UIWorldVocabularySeed {
        guard let seed = document.vocabulary[fixtureID.rawValue] else {
            preconditionFailure("UI World is missing vocabulary.\(fixtureID.rawValue)")
        }
        guard !visiting.contains(fixtureID.rawValue) else {
            preconditionFailure("UI World vocabulary inheritance cycle at \(fixtureID.rawValue)")
        }

        guard let baseFixture = seed.baseFixture else {
            validateVocabularyOverrides(seed.entryOverrides, entries: seed.entries, fixtureID: fixtureID)
            return seed
        }
        guard let baseID = UIWorldVocabularyFixtureID(rawValue: baseFixture) else {
            preconditionFailure(
                "UI World vocabulary.\(fixtureID.rawValue).baseFixture is unknown: \(baseFixture)"
            )
        }
        let base = resolveVocabularySeed(
            baseID,
            in: document,
            visiting: visiting.union([fixtureID.rawValue])
        )
        guard seed.entries.isEmpty else {
            preconditionFailure(
                "UI World vocabulary.\(fixtureID.rawValue) inherited seed must leave entries empty"
            )
        }
        let overrides = base.entryOverrides + seed.entryOverrides
        validateVocabularyOverrides(overrides, entries: base.entries, fixtureID: fixtureID)
        return UIWorldVocabularySeed(
            notebookRemoteId: seed.notebookRemoteId,
            notebookName: seed.notebookName,
            notebookSyncStatus: seed.notebookSyncStatus,
            bookTitle: seed.bookTitle,
            entries: base.entries,
            reviewHistory: seed.reviewHistory,
            entryOverrides: overrides
        )
    }

    private static func validateVocabularyOverrides(
        _ overrides: [UIWorldVocabularyEntryOverride],
        entries: [UIWorldVocabularyEntrySeed],
        fixtureID: UIWorldVocabularyFixtureID
    ) {
        let words = Set(entries.map(\.word))
        var seen: Set<String> = []
        for override in overrides {
            guard words.contains(override.word) else {
                preconditionFailure(
                    "UI World vocabulary.\(fixtureID.rawValue).entryOverrides references missing word \(override.word)"
                )
            }
            guard seen.insert(override.word).inserted else {
                preconditionFailure(
                    "UI World vocabulary.\(fixtureID.rawValue).entryOverrides duplicates word \(override.word)"
                )
            }
        }
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

    /// Resolve the canonical dictionary source only through the matrix-facing
    /// surface contract. A dictionary payload without its declared P1 surface
    /// row is not a consumable fixture and must not silently become a fake
    /// service response.
    static func dictionarySurfaceContract(
        for fixtureID: UIWorldDictionaryFixtureID
    ) -> UIWorldSurfaceContractRowSeed? {
        guard case let .loaded(document, _) = loadState(),
              let context = document.scenarioContext,
              let dictionaryContract = context.surfaceContracts?["dictionary"] else {
            return nil
        }
        return dictionaryContract.required.first {
            $0.fixtureID == fixtureID.rawValue &&
            $0.stepLabel == fixtureID.requiredStepLabel
        }
    }

    static func dictionarySeed(
        for fixtureID: UIWorldDictionaryFixtureID
    ) -> UIWorldDictionarySeed? {
        guard dictionarySurfaceContract(for: fixtureID) != nil,
              case let .loaded(document, _) = loadState() else {
            return nil
        }
        return document.scenarioContext?.dictionary
    }

    static func requireDictionarySeed(
        for fixtureID: UIWorldDictionaryFixtureID
    ) -> UIWorldDictionarySeed {
        guard let seed = dictionarySeed(for: fixtureID) else {
            preconditionFailure(seedResolutionFailureDescription(resolving: "dictionary.\(fixtureID.rawValue)"))
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

    static var availability: Availability {
        switch loadState() {
        case .absent: return .absent
        case .loaded: return .loaded
        case let .invalid(_, error): return .invalid(error)
        }
    }

    static func dictionaryRuntimeMaterialization(
        for fixtureID: UIWorldDictionaryFixtureID
    ) throws -> DictionaryMaterializationSnapshot {
        guard case let .loaded(document, _) = loadState() else {
            throw RuntimeMaterializationError.unavailable(fixtureID: fixtureID.rawValue)
        }
        guard let dictionary = document.scenarioContext?.dictionary,
              dictionarySurfaceContract(for: fixtureID) != nil,
              let data = rawDatasetData() else {
            throw RuntimeMaterializationError.unavailable(fixtureID: fixtureID.rawValue)
        }
        guard !document.datasetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw RuntimeMaterializationError.invalidSourceAsset(
                ref: "dataset",
                reason: "datasetID is empty"
            )
        }
        guard let requiredCoverage = dictionary.coverage["required"],
              requiredCoverage.assetIDs.count == 1,
              let assetID = requiredCoverage.assetIDs.first,
              let assetBucket = document.assets.typeByID[assetID],
              let asset = document.assets.asset(for: "\(assetBucket).\(assetID)") else {
            throw RuntimeMaterializationError.missingSourceAsset(
                assetID: dictionary.coverage["required"]?.assetIDs.first ?? ""
            )
        }

        let sourceRef = "\(assetBucket).\(assetID)"
        let sourceURL: URL
        do {
            sourceURL = try validatedSourceURL(for: asset, ref: sourceRef)
        } catch {
            throw RuntimeMaterializationError.invalidSourceAsset(
                ref: sourceRef,
                reason: String(describing: error)
            )
        }
        do {
            let actualByteSize = try byteSize(for: sourceURL)
            let actualSHA256 = try sha256Hex(for: sourceURL)
            guard actualByteSize == asset.byteSize else {
                throw RuntimeMaterializationError.invalidSourceAsset(
                    ref: sourceRef,
                    reason: "byteSize mismatch: expected \(asset.byteSize), got \(actualByteSize)"
                )
            }
            guard actualSHA256 == asset.sha256 else {
                throw RuntimeMaterializationError.invalidSourceAsset(
                    ref: sourceRef,
                    reason: "sha256 mismatch: expected \(asset.sha256), got \(actualSHA256)"
                )
            }
            return DictionaryMaterializationSnapshot(
                status: dictionary.materialization.status,
                selectedSenseID: dictionary.materialization.selectedSenseID,
                selectedExampleID: dictionary.materialization.selectedExampleID,
                sourceFixtureID: dictionary.materialization.sourceFixtureID,
                datasetID: document.datasetID,
                datasetSHA256: sha256Hex(for: data),
                sourceAssetID: assetID,
                sourceAssetPath: sourceURL.path,
                sourceAssetByteSize: actualByteSize,
                sourceAssetSHA256: actualSHA256
            )
        } catch let error as RuntimeMaterializationError {
            throw error
        } catch {
            throw RuntimeMaterializationError.invalidSourceAsset(
                ref: sourceRef,
                reason: String(describing: error)
            )
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
