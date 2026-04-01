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
            await GlobalDebouncer.shared.debounce(key: "markVocabWords", duration: 0.8) { [weak self] in
                guard let self else { return }
                await MainActor.run {
                    guard let navigator = self.navigator else { return }

                    let escaped = words.map {
                        $0.replacingOccurrences(of: "\\", with: "\\\\")
                            .replacingOccurrences(of: "\"", with: "\\\"")
                    }
                    let wordsJSON = escaped.map { "\"\($0)\"" }.joined(separator: ",")
                    let js = "if(window.__markVocabWords) window.__markVocabWords([\(wordsJSON)]);"

                    Task { _ = await navigator.evaluateJavaScript(js) }
                    AppLog.reader.debug("Marked \(words.count) vocab words")
                }
            }
        }
    }

    func markNewVocabWord(_ word: String) {
        guard let navigator else { return }
        let escaped = word.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let js = "if(window.__markVocabWord) window.__markVocabWord(\"\(escaped)\");"
        Task { @MainActor in
            _ = await navigator.evaluateJavaScript(js)
            AppLog.reader.debug("Marked new vocab: \(word)")
        }
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
            _ = await navigator.evaluateJavaScript(js)
            AppLog.reader.debug("Cleared all vocab highlights")
        }
    }

    func removeVocabWord(_ word: String) {
        guard let navigator else { return }
        let escaped = word.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
        let js = "if(window.__removeVocabWord) window.__removeVocabWord(\"\(escaped)\");"
        Task { @MainActor in
            _ = await navigator.evaluateJavaScript(js)
            AppLog.reader.debug("Removed vocab underline: \(word)")
        }
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
            _ = await navigator.evaluateJavaScript(js)
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
}
#endif
