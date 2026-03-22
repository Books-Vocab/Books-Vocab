import SwiftUI

struct ReaderViewPresenter<MainContent: View, TranslationPanelContent: View, SettingsPanelContent: View>: View {
    @Environment(\.vocabSkin) var vocabSkin
    @Environment(\.horizontalSizeClass) var sizeClass

    let state: ReaderViewPresenterState
    let onDismiss: () -> Void
    let onShowTableOfContents: () -> Void
    let onShowReaderSettings: () -> Void
    let onShowNotebookPicker: () -> Void
    let onExpandHeader: () -> Void
    let onCollapseHeader: () -> Void
    @ViewBuilder let mainContent: MainContent
    let translationPanelBuilder: () -> TranslationPanelContent
    let settingsPanelBuilder: () -> SettingsPanelContent

    init(
        state: ReaderViewPresenterState,
        onDismiss: @escaping () -> Void,
        onShowTableOfContents: @escaping () -> Void,
        onShowReaderSettings: @escaping () -> Void,
        onShowNotebookPicker: @escaping () -> Void,
        onExpandHeader: @escaping () -> Void,
        onCollapseHeader: @escaping () -> Void,
        @ViewBuilder mainContent: () -> MainContent,
        @ViewBuilder translationPanel: @escaping () -> TranslationPanelContent,
        @ViewBuilder settingsPanel: @escaping () -> SettingsPanelContent
    ) {
        self.state = state
        self.onDismiss = onDismiss
        self.onShowTableOfContents = onShowTableOfContents
        self.onShowReaderSettings = onShowReaderSettings
        self.onShowNotebookPicker = onShowNotebookPicker
        self.onExpandHeader = onExpandHeader
        self.onCollapseHeader = onCollapseHeader
        self.mainContent = mainContent()
        self.translationPanelBuilder = translationPanel
        self.settingsPanelBuilder = settingsPanel
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
    }
}
