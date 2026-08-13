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
        await withTaskGroup(of: ReaderTOCNavigationEvent.self) { group in
            group.addTask { @MainActor [navigator] in
                guard let navigator else {
                    return .navigatorUnavailable(requestID: requestID)
                }
                guard !Task.isCancelled else {
                    return .cancelled(requestID: requestID)
                }
                guard let accepted = await navigator.go(to: locator) else {
                    return .navigatorUnavailable(requestID: requestID)
                }
                return accepted
                    ? .goAccepted(requestID: requestID, locatorHref: locator.href.string)
                    : .goRejected(requestID: requestID)
            }
            group.addTask {
                do {
                    try await Task.sleep(nanoseconds: self.timeoutNanoseconds)
                    return .timedOut(requestID: requestID)
                } catch {
                    return .cancelled(requestID: requestID)
                }
            }

            let result = await group.next() ?? .cancelled(requestID: requestID)
            group.cancelAll()
            return result
        }
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
        case .goAccepted(_, let locatorHref), .locationDidChange(_, let locatorHref):
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

struct ReaderTOCEvidenceRun: Codable, Equatable {
    let verdictPath: String
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
    let observation: ReaderTOCEvidenceObservation
}

struct ReaderTOCEvidenceArtifact: Codable, Equatable {
    let schema: String
    let run: ReaderTOCEvidenceRun
    var entries: [ReaderTOCEvidenceEntry]

    var validationErrors: [String] {
        var errors: [String] = []
        if schema != "kg.ui.perf.evidence.v2" { errors.append("schema") }
        if run.verdictPath.isEmpty { errors.append("run.verdictPath") }
        if run.sourceCommit.isEmpty { errors.append("run.sourceCommit") }
        if run.sourceTreeDirty { errors.append("run.sourceTreeDirty") }
        if run.datasetID.isEmpty { errors.append("run.datasetID") }
        if run.datasetSHA256.isEmpty { errors.append("run.datasetSHA256") }
        if run.device.isEmpty { errors.append("run.device") }
        if run.selector.isEmpty { errors.append("run.selector") }
        if run.runIdentity.isEmpty { errors.append("run.runIdentity") }
        if run.logPath.isEmpty
            || run.xcresultPath.isEmpty
            || run.uiScreenshotDirectory.isEmpty
            || run.uiVisualReviewManifest.isEmpty
            || run.uiReviewRoot.isEmpty
            || run.uiVideo.isEmpty {
            errors.append("run.artifacts")
        }
        for (index, entry) in entries.enumerated() {
            let prefix = "entries[\(index)]"
            if entry.label.isEmpty { errors.append("\(prefix).label") }
            if entry.partition.isEmpty { errors.append("\(prefix).partition") }
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
            if entry.observation.requestedHref.isEmpty {
                errors.append("\(prefix).observation.requestedHref")
            }
        }
        return errors
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
