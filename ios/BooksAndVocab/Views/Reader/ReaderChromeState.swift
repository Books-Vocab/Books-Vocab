#if os(iOS)
import SwiftUI

enum HeaderState: Equatable {
    case compact
    case expanded
}

enum ReaderChromeOverlay: Equatable {
    case none
    case translation
    case settings
}

struct ReaderChromeState: Equatable {
    var header: HeaderState = .compact
    var overlay: ReaderChromeOverlay = .none

    var blocksReaderInteraction: Bool {
        overlay != .none
    }

    var showsHeader: Bool {
        overlay == .none
    }
}

struct ReaderViewPresenterState {
    let paperColor: Color
    let isWebViewReady: Bool
    let loadingPhase: String
    let underlineProgress: Double?
    let chrome: ReaderChromeState
    let totalProgression: Double?
    let bookTitle: String
    let progressState: ReaderProgressState
    let loadingState: ReaderLoadingState
    let runtimeStateAccessibilityValue: String
    let canResolveSlowLoading: Bool

    init(
        paperColor: Color,
        isWebViewReady: Bool,
        loadingPhase: String,
        underlineProgress: Double?,
        chrome: ReaderChromeState,
        totalProgression: Double?,
        bookTitle: String,
        progressState: ReaderProgressState? = nil,
        loadingState: ReaderLoadingState? = nil,
        runtimeStateAccessibilityValue: String? = nil,
        canResolveSlowLoading: Bool = false
    ) {
        self.paperColor = paperColor
        self.isWebViewReady = isWebViewReady
        self.loadingPhase = loadingPhase
        self.underlineProgress = underlineProgress
        self.chrome = chrome
        self.totalProgression = totalProgression
        self.bookTitle = bookTitle
        let resolvedProgressState = progressState ?? {
            guard let totalProgression else { return .unknown }
            if !isWebViewReady, totalProgression == 0 { return .unknown }
            return ReaderProgressState.classify(progression: totalProgression)
        }()
        let resolvedLoadingState = loadingState ?? (isWebViewReady ? .ready : .loading(.opening))
        self.progressState = resolvedProgressState
        self.loadingState = resolvedLoadingState
        self.runtimeStateAccessibilityValue = runtimeStateAccessibilityValue
            ?? "scenario=preview;progress=\(resolvedProgressState.accessibilityIdentifier);loading=\(resolvedLoadingState.accessibilityIdentifier);state=preview"
        self.canResolveSlowLoading = canResolveSlowLoading
    }
}
#endif
