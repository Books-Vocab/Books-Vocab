#if os(iOS)
import SwiftUI
import ReadiumShared

enum ReaderTOCNavigationPhase: Equatable {
    case idle
    case loading
    case success
    case failure
    case missingDestination
}

enum ReaderTOCNavigationResolution: Equatable {
    case success
    case failure
    case missingDestination

    static func resolve(hasLocator: Bool, href: String) -> Self {
        if hasLocator {
            return .success
        }
        return href == "#" ? .missingDestination : .failure
    }
}

struct ReaderTOCNavigationState: Equatable {
    private(set) var phase: ReaderTOCNavigationPhase = .idle
    private(set) var selectedPath: [Int]?
    private(set) var selectedTitle: String?
    private(set) var errorMessage: String?
    private(set) var destinationHref: String?

    var canDismissSheet: Bool {
        phase == .idle || phase == .success
    }

    var canRetry: Bool {
        phase == .failure || phase == .missingDestination
    }

    mutating func beginSelection(path: [Int], title: String) {
        selectedPath = path
        selectedTitle = title
        errorMessage = nil
        destinationHref = nil
        phase = .loading
    }

    mutating func beginRetry() {
        guard selectedPath != nil else { return }
        errorMessage = nil
        phase = .loading
    }

    mutating func succeed(destinationHref: String? = nil) {
        errorMessage = nil
        self.destinationHref = destinationHref
        phase = .success
    }

    mutating func failSelection(message: String) {
        errorMessage = message
        phase = .failure
    }

    mutating func markMissingDestination() {
        errorMessage = L10n.string("找不到章節位置")
        destinationHref = nil
        phase = .missingDestination
    }

    mutating func reset() {
        phase = .idle
        selectedPath = nil
        selectedTitle = nil
        errorMessage = nil
        destinationHref = nil
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
