#if os(iOS)
import SwiftUI

/// Reader 殼層。**不含**閱讀設定面板：那一頁自 APP-20260808-240a94 起是
/// `ReaderView` 掛的系統 sheet（原生 detents / drag indicator），不再由本
/// presenter 當 overlay 疊出來。
struct ReaderViewPresenter<MainContent: View, TranslationPanelContent: View>: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) var appSkin
    @Environment(\.horizontalSizeClass) var sizeClass

    let state: ReaderViewPresenterState
    let onDismiss: () -> Void
    let onShowTableOfContents: () -> Void
    let onShowReaderSettings: () -> Void
    let onShowNotebookPicker: () -> Void
    let onExpandHeader: () -> Void
    let onCollapseHeader: () -> Void
    @ViewBuilder let mainContent: MainContent
    @ViewBuilder let translationPanel: TranslationPanelContent

    init(
        state: ReaderViewPresenterState,
        onDismiss: @escaping () -> Void,
        onShowTableOfContents: @escaping () -> Void,
        onShowReaderSettings: @escaping () -> Void,
        onShowNotebookPicker: @escaping () -> Void,
        onExpandHeader: @escaping () -> Void,
        onCollapseHeader: @escaping () -> Void,
        @ViewBuilder mainContent: () -> MainContent,
        @ViewBuilder translationPanel: () -> TranslationPanelContent
    ) {
        self.state = state
        self.onDismiss = onDismiss
        self.onShowTableOfContents = onShowTableOfContents
        self.onShowReaderSettings = onShowReaderSettings
        self.onShowNotebookPicker = onShowNotebookPicker
        self.onExpandHeader = onExpandHeader
        self.onCollapseHeader = onCollapseHeader
        self.mainContent = mainContent()
        self.translationPanel = translationPanel()
    }

    var body: some View {
        ZStack {
            state.paperColor.ignoresSafeArea()

            mainContent

            if !state.isWebViewReady {
                loadingOverlay
            }

            if let progress = state.underlineProgress {
                underlineProgressOverlay(progress)
            }

            bottomOverlay
            topOverlay
        }
        .enableInjection()
    }
}
#endif
