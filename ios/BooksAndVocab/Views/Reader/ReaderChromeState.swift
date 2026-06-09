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
    let totalProgression: Double
    let bookTitle: String
}
#endif
