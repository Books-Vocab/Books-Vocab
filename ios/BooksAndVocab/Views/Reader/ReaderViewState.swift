#if os(iOS)
import Foundation
import SwiftUI
import ReadiumShared

enum ReaderTOCNavigationPhase: Equatable {
    case idle
    case loading
    case success
    case failure
    case missingDestination
}

enum ReaderTOCNavigationFailure: Equatable, Sendable {
    case navigatorRejected
    case navigatorUnavailable
    case timedOut
    case cancelled
    case locatorMismatch
    case missingDestination
}

enum ReaderTOCNavigationEvent: Equatable, Sendable {
    case goAccepted(requestID: UUID, locatorHref: String)
    case goRejected(requestID: UUID)
    case navigatorUnavailable(requestID: UUID)
    case locationDidChange(requestID: UUID, locatorHref: String)
    case timedOut(requestID: UUID)
    case cancelled(requestID: UUID)
    case missingDestination(requestID: UUID)

    var requestID: UUID {
        switch self {
        case .goAccepted(let requestID, _),
             .goRejected(let requestID),
             .navigatorUnavailable(let requestID),
             .locationDidChange(let requestID, _),
             .timedOut(let requestID),
             .cancelled(let requestID),
             .missingDestination(let requestID):
            return requestID
        }
    }
}

@MainActor
protocol ReaderNavigatorDriving: AnyObject {
    func go(to locator: Locator) async -> Bool?
}

@MainActor
final class ReaderTOCNavigationBridge {
    private let navigator: ReaderNavigatorDriving?
    private let timeoutNanoseconds: UInt64

    init(
        navigator: ReaderNavigatorDriving?,
        timeoutNanoseconds: UInt64
    ) {
        self.navigator = navigator
        self.timeoutNanoseconds = timeoutNanoseconds
    }

    func navigate(requestID: UUID, locator: Locator) async -> ReaderTOCNavigationEvent {
        let race = ReaderTOCNavigationRace()
        let navigator = self.navigator
        let timeoutNanoseconds = self.timeoutNanoseconds

        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { (continuation: CheckedContinuation<ReaderTOCNavigationEvent, Never>) in
                race.setContinuation(continuation)

                let navigationTask: Task<Void, Never> = Task { @MainActor in
                    guard let navigator else {
                        race.finish(.navigatorUnavailable(requestID: requestID))
                        return
                    }
                    guard !Task.isCancelled else {
                        race.finish(.cancelled(requestID: requestID))
                        return
                    }
                    guard let accepted = await navigator.go(to: locator) else {
                        race.finish(.navigatorUnavailable(requestID: requestID))
                        return
                    }
                    race.finish(
                        accepted
                            ? .goAccepted(requestID: requestID, locatorHref: locator.href.string)
                            : .goRejected(requestID: requestID)
                    )
                }
                let timeoutTask: Task<Void, Never> = Task.detached {
                    do {
                        try await Task.sleep(nanoseconds: timeoutNanoseconds)
                    } catch {
                        return
                    }
                    race.finish(.timedOut(requestID: requestID))
                }
                race.setTasks(navigationTask: navigationTask, timeoutTask: timeoutTask)
            }
        }, onCancel: {
            race.finish(.cancelled(requestID: requestID))
        })
    }
}

private final class ReaderTOCNavigationRace: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<ReaderTOCNavigationEvent, Never>?
    private var finished = false
    private var navigationTask: Task<Void, Never>?
    private var timeoutTask: Task<Void, Never>?

    func setContinuation(
        _ continuation: CheckedContinuation<ReaderTOCNavigationEvent, Never>
    ) {
        lock.lock()
        self.continuation = continuation
        let shouldCancel = finished
        lock.unlock()
        if shouldCancel {
            continuation.resume(returning: .cancelled(requestID: UUID()))
        }
    }

    func setTasks(
        navigationTask: Task<Void, Never>,
        timeoutTask: Task<Void, Never>
    ) {
        lock.lock()
        if finished {
            lock.unlock()
            navigationTask.cancel()
            timeoutTask.cancel()
            return
        }
        self.navigationTask = navigationTask
        self.timeoutTask = timeoutTask
        lock.unlock()
    }

    func finish(_ event: ReaderTOCNavigationEvent) {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        let continuation = self.continuation
        self.continuation = nil
        let navigationTask = self.navigationTask
        let timeoutTask = self.timeoutTask
        self.navigationTask = nil
        self.timeoutTask = nil
        lock.unlock()

        navigationTask?.cancel()
        timeoutTask?.cancel()
        continuation?.resume(returning: event)
    }
}

struct ReaderTOCNavigationState: Equatable {
    private(set) var phase: ReaderTOCNavigationPhase = .idle
    private(set) var selectedPath: [Int]?
    private(set) var selectedTitle: String?
    private(set) var errorMessage: String?
    private(set) var destinationHref: String?
    private(set) var observedLocatorHref: String?
    private(set) var failureReason: ReaderTOCNavigationFailure?
    private(set) var activeRequestID: UUID?
    private(set) var expectedLocatorHref: String?

    var canDismissSheet: Bool {
        phase == .idle || phase == .success
    }

    var canRetry: Bool {
        phase == .failure || phase == .missingDestination
    }

    @discardableResult
    mutating func beginSelection(
        path: [Int],
        title: String,
        expectedHref: String,
        requestID: UUID = UUID()
    ) -> UUID {
        selectedPath = path
        selectedTitle = title
        errorMessage = nil
        destinationHref = nil
        observedLocatorHref = nil
        failureReason = nil
        activeRequestID = requestID
        expectedLocatorHref = expectedHref
        phase = .loading
        return requestID
    }

    @discardableResult
    mutating func beginRetry(requestID: UUID = UUID()) -> UUID {
        guard selectedPath != nil else { return requestID }
        errorMessage = nil
        destinationHref = nil
        observedLocatorHref = nil
        failureReason = nil
        activeRequestID = requestID
        phase = .loading
        return requestID
    }

    mutating func apply(_ event: ReaderTOCNavigationEvent) {
        guard phase == .loading, activeRequestID == event.requestID else { return }

        switch event {
        case .goAccepted:
            // Readium's go() result only acknowledges that navigation was
            // requested. The delegate callback is the sole success signal.
            break
        case .locationDidChange(_, let locatorHref):
            guard locatorHref == expectedLocatorHref else {
                fail(
                    reason: .locatorMismatch,
                    message: L10n.string("章節無法開啟，請重試。")
                )
                return
            }
            observedLocatorHref = locatorHref
            destinationHref = locatorHref
            errorMessage = nil
            failureReason = nil
            phase = .success
        case .goRejected:
            fail(
                reason: .navigatorRejected,
                message: L10n.string("章節無法開啟，請重試。")
            )
        case .navigatorUnavailable:
            fail(
                reason: .navigatorUnavailable,
                message: L10n.string("章節無法開啟，請重試。")
            )
        case .timedOut:
            fail(
                reason: .timedOut,
                message: L10n.string("章節無法開啟，請重試。")
            )
        case .cancelled:
            fail(
                reason: .cancelled,
                message: L10n.string("章節無法開啟，請重試。")
            )
        case .missingDestination:
            errorMessage = L10n.string("找不到章節位置")
            destinationHref = nil
            observedLocatorHref = nil
            failureReason = .missingDestination
            phase = .missingDestination
        }
    }

    mutating func reset() {
        phase = .idle
        selectedPath = nil
        selectedTitle = nil
        errorMessage = nil
        destinationHref = nil
        observedLocatorHref = nil
        failureReason = nil
        activeRequestID = nil
        expectedLocatorHref = nil
    }

    private mutating func fail(
        reason: ReaderTOCNavigationFailure,
        message: String
    ) {
        errorMessage = message
        failureReason = reason
        destinationHref = nil
        observedLocatorHref = nil
        phase = .failure
    }
}

struct ReaderTOCEvidenceRunnerVerdict: Decodable, Equatable {
    struct Options: Decodable, Equatable {
        let sourceCommit: String?
        let sourceTreeDirty: Bool?
        let datasetID: String?
        let datasetSHA256: String?
        let device: String?
    }

    struct Invocation: Decodable, Equatable {
        let ts: Int?
        let pid: Int?
        let verdictFile: String?
    }

    struct Artifacts: Decodable, Equatable {
        let log: String?
        let xcresult: String?
        let uiScreenshotDir: String?
        let uiVisualReviewManifest: String?
        let uiReviewRoot: String?
        let uiVideo: String?
    }

    let status: String?
    let result: String?
    let exit: String?
    let options: Options?
    let invocation: Invocation?
    let device: String?
    let artifacts: Artifacts?
}

struct ReaderTOCEvidenceContext: Codable, Equatable {
    struct Invocation: Codable, Equatable {
        let verdictFile: String
    }

    static let schema = "kg.ui.perf.evidence.context.v1"
    let schema: String
    let invocation: Invocation
    var selectors: [String]
    let screenshotDirectory: String
    var screenshotPath: String
    var entries: [ReaderTOCEvidenceEntry]

    var validationErrors: [String] {
        var errors: [String] = []
        if schema != Self.schema { errors.append("schema") }
        if invocation.verdictFile.isEmpty || !invocation.verdictFile.hasPrefix("/") {
            errors.append("invocation.verdictFile")
        }
        if selectors.isEmpty || selectors.contains(where: { $0.isEmpty }) {
            errors.append("selectors")
        }
        if screenshotDirectory.isEmpty || !screenshotDirectory.hasPrefix("/") {
            errors.append("screenshotDirectory")
        }
        if screenshotPath.isEmpty || !screenshotPath.hasPrefix("/") {
            errors.append("screenshotPath")
        }
        errors.append(contentsOf: ReaderTOCEvidenceEntry.validationErrors(for: entries))
        return errors
    }
}

struct ReaderTOCEvidenceInvocation: Codable, Equatable {
    let ts: Int
    let pid: Int
    let verdictFile: String
}

struct ReaderTOCEvidenceRun: Codable, Equatable {
    let invocation: ReaderTOCEvidenceInvocation
    let status: String
    let result: String
    let exit: String
    let sourceCommit: String
    let sourceTreeDirty: Bool
    let datasetID: String
    let datasetSHA256: String
    let device: String
    let selector: String
    let runIdentity: String
    let logPath: String
    let xcresultPath: String
    let uiScreenshotDirectory: String
    let screenshotPath: String
    let uiVisualReviewManifest: String
    let uiReviewRoot: String
    let uiVideo: String
}

struct ReaderTOCEvidenceAsset: Codable, Equatable {
    let assetID: String
    let installedPath: String
    let expectedSHA256: String
    let expectedByteSize: Int
    let actualSHA256: String
    let actualByteSize: Int
}

struct ReaderTOCEvidenceSelectedRow: Codable, Equatable {
    let path: [Int]
    let href: String
    let title: String
}

struct ReaderTOCEvidenceObservation: Codable, Equatable {
    let requestedHref: String
    let observedLocatorHref: String?
    let observedContent: String?
    let contentSelector: String?
}

struct ReaderTOCEvidenceEntry: Codable, Equatable {
    let label: String
    let partition: String
    let fixtureID: String
    let asset: ReaderTOCEvidenceAsset
    let path: [Int]
    let selectedRow: ReaderTOCEvidenceSelectedRow
    let observation: ReaderTOCEvidenceObservation

    static func validationErrors(for entries: [ReaderTOCEvidenceEntry]) -> [String] {
        var errors: [String] = []
        for (index, entry) in entries.enumerated() {
            let prefix = "entries[\(index)]"
            if entry.label.isEmpty { errors.append("\(prefix).label") }
            if !["required", "counterexample"].contains(entry.partition) {
                errors.append("\(prefix).partition")
            }
            if entry.fixtureID.isEmpty { errors.append("\(prefix).fixtureID") }
            if !entry.asset.assetID.hasPrefix("books.") { errors.append("\(prefix).asset.assetID") }
            if entry.asset.installedPath.isEmpty || !entry.asset.installedPath.hasPrefix("/") {
                errors.append("\(prefix).asset.installedPath")
            }
            if entry.asset.expectedSHA256.count != 64 { errors.append("\(prefix).asset.expectedSHA256") }
            if entry.asset.actualSHA256.count != 64 { errors.append("\(prefix).asset.actualSHA256") }
            if !entry.asset.expectedSHA256.allSatisfy(\.isHexDigit) {
                errors.append("\(prefix).asset.expectedSHA256")
            }
            if !entry.asset.actualSHA256.allSatisfy(\.isHexDigit) {
                errors.append("\(prefix).asset.actualSHA256")
            }
            if entry.asset.expectedByteSize <= 0 { errors.append("\(prefix).asset.expectedByteSize") }
            if entry.asset.actualByteSize <= 0 { errors.append("\(prefix).asset.actualByteSize") }
            if entry.asset.expectedSHA256 != entry.asset.actualSHA256 {
                errors.append("\(prefix).asset.sha256Mismatch")
            }
            if entry.asset.expectedByteSize != entry.asset.actualByteSize {
                errors.append("\(prefix).asset.byteSizeMismatch")
            }
            if entry.path.contains(where: { $0 < 0 }) { errors.append("\(prefix).path") }
            if entry.selectedRow.path != entry.path {
                errors.append("\(prefix).selectedRow.pathMismatch")
            }
            if entry.selectedRow.href.isEmpty || entry.selectedRow.href != entry.observation.requestedHref {
                errors.append("\(prefix).selectedRow.hrefMismatch")
            }
            if entry.selectedRow.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("\(prefix).selectedRow.title")
            }
            if entry.observation.requestedHref.isEmpty {
                errors.append("\(prefix).observation.requestedHref")
            }
            switch entry.partition {
            case "required":
                if entry.observation.observedLocatorHref != entry.observation.requestedHref {
                    errors.append("\(prefix).observation.locatorMismatch")
                }
                if entry.observation.contentSelector?.isEmpty != false
                    || entry.observation.observedContent?.isEmpty != false {
                    errors.append("\(prefix).observation.content")
                }
            case "counterexample":
                if entry.observation.observedLocatorHref == nil
                    || entry.observation.observedLocatorHref == entry.observation.requestedHref {
                    errors.append("\(prefix).observation.counterexampleLocator")
                }
                if entry.observation.contentSelector != nil || entry.observation.observedContent != nil {
                    errors.append("\(prefix).observation.counterexampleContent")
                }
            default:
                break
            }
        }
        return errors
    }
}

struct ReaderTOCEvidenceArtifact: Codable, Equatable {
    let schema: String
    let run: ReaderTOCEvidenceRun
    var entries: [ReaderTOCEvidenceEntry]

    var validationErrors: [String] {
        var errors: [String] = []
        if schema != "kg.ui.perf.evidence.v2" { errors.append("schema") }
        if run.invocation.verdictFile.isEmpty { errors.append("run.invocation.verdictFile") }
        if run.status != "ok" { errors.append("run.status") }
        if run.result != "ok" { errors.append("run.result") }
        if run.status != run.result { errors.append("run.statusResultMismatch") }
        if run.exit != "0" { errors.append("run.exit") }
        if run.sourceCommit.isEmpty { errors.append("run.sourceCommit") }
        if run.sourceTreeDirty { errors.append("run.sourceTreeDirty") }
        if run.datasetID.isEmpty { errors.append("run.datasetID") }
        if run.datasetSHA256.count != 64 || !run.datasetSHA256.allSatisfy(\.isHexDigit) {
            errors.append("run.datasetSHA256")
        }
        if run.device.isEmpty { errors.append("run.device") }
        if run.selector.isEmpty { errors.append("run.selector") }
        if run.runIdentity.isEmpty { errors.append("run.runIdentity") }
        if run.screenshotPath.isEmpty || !run.screenshotPath.hasPrefix("/") {
            errors.append("run.screenshotPath")
        }
        if run.logPath.isEmpty
            || run.xcresultPath.isEmpty
            || run.uiScreenshotDirectory.isEmpty
            || run.uiVisualReviewManifest.isEmpty
            || run.uiReviewRoot.isEmpty
            || run.uiVideo.isEmpty {
            errors.append("run.artifacts")
        }
        errors.append(contentsOf: ReaderTOCEvidenceEntry.validationErrors(for: entries))

        let required = entries.filter { $0.partition == "required" }
        let counterexamples = entries.filter { $0.partition == "counterexample" }
        if required.count != 1 { errors.append("partitions.required.count") }
        if counterexamples.count != 2 { errors.append("partitions.counterexample.count") }
        if entries.contains(where: { !["required", "counterexample"].contains($0.partition) }) {
            errors.append("partitions.disjoint")
        }
        if Set(required.map(\.label)).intersection(Set(counterexamples.map(\.label))).isEmpty == false {
            errors.append("partitions.labelsOverlap")
        }
        if Set(required.map(\.fixtureID)).intersection(Set(counterexamples.map(\.fixtureID))).isEmpty == false {
            errors.append("partitions.fixturesOverlap")
        }
        if Set(required.map { $0.asset.assetID }).intersection(Set(counterexamples.map { $0.asset.assetID })).isEmpty == false {
            errors.append("partitions.assetsOverlap")
        }
        return errors
    }
}

enum ReaderTOCEvidenceAssemblyError: Error, Equatable {
    case invalidContext([String])
    case invalidVerdict(String)
    case verdictPathMismatch
    case missingArtifact(String)
    case invalidArtifact([String])
}

enum ReaderTOCEvidenceAssembler {
    static func assemble(
        context: ReaderTOCEvidenceContext,
        verdict: ReaderTOCEvidenceRunnerVerdict,
        verdictJSONPath: String
    ) throws -> ReaderTOCEvidenceArtifact {
        let contextErrors = context.validationErrors
        guard contextErrors.isEmpty else {
            throw ReaderTOCEvidenceAssemblyError.invalidContext(contextErrors)
        }

        guard verdictJSONPath == context.invocation.verdictFile + ".json",
              FileManager.default.fileExists(atPath: verdictJSONPath),
              let invocation = verdict.invocation,
              invocation.verdictFile == context.invocation.verdictFile else {
            throw ReaderTOCEvidenceAssemblyError.verdictPathMismatch
        }
        guard let finalStatus = nonEmpty(verdict.status),
              let finalResult = nonEmpty(verdict.result),
              let finalExit = nonEmpty(verdict.exit),
              finalStatus == "ok",
              finalResult == "ok",
              finalExit == "0",
              finalStatus == finalResult else {
            throw ReaderTOCEvidenceAssemblyError.invalidVerdict("status-result-exit")
        }
        guard let options = verdict.options,
              let sourceCommit = nonEmpty(options.sourceCommit),
              options.sourceTreeDirty == false,
              let datasetID = nonEmpty(options.datasetID),
              let datasetSHA256 = nonEmpty(options.datasetSHA256),
              let destination = nonEmpty(options.device),
              let resolvedDevice = nonEmpty(verdict.device),
              let artifacts = verdict.artifacts,
              let logPath = nonEmpty(artifacts.log),
              let xcresultPath = nonEmpty(artifacts.xcresult),
              let screenshotDirectory = nonEmpty(artifacts.uiScreenshotDir),
              let visualManifest = nonEmpty(artifacts.uiVisualReviewManifest),
              let reviewRoot = nonEmpty(artifacts.uiReviewRoot),
              let video = nonEmpty(artifacts.uiVideo),
              let invocationVerdictFile = nonEmpty(invocation.verdictFile),
              let ts = invocation.ts,
              let pid = invocation.pid else {
            throw ReaderTOCEvidenceAssemblyError.invalidVerdict("provenance")
        }
        guard screenshotDirectory == context.screenshotDirectory,
              context.screenshotPath.hasPrefix(screenshotDirectory + "/"),
              FileManager.default.fileExists(atPath: context.screenshotPath) else {
            throw ReaderTOCEvidenceAssemblyError.missingArtifact("screenshotPath")
        }

        let selector = context.selectors.sorted().joined(separator: "|")
        let run = ReaderTOCEvidenceRun(
            invocation: ReaderTOCEvidenceInvocation(
                ts: ts,
                pid: pid,
                verdictFile: invocationVerdictFile
            ),
            status: finalStatus,
            result: finalResult,
            exit: finalExit,
            sourceCommit: sourceCommit,
            sourceTreeDirty: false,
            datasetID: datasetID,
            datasetSHA256: datasetSHA256,
            device: "\(destination) | \(resolvedDevice)",
            selector: selector,
            runIdentity: "\(ts)-\(pid)-\(selector)",
            logPath: logPath,
            xcresultPath: xcresultPath,
            uiScreenshotDirectory: screenshotDirectory,
            screenshotPath: context.screenshotPath,
            uiVisualReviewManifest: visualManifest,
            uiReviewRoot: reviewRoot,
            uiVideo: video
        )
        let artifact = ReaderTOCEvidenceArtifact(
            schema: "kg.ui.perf.evidence.v2",
            run: run,
            entries: context.entries
        )
        let errors = artifact.validationErrors
        guard errors.isEmpty else {
            throw ReaderTOCEvidenceAssemblyError.invalidArtifact(errors)
        }
        return artifact
    }

    private static func nonEmpty(_ value: String?) -> String? {
        guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        return value
    }
}

struct ReaderTOCItem: Identifiable {
    let id: String
    let path: [Int]
    let depth: Int
    let title: String
    let href: String
    let link: ReadiumShared.Link
}

enum ReaderTOCHierarchy {
    static func flatten(_ links: [ReadiumShared.Link]) -> [ReaderTOCItem] {
        var items: [ReaderTOCItem] = []

        func append(_ links: [ReadiumShared.Link], parentPath: [Int], depth: Int) {
            for (index, link) in links.enumerated() {
                let path = parentPath + [index]
                items.append(
                    ReaderTOCItem(
                        id: path.map(String.init).joined(separator: "."),
                        path: path,
                        depth: depth,
                        title: link.title?.isEmpty == false ? link.title! : L10n.string("目錄"),
                        href: link.url().string,
                        link: link
                    )
                )
                append(link.children, parentPath: path, depth: depth + 1)
            }
        }

        append(links, parentPath: [], depth: 0)
        return items
    }
}

/// 閱讀器 UI 狀態容器，整合原本散落在 ReaderView 的 @State 屬性
@Observable
final class ReaderViewState {
    // Loading
    var isLoading = true
    var isWebViewReady = false
    var loadingPhase = L10n.string("開啟書本…")
    var errorMessage: String?

    // Progress
    var underlineProgress: Double?
    var hasCompletedInitialMarking = false

    // Navigation
    var showTableOfContents = false
    var showSubscriptionPaywall = false
    var detailEntry: VocabularyEntry?
}
#endif
