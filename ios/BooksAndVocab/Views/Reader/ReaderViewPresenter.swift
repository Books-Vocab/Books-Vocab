#if os(iOS)
import SwiftUI

struct ReaderViewPresenter<MainContent: View, TranslationPanelContent: View, SettingsPanelContent: View>: View {
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
    @ViewBuilder let settingsPanel: SettingsPanelContent

    init(
        state: ReaderViewPresenterState,
        onDismiss: @escaping () -> Void,
        onShowTableOfContents: @escaping () -> Void,
        onShowReaderSettings: @escaping () -> Void,
        onShowNotebookPicker: @escaping () -> Void,
        onExpandHeader: @escaping () -> Void,
        onCollapseHeader: @escaping () -> Void,
        @ViewBuilder mainContent: () -> MainContent,
        @ViewBuilder translationPanel: () -> TranslationPanelContent,
        @ViewBuilder settingsPanel: () -> SettingsPanelContent
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
        self.settingsPanel = settingsPanel()
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
