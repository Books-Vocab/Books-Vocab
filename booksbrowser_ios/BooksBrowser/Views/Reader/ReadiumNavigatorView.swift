//
//  ReadiumNavigatorView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import WebKit
import ReadiumShared
import ReadiumStreamer
import ReadiumNavigator

// MARK: - SwiftUI Representable

struct ReadiumNavigatorView: UIViewControllerRepresentable {
    let publication: Publication
    let initialLocator: Locator?
    let httpServer: HTTPServer
    let lookedUpWords: [String]
    let bookUniqueWords: Set<String>?
    let viewConfiguration: ReaderViewConfiguration
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
                    preferences: viewConfiguration.epubPreferences,
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
        let newPrefs = viewConfiguration.epubPreferences
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
        let currentOpacity = viewConfiguration.underlineOpacity
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
        let currentDebug = viewConfiguration.showHitTestingDebug
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
        var selectionPageAnchor: CGPoint?
        var contentOffsetObserver: NSKeyValueObservation?

        init(parent: ReadiumNavigatorView) {
            self.parent = parent
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
            let isDebugMode = parent.viewConfiguration.showHitTestingDebug ? "true" : "false"

            let js = ReadiumNavigatorJS.buildInjectionScript(
                fontFaceCSS: fontFaceCSS,
                underlineOpacity: parent.viewConfiguration.underlineOpacity,
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
    }
}
