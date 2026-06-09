#if os(iOS)
//
//  ReadiumNavigatorView.swift
//  Books & Vocab
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

    private static func installLoadErrorLabel(on host: NavigatorHostViewController) {
        let errorLabel = UILabel()
        errorLabel.text = "無法開啟此書籍".localized
        errorLabel.textAlignment = .center
        errorLabel.translatesAutoresizingMaskIntoConstraints = false
        host.view.addSubview(errorLabel)
        NSLayoutConstraint.activate([
            errorLabel.centerXAnchor.constraint(equalTo: host.view.centerXAnchor),
            errorLabel.centerYAnchor.constraint(equalTo: host.view.centerYAnchor),
        ])
    }

    private static func installInteractionBlocker(on host: NavigatorHostViewController, coordinator: Coordinator) {
        // 透明觸控攔截層：當翻譯面板開啟時覆蓋整個 WebView，阻止 click 穿透
        let blocker = UIView(frame: host.view.bounds)
        blocker.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        blocker.backgroundColor = .clear
        blocker.isUserInteractionEnabled = false // 預設關閉
        blocker.tag = 9001

        let tap = UITapGestureRecognizer(target: coordinator, action: #selector(Coordinator.handleBlockerTap(_:)))
        blocker.addGestureRecognizer(tap)

        host.view.addSubview(blocker)
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
                )
            )
        } catch {
            AppLog.reader.error("Failed to create EPUBNavigatorViewController: \(error)")
            Self.installLoadErrorLabel(on: host)
            return host
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

        Self.installInteractionBlocker(on: host, coordinator: context.coordinator)

        return host
    }

    static func dismantleUIViewController(_ uiViewController: NavigatorHostViewController, coordinator: Coordinator) {
        // 移除 WKUserContentController 對 Coordinator 的強引用，打斷 retain cycle
        if let controller = coordinator.registeredContentController {
            for name in Coordinator.registeredHandlerNames {
                controller.removeScriptMessageHandler(forName: name)
            }
            coordinator.registeredContentController = nil
        }
        coordinator.navigator = nil
        coordinator.contentOffsetObserver = nil
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

        /// 記住 setupUserScripts 傳入的 controller，供 dismantle 時移除 handler 打斷 retain cycle
        weak var registeredContentController: WKUserContentController?
        static let registeredHandlerNames = ["wordTap", "wordDeselect", "selectionState", "markingProgress"]

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
            true
        }

        func navigator(_ navigator: any SelectableNavigator, shouldShowMenuForSelection selection: Selection) -> Bool {
            true
        }

        // MARK: EPUBNavigatorDelegate — JS 注入

        func navigator(_ navigator: EPUBNavigatorViewController, setupUserScripts userContentController: WKUserContentController) {
            registeredContentController = userContentController
            for name in Self.registeredHandlerNames {
                userContentController.add(self, name: name)
            }

            // ── 自訂字體：從 App Bundle 讀取 TTF → base64 → @font-face ──
            let fontFaceCSS = Self.buildFontFaceCSS()

            // ★ 傳遞除錯模式開關
            let isDebugMode = parent.viewConfiguration.showHitTestingDebug ? "true" : "false"
            let contentStyleCSS = parent.viewConfiguration.contentStyleCSS

            let js = ReadiumNavigatorJS.buildInjectionScript(
                fontFaceCSS: fontFaceCSS,
                contentStyleCSS: contentStyleCSS,
                underlineOpacity: parent.viewConfiguration.underlineOpacity,
                isDebugMode: isDebugMode
            )

            let script = WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
            userContentController.addUserScript(script)
            AppLog.reader.info("User scripts injected")
            PerfLog.reader.mark("userScriptsInjected")

            // Scripts 注入後重新標記所有生字（修復初始載入的 race condition）
            let words = parent.lookedUpWords
            if !words.isEmpty {
                let validWords = filterValidWords(words, bookWords: parent.bookUniqueWords)
                self.markVocabWords(validWords)
            }
        }
    }
}
#endif
