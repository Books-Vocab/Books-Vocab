//
//  ReadiumNavigatorView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import WebKit
import WebKit
import ReadiumShared
import ReadiumStreamer
import ReadiumNavigator

// MARK: - Global Debouncer

/// A utility to globally debounce high-frequency operations, preventing duplicate calls across instances.
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

// MARK: - Host ViewController（在 responder chain 中，處理自訂選單）

class NavigatorHostViewController: UIViewController {
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

        print("🔍 AI Search: \(highlight)")

        // 用 JS 把當前選取範圍包裹成黃色高亮
        Task { @MainActor in
            let js = """
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
            _ = await navigator.evaluateJavaScript(js)
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

        print("💬 AI Explain: \(highlight)")

        Task { @MainActor in
            let js = """
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
            _ = await navigator.evaluateJavaScript(js)
            navigator.clearSelection()
        }

        onExplainSelected?(highlight, context)
    }
}

// MARK: - Helpers

/// 把 Locator.Text 組成帶 **highlight** 標記的 context 字串
private func buildMarkedContext(_ text: Locator.Text) -> String {
    let before = text.before ?? ""
    let highlight = text.highlight ?? ""
    let after = text.after ?? ""
    return before + "**\(highlight)**" + after
}

// MARK: - 生字過濾（片語直接通過，單字才做 bookUniqueWords 交集）

private func filterValidWords(_ words: some Collection<String>, bookWords: Set<String>?) -> [String] {
    guard let bookWords else { return Array(words) }
    return words.filter { $0.contains(" ") || bookWords.contains($0) }
}

// MARK: - SwiftUI Representable

struct ReadiumNavigatorView: UIViewControllerRepresentable {
    let publication: Publication
    let initialLocator: Locator?
    let httpServer: HTTPServer
    let lookedUpWords: [String]
    let bookUniqueWords: Set<String>?
    let preferences: EPUBPreferences
    let clearHighlightTrigger: UUID
    let removeWordTrigger: (word: String, id: UUID)?
    let navigateToLocator: (locator: Locator, id: UUID)?
    /// 當翻譯面板或其他覆蓋層開啟時設為 true，阻擋 WebView 接收觸控事件
    let isInteractionBlocked: Bool
    let onLocationChanged: (Locator) -> Void
    let onWordSelected: (String, String) -> Void
    let onPhraseSelected: (String, String) -> Void
    let onExplainSelected: (String, String) -> Void
    let onWordDeselected: () -> Void
    var onMarkingProgress: ((Double) -> Void)?

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIViewController(context: Context) -> NavigatorHostViewController {
        let host = NavigatorHostViewController()
        host.onWordSelected = onWordSelected
        host.onPhraseSelected = onPhraseSelected
        host.onExplainSelected = onExplainSelected

        let navigator: EPUBNavigatorViewController
        do {
            let aiSearchAction = EditingAction(
                title: "翻譯",
                action: #selector(NavigatorHostViewController.aiSearch)
            )
                let aiExplainAction = EditingAction(
                    title: "解釋",
                    action: #selector(NavigatorHostViewController.aiExplain)
                )

            navigator = try EPUBNavigatorViewController(
                publication: publication,
                initialLocation: initialLocator,
                config: .init(
                    preferences: preferences,
                    defaults: EPUBDefaults(
                        scroll: false
                    ),
                    editingActions: [aiSearchAction, aiExplainAction, .copy, .lookup]
                ),
                httpServer: httpServer
            )
        } catch {
            fatalError("Failed to create EPUBNavigatorViewController: \(error)")
        }

        navigator.delegate = context.coordinator
        context.coordinator.navigator = navigator
        host.epubNavigator = navigator

        host.addChild(navigator)
        navigator.view.frame = host.view.bounds
        navigator.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        host.view.addSubview(navigator.view)
        navigator.didMove(toParent: host)

        // 透明觸控攔截層：當翻譯面板開啟時覆蓋整個 WebView，阻止 click 穿透
        let blocker = UIView(frame: host.view.bounds)
        blocker.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        blocker.backgroundColor = .clear
        blocker.isUserInteractionEnabled = false // 預設關閉
        blocker.tag = 9001
        
        let tap = UITapGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.handleBlockerTap(_:)))
        blocker.addGestureRecognizer(tap)
        
        host.view.addSubview(blocker)

        return host
    }

    func updateUIViewController(_ uiViewController: NavigatorHostViewController, context: Context) {
        // 同步最新的 SwiftUI View 給 Coordinator，避免舊的 state capture 導致閉包操作拿不到最新的 bookUniqueWords
        context.coordinator.parent = self

        // 同步觸控攔截層狀態
        if let blocker = uiViewController.view.viewWithTag(9001) {
            blocker.isUserInteractionEnabled = isInteractionBlocked
        }

        // 清除 highlight 觸發
        if context.coordinator.lastClearHighlightTrigger != clearHighlightTrigger {
            context.coordinator.lastClearHighlightTrigger = clearHighlightTrigger
            context.coordinator.clearActiveHighlight()
        }

        // 偵測生字庫新增 → 即時標記新字的底線
        let oldCount = context.coordinator.lastVocabCount
        let newCount = lookedUpWords.count
        
        // 如果 bookUniqueWords 剛載入完成，觸發全量標記
        let didLoadBookWords = (bookUniqueWords != nil && context.coordinator.lastBookUniqueWordsCount == nil)
        
        if newCount < oldCount {
            let newSet = Set(lookedUpWords)
            let removedWords = context.coordinator.lastVocabWordsSet.subtracting(newSet)
            if newCount == 0 || removedWords.count > 10 {
                // 大量移除（如登出）→ 全清更有效率
                context.coordinator.clearAllVocabHighlights()
                if newCount > 0 {
                    let validWords = filterValidWords(newSet, bookWords: bookUniqueWords)
                    if !validWords.isEmpty {
                        context.coordinator.markVocabWords(validWords)
                    }
                }
            } else {
                // 少量移除（例如刪除單字）→ 精準逐字移除，避免全清閃爍
                for word in removedWords {
                    context.coordinator.removeVocabWord(word)
                }
            }
        } else if newCount > oldCount || didLoadBookWords {
            if didLoadBookWords {
                context.coordinator.lastBookUniqueWordsCount = bookUniqueWords?.count ?? 0
                
                // 進行交集過濾
                let validWords = filterValidWords(lookedUpWords, bookWords: bookUniqueWords)
                print("📊 生字預過濾：全域 \(lookedUpWords.count) 字 -> 本書 \(validWords.count) 字 (\(String(format: "%.1f", (1.0 - Double(validWords.count)/Double(max(1, lookedUpWords.count))) * 100))% 縮減)")
                
                context.coordinator.markVocabWords(validWords)
            } else {
                // 用 Set Diff 找出真正新增的字，避免 loadLookedUpWords 重排後 suffix() 取到錯誤的字
                let addedWords = lookedUpWords.filter { !context.coordinator.lastVocabWordsSet.contains($0) }
                if addedWords.count == 1 {
                    context.coordinator.markNewVocabWord(addedWords[0])
                } else if !addedWords.isEmpty {
                    let validNew = filterValidWords(addedWords, bookWords: bookUniqueWords)
                    if !validNew.isEmpty { context.coordinator.markVocabWords(validNew) }
                }
            }
        }
        context.coordinator.lastVocabCount = newCount
        context.coordinator.lastVocabWordsSet = Set(lookedUpWords)

        // 移除生字觸發
        if let trigger = removeWordTrigger,
           context.coordinator.lastRemoveWordId != trigger.id {
            context.coordinator.lastRemoveWordId = trigger.id
            context.coordinator.removeVocabWord(trigger.word)
        }

        // 導航觸發
        if let nav = navigateToLocator,
           context.coordinator.lastNavigateId != nav.id {
            context.coordinator.lastNavigateId = nav.id
            Task { @MainActor in
                print("🧭 Attempting navigation to: \(nav.locator.href)")
                let success = await context.coordinator.navigator?.go(to: nav.locator)
                print("🧭 Navigation result: \(String(describing: success))")
            }
        }

        // 偵測閱讀設定變化
        let oldPrefs = context.coordinator.lastPreferences
        let newPrefs = preferences
        if oldPrefs != newPrefs {
            context.coordinator.lastPreferences = newPrefs
            context.coordinator.isApplyingPreferences = true
            Task { @MainActor in
                uiViewController.epubNavigator?.submitPreferences(newPrefs)
                try? await Task.sleep(for: .milliseconds(800))
                context.coordinator.isApplyingPreferences = false
            }
        }
        
        // 偵測底線透明度變化
        let currentOpacity = ReaderSettings.shared.underlineOpacity
        if let lastOpacity = context.coordinator.lastUnderlineOpacity, currentOpacity != lastOpacity {
            context.coordinator.lastUnderlineOpacity = currentOpacity
            let js = "document.documentElement.style.setProperty('--vocab-opacity', '\(currentOpacity)');"
            Task { @MainActor in
                _ = await context.coordinator.navigator?.evaluateJavaScript(js)
            }
        } else if context.coordinator.lastUnderlineOpacity == nil {
            context.coordinator.lastUnderlineOpacity = currentOpacity
        }
        
        // 偵測除錯按鈕變化：即時標記/移除所有單字 token
        let currentDebug = ReaderSettings.shared.showHitTestingDebug
        if let lastDebug = context.coordinator.lastHitTestingDebug, currentDebug != lastDebug {
            context.coordinator.lastHitTestingDebug = currentDebug
            let js = "if(window.__toggleDebugBoxes) window.__toggleDebugBoxes(\(currentDebug ? "true" : "false"));"
            Task { @MainActor in
                _ = await context.coordinator.navigator?.evaluateJavaScript(js)
            }
        } else if context.coordinator.lastHitTestingDebug == nil {
            context.coordinator.lastHitTestingDebug = currentDebug
        }
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, EPUBNavigatorDelegate {
        var parent: ReadiumNavigatorView
        weak var navigator: EPUBNavigatorViewController?
        var lastClearHighlightTrigger: UUID?
        var lastRemoveWordId: UUID?
        var lastNavigateId: UUID?
        var lastVocabCount: Int = 0
        var lastVocabWordsSet: Set<String> = []
        var lastBookUniqueWordsCount: Int?
        var lastPreferences: EPUBPreferences?
        var isApplyingPreferences = false
        var lastUnderlineOpacity: Double?
        var lastHitTestingDebug: Bool?

        // 選取期間鎖定翻頁
        private var selectionPageAnchor: CGPoint?
        private var contentOffsetObserver: NSKeyValueObservation?

        init(parent: ReadiumNavigatorView) {
            self.parent = parent
        }

        func findWebView(in view: UIView?) -> WKWebView? {
            guard let view = view else { return nil }
            if let webView = view as? WKWebView { return webView }
            for subview in view.subviews {
                if let found = findWebView(in: subview) { return found }
            }
            return nil
        }

        // MARK: Blocker Gesture
        @objc func handleBlockerTap(_ gesture: UITapGestureRecognizer) {
            print("👋 Blocker tapped, clearing selection...")
            DispatchQueue.main.async {
                self.parent.onWordDeselected()
            }
        }

        // MARK: NavigatorDelegate

        func navigator(_ navigator: any Navigator, locationDidChange locator: Locator) {
            parent.onLocationChanged(locator)

            // 翻頁後重新標記所有生字庫底線（設定調整期間跳過，避免卡頓）
            let words = parent.lookedUpWords
            if !words.isEmpty && !isApplyingPreferences {
                let validWords = filterValidWords(words, bookWords: parent.bookUniqueWords)
                self.markVocabWords(validWords)
            }
        }

        func navigator(_ navigator: any Navigator, presentError error: NavigatorError) {
            print("❌ Navigator error: \(error)")
        }

        // MARK: VisualNavigatorDelegate
        // 注意：不在 didTapAt 呼叫 handleTap，因為注入的 JS click listener 已處理
        // 若在此也呼叫 handleTap 會和 JS toggle 邏輯衝突

        func navigator(_ navigator: any VisualNavigator, didTapAt point: CGPoint) {
            // 由注入的 JS click listener 處理，此處不做額外操作
        }

        // MARK: SelectableNavigatorDelegate

        func navigator(_ navigator: any SelectableNavigator, canPerformAction action: EditingAction, for selection: Selection) -> Bool {
            return true
        }

        func navigator(_ navigator: any SelectableNavigator, shouldShowMenuForSelection selection: Selection) -> Bool {
            return true
        }

        // MARK: EPUBNavigatorDelegate — JS 注入

        func navigator(_ navigator: EPUBNavigatorViewController, setupUserScripts userContentController: WKUserContentController) {
            userContentController.add(self, name: "wordTap")
            userContentController.add(self, name: "wordDeselect")
            userContentController.add(self, name: "selectionState")
            userContentController.add(self, name: "markingProgress")

            // ── 自訂字體：從 App Bundle 讀取 TTF → base64 → @font-face ──
            let fontFaceCSS = Self.buildFontFaceCSS()

            // ★ 傳遞除錯模式開關
            let isDebugMode = ReaderSettings.shared.showHitTestingDebug ? "true" : "false"

            let js = ReadiumNavigatorJS.buildInjectionScript(
                fontFaceCSS: fontFaceCSS,
                underlineOpacity: ReaderSettings.shared.underlineOpacity,
                isDebugMode: isDebugMode
            )

            let script = WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
            userContentController.addUserScript(script)
            print("📝 User scripts injected (三種狀態)")

            // Scripts 注入後重新標記所有生字（修復初始載入的 race condition）
            let words = parent.lookedUpWords
            if !words.isEmpty {
                let validWords = filterValidWords(words, bookWords: parent.bookUniqueWords)
                self.markVocabWords(validWords)
            }
        }

        // MARK: 生字庫底線

        func markVocabWords(_ words: [String]) {
            guard !words.isEmpty else { return }
            
            Task {
                await GlobalDebouncer.shared.debounce(key: "markVocabWords", duration: 0.8) { [weak self] in
                    guard let self = self else { return }
                    await MainActor.run {
                        guard let navigator = self.navigator else { return }
                        
                        let escaped = words.map { $0.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") }
                        let wordsJSON = escaped.map { "\"\($0)\"" }.joined(separator: ",")
                        let js = "if(window.__markVocabWords) window.__markVocabWords([\(wordsJSON)]);"
                        
                        Task { _ = await navigator.evaluateJavaScript(js) }
                        print("📘 Marked \(words.count) vocab words")
                    }
                }
            }
        }

        func markNewVocabWord(_ word: String) {
            guard let navigator = navigator else { return }
            let escaped = word.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
            let js = "if(window.__markVocabWord) window.__markVocabWord(\"\(escaped)\");"
            Task { @MainActor in
                _ = await navigator.evaluateJavaScript(js)
                print("📘 Marked new vocab: \(word)")
            }
        }

        func clearAllVocabHighlights() {
            guard let navigator = navigator else { return }
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
                print("🧹 Cleared all vocab highlights")
            }
        }

        func removeVocabWord(_ word: String) {
            guard let navigator = navigator else { return }
            let escaped = word.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
            let js = "if(window.__removeVocabWord) window.__removeVocabWord(\"\(escaped)\");"
            Task { @MainActor in
                _ = await navigator.evaluateJavaScript(js)
                print("🗑️ Removed vocab underline: \(word)")
            }
        }

        // MARK: 清除選中高亮（保留底線）

        func clearActiveHighlight() {
            guard let navigator = navigator else { return }
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

        // MARK: 自訂字體 @font-face 生成

        /// Reads bundled TTF files from Bundle.main and generates CSS @font-face declarations.
        /// This is needed because WKWebView cannot access UIKit-registered fonts directly.
        static func buildFontFaceCSS() -> String {
            let fontDefs: [(file: String, family: String, weight: String, style: String)] = [
                ("CormorantGaramond-Regular",    "Cormorant Garamond", "normal", "normal"),
                ("CormorantGaramond-Bold",       "Cormorant Garamond", "bold",   "normal"),
                ("CormorantGaramond-Italic",     "Cormorant Garamond", "normal", "italic"),
                ("CormorantGaramond-BoldItalic", "Cormorant Garamond", "bold",   "italic"),
                ("ElmsSans-Regular",             "Elms Sans",          "normal", "normal"),
                ("ElmsSans-Bold",                "Elms Sans",          "bold",   "normal"),
                ("ElmsSans-Italic",              "Elms Sans",          "normal", "italic"),
                ("ElmsSans-BoldItalic",          "Elms Sans",          "bold",   "italic"),
                ("SpaceMono-Regular",            "Space Mono",         "normal", "normal"),
                ("SpaceMono-Bold",               "Space Mono",         "bold",   "normal"),
                ("SpaceMono-Italic",             "Space Mono",         "normal", "italic"),
                ("SpaceMono-BoldItalic",         "Space Mono",         "bold",   "italic"),
            ]

            var css = ""
            for def in fontDefs {
                guard let url = Bundle.main.url(forResource: def.file, withExtension: "ttf"),
                      let data = try? Data(contentsOf: url) else {
                    print("⚠️ Font not found in bundle: \(def.file).ttf")
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
        }
    }
}

// MARK: - WKScriptMessageHandler

extension ReadiumNavigatorView.Coordinator: WKScriptMessageHandler {
    nonisolated func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        Task { @MainActor in
            if message.name == "selectionState" {
                if let isActive = message.body as? String {
                    if let webView = self.findWebView(in: self.navigator?.view) {
                        let scrollView = webView.scrollView
                        if isActive == "active" {
                            // 記錄當前頁面 anchor（snap 到最近整頁）
                            let pageWidth = scrollView.bounds.width
                            let anchorX: CGFloat
                            if pageWidth > 0 {
                                let page = (scrollView.contentOffset.x / pageWidth).rounded()
                                anchorX = page * pageWidth
                            } else {
                                anchorX = scrollView.contentOffset.x
                            }
                            self.selectionPageAnchor = CGPoint(x: anchorX, y: scrollView.contentOffset.y)
                            // KVO 監聽 contentOffset，一旦偏移立即拉回
                            self.contentOffsetObserver = scrollView.observe(\.contentOffset, options: [.new]) { [weak self] sv, _ in
                                guard let anchor = self?.selectionPageAnchor else { return }
                                if abs(sv.contentOffset.x - anchor.x) > 1 {
                                    sv.contentOffset = anchor
                                }
                            }
                        } else {
                            // 結束選取：停止 KVO，snap 回最近整頁
                            self.contentOffsetObserver = nil
                            self.selectionPageAnchor = nil
                            let pageWidth = scrollView.bounds.width
                            if pageWidth > 0 {
                                let page = (scrollView.contentOffset.x / pageWidth).rounded()
                                let snapX = page * pageWidth
                                if abs(scrollView.contentOffset.x - snapX) > 1 {
                                    scrollView.setContentOffset(CGPoint(x: snapX, y: scrollView.contentOffset.y), animated: true)
                                }
                            }
                        }
                        print("📜 Selection state: \\(isActive)")
                    }
                }
                return
            }

            if message.name == "markingProgress" {
                if let body = message.body as? String,
                   let data = body.data(using: .utf8),
                   let json = try? JSONSerialization.jsonObject(with: data) as? [String: Int],
                   let done = json["done"], let total = json["total"], total > 0 {
                    let progress = Double(done) / Double(total)
                    self.parent.onMarkingProgress?(progress)
                }
                return
            }

            if message.name == "wordDeselect" {
                print("👋 Word deselected (toggle off)")
                self.parent.onWordDeselected()
                return
            }

            guard message.name == "wordTap" else { return }
            guard let body = message.body as? String,
                  let data = body.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
                  let word = json["word"],
                  let context = json["context"] else { return }

            print("📝 Word from JS: \(word)")
            self.parent.onWordSelected(word, context)
        }
    }
}
