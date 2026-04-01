#if os(iOS)
import SwiftUI
import ReadiumShared

extension ReaderView {
    func handleLocationChange(_ locator: Locator) {
        if !readerState.isWebViewReady {
            withAnimation(AppMotion.loadingState) { readerState.isWebViewReady = true }
        }
        currentLocator = locator
        totalProgression = locator.locations.totalProgression ?? 0
        book.lastReadLocatorJSON = locator.jsonString
        book.dateLastRead = Date()
        book.progression = totalProgression
    }

    func handleWordSelected(_ word: String, _ context: String) {
        guard canUseProReaderFeature() else { return }
        handler.handleWordSelected(
            word: word,
            context: context,
            vocabularyContext: vocabularyContext
        )
        withAnimation(AppMotion.panelState) { chromeState.overlay = .translation }
    }

    func handlePhraseSelected(_ phrase: String, _ context: String) {
        guard canUseProReaderFeature() else { return }
        handler.handlePhraseSelected(
            phrase: phrase,
            context: context,
            vocabularyContext: vocabularyContext
        )
        withAnimation(AppMotion.panelState) { chromeState.overlay = .translation }
    }

    func handleMarkingProgress(_ progress: Double) {
        guard !readerState.hasCompletedInitialMarking else { return }
        withAnimation(AppMotion.progressLinear) {
            readerState.underlineProgress = progress
        }
        if progress >= 1.0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                withAnimation(AppMotion.contentFade) {
                    readerState.underlineProgress = nil
                }
                readerState.hasCompletedInitialMarking = true
            }
        }
    }

    func showReaderSettingsPanel() {
        withAnimation(AppMotion.panelState) {
            chromeState.overlay = .settings
            chromeState.header = .compact
        }
    }

    func expandHeader() {
        withAnimation(AppMotion.headerState) {
            chromeState.header = .expanded
        }
    }

    func collapseHeader() {
        withAnimation(AppMotion.headerState) {
            chromeState.header = .compact
        }
    }

    func closeOverlay(_ overlay: ReaderChromeOverlay) {
        guard chromeState.overlay == overlay else { return }
        chromeState.overlay = .none
    }

    func handleWordDeselected() {
        if chromeState.overlay == .translation {
            withAnimation(AppMotion.panelState) {
                handler.dismiss()
                closeOverlay(.translation)
            }
        } else if chromeState.overlay == .settings {
            withAnimation(AppMotion.panelState) {
                closeOverlay(.settings)
            }
            handler.clearHighlightTrigger = UUID()
        } else {
            handler.clearHighlightTrigger = UUID()
        }
    }

    func canUseProReaderFeature() -> Bool {
        return true
    }
}
#endif
