import Foundation
import XCTest
@testable import BooksAndVocab

private enum ReaderTOCEvidenceWriterError: Error, CustomStringConvertible {
    case missingRunnerVerdict
    case invalidRunnerVerdict(String)
    case missingAccessibilityObservation(String)
    case observationMismatch(String)
    case assetIntegrityMismatch(String)
    case missingScreenshotBundle
    case invalidArtifact

    var description: String {
        switch self {
        case .missingRunnerVerdict:
            return "current ios_test --json verdict is required"
        case .invalidRunnerVerdict(let field):
            return "current ios_test --json is missing \(field)"
        case .missingAccessibilityObservation(let identifier):
            return "current Reader accessibility observation is missing \(identifier)"
        case .observationMismatch(let field):
            return "Reader observation does not match \(field)"
        case .assetIntegrityMismatch(let field):
            return "Reader evidence asset does not match canonical fixture \(field)"
        case .missingScreenshotBundle:
            return "current UI screenshot bundle is missing"
        case .invalidArtifact:
            return "Reader TOC evidence contract validation failed"
        }
    }
}

private struct IOSRunVerdict: Decodable {
    struct Options: Decodable {
        let sourceCommit: String?
        let sourceTreeDirty: Bool?
        let datasetID: String?
        let datasetSHA256: String?
        let device: String?
    }

    struct Invocation: Decodable {
        let ts: Int?
        let pid: Int?
        let verdictFile: String?
    }

    struct Artifacts: Decodable {
        let log: String?
        let xcresult: String?
        let uiScreenshotDir: String?
        let uiVisualReviewManifest: String?
        let uiReviewRoot: String?
        let uiVideo: String?
    }

    let options: Options
    let invocation: Invocation?
    let device: String?
    let artifacts: Artifacts
}

extension UITestCase {
    /// Writes only evidence from the current UI run. The runner verdict is
    /// intentionally required: a fixture manifest or caller-provided href is
    /// not provenance for an installed EPUB or a current simulator run.
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
        let verdict = try Self.currentIOSRunVerdict()
        let app = try XCTUnwrap(currentApp)
        let run = try Self.makeRun(
            verdict: verdict,
            selector: name,
            screenshotDirectory: ProcessInfo.processInfo.environment[
                "KG_UI_TEST_SCREENSHOT_DIR"
            ]
        )
        let asset = try Self.readInstalledAsset(from: app, assetID: assetID)
        let observedLocator = try Self.readRequiredValue(
            app,
            identifier: "reader.currentLocator"
        )
        let observedContent = try Self.readContent(
            app,
            selector: contentSelector
        )
        if let locatorHref, locatorHref != observedLocator {
            throw ReaderTOCEvidenceWriterError.observationMismatch("locatorHref")
        }
        if let destinationSelector {
            let destination = try Self.readScopedValue(
                app,
                rootIdentifier: "reader.toc.readerOverlay",
                identifier: destinationSelector
            )
            guard destination == observedLocator else {
                throw ReaderTOCEvidenceWriterError.observationMismatch(
                    "destinationSelector"
                )
            }
        }

        guard !href.isEmpty, !label.isEmpty, !fixtureID.isEmpty, !assetID.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidArtifact
        }

        let artifactDirectory = URL(fileURLWithPath: run.uiScreenshotDirectory)
        guard FileManager.default.fileExists(atPath: artifactDirectory.path) else {
            throw ReaderTOCEvidenceWriterError.missingScreenshotBundle
        }
        let screenshotNames = try FileManager.default.contentsOfDirectory(
            at: artifactDirectory,
            includingPropertiesForKeys: nil
        )
        .filter { $0.pathExtension.lowercased() == "png" }
        guard !screenshotNames.isEmpty else {
            throw ReaderTOCEvidenceWriterError.missingScreenshotBundle
        }

        let artifactURL = artifactDirectory.appendingPathComponent(
            "reader-toc-ui-evidence.json"
        )
        var artifact: ReaderTOCEvidenceArtifact
        if FileManager.default.fileExists(atPath: artifactURL.path) {
            artifact = try JSONDecoder().decode(
                ReaderTOCEvidenceArtifact.self,
                from: Data(contentsOf: artifactURL)
            )
            guard artifact.run.runIdentity == run.runIdentity else {
                throw ReaderTOCEvidenceWriterError.observationMismatch("runIdentity")
            }
        } else {
            artifact = ReaderTOCEvidenceArtifact(
                schema: "kg.ui.perf.evidence.v2",
                run: run,
                entries: []
            )
        }

        artifact.entries.append(
            ReaderTOCEvidenceEntry(
                label: label,
                partition: partition,
                fixtureID: fixtureID,
                asset: asset,
                path: path,
                observation: ReaderTOCEvidenceObservation(
                    requestedHref: href,
                    observedLocatorHref: observedLocator,
                    observedContent: observedContent,
                    contentSelector: contentSelector
                )
            )
        )
        guard artifact.validationErrors.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidArtifact
        }

        let encoded = try JSONEncoder.readerTOCEvidence.encode(artifact)
        try encoded.write(to: artifactURL, options: .atomic)
        let reparsed = try JSONDecoder().decode(
            ReaderTOCEvidenceArtifact.self,
            from: Data(contentsOf: artifactURL)
        )
        guard reparsed.validationErrors.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidArtifact
        }
        attachText(
            String(decoding: encoded, as: UTF8.self),
            named: "KG_PERF UI Evidence \(label)"
        )
    }

    private static func currentIOSRunVerdict() throws -> IOSRunVerdict {
        let environment = ProcessInfo.processInfo.environment
        var candidates: [URL] = []
        if let path = environment["KG_UI_TEST_VERDICT_JSON"], !path.isEmpty {
            candidates.append(URL(fileURLWithPath: path))
        }
        if let path = environment["KG_IOS_VERDICT_FILE"], !path.isEmpty {
            candidates.append(URL(fileURLWithPath: "\(path).json"))
        }
        guard let url = candidates.first(where: {
            FileManager.default.fileExists(atPath: $0.path)
        }) else {
            throw ReaderTOCEvidenceWriterError.missingRunnerVerdict
        }
        do {
            return try JSONDecoder().decode(
                IOSRunVerdict.self,
                from: Data(contentsOf: url)
            )
        } catch {
            throw ReaderTOCEvidenceWriterError.invalidRunnerVerdict(error.localizedDescription)
        }
    }

    private static func makeRun(
        verdict: IOSRunVerdict,
        selector: String,
        screenshotDirectory: String?
    ) throws -> ReaderTOCEvidenceRun {
        let sourceCommit = try required(verdict.options.sourceCommit, "options.sourceCommit")
        let sourceTreeDirty = try required(verdict.options.sourceTreeDirty, "options.sourceTreeDirty")
        guard !sourceTreeDirty else {
            throw ReaderTOCEvidenceWriterError.invalidRunnerVerdict(
                "options.sourceTreeDirty=true"
            )
        }
        let datasetID = try required(verdict.options.datasetID, "options.datasetID")
        let datasetSHA256 = try required(
            verdict.options.datasetSHA256,
            "options.datasetSHA256"
        )
        let destination = try required(verdict.options.device, "options.device")
        let resolvedDevice = verdict.device ?? ""
        let logPath = try required(verdict.artifacts.log, "artifacts.log")
        let xcresultPath = try required(verdict.artifacts.xcresult, "artifacts.xcresult")
        let uiScreenshotDirectory = try required(
            screenshotDirectory ?? verdict.artifacts.uiScreenshotDir,
            "artifacts.uiScreenshotDir"
        )
        let uiVisualReviewManifest = try required(
            verdict.artifacts.uiVisualReviewManifest,
            "artifacts.uiVisualReviewManifest"
        )
        let uiReviewRoot = try required(
            verdict.artifacts.uiReviewRoot,
            "artifacts.uiReviewRoot"
        )
        let uiVideo = try required(verdict.artifacts.uiVideo, "artifacts.uiVideo")
        let timestamp = try required(verdict.invocation?.ts, "invocation.ts")
        let pid = try required(verdict.invocation?.pid, "invocation.pid")
        guard !selector.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidRunnerVerdict("selector")
        }

        return ReaderTOCEvidenceRun(
            verdictPath: try required(
                verdict.invocation?.verdictFile,
                "invocation.verdictFile"
            ),
            sourceCommit: sourceCommit,
            sourceTreeDirty: sourceTreeDirty,
            datasetID: datasetID,
            datasetSHA256: datasetSHA256,
            device: resolvedDevice.isEmpty ? destination : "\(destination) | \(resolvedDevice)",
            selector: selector,
            runIdentity: "\(timestamp)-\(pid)-\(selector)",
            logPath: logPath,
            xcresultPath: xcresultPath,
            uiScreenshotDirectory: uiScreenshotDirectory,
            uiVisualReviewManifest: uiVisualReviewManifest,
            uiReviewRoot: uiReviewRoot,
            uiVideo: uiVideo
        )
    }

    private static func readInstalledAsset(
        from app: XCUIApplication,
        assetID: String
    ) throws -> ReaderTOCEvidenceAsset {
        let descriptor = try readRequiredValue(app, identifier: "reader.evidence.asset")
        let parts = descriptor.split(separator: "|", omittingEmptySubsequences: false)
        guard parts.count == 6,
              let expectedByteSize = Int(parts[3]),
              let actualByteSize = Int(parts[5]),
              !parts[0].isEmpty,
              !parts[1].isEmpty,
              parts[2].count == 64,
              parts[4].count == 64 else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(
                "reader.evidence.asset"
            )
        }
        guard String(parts[0]) == assetID else {
            throw ReaderTOCEvidenceWriterError.assetIntegrityMismatch("assetID")
        }
        let installedURL = URL(fileURLWithPath: String(parts[1]))
        let proof = try FixtureDatasetStore.readerAssetProof(
            forInstalledFileName: installedURL.lastPathComponent
        )
        guard proof.assetID == assetID,
              proof.installedPath == installedURL.path,
              proof.expectedSHA256 == String(parts[2]),
              proof.expectedByteSize == expectedByteSize,
              proof.actualSHA256 == String(parts[4]),
              proof.actualByteSize == actualByteSize else {
            throw ReaderTOCEvidenceWriterError.assetIntegrityMismatch("manifest-or-installed-copy")
        }
        return ReaderTOCEvidenceAsset(
            assetID: assetID,
            installedPath: proof.installedPath,
            expectedSHA256: proof.expectedSHA256,
            expectedByteSize: proof.expectedByteSize,
            actualSHA256: proof.actualSHA256,
            actualByteSize: proof.actualByteSize
        )
    }

    private static func readContent(
        _ app: XCUIApplication,
        selector: String?
    ) throws -> String? {
        guard let selector, !selector.isEmpty else { return nil }
        let webViews = app.webViews
        guard webViews.count == 1 else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(
                "webView"
            )
        }
        let content = webViews.element(boundBy: 0).staticTexts[selector]
        guard content.count == 1 else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(
                "contentSelector:\(selector)"
            )
        }
        return content.element(boundBy: 0).label
    }

    private static func readScopedValue(
        _ app: XCUIApplication,
        rootIdentifier: String,
        identifier: String
    ) throws -> String {
        let roots = app.otherElements[rootIdentifier]
        guard roots.count == 1 else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(rootIdentifier)
        }
        let elements = roots.element(boundBy: 0).staticTexts[identifier]
        guard elements.count == 1,
              let value = elements.element(boundBy: 0).value as? String,
              !value.isEmpty else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(identifier)
        }
        return value
    }

    private static func readRequiredValue(
        _ app: XCUIApplication,
        identifier: String
    ) throws -> String {
        let elements = app.staticTexts[identifier]
        guard elements.count == 1,
              let value = elements.element(boundBy: 0).value as? String,
              !value.isEmpty else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(identifier)
        }
        return value
    }

    private static func required<T>(_ value: T?, _ field: String) throws -> T {
        guard let value else {
            throw ReaderTOCEvidenceWriterError.invalidRunnerVerdict(field)
        }
        if let string = value as? String, string.isEmpty {
            throw ReaderTOCEvidenceWriterError.invalidRunnerVerdict(field)
        }
        return value
    }
}

private extension JSONEncoder {
    static var readerTOCEvidence: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        return encoder
    }
}
