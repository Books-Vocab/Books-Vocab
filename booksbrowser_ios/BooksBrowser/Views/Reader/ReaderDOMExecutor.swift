import Foundation
import ReadiumNavigator

struct ReaderDOMExecutor {
    func execute(
        _ command: ReadiumNavigatorView.Coordinator.DOMCommand,
        navigator: EPUBNavigatorViewController?,
        clearActiveHighlight: @escaping () -> Void,
        clearAllVocabHighlights: @escaping () -> Void,
        markVocabWords: @escaping ([String]) -> Void,
        markNewVocabWord: @escaping (String) -> Void,
        removeVocabWord: @escaping (String) -> Void
    ) {
        switch command {
        case .clearActiveHighlight:
            clearActiveHighlight()
        case .clearAllVocabHighlights:
            clearAllVocabHighlights()
        case .markVocabWords(let words):
            markVocabWords(words)
        case .markNewVocabWord(let word):
            markNewVocabWord(word)
        case .removeVocabWord(let word):
            removeVocabWord(word)
        case .setUnderlineOpacity(let opacity):
            evaluateJavaScript(
                "document.documentElement.style.setProperty('--vocab-opacity', '\(opacity)');",
                navigator: navigator
            )
        case .setDebugMode(let isEnabled):
            evaluateJavaScript(
                "if(window.__toggleDebugBoxes) window.__toggleDebugBoxes(\(isEnabled ? "true" : "false"));",
                navigator: navigator
            )
        }
    }

    private func evaluateJavaScript(
        _ script: String,
        navigator: EPUBNavigatorViewController?
    ) {
        Task { @MainActor in
            _ = await navigator?.evaluateJavaScript(script)
        }
    }
}
