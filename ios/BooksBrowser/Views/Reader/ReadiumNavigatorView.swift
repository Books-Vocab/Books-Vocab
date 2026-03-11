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
                title: "翻譯".localized,
                action: #selector(NavigatorHostViewController.aiSearch)
            )
                let aiExplainAction = EditingAction(
                    title: "解釋".localized,
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

        // 將 UIKit 層背景設為紙色，避免 iOS 26 glass effect 取樣到
        // WKWebView 的原生深色背景（系統深色模式時 CSS 層與 UIKit 層不一致）
        let paperUIColor = UIColor(viewConfiguration.paperColor)
        host.view.backgroundColor = paperUIColor
        navigator.view.backgroundColor = paperUIColor

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

        // 同步 UIKit 層背景色（使用者切換閱讀主題時紙色會變）
        let paperUIColor = UIColor(viewConfiguration.paperColor)
        uiViewController.view.backgroundColor = paperUIColor
        uiViewController.epubNavigator?.view.backgroundColor = paperUIColor
    }

    // MARK: - Coordinator

    class Coordinator: NSObject, EPUBNavigatorDelegate {
        enum BridgeCommand {
            case host(HostCommand)
            case navigator(NavigatorCommand)
            case dom(DOMCommand)
        }

        enum HostCommand {
            case setInteractionBlocked(Bool)
        }

        enum NavigatorCommand {
            case navigate(Locator)
            case applyPreferences(EPUBPreferences)
        }

        enum DOMCommand {
            case clearActiveHighlight
            case clearAllVocabHighlights
            case markVocabWords([String])
            case markNewVocabWord(String)
            case removeVocabWord(String)
            case setContentStyle(String)
            case setUnderlineOpacity(Double)
            case setDebugMode(Bool)
        }

        struct BridgePlanner {
            var lastClearHighlightTrigger: UUID?
            var lastRemoveWordId: UUID?
            var lastNavigateId: UUID?
            var lastVocabCount: Int = 0
            var lastVocabWordsSet: Set<String> = []
            var lastBookUniqueWordsCount: Int?
            var lastPreferences: EPUBPreferences?
            var lastPanelMode: TranslationPanelMode?
            var lastUnderlineOpacity: Double?
            var lastHitTestingDebug: Bool?

            mutating func makeCommands(
                from snapshot: ReadiumNavigatorView.BridgeSnapshot
            ) -> [BridgeCommand] {
                var commands: [BridgeCommand] = []

                commands.append(.host(.setInteractionBlocked(snapshot.isInteractionBlocked)))
                commands.append(contentsOf: commandsForClearHighlight(trigger: snapshot.clearHighlightTrigger))
                commands.append(contentsOf: commandsForVocabularyHighlights(
                    lookedUpWords: snapshot.lookedUpWords,
                    bookUniqueWords: snapshot.bookUniqueWords
                ))
                commands.append(contentsOf: commandsForRemovedWord(trigger: snapshot.removeWordTrigger))
                commands.append(contentsOf: commandsForNavigation(trigger: snapshot.navigateToLocator))
                commands.append(contentsOf: commandsForPreferences(snapshot.viewConfiguration.epubPreferences))
                commands.append(contentsOf: commandsForContentStyle(snapshot.viewConfiguration.translationPanelMode))
                commands.append(contentsOf: commandsForUnderlineOpacity(snapshot.viewConfiguration.underlineOpacity))
                commands.append(contentsOf: commandsForDebugMode(snapshot.viewConfiguration.showHitTestingDebug))
                return commands
            }

            private mutating func commandsForClearHighlight(trigger: UUID) -> [BridgeCommand] {
                guard lastClearHighlightTrigger != trigger else { return [] }
                lastClearHighlightTrigger = trigger
                return [.dom(.clearActiveHighlight)]
            }

            private mutating func commandsForVocabularyHighlights(
                lookedUpWords: [String],
                bookUniqueWords: Set<String>?
            ) -> [BridgeCommand] {
                let previousCount = lastVocabCount
                let currentCount = lookedUpWords.count
                let currentSet = Set(lookedUpWords)
                let didLoadBookWords = (bookUniqueWords != nil && lastBookUniqueWordsCount == nil)
                var commands: [BridgeCommand] = []

                if currentCount < previousCount {
                    let removedWords = lastVocabWordsSet.subtracting(currentSet)
                    commands.append(contentsOf: commandsForRemovedVocabulary(
                        newCount: currentCount,
                        removedWords: removedWords,
                        remainingWords: currentSet,
                        bookUniqueWords: bookUniqueWords
                    ))
                } else if currentCount > previousCount || didLoadBookWords {
                    commands.append(contentsOf: commandsForAddedVocabulary(
                        lookedUpWords: lookedUpWords,
                        didLoadBookWords: didLoadBookWords,
                        bookUniqueWords: bookUniqueWords
                    ))
                }

                lastVocabCount = currentCount
                lastVocabWordsSet = currentSet
                return commands
            }

            private mutating func commandsForRemovedVocabulary(
                newCount: Int,
                removedWords: Set<String>,
                remainingWords: Set<String>,
                bookUniqueWords: Set<String>?
            ) -> [BridgeCommand] {
                if newCount == 0 || removedWords.count > 10 {
                    var commands: [BridgeCommand] = [.dom(.clearAllVocabHighlights)]
                    if newCount > 0 {
                        let validWords = filterValidWords(remainingWords, bookWords: bookUniqueWords)
                        if !validWords.isEmpty {
                            commands.append(.dom(.markVocabWords(validWords)))
                        }
                    }
                    return commands
                }

                return removedWords.map { .dom(.removeVocabWord($0)) }
            }

            private mutating func commandsForAddedVocabulary(
                lookedUpWords: [String],
                didLoadBookWords: Bool,
                bookUniqueWords: Set<String>?
            ) -> [BridgeCommand] {
                if didLoadBookWords {
                    lastBookUniqueWordsCount = bookUniqueWords?.count ?? 0
                    let validWords = filterValidWords(lookedUpWords, bookWords: bookUniqueWords)
                    print("📊 生字預過濾：全域 \(lookedUpWords.count) 字 -> 本書 \(validWords.count) 字 (\(String(format: "%.1f", (1.0 - Double(validWords.count)/Double(max(1, lookedUpWords.count))) * 100))% 縮減)")
                    return validWords.isEmpty ? [] : [.dom(.markVocabWords(validWords))]
                }

                let addedWords = lookedUpWords.filter { !lastVocabWordsSet.contains($0) }
                if addedWords.count == 1 {
                    return [.dom(.markNewVocabWord(addedWords[0]))]
                } else if !addedWords.isEmpty {
                    let validNew = filterValidWords(addedWords, bookWords: bookUniqueWords)
                    if !validNew.isEmpty {
                        return [.dom(.markVocabWords(validNew))]
                    }
                }
                return []
            }

            private mutating func commandsForRemovedWord(trigger: (word: String, id: UUID)?) -> [BridgeCommand] {
                guard let trigger, lastRemoveWordId != trigger.id else { return [] }
                lastRemoveWordId = trigger.id
                return [.dom(.removeVocabWord(trigger.word))]
            }

            private mutating func commandsForNavigation(trigger: (locator: Locator, id: UUID)?) -> [BridgeCommand] {
                guard let trigger, lastNavigateId != trigger.id else { return [] }
                lastNavigateId = trigger.id
                return [.navigator(.navigate(trigger.locator))]
            }

            private mutating func commandsForPreferences(_ preferences: EPUBPreferences) -> [BridgeCommand] {
                guard lastPreferences != preferences else { return [] }
                lastPreferences = preferences
                return [.navigator(.applyPreferences(preferences))]
            }

            private mutating func commandsForContentStyle(_ mode: TranslationPanelMode) -> [BridgeCommand] {
                if let lastPanelMode, mode != lastPanelMode {
                    self.lastPanelMode = mode
                    let css = ReaderContentStyleFactory.make(mode: mode).css()
                    return [.dom(.setContentStyle(css))]
                } else if lastPanelMode == nil {
                    lastPanelMode = mode
                }
                return []
            }

            private mutating func commandsForUnderlineOpacity(_ opacity: Double) -> [BridgeCommand] {
                if let lastUnderlineOpacity, opacity != lastUnderlineOpacity {
                    self.lastUnderlineOpacity = opacity
                    return [.dom(.setUnderlineOpacity(opacity))]
                } else if lastUnderlineOpacity == nil {
                    lastUnderlineOpacity = opacity
                }
                return []
            }

            private mutating func commandsForDebugMode(_ isEnabled: Bool) -> [BridgeCommand] {
                if let lastHitTestingDebug, isEnabled != lastHitTestingDebug {
                    self.lastHitTestingDebug = isEnabled
                    return [.dom(.setDebugMode(isEnabled))]
                } else if lastHitTestingDebug == nil {
                    lastHitTestingDebug = isEnabled
                }
                return []
            }
        }

        var parent: ReadiumNavigatorView
        weak var navigator: EPUBNavigatorViewController?
        var planner = BridgePlanner()
        var isApplyingPreferences = false
        let domExecutor = ReaderDOMExecutor()

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
            let commands = makeCommands(
                from: snapshot,
                in: host
            )
            apply(commands, in: host)
        }

        private func makeCommands(
            from snapshot: ReadiumNavigatorView.BridgeSnapshot,
            in host: NavigatorHostViewController
        ) -> [BridgeCommand] {
            planner.makeCommands(from: snapshot)
        }

        private func apply(_ commands: [BridgeCommand], in host: NavigatorHostViewController) {
            for command in commands {
                switch command {
                case .host(let hostCommand):
                    apply(hostCommand, in: host)
                case .navigator(let navigatorCommand):
                    apply(navigatorCommand, in: host)
                case .dom(let domCommand):
                    apply(domCommand)
                }
            }
        }

        private func apply(_ command: HostCommand, in host: NavigatorHostViewController) {
            switch command {
            case .setInteractionBlocked(let isBlocked):
                if let blocker = host.view.viewWithTag(9001) {
                    blocker.isUserInteractionEnabled = isBlocked
                }
            }
        }

        private func apply(_ command: NavigatorCommand, in host: NavigatorHostViewController) {
            switch command {
            case .navigate(let locator):
                Task { @MainActor in
                    print("🧭 Attempting navigation to: \(locator.href)")
                    let success = await navigator?.go(to: locator)
                    print("🧭 Navigation result: \(String(describing: success))")
                }
            case .applyPreferences(let preferences):
                isApplyingPreferences = true
                Task { @MainActor in
                    host.epubNavigator?.submitPreferences(preferences)
                    try? await Task.sleep(for: .milliseconds(800))
                    self.isApplyingPreferences = false
                }
            }
        }

        private func apply(_ command: DOMCommand) {
            domExecutor.execute(
                command,
                navigator: navigator,
                clearActiveHighlight: { [weak self] in self?.clearActiveHighlight() },
                clearAllVocabHighlights: { [weak self] in self?.clearAllVocabHighlights() },
                markVocabWords: { [weak self] words in self?.markVocabWords(words) },
                markNewVocabWord: { [weak self] word in self?.markNewVocabWord(word) },
                removeVocabWord: { [weak self] word in self?.removeVocabWord(word) }
            )
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
            let contentStyleCSS = ReaderContentStyleFactory.make(
                mode: parent.viewConfiguration.translationPanelMode
            ).css()

            let js = ReadiumNavigatorJS.buildInjectionScript(
                fontFaceCSS: fontFaceCSS,
                contentStyleCSS: contentStyleCSS,
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
