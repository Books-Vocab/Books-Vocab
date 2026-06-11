#if os(iOS)
import Foundation
import UIKit
import ReadiumNavigator
import os

extension ReadiumNavigatorView.Coordinator {
    @objc func handleBlockerTap(_ gesture: UITapGestureRecognizer) {
        AppLog.reader.debug("Blocker tapped, clearing selection...")
        Task { @MainActor in
            self.parent.onWordDeselected()
        }
    }

    func markVocabWords(_ words: [String]) {
        guard !words.isEmpty else { return }

        Task {
            await GlobalDebouncer.shared.debounce(key: "markVocabWords", duration: ReaderMetrics.markVocabDebounceDuration) { [weak self] in
                guard let self else { return }
                await MainActor.run { self.emitMarkVocabWordsJS(words) }
            }
        }
    }

    @MainActor
    private func emitMarkVocabWordsJS(_ words: [String]) {
        guard let navigator = self.navigator else { return }

        let escaped = words.map { Self.jsEscaped($0) }
        let wordsJSON = escaped.map { "\"\($0)\"" }.joined(separator: ",")
        let js = "if(window.__markVocabWords) window.__markVocabWords([\(wordsJSON)]);"

        Task { ReaderJSEval.log(await navigator.evaluateJavaScript(js), "markVocabWords") }
        PerfLog.reader.mark("markVocabWords", "\(words.count)")
        AppLog.reader.debug("Marked \(words.count) vocab words")
    }

    private func invokeSingleWordBridge(_ word: String, jsFunction: String, label: StaticString, logMessage: String) {
        guard let navigator else { return }
        let escaped = Self.jsEscaped(word)
        let js = "if(window.\(jsFunction)) window.\(jsFunction)(\"\(escaped)\");"
        Task { @MainActor in
            ReaderJSEval.log(await navigator.evaluateJavaScript(js), label)
            AppLog.reader.debug("\(logMessage)")
        }
    }

    func markNewVocabWord(_ word: String) {
        invokeSingleWordBridge(word, jsFunction: "__markVocabWord", label: "markNewVocabWord", logMessage: "Marked new vocab: \(word)")
    }

    func clearAllVocabHighlights() {
        guard let navigator else { return }
        let js = """
        document.querySelectorAll('.vocab-word').forEach(function(el) {
            el.classList.remove('vocab-word', 'active-word');
            var parent = el.parentNode;
            if (parent) {
                while (el.firstChild) parent.insertBefore(el.firstChild, el);
                parent.removeChild(el);
                parent.normalize();
            }
        });
        """
        Task { @MainActor in
            ReaderJSEval.log(await navigator.evaluateJavaScript(js), "clearAllVocabHighlights")
            AppLog.reader.debug("Cleared all vocab highlights")
        }
    }

    func removeVocabWord(_ word: String) {
        invokeSingleWordBridge(word, jsFunction: "__removeVocabWord", label: "removeVocabWord", logMessage: "Removed vocab underline: \(word)")
    }

    func clearActiveHighlight() {
        guard let navigator else { return }
        let js = """
        document.querySelectorAll('.active-word').forEach(function(el) {
            if (el.classList.contains('vocab-word')) {
                el.classList.remove('active-word');
                return;
            }
            var parent = el.parentNode;
            while (el.firstChild) parent.insertBefore(el.firstChild, el);
            parent.removeChild(el);
            parent.normalize();
        });
        """
        Task { @MainActor in
            ReaderJSEval.log(await navigator.evaluateJavaScript(js), "clearActiveHighlight")
            navigator.clearSelection()
        }
    }

    /// Cached font-face CSS — fonts are bundled resources that never change at runtime,
    /// so we build the ~6 MB base64 CSS string once and reuse it across all page turns.
    private static let _fontFaceCSS: String = {
        let fontDefs: [(file: String, family: String, weight: String, style: String)] = [
            ("CormorantGaramond-Regular", "Cormorant Garamond", "normal", "normal"),
            ("CormorantGaramond-Bold", "Cormorant Garamond", "bold", "normal"),
            ("CormorantGaramond-Italic", "Cormorant Garamond", "normal", "italic"),
            ("CormorantGaramond-BoldItalic", "Cormorant Garamond", "bold", "italic"),
            ("CrimsonPro-Regular", "Crimson Pro", "normal", "normal"),
            ("CrimsonPro-Bold", "Crimson Pro", "bold", "normal"),
            ("CrimsonPro-Italic", "Crimson Pro", "normal", "italic"),
            ("CrimsonPro-BoldItalic", "Crimson Pro", "bold", "italic"),
            ("ElmsSans-Regular", "Elms Sans", "normal", "normal"),
            ("ElmsSans-Bold", "Elms Sans", "bold", "normal"),
            ("ElmsSans-Italic", "Elms Sans", "normal", "italic"),
            ("ElmsSans-BoldItalic", "Elms Sans", "bold", "italic"),
            ("SpaceMono-Regular", "Space Mono", "normal", "normal"),
            ("SpaceMono-Bold", "Space Mono", "bold", "normal"),
            ("SpaceMono-Italic", "Space Mono", "normal", "italic"),
            ("SpaceMono-BoldItalic", "Space Mono", "bold", "italic"),
        ]

        var css = ""
        for def in fontDefs {
            guard let url = Bundle.main.url(forResource: def.file, withExtension: "ttf"),
                  let data = try? Data(contentsOf: url) else {
                AppLog.reader.warning("Font not found in bundle: \(def.file).ttf")
                continue
            }
            let b64 = data.base64EncodedString()
            css += """
            @font-face {
                font-family: '\(def.family)';
                font-weight: \(def.weight);
                font-style: \(def.style);
                src: url('data:font/truetype;base64,\(b64)') format('truetype');
            }

            """
        }
        return css
    }()

    static func buildFontFaceCSS() -> String {
        _fontFaceCSS
    }

    /// Escapes a string for safe embedding inside a double-quoted JS string literal:
    /// backslashes first, then double quotes.
    private static func jsEscaped(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
#endif
