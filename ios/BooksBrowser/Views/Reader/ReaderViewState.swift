#if os(iOS)
import SwiftUI

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
