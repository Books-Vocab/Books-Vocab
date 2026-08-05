#if os(iOS)
import SwiftUI

// MARK: - AppFloatingChrome
//
// 浮在內容上的玻璃 chrome 原語。給「沒有系統 bar 可繼承」的畫面用——Reader 把
// navigationBar/tabBar 都關掉了（ReaderView.swift），所以拿不到平台自己給的玻璃，
// 必須自己表達。設計憲法見 docs/sop/ui-design.md 北極星 #1：材質交給系統的
// glassEffect，app 這層只決定分組與內容，不疊第二層背景、不描邊、不加 elevation。
//
// **為什麼不用 .buttonStyle(.glass)**：`.glassEffectUnion` 只作用在掛了 `.glassEffect`
// 的 view 上，而 `.buttonStyle(.glass)` 自己提供玻璃、不進 union。要「多顆按鈕合成一塊
// 共享膠囊」就只能走 glassEffect + union 這條。代價是**系統不會給你 44pt 命中區**，
// 所以下面每個 item 都自己撐 minWidth/minHeight 44 + contentShape——與
// VocabShellComponents.VocabChromeIconButton 同一招，理由也相同（HIG 觸控下限）。
//
// **為什麼不用系統 .toolbar**：Reader 內容在上緣是吃 safe area 的
// （ReaderView+Panels.swift `.ignoresSafeArea(edges: [.horizontal, .bottom])`），
// 而 ReadiumNavigatorView 讓 webview 填滿被 inset 後的 bounds。真 bar 每次顯示/隱藏
// 都會改 webview 高度 → ReadiumCSS multicol 重排 → scrollWidth 變 → totalProgression
// 偏移，而 handleLocationChange 會把它無條件寫進 lastReadLocatorJSON。浮動 overlay
// 不佔高度，所以不觸發這條鏈。

/// 玻璃 chrome 的容器。內部 item 靠 `spacing` 決定彼此的融合距離，
/// 同 `union` id 的 item 會合成一塊共享背景。
struct AppFloatingChrome<Content: View>: View {
    private let spacing: CGFloat
    private let content: Content

    init(spacing: CGFloat = AppSpacing.s2, @ViewBuilder content: () -> Content) {
        self.spacing = spacing
        self.content = content()
    }

    var body: some View {
        GlassEffectContainer(spacing: spacing) {
            content
        }
    }
}

extension View {
    /// 把一個 chrome item 變成玻璃膠囊。`union` 相同者合成一塊共享背景。
    ///
    /// **只管材質，不管命中區。** 命中區由 `AppFloatingChromeButton` 在 Button 的
    /// label 內自撐——`.plain` Button 的手勢掛在 styled label 上，祖先的
    /// `contentShape` 只能決定觸控能否下探，無法讓後代手勢認領自己 frame 以外的點。
    /// 掛在外層會得到一圈「可命中但無行為」的死區，在 Reader 更糟：它疊在 WKWebView
    /// 上，那圈死區會吞掉原本該落到內容的翻頁／選字觸控。
    /// repo 既有三個前例（VocabShellComponents.swift:109、PodcastControlsView.swift:38,63）
    /// 都放在 label 內，本 primitive 對齊它們。
    func appFloatingChromeItem(
        union: String,
        in namespace: Namespace.ID,
        interactive: Bool = true
    ) -> some View {
        self
            .glassEffect(
                interactive ? .regular.interactive() : .regular,
                in: AppRoundedRect(roundness: AppRoundness.pill)
            )
            .glassEffectUnion(id: union, namespace: namespace)
    }

    /// compact ↔ expanded 之間的形變由系統的 matchedGeometry 接手，
    /// 取代手寫的 AnyTransition。同 id 的兩個狀態會互相變形而不是淡入淡出。
    func appFloatingChromeMorph(id: String, in namespace: Namespace.ID) -> some View {
        glassEffectID(id, in: namespace)
    }
}

/// 只有真的給了 identifier 才掛——對其餘按鈕塞空字串會在 a11y 樹裡留下空 id。
private struct OptionalAccessibilityIdentifier: ViewModifier {
    let id: String?
    func body(content: Content) -> some View {
        if let id { content.accessibilityIdentifier(id) } else { content }
    }
}

enum AppFloatingChromeMetrics {
    /// HIG 觸控下限。視覺尺寸由 label 自己決定，這裡只保證可點區域。
    static let hitTarget: CGFloat = 44
}

/// chrome 內的圖示按鈕。視覺是 label，命中區與玻璃由 `appFloatingChromeItem` 給。
struct AppFloatingChromeButton<Label: View>: View {
    private let accessibilityLabel: String
    private let accessibilityIdentifier: String?
    private let action: () -> Void
    private let label: Label

    init(
        accessibilityLabel: String,
        accessibilityIdentifier: String? = nil,
        action: @escaping () -> Void,
        @ViewBuilder label: () -> Label
    ) {
        self.accessibilityLabel = accessibilityLabel
        self.accessibilityIdentifier = accessibilityIdentifier
        self.action = action
        self.label = label()
    }

    var body: some View {
        Button(action: action) {
            label
                // 命中區在 label 內撐開，手勢才認得這圈區域（見 appFloatingChromeItem 註解）。
                .frame(minWidth: AppFloatingChromeMetrics.hitTarget,
                       minHeight: AppFloatingChromeMetrics.hitTarget)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .appPointerHover()
        .accessibilityLabel(accessibilityLabel)
        // identifier 掛在 Button 本身，不掛在外層：外層還要再包 frame /
        // contentShape / glassEffect，掛外面會變成容器元素，`app.buttons[id]`
        // 就找不到（實測 XCTAssertTrue failed - Expected element to exist）。
        .modifier(OptionalAccessibilityIdentifier(id: accessibilityIdentifier))
    }
}
#endif
