#if os(iOS)
import SwiftUI
import ReadiumShared

extension ReaderView {
    func handleLocationChange(_ locator: Locator) {
        if !readerState.isWebViewReady {
            withAnimation(AppMotion.contentFade) { readerState.isWebViewReady = true }
        }
        currentLocator = locator
        totalProgression = locator.locations.totalProgression ?? 0

        // 序列化失敗時**不覆寫**既有值（避免舊 `"{}"` 污染下次還原），整筆 persist
        // 一併跳過，保留上次有效的 locator/progression 快照不致 JSON 與進度錯配。
        guard let json = ReaderProgressSaver.encodedLocatorJSON(locator) else { return }
        let progression = totalProgression

        // in-memory 寫入立即（panel 即時讀取），落盤經 debounce coalesce —— 對齊 PDF
        // 路徑的顯式 save，但避開每頁同步 I/O 卡頓。
        progressSaver.recordChange {
            book.lastReadLocatorJSON = json
            book.dateLastRead = Date()
            book.progression = progression
        } save: { [modelContext] in
            modelContext.safeSave()
        }
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
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: UInt64(0.4 * 1_000_000_000))
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
        // translation overlay 走 dismiss，自帶清除語意，不需另發清高亮信號；
        // 其餘情況（settings / 無 overlay）統一在分支前設一次 clearHighlightTrigger，
        // dedup 掉 <1% fast-tap race 下重複觸發。
        if chromeState.overlay == .translation {
            withAnimation(AppMotion.panelState) {
                handler.dismiss()
                closeOverlay(.translation)
            }
        } else {
            if chromeState.overlay == .settings {
                withAnimation(AppMotion.panelState) {
                    closeOverlay(.settings)
                }
            }
            handler.clearHighlightTrigger = UUID()
        }
    }

    func canUseProReaderFeature() -> Bool {
        return true
    }
}
#endif
