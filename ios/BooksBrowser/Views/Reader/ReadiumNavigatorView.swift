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
import os

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
            AppLog.reader.error("Navigator error: \(String(describing: error))")
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
            let contentStyleCSS = ReaderContentStyleFactory.make().css()

            let js = ReadiumNavigatorJS.buildInjectionScript(
                fontFaceCSS: fontFaceCSS,
                contentStyleCSS: contentStyleCSS,
                underlineOpacity: parent.viewConfiguration.underlineOpacity,
                isDebugMode: isDebugMode
            )

            let script = WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
            userContentController.addUserScript(script)
            AppLog.reader.info("User scripts injected")

            // Scripts 注入後重新標記所有生字（修復初始載入的 race condition）
            let words = parent.lookedUpWords
            if !words.isEmpty {
                let validWords = filterValidWords(words, bookWords: parent.bookUniqueWords)
                self.markVocabWords(validWords)
            }
        }
    }
}
