import Foundation
import CryptoKit
import AVFoundation
import AVFAudio
import UniformTypeIdentifiers

struct FixtureDatasetResolver {
    static let assetRootEnvironmentKey = "KG_FIXTURE_ASSET_ROOT"

    struct MaterializedEvidence {
        let proof: UIWorldInstalledFixtureProof
        let encodedProof: String
        let destination: URL
    }

    let document: FixtureDatasetDocument
    private let assetRoot: URL?

    init(document: FixtureDatasetDocument, assetRoot: URL? = nil) {
        self.document = document
        self.assetRoot = assetRoot?.standardizedFileURL
    }

    func settingsSeed(for fixtureID: SettingsFixtureID) -> SettingsFixtureSeed? {
        document.settings[fixtureID.rawValue]
    }

    func authSeed(for fixtureID: UIWorldAuthFixtureID) -> UIWorldAuthSeed? {
        document.auth[fixtureID.rawValue]
    }

    func entitlementsSeed(for fixtureID: UIWorldEntitlementsFixtureID) -> UIWorldEntitlementsSeed? {
        document.entitlements[fixtureID.rawValue]
    }

    func syncPresenterSeed(for fixtureID: UIWorldSyncPresenterFixtureID) -> UIWorldSyncPresenterSeed? {
        document.syncPresenter[fixtureID.rawValue]
    }

    func bookshelfSeed(for fixtureID: BookshelfFixtureID) -> BookshelfFixtureSeed? {
        document.bookshelf[fixtureID.rawValue]
    }

    func todayReviewSeed(for fixtureID: TodayReviewFixtureID) -> TodayReviewSessionSeed? {
        document.todayReview[fixtureID.rawValue]
    }

    func notebookSeed(for fixtureID: NotebookFixtureID) -> NotebookFixtureSeed? {
        document.notebook[fixtureID.rawValue]
    }

    func podcastSeed(for fixtureID: PodcastFixtureID) -> PodcastFixtureSeed? {
        document.podcast[fixtureID.rawValue]
    }

    func runtimePodcastSeed(for fixtureID: UIWorldRuntimePodcastFixtureID) -> UIWorldRuntimePodcastSeed? {
        document.runtimePodcast[fixtureID.rawValue]
    }

    func readerSeed(for fixtureID: UIWorldReaderFixtureID) -> UIWorldReaderSeed? {
        document.reader[fixtureID.rawValue]
    }

    func vocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed? {
        document.vocabulary[fixtureID.rawValue]
    }

    func requireVocabularySeed(for fixtureID: UIWorldVocabularyFixtureID) -> UIWorldVocabularySeed {
        guard document.vocabulary[fixtureID.rawValue] != nil else {
            preconditionFailure("UI World is missing vocabulary.\(fixtureID.rawValue)")
        }
        return resolveVocabularySeed(fixtureID, visiting: [])
    }

    func reviewDeckSeed(for fixtureID: UIWorldReviewDeckFixtureID) -> UIWorldReviewDeckSeed? {
        document.reviewDeck[fixtureID.rawValue]
    }

    func sharedDeckCatalogSeed() -> UIWorldSharedDeckCatalogSeed? {
        document.sharedDecks
    }

    func scenarioContext() -> UIWorldScenarioContextSeed? {
        document.scenarioContext
    }

    static func materializeVocabularyInheritance(
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
            sharedDecks: document.sharedDecks,
            scenarioContext: document.scenarioContext
        )
    }

    static func assetRootURL(
        testingRoot: URL?,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> URL {
        let rawRoot = testingRoot?.path ?? environment[assetRootEnvironmentKey]
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

    static func resolveSourceURL(for asset: UIWorldAsset, assetRoot: URL) throws -> URL {
        let root = assetRoot.standardizedFileURL
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

    func requireInstalledAsset(ref: String) throws -> UIWorldInstalledAsset {
        _ = try requireInstalledAssetURL(ref: ref)
        return try installedAssetSnapshot(ref: ref)
    }

    func requireInstalledAssetURL(ref: String) throws -> URL {
        let asset = try requireAsset(ref: ref)
        let sourceURL = try validatedSourceURL(for: asset, ref: ref)
        let destination = try installURL(for: asset, ref: ref)
        let documentsRoot = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .standardizedFileURL
        // Resolve the destination before creating, deleting, or overwriting
        // anything. A pre-existing symlink must never escape Documents.
        try Self.validateDestinationContainment(destination, in: documentsRoot, ref: ref)
        let fm = FileManager.default
        try fm.createDirectory(at: destination.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Self.validateDestinationContainment(destination, in: documentsRoot, ref: ref)
        if fm.fileExists(atPath: destination.path) {
            try fm.removeItem(at: destination)
        }
        try Self.validateDestinationContainment(destination, in: documentsRoot, ref: ref)
        try fm.copyItem(at: sourceURL, to: destination)
        let installedSize = try Self.byteSize(for: destination)
        guard installedSize == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(installedSize)",
            ])
        }
        let installedHash = try Self.sha256Hex(for: destination)
        guard installedHash == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(installedHash)",
            ])
        }
        try validateInstalledAsset(destination, asset: asset, ref: ref)
        return try installedAssetSnapshot(ref: ref).url
    }

    func installedAssetSnapshot(ref: String) throws -> UIWorldInstalledAsset {
        let asset = try requireAsset(ref: ref)
        let destination = try installURL(for: asset, ref: ref)
        let fm = FileManager.default
        guard fm.fileExists(atPath: destination.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: destination.path])
        }
        let installedSize = try Self.byteSize(for: destination)
        guard installedSize == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: destination.path,
                NSLocalizedDescriptionKey: "UI World installed asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(installedSize)",
            ])
        }
        let installedHash = try Self.sha256Hex(for: destination)
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
            fileSystemInode: try Self.fileSystemInode(for: destination)
        )
    }

    func readerAssetProof(forInstalledFileName fileName: String) throws -> FixtureInstalledAssetProof {
        let trimmedFileName = fileName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedFileName.isEmpty,
              URL(fileURLWithPath: trimmedFileName).lastPathComponent == trimmedFileName,
              !trimmedFileName.contains("/") else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "Reader evidence file name is not a single safe path component: \(fileName)",
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
        let fm = FileManager.default
        guard fm.fileExists(atPath: installedURL.path) else {
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
        let actualByteSize = try Self.byteSize(for: installedURL)
        let actualSHA256 = try Self.sha256Hex(for: installedURL)
        guard actualByteSize == asset.byteSize, actualSHA256 == asset.sha256 else {
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

    func materializeEvidenceFixture(
        sourceData: Data,
        sourceCommit: String,
        relativePath: String
    ) throws -> MaterializedEvidence {
        let sourceDocument = try FixtureDatasetLoader.decode(sourceData)
        let sourceHash = Self.sha256Hex(for: sourceData)
        let jsonObject = try JSONSerialization.jsonObject(with: sourceData, options: [.fragmentsAllowed])
        guard JSONSerialization.isValidJSONObject(jsonObject) else {
            throw CocoaError(.propertyListWriteInvalid)
        }
        let canonical = try JSONSerialization.data(withJSONObject: jsonObject, options: [.sortedKeys])
        let materializedDocument = try Self.materializeVocabularyInheritance(
            in: FixtureDatasetLoader.decode(canonical)
        )
        guard materializedDocument.datasetID == sourceDocument.datasetID,
              materializedDocument.datasetID == document.datasetID else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSLocalizedDescriptionKey: "materialized UI World dataset identity drifted",
            ])
        }
        guard !relativePath.hasPrefix("/"),
              relativePath.split(separator: "/").allSatisfy({ $0 != "." && $0 != ".." }) else {
            throw CocoaError(.fileWriteInvalidFileName, userInfo: [
                NSLocalizedDescriptionKey: "installed fixture proof path must be portable",
            ])
        }
        let destination = documentsRoot.appendingPathComponent(relativePath)
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
            sha256: Self.sha256Hex(for: installedBytes),
            type: "application/json",
            sourceCommit: sourceCommit,
            datasetSHA256: sourceHash
        )
        let encodedProof = String(decoding: try JSONEncoder().encode(proof), as: UTF8.self)
        return MaterializedEvidence(proof: proof, encodedProof: encodedProof, destination: destination)
    }

    static func sha256Hex(for url: URL) throws -> String {
        sha256Hex(for: try Data(contentsOf: url))
    }

    static func sha256Hex(for data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    static func byteSize(for url: URL) throws -> Int {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        guard let size = values.fileSize else {
            throw CocoaError(.fileReadUnknown, userInfo: [NSFilePathErrorKey: url.path])
        }
        return size
    }

    private var documentsRoot: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .standardizedFileURL
    }

    private func requireAsset(ref: String) throws -> UIWorldAsset {
        guard let asset = document.assets.asset(for: ref) else {
            preconditionFailure("UI World is missing asset \(ref)")
        }
        return asset
    }

    private func validatedSourceURL(for asset: UIWorldAsset, ref: String) throws -> URL {
        let sourcePath = asset.sourcePath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !(!sourcePath.isEmpty && isReaderBookAsset(ref: ref) && sourcePath.hasPrefix("/")) else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: sourcePath,
                NSLocalizedDescriptionKey: "Reader asset \(ref) sourcePath must be repo-relative, not absolute",
            ])
        }
        guard let assetRoot else {
            throw CocoaError(.fileNoSuchFile, userInfo: [
                NSLocalizedDescriptionKey: "UI World asset root is unavailable",
            ])
        }
        let url = try Self.resolveSourceURL(for: asset, assetRoot: assetRoot)
        let size = try Self.byteSize(for: url)
        guard size == asset.byteSize else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) byteSize mismatch: expected \(asset.byteSize), got \(size)",
            ])
        }
        let actual = try Self.sha256Hex(for: url)
        guard actual == asset.sha256 else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [
                NSFilePathErrorKey: url.path,
                NSLocalizedDescriptionKey: "UI World asset \(ref) sha256 mismatch: expected \(asset.sha256), got \(actual)",
            ])
        }
        try validateContentType(asset.contentType, for: url, ref: ref)
        return url
    }

    private func isReaderBookAsset(ref: String) -> Bool {
        document.reader.values.contains { $0.bookAssetRef == ref }
    }

    private static func isContained(_ candidate: URL, in root: URL) -> Bool {
        let rootPath = root.standardizedFileURL.path
        let candidatePath = candidate.standardizedFileURL.path
        return candidatePath == rootPath || candidatePath.hasPrefix(rootPath + "/")
    }

    private static var repositoryRootURL: URL {
        var candidate = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .standardizedFileURL
        let fileManager = FileManager.default
        for _ in 0..<10 {
            let hasIOSProject = fileManager.fileExists(
                atPath: candidate.appendingPathComponent("ios/BooksAndVocab").path,
                isDirectory: nil
            )
            let hasFixtureAssets = fileManager.fileExists(
                atPath: candidate.appendingPathComponent("ops/fixtures/assets").path,
                isDirectory: nil
            )
            if hasIOSProject && hasFixtureAssets {
                return candidate
            }
            let parent = candidate.deletingLastPathComponent().standardizedFileURL
            if parent == candidate { break }
            candidate = parent
        }
        return URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
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

    private func validateInstalledAsset(_ url: URL, asset: UIWorldAsset, ref: String) throws {
        let declaredType = asset.contentType.split(separator: ";", maxSplits: 1).first.map(String.init) ?? asset.contentType
        guard declaredType == "audio/mpeg" || declaredType == "audio/mp4" else { return }

        let extensionName = url.pathExtension.lowercased()
        let expectedExtension = declaredType == "audio/mpeg" ? "mp3" : "m4a"
        guard extensionName == expectedExtension,
              let type = UTType(filenameExtension: extensionName),
              type.preferredMIMEType == declaredType else {
            throw assetFormatError(ref: ref, url: url, reason: "extension/UTType mismatch for declared \(declaredType)")
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

    private func assetFormatError(ref: String, url: URL, reason: String) -> CocoaError {
        CocoaError(.fileReadCorruptFile, userInfo: [
            NSFilePathErrorKey: url.path,
            NSLocalizedDescriptionKey: "UI World installed audio asset \(ref) is invalid: \(reason)",
        ])
    }

    private func audioContainerType(for data: Data) -> String? {
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

    private func installURL(for asset: UIWorldAsset, ref: String) throws -> URL {
        let installAs = asset.installAs.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !installAs.hasPrefix("/") else {
            preconditionFailure("UI World asset \(ref) installAs must be relative: \(installAs)")
        }
        let components = installAs.split(separator: "/").map(String.init)
        guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
            preconditionFailure("UI World asset \(ref) installAs contains an unsafe path component: \(installAs)")
        }
        let destination = documentsRoot.appendingPathComponent(installAs).standardizedFileURL
        guard Self.isContained(destination, in: documentsRoot) else {
            preconditionFailure("UI World asset \(ref) installAs escaped the document directory: \(installAs)")
        }
        return destination
    }

    private func validateContentType(_ contentType: String, for url: URL, ref: String) throws {
        let expected = contentType.split(separator: ";", maxSplits: 1).first.map(String.init) ?? contentType
        let extensionType: String? = switch url.pathExtension.lowercased() {
        case "epub": "application/epub+zip"
        case "pdf": "application/pdf"
        case "md": "text/markdown"
        case "txt": "text/plain"
        case "mp3": "audio/mpeg"
        case "m4a": "audio/mp4"
        case "srt": "application/x-subrip"
        case "vtt": "text/vtt"
        case "png": "image/png"
        case "jpg", "jpeg": "image/jpeg"
        default: nil
        }
        let actual = extensionType ?? UTType(filenameExtension: url.pathExtension)?.preferredMIMEType
        guard actual == expected else {
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

    private func resolveVocabularySeed(
        _ fixtureID: UIWorldVocabularyFixtureID,
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

    private func validateVocabularyOverrides(
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
}
