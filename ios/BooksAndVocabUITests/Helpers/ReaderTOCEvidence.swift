import Foundation

private enum ReaderTOCEvidenceWriterError: Error, CustomStringConvertible {
    case invalidManifest
    case missingAsset(String)
    case missingAssetSource(String)

    var description: String {
        switch self {
        case .invalidManifest:
            return "marketing_demo UI World manifest is invalid"
        case .missingAsset(let assetID):
            return "UI World manifest is missing asset \(assetID)"
        case .missingAssetSource(let path):
            return "UI World asset source is missing or has no inode: \(path)"
        }
    }
}

private struct ReaderTOCEvidenceArtifact: Codable {
    let schema: String
    let datasetID: String
    let producer: String
    var entries: [ReaderTOCEvidenceEntry]
}

private struct ReaderTOCEvidenceEntry: Codable {
    let label: String
    let partition: String
    let fixtureID: String
    let assetID: String
    let assetPath: String
    let assetInode: String
    let path: [Int]
    let href: String
    let locatorHref: String?
    let destinationSelector: String?
    let contentSelector: String?
}

extension UITestCase {
    /// Produce the structured KG_PERF/UI artifact consumed by the unit
    /// partition test. The label is recorded from the running test, while the
    /// asset ID/path/inode are resolved from the real UI World manifest; no
    /// test-source parsing is involved.
    func writeReaderTOCEvidence(
        label: String,
        partition: String,
        fixtureID: String,
        assetID: String,
        path: [Int],
        href: String,
        locatorHref: String?,
        destinationSelector: String? = nil,
        contentSelector: String? = nil
    ) throws {
        let artifactDirectory: URL
        if let screenshotDirectory = ProcessInfo.processInfo.environment["KG_UI_TEST_SCREENSHOT_DIR"],
           !screenshotDirectory.isEmpty {
            artifactDirectory = URL(fileURLWithPath: screenshotDirectory)
        } else {
            // xcodebuild does not reliably forward runner-only environment
            // variables into the XCTest process. Keep the artifact contract
            // fail-closed by saving to XCTest's writable temporary directory;
            // the JSON is also attached to the xcresult below.
            artifactDirectory = FileManager.default.temporaryDirectory
                .appendingPathComponent("kg-reader-toc-ui-evidence", isDirectory: true)
        }

        var rootURL = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 {
            rootURL.deleteLastPathComponent()
        }
        let manifestURL = rootURL.appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
        let manifestData = try Data(contentsOf: manifestURL)
        guard let manifest = try JSONSerialization.jsonObject(with: manifestData) as? [String: Any],
              let datasetID = manifest["datasetID"] as? String,
              let assets = manifest["assets"] as? [String: Any] else {
            throw ReaderTOCEvidenceWriterError.invalidManifest
        }

        let asset = try Self.manifestAsset(assetID, in: assets)
        guard let sourcePath = asset["sourcePath"] as? String else {
            throw ReaderTOCEvidenceWriterError.missingAsset(assetID)
        }
        let sourceURL = URL(fileURLWithPath: sourcePath)
        let attributes = try? FileManager.default.attributesOfItem(atPath: sourceURL.path)
        guard let inode = attributes?[.systemFileNumber] as? NSNumber else {
            throw ReaderTOCEvidenceWriterError.missingAssetSource(sourceURL.path)
        }

        let artifactURL = artifactDirectory.appendingPathComponent("reader-toc-ui-evidence.json")
        try FileManager.default.createDirectory(
            at: artifactDirectory,
            withIntermediateDirectories: true
        )

        var artifact: ReaderTOCEvidenceArtifact
        if FileManager.default.fileExists(atPath: artifactURL.path) {
            let existingData = try Data(contentsOf: artifactURL)
            artifact = try JSONDecoder().decode(ReaderTOCEvidenceArtifact.self, from: existingData)
            guard artifact.schema == "kg.ui.perf.evidence.v1",
                  artifact.datasetID == datasetID else {
                throw ReaderTOCEvidenceWriterError.invalidManifest
            }
        } else {
            artifact = ReaderTOCEvidenceArtifact(
                schema: "kg.ui.perf.evidence.v1",
                datasetID: datasetID,
                producer: "BooksAndVocabUITests.ReaderFlowUITests",
                entries: []
            )
        }

        artifact.entries.append(
            ReaderTOCEvidenceEntry(
                label: label,
                partition: partition,
                fixtureID: fixtureID,
                assetID: assetID,
                assetPath: sourceURL.path,
                assetInode: inode.stringValue,
                path: path,
                href: href,
                locatorHref: locatorHref,
                destinationSelector: destinationSelector,
                contentSelector: contentSelector
            )
        )

        let encoded = try JSONEncoder.readerTOCEvidence.encode(artifact)
        try encoded.write(to: artifactURL, options: .atomic)
        // Parse the persisted bytes again before attaching them. This makes
        // the attachment itself proof that the saved runner artifact is valid.
        let persistedData = try Data(contentsOf: artifactURL)
        let reparsed = try JSONDecoder().decode(ReaderTOCEvidenceArtifact.self, from: persistedData)
        guard reparsed.entries.last?.label == label else {
            throw ReaderTOCEvidenceWriterError.invalidManifest
        }
        attachText(
            String(decoding: persistedData, as: UTF8.self),
            named: "KG_PERF UI Evidence \(label)"
        )
    }

    private static func manifestAsset(
        _ assetID: String,
        in assets: [String: Any]
    ) throws -> [String: Any] {
        var cursor: Any = assets
        for component in assetID.split(separator: ".") {
            guard let dictionary = cursor as? [String: Any],
                  let next = dictionary[String(component)] else {
                throw ReaderTOCEvidenceWriterError.missingAsset(assetID)
            }
            cursor = next
        }
        guard let asset = cursor as? [String: Any] else {
            throw ReaderTOCEvidenceWriterError.missingAsset(assetID)
        }
        return asset
    }
}

private extension JSONEncoder {
    static var readerTOCEvidence: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}
