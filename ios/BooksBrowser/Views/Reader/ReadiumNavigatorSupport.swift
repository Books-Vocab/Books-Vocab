#if os(iOS)
import Foundation
import UIKit
import ReadiumShared
import ReadiumNavigator
import os

/// Globally debounces high-frequency navigator operations across instances.
actor GlobalDebouncer {
    static let shared = GlobalDebouncer()

    private var tasks: [String: Task<Void, Never>] = [:]

    private init() {}

    func debounce(key: String, duration: TimeInterval, action: @escaping @Sendable () async -> Void) {
        tasks[key]?.cancel()
        tasks[key] = Task {
            try? await Task.sleep(for: .seconds(duration))
            guard !Task.isCancelled else { return }
            await action()
            tasks[key] = nil
        }
    }
}

final class NavigatorHostViewController: UIViewController {
    var onWordSelected: ((String, String) -> Void)?
    var onPhraseSelected: ((String, String) -> Void)?
    var onExplainSelected: ((String, String) -> Void)?
    weak var epubNavigator: EPUBNavigatorViewController?

    @objc func aiSearch() {
        guard let navigator = epubNavigator else { return }
        guard let selection = navigator.currentSelection else { return }

        let highlight = selection.locator.text.highlight ?? ""
        guard !highlight.isEmpty else { return }

        let context = buildMarkedContext(selection.locator.text)
        AppLog.reader.debug("AI Search: \(highlight)")

        Task { @MainActor in
            _ = await navigator.evaluateJavaScript(activeSelectionWrapScript)
            navigator.clearSelection()
        }

        onPhraseSelected?(highlight, context)
    }

    @objc func aiExplain() {
        guard let navigator = epubNavigator else { return }
        guard let selection = navigator.currentSelection else { return }

        let highlight = selection.locator.text.highlight ?? ""
        guard !highlight.isEmpty else { return }

        let context = buildMarkedContext(selection.locator.text)
        AppLog.reader.debug("AI Explain: \(highlight)")

        Task { @MainActor in
            _ = await navigator.evaluateJavaScript(activeSelectionWrapScript)
            navigator.clearSelection()
        }

        onExplainSelected?(highlight, context)
    }
}

func buildMarkedContext(_ text: Locator.Text) -> String {
    let before = text.before ?? ""
    let highlight = text.highlight ?? ""
    let after = text.after ?? ""
    return before + "**\(highlight)**" + after
}

func filterValidWords(_ words: some Collection<String>, bookWords: Set<String>?) -> [String] {
    guard let bookWords else { return Array(words) }
    return words.filter { $0.contains(" ") || bookWords.contains($0) }
}

private let activeSelectionWrapScript = """
(function() {
    document.querySelectorAll('.active-word').forEach(function(el) {
        var parent = el.parentNode;
        while (el.firstChild) parent.insertBefore(el.firstChild, el);
        parent.removeChild(el);
        parent.normalize();
    });
    var sel = window.getSelection();
    if (sel.rangeCount > 0) {
        try {
            var range = sel.getRangeAt(0);
            var span = document.createElement('span');
            span.className = 'active-word';
            range.surroundContents(span);
        } catch(e) {}
    }
})();
"""
#endif
