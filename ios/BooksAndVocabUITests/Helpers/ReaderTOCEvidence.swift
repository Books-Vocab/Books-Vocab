import Foundation
import XCTest
@testable import BooksAndVocab

private enum ReaderTOCEvidenceWriterError: Error, CustomStringConvertible {
    case missingInvocationContext
    case invalidContext(String)
    case missingAccessibilityObservation(String)
    case observationMismatch(String)
    case assetIntegrityMismatch(String)
    case missingScreenshot

    var description: String {
        switch self {
        case .missingInvocationContext:
            return "pre-run Reader evidence context requires KG_IOS_VERDICT_FILE"
        case .invalidContext(let field):
            return "Reader evidence context is invalid: \(field)"
        case .missingAccessibilityObservation(let identifier):
            return "current Reader accessibility observation is missing \(identifier)"
        case .observationMismatch(let field):
            return "Reader observation does not match \(field)"
        case .assetIntegrityMismatch(let field):
            return "Reader evidence asset does not match canonical fixture \(field)"
        case .missingScreenshot:
            return "current Reader screenshot path is missing"
        }
    }
}

extension UITestCase {
    /// Records only identity/context and observations available during the UI
    /// body. It deliberately never opens the runner's final verdict JSON. The
    /// canonical `ios_test.sh` UI bundle retains this XCTest attachment,
    /// screenshot directory, xcresult, and invocation verdict path together.
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
        guard !label.isEmpty, !fixtureID.isEmpty, !assetID.isEmpty, !href.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidContext("entry identity")
        }
        guard ReaderTOCEvidenceHref.isSafeRelative(href) else {
            throw ReaderTOCEvidenceWriterError.invalidContext("unsafe href")
        }
        let environment = ProcessInfo.processInfo.environment
        guard let verdictFile = Self.preRunVerdictFile(from: environment) else {
            throw ReaderTOCEvidenceWriterError.missingInvocationContext
        }
        guard let screenshotDirectory = environment["KG_UI_TEST_SCREENSHOT_DIR"],
              !screenshotDirectory.isEmpty,
              let screenshotPath = lastCapturedScreenshotPath,
              screenshotPath.hasPrefix(screenshotDirectory + "/"),
              FileManager.default.fileExists(atPath: screenshotPath) else {
            throw ReaderTOCEvidenceWriterError.missingScreenshot
        }
        let app = try XCTUnwrap(currentApp)
        let asset = try Self.readInstalledAsset(from: app, assetID: assetID)
        let observedLocator = try Self.readRequiredValue(
            app,
            identifier: "reader.currentLocator"
        )
        let observedContent = try Self.readContent(
            app,
            selector: contentSelector
        )
        let selectedRow = try Self.readSelectedRow(
            app,
            path: path,
            expectedHref: href
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

        let entry = ReaderTOCEvidenceEntry(
            label: label,
            partition: partition,
            fixtureID: fixtureID,
            asset: asset,
            path: path,
            selectedRow: selectedRow,
            observation: ReaderTOCEvidenceObservation(
                requestedHref: href,
                observedLocatorHref: observedLocator,
                observedContent: observedContent,
                contentSelector: contentSelector
            )
        )
        let contextURL = URL(fileURLWithPath: screenshotDirectory)
            .appendingPathComponent("reader-toc-ui-context.json")
        var context: ReaderTOCEvidenceContext
        if FileManager.default.fileExists(atPath: contextURL.path) {
            context = try JSONDecoder().decode(
                ReaderTOCEvidenceContext.self,
                from: Data(contentsOf: contextURL)
            )
            guard context.invocation.verdictFile == verdictFile,
                  context.screenshotDirectory == screenshotDirectory else {
                throw ReaderTOCEvidenceWriterError.invalidContext("invocation or screenshot identity")
            }
        } else {
            context = ReaderTOCEvidenceContext(
                schema: ReaderTOCEvidenceContext.schema,
                invocation: ReaderTOCEvidenceContext.Invocation(verdictFile: verdictFile),
                selectors: [],
                screenshotDirectory: screenshotDirectory,
                screenshotPath: screenshotPath,
                entries: []
            )
        }
        if !context.selectors.contains(name) {
            context.selectors.append(name)
        }
        context.screenshotPath = screenshotPath
        context.entries.append(entry)
        let errors = context.entries.count >= 3
            ? context.completeValidationErrors
            : context.validationErrors
        guard errors.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidContext(errors.joined(separator: ","))
        }
        let encoded = try JSONEncoder.readerTOCEvidence.encode(context)
        try FileManager.default.createDirectory(
            at: URL(fileURLWithPath: screenshotDirectory),
            withIntermediateDirectories: true
        )
        try encoded.write(to: contextURL, options: .atomic)
        let reparsed = try JSONDecoder().decode(
            ReaderTOCEvidenceContext.self,
            from: Data(contentsOf: contextURL)
        )
        guard reparsed.validationErrors.isEmpty else {
            throw ReaderTOCEvidenceWriterError.invalidContext("persisted context")
        }
        attachText(
            String(decoding: encoded, as: UTF8.self),
            named: "KG_PERF UI Evidence Context \(label)"
        )
    }

    private static func preRunVerdictFile(
        from environment: [String: String]
    ) -> String? {
        if let path = environment["KG_IOS_VERDICT_FILE"], !path.isEmpty {
            return path
        }
        if let jsonPath = environment["KG_UI_TEST_VERDICT_JSON"], !jsonPath.isEmpty {
            return jsonPath.hasSuffix(".json")
                ? String(jsonPath.dropLast(5))
                : jsonPath
        }
        return nil
    }

    private static func readSelectedRow(
        _ app: XCUIApplication,
        path: [Int],
        expectedHref: String
    ) throws -> ReaderTOCEvidenceSelectedRow {
        guard ReaderTOCEvidenceHref.isSafeRelative(expectedHref) else {
            throw ReaderTOCEvidenceWriterError.invalidContext("unsafe selected row href")
        }
        let pathID = path.map(String.init).joined(separator: ".")
        let identifier = "reader.toc.chapter.\(pathID)"
        let rows = app.buttons[identifier]
        guard rows.count == 1,
              let row = rows.allElementsBoundByIndex.first,
              row.exists,
              !row.label.isEmpty,
              let value = row.value as? String,
              !value.isEmpty else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(identifier)
        }
        guard ReaderTOCEvidenceHref.isSafeRelative(value), value == expectedHref else {
            throw ReaderTOCEvidenceWriterError.observationMismatch("selectedRow.href")
        }
        return ReaderTOCEvidenceSelectedRow(
            path: path,
            href: value,
            title: row.label
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
            throw ReaderTOCEvidenceWriterError.assetIntegrityMismatch(
                "manifest-or-installed-copy"
            )
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
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation("webView")
        }
        guard let webView = webViews.allElementsBoundByIndex.first else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation("webView")
        }
        let content = webView.staticTexts[selector]
        guard content.count == 1,
              let element = content.allElementsBoundByIndex.first else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(
                "contentSelector:\(selector)"
            )
        }
        return element.label
    }

    private static func readScopedValue(
        _ app: XCUIApplication,
        rootIdentifier: String,
        identifier: String
    ) throws -> String {
        let roots = app.otherElements[rootIdentifier]
        guard roots.count == 1,
              let root = roots.allElementsBoundByIndex.first else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(rootIdentifier)
        }
        let elements = root.staticTexts[identifier]
        guard elements.count == 1,
              let element = elements.allElementsBoundByIndex.first,
              let value = element.value as? String,
              !value.isEmpty else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(identifier)
        }
        return value
    }

    private static func readRequiredValue(
        _ app: XCUIApplication,
        identifier: String
    ) throws -> String {
        let predicate = NSPredicate(format: "identifier == %@", identifier)
        let elements = app.staticTexts.matching(predicate)
        let element = app.staticTexts.element(matching: predicate)
        guard elements.count == 1,
              element.exists,
              let value = element.value as? String,
              !value.isEmpty else {
            throw ReaderTOCEvidenceWriterError.missingAccessibilityObservation(identifier)
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
