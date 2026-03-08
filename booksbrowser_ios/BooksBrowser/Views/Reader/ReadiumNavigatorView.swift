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

    struct BridgeSnapshot {
        let lookedUpWords: [String]
        let bookUniqueWords: Set<String>?
        let viewConfiguration: ReaderViewConfiguration
        let clearHighlightTrigger: UUID
        let removeWordTrigger: (word: String, id: UUID)?
        let navigateToLocator: (locator: Locator, id: UUID)?
        let isInteractionBlocked: Bool
    }

    var bridgeSnapshot: BridgeSnapshot {
        .init(
            lookedUpWords: lookedUpWords,
            bookUniqueWords: bookUniqueWords,
            viewConfiguration: viewConfiguration,
            clearHighlightTrigger: clearHighlightTrigger,
            removeWordTrigger: removeWordTrigger,
            navigateToLocator: navigateToLocator,
            isInteractionBlocked: isInteractionBlocked
        )
    }

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
        context.coordinator.sync(with: bridgeSnapshot, in: uiViewController)
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

        func sync(
            with snapshot: ReadiumNavigatorView.BridgeSnapshot,
            in host: NavigatorHostViewController
        ) {
            syncInteractionBlocker(in: host, isBlocked: snapshot.isInteractionBlocked)
            syncClearHighlight(trigger: snapshot.clearHighlightTrigger)
            syncVocabularyHighlights(
                lookedUpWords: snapshot.lookedUpWords,
                bookUniqueWords: snapshot.bookUniqueWords
            )
            syncRemovedWord(trigger: snapshot.removeWordTrigger)
            syncNavigation(trigger: snapshot.navigateToLocator)
            syncPreferences(snapshot.viewConfiguration.epubPreferences, in: host)
            syncUnderlineOpacity(snapshot.viewConfiguration.underlineOpacity)
            syncDebugMode(snapshot.viewConfiguration.showHitTestingDebug)
        }

        private func syncInteractionBlocker(in host: NavigatorHostViewController, isBlocked: Bool) {
            if let blocker = host.view.viewWithTag(9001) {
                blocker.isUserInteractionEnabled = isBlocked
            }
        }

        private func syncClearHighlight(trigger: UUID) {
            guard lastClearHighlightTrigger != trigger else { return }
            lastClearHighlightTrigger = trigger
            clearActiveHighlight()
        }

        private func syncVocabularyHighlights(
            lookedUpWords: [String],
            bookUniqueWords: Set<String>?
        ) {
            let previousCount = lastVocabCount
            let currentCount = lookedUpWords.count
            let currentSet = Set(lookedUpWords)
            let didLoadBookWords = (bookUniqueWords != nil && lastBookUniqueWordsCount == nil)

            if currentCount < previousCount {
                let removedWords = lastVocabWordsSet.subtracting(currentSet)
                handleRemovedVocabulary(
                    newCount: currentCount,
                    removedWords: removedWords,
                    remainingWords: currentSet,
                    bookUniqueWords: bookUniqueWords
                )
            } else if currentCount > previousCount || didLoadBookWords {
                handleAddedVocabulary(
                    lookedUpWords: lookedUpWords,
                    didLoadBookWords: didLoadBookWords,
                    bookUniqueWords: bookUniqueWords
                )
            }

            lastVocabCount = currentCount
            lastVocabWordsSet = currentSet
        }

        private func handleRemovedVocabulary(
            newCount: Int,
            removedWords: Set<String>,
            remainingWords: Set<String>,
            bookUniqueWords: Set<String>?
        ) {
            if newCount == 0 || removedWords.count > 10 {
                clearAllVocabHighlights()
                if newCount > 0 {
                    let validWords = filterValidWords(remainingWords, bookWords: bookUniqueWords)
                    if !validWords.isEmpty {
                        markVocabWords(validWords)
                    }
                }
                return
            }

            for word in removedWords {
                removeVocabWord(word)
            }
        }

        private func handleAddedVocabulary(
            lookedUpWords: [String],
            didLoadBookWords: Bool,
            bookUniqueWords: Set<String>?
        ) {
            if didLoadBookWords {
                lastBookUniqueWordsCount = bookUniqueWords?.count ?? 0
                let validWords = filterValidWords(lookedUpWords, bookWords: bookUniqueWords)
                print("📊 生字預過濾：全域 \(lookedUpWords.count) 字 -> 本書 \(validWords.count) 字 (\(String(format: "%.1f", (1.0 - Double(validWords.count)/Double(max(1, lookedUpWords.count))) * 100))% 縮減)")
                markVocabWords(validWords)
                return
            }

            let addedWords = lookedUpWords.filter { !lastVocabWordsSet.contains($0) }
            if addedWords.count == 1 {
                markNewVocabWord(addedWords[0])
            } else if !addedWords.isEmpty {
                let validNew = filterValidWords(addedWords, bookWords: bookUniqueWords)
                if !validNew.isEmpty {
                    markVocabWords(validNew)
                }
            }
        }

        private func syncRemovedWord(trigger: (word: String, id: UUID)?) {
            guard let trigger, lastRemoveWordId != trigger.id else { return }
            lastRemoveWordId = trigger.id
            removeVocabWord(trigger.word)
        }

        private func syncNavigation(trigger: (locator: Locator, id: UUID)?) {
            guard let trigger, lastNavigateId != trigger.id else { return }
            lastNavigateId = trigger.id
            Task { @MainActor in
                print("🧭 Attempting navigation to: \(trigger.locator.href)")
                let success = await navigator?.go(to: trigger.locator)
                print("🧭 Navigation result: \(String(describing: success))")
            }
        }

        private func syncPreferences(
            _ preferences: EPUBPreferences,
            in host: NavigatorHostViewController
        ) {
            guard lastPreferences != preferences else { return }
            lastPreferences = preferences
            isApplyingPreferences = true
            Task { @MainActor in
                host.epubNavigator?.submitPreferences(preferences)
                try? await Task.sleep(for: .milliseconds(800))
                self.isApplyingPreferences = false
            }
        }

        private func syncUnderlineOpacity(_ opacity: Double) {
            if let lastUnderlineOpacity, opacity != lastUnderlineOpacity {
                self.lastUnderlineOpacity = opacity
                let js = "document.documentElement.style.setProperty('--vocab-opacity', '\(opacity)');"
                Task { @MainActor in
                    _ = await navigator?.evaluateJavaScript(js)
                }
            } else if lastUnderlineOpacity == nil {
                lastUnderlineOpacity = opacity
            }
        }

        private func syncDebugMode(_ isEnabled: Bool) {
            if let lastHitTestingDebug, isEnabled != lastHitTestingDebug {
                self.lastHitTestingDebug = isEnabled
                let js = "if(window.__toggleDebugBoxes) window.__toggleDebugBoxes(\(isEnabled ? "true" : "false"));"
                Task { @MainActor in
                    _ = await navigator?.evaluateJavaScript(js)
                }
            } else if lastHitTestingDebug == nil {
                lastHitTestingDebug = isEnabled
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
