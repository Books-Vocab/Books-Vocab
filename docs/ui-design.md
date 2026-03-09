# iOS 26 Liquid Glass 完整 API 參考

> 文檔網絡：
> - 開發入口與編譯流程：`docs/ios-dev.md`
> - App 架構與 UI 脈絡：`booksbrowser_ios/Architecture.md`
> - Vocabulary 設計系統稽核：`docs/vocab_design_system_audit.md`

> 適用：iOS 26.0+、Xcode 26.0+

## 目錄
1. [核心 API](#核心-api)
2. [Glass 類型與修飾符](#glass-類型與修飾符)
3. [GlassEffectContainer](#glasseffectcontainer)
4. [Morphing 過渡動畫](#morphing-過渡動畫)
5. [Button Styles](#button-styles)
6. [Toolbar 整合](#toolbar-整合)
7. [TabView](#tabview)
8. [Sheet 與呈現](#sheet-與呈現)
9. [進階 API](#進階-api)
10. [UIKit 整合](#uikit-整合)
11. [效能最佳化](#效能最佳化)
12. [常見 Bug 與 Workaround](#常見-bug-與-workaround)
13. [設計原則](#設計原則)
14. [向後相容](#向後相容)

---

## 核心 API

```swift
// 基本用法
.glassEffect()
.glassEffect(_ glass: Glass = .regular, in shape: some Shape = Capsule(), isEnabled: Bool = true) -> some View

// Morphing ID
.glassEffectID<ID: Hashable>(_ id: ID, in namespace: Namespace.ID) -> some View

// 合併遠距元素
.glassEffectUnion<ID: Hashable>(id: ID, namespace: Namespace.ID) -> some View

// 自訂過渡
.glassEffectTransition(_ transition: GlassEffectTransition, isEnabled: Bool = true) -> some View
```

---

## Motion Contract

BooksBrowser 的 motion system 不再接受各頁自由書寫 `.spring(...)` / `.easeOut(...)`。
動畫必須優先走 `BooksBrowser/Models/AppMetrics.swift` 中的 `AppMotion` 與共享 `AnyTransition` 語意 token。

### 核心原則

1. 先選語意，再選數值。
2. 同一類互動跨 feature 必須共用同一 token。
3. feedback 要成對出現：
   視覺 feedback 與 haptic feedback 應一起設計。
4. 不為了「有在動」而加動畫。
   animation 只服務於 state change、hierarchy、feedback、continuity。

### AppMotion 語意層

| Token | 用途 | 目前主要路徑 |
|------|------|-------------|
| `panelState` | panel / drawer / settings 開合 | Reader、Translation、Graph Settings |
| `panelSnapBack` | drag release 回位 | TranslationPanel |
| `headerState` | compact / expanded header 切換 | Reader header |
| `phaseChange` | 流程狀態切換 | Sync、Settings 狀態卡 |
| `feedbackPulse` | 成功保存、數字跳動、局部確認 | Translation save、Sync step、Review feedback |
| `contentFade` | 短暫內容淡出 | Reader progress / transient overlay |
| `loadingState` | loading 文案、loading overlay 的 state swap | Reader loading |
| `reviewRevealSpring` | review front/back/details 展開 | Today Review |
| `reviewNavigationSpring` | review 上一張 / 下一張 / 洗牌 | Today Review |
| `reviewCardSwapSpring` | review 回答後換卡 | Today Review |

### Transition 語意層

| Token | 用途 |
|------|------|
| `overlayFade` | scrim、暫時性 overlay、toolbar 進出 |
| `readerPanelReveal` | 底部 panel / drawer 進出 |
| `headerSwap` | header compact / expanded swap |
| `feedbackBadge` | saved / success 類 badge |
| `linkedOverlayCard` | linked card 疊層卡片 |
| `modalSwap` | 同區塊登入/登出、模式切換 |
| `statusRowReveal` | Settings / status row 延伸顯示 |

### 禁止事項

- 不要在 feature 檔案裡直接寫新的 `.spring(response:...)`，除非先把它提升為 `AppMotion` 語意 token。
- 不要為相似 overlay 各自定義不同 transition。
- 不要把 loading、success、error 都混用同一個動畫。
- 不要用 `.default` 當正式產品互動動畫。

### Feature Mapping

- Reader：
  `panelState`、`panelSnapBack`、`headerState`、`loadingState`、`feedbackBadge`
- Review：
  `reviewRevealSpring`、`reviewNavigationSpring`、`reviewCardSwapSpring`、`overlayFade`
- Sync：
  `phaseChange`、`feedbackPulse`、`blurReplace`
- Settings：
  `modalSwap`、`statusRowReveal`

### 文件責任

- 若是要改 token 定義：
  先更新 `BooksBrowser/Models/AppMetrics.swift`
- 若是要改互動規則：
  先更新本頁，再改程式
- 若是要排查編譯或 SwiftUI 實作錯誤：
  回到 `docs/ios-dev.md`
- 若是要理解 UI 為何出現在某個資料流程中：
  回到 `booksbrowser_ios/Architecture.md`

---

## Glass 類型與修飾符

```swift
// 三種 Glass 類型
Glass.regular    // 預設自適應，大多數場景
Glass.clear      // 高透明度，媒體豐富背景（需符合三條件才用）
Glass.identity   // 無效果，用於條件切換（不觸發 layout 重算）

// 鏈式修飾符
.tint(_ color: Color)    // 加色彩語意（主操作才用，避免濫用）
.interactive()           // 啟用縮放/彈跳/光暈互動效果（僅 iOS）

// 組合範例
.glassEffect(.regular.interactive())
.glassEffect(.regular.tint(.blue))
.glassEffect(.regular.tint(.orange).interactive())

// 條件切換（避免 layout 重算）
.glassEffect(isEnabled ? .regular : .identity)
```

**clear 類型的三個必要條件**（全部滿足才用）：
1. 元素位於媒體豐富的內容上方
2. 該內容不受 dimming layer 負面影響
3. 玻璃上方的前景內容粗體且明亮

---

## GlassEffectContainer

多個 glass 元素的父容器，提供共享 sampling region（效能更好，渲染更正確）。

```swift
// 基本
GlassEffectContainer {
    Button("A") { }.glassEffect()
    Button("B") { }.glassEffect()
}

// 控制 Morphing 距離
GlassEffectContainer(spacing: 20.0) {
    // spacing 內的元素會在過渡時視覺融合
}
```

```swift
struct GlassEffectContainer<Content: View>: View {
    init(spacing: CGFloat? = nil, @ViewBuilder content: () -> Content)
}
```

**Glass 不能 sample 其他 Glass**，必須用 Container 提供共享採樣區域。

---

## Morphing 過渡動畫

元素在同一 Container 內條件顯示/隱藏時，自動觸發流體變形。

```swift
struct MorphingExample: View {
    @State private var isExpanded = false
    @Namespace private var ns

    var body: some View {
        GlassEffectContainer(spacing: 30) {
            Button(isExpanded ? "收起" : "展開") {
                withAnimation(.bouncy) { isExpanded.toggle() }
            }
            .glassEffect()
            .glassEffectID("toggle", in: ns)

            if isExpanded {
                Button("操作 A") { }
                    .glassEffect()
                    .glassEffectID("actionA", in: ns)
            }
        }
    }
}
```

**Morphing 必要條件**：
1. 在同一個 `GlassEffectContainer` 內
2. 每個 view 有 `glassEffectID`（共享 namespace）
3. 條件顯示/隱藏
4. 有動畫（`withAnimation`）

**GlassEffectTransition 類型**：
```swift
enum GlassEffectTransition {
    case identity        // 無變化
    case matchedGeometry // 位置匹配過渡（預設）
    case materialize     // 材質出現/消失
}

// 使用
.glassEffectTransition(.materialize)
```

---

## Button Styles

```swift
// 次要操作（半透明）
Button("取消") { }
    .buttonStyle(.glass)

// 主要操作（不透明）
Button("確認") { }
    .buttonStyle(.glassProminent)
    .tint(.blue)

// 完整自訂
Button("操作") { }
    .buttonStyle(.glass)
    .tint(.purple)
    .controlSize(.large)
    .buttonBorderShape(.circle)
```

```swift
// controlSize 選項
.controlSize(.mini)
.controlSize(.small)
.controlSize(.regular)     // 預設
.controlSize(.large)
.controlSize(.extraLarge)  // iOS 26 新增

// buttonBorderShape 選項
.buttonBorderShape(.capsule)                    // 預設
.buttonBorderShape(.roundedRectangle(radius: 8))
.buttonBorderShape(.circle)
```

---

## Toolbar 整合

Toolbar 在 iOS 26 自動採用 Liquid Glass，無需額外設定：

```swift
NavigationStack {
    ContentView()
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("通知", systemImage: "bell") { }
                    .badge(5)
            }
            ToolbarItem(placement: .confirmationAction) {
                Button("完成") { }
                // 自動獲得 .glassProminent 樣式
            }
        }
}
```

```swift
// Toolbar 間距（iOS 26 新增）
ToolbarSpacer(.fixed, spacing: 20)
ToolbarSpacer(.flexible)

// 隱藏特定項目的 glass 背景
.sharedBackgroundVisibility(.hidden)
```

---

## TabView

```swift
TabView {
    Tab("主頁", systemImage: "house") { HomeView() }
    Tab("搜尋", systemImage: "magnifyingglass", role: .search) {
        SearchView()  // role: .search 在右下角顯示浮動搜尋按鈕
    }
}
.tabBarMinimizeBehavior(.onScrollDown)  // 向下滾動時自動收起
.tabViewBottomAccessory {
    NowPlayingView()  // Tab bar 上方的持久 glass 視圖
}
```

```swift
// tabBarMinimizeBehavior 選項
.automatic   // 系統決定
.onScrollDown // 向下滾動時收起
.never       // 永遠顯示

// 在 tabViewBottomAccessory 中讀取狀態
@Environment(\.tabViewBottomAccessoryPlacement) var placement
// 返回 .expanded 或 .collapsed
```

---

## Sheet 與呈現

iOS 26 sheets 自動獲得 inset Liquid Glass 背景：

```swift
// 基本（自動 glass）
.sheet(isPresented: $show) {
    SheetView()
        .presentationDetents([.medium, .large])
}

// 移除自訂背景讓 glass 顯示
Form { /* ... */ }
    .scrollContentBackground(.hidden)
    .containerBackground(.clear, for: .navigation)
```

**Toolbar → Sheet Morphing**：
```swift
struct ContentView: View {
    @Namespace private var transition
    @State private var showInfo = false

    var body: some View {
        NavigationStack {
            ContentView()
                .toolbar {
                    ToolbarItem(placement: .bottomBar) {
                        Button("資訊", systemImage: "info") { showInfo = true }
                            .matchedTransitionSource(id: "info", in: transition)
                    }
                }
                .sheet(isPresented: $showInfo) {
                    InfoSheet()
                        .navigationTransition(.zoom(sourceID: "info", in: transition))
                }
        }
    }
}
```

---

## 進階 API

### glassEffectUnion（合併遠距元素）

```swift
GlassEffectContainer {
    VStack(spacing: 0) {
        Button("編輯") { }
            .buttonStyle(.glass)
            .glassEffectUnion(id: "tools", namespace: ns)

        Spacer().frame(height: 100)  // 超過 spacing 距離

        Button("刪除") { }
            .buttonStyle(.glass)
            .glassEffectUnion(id: "tools", namespace: ns)
        // 這兩個按鈕會合併為一個 glass 形狀
    }
}
```

**要求**：相同 ID、相同 glass 類型、相似形狀。

### backgroundExtensionEffect（側邊欄延伸）

```swift
NavigationSplitView {
    List(items) { item in
        NavigationLink(item.name, value: item)
    }
    .backgroundExtensionEffect()  // 超出安全區域延伸 glass
} detail: {
    DetailView()
}
```

---

## UIKit 整合

```swift
import UIKit

// UIGlassEffect
let glassEffect = UIGlassEffect(glass: .regular, isInteractive: true)
let effectView = UIVisualEffectView(effect: glassEffect)
effectView.frame = CGRect(x: 0, y: 0, width: 200, height: 50)
view.addSubview(effectView)

// UIGlassContainerEffect（多元素共享採樣）
let containerEffect = UIGlassContainerEffect()
let containerView = UIVisualEffectView(effect: containerEffect)
```

UIKit 最佳實踐：
- 移除自訂背景讓 glass 顯示
- 更新 presentation controllers 支援 sheets
- 使用 `hidesSharedBackground = true` 移除特定項目的 glass

---

## 效能最佳化

```swift
// ✅ 多元素用 Container
GlassEffectContainer {
    Button("A") { }.glassEffect()
    Button("B") { }.glassEffect()
}

// ❌ 各自獨立（渲染效率差，且視覺不一致）
Button("A") { }.glassEffect()
Button("B") { }.glassEffect()
```

其他最佳化原則：
- 用 `.identity` 代替條件性移除（避免 layout 重算）
- 避免對 glass 元素使用持續旋轉動畫
- 在舊裝置上測試（iPhone 11-13 可能出現 lag）
- 用 Instruments 監控 GPU 使用率

---

## 常見 Bug 與 Workaround

### Bug 1：interactive + 自訂形狀 → 互動區域是 Capsule

**狀態**：已知 Beta 問題
**Workaround**：按鈕用 `.buttonStyle(.glass)` 代替 `.glassEffect(.interactive())`

### Bug 2：glassProminent + circle → 渲染毛邊

```swift
Button("操作") { }
    .buttonStyle(.glassProminent)
    .buttonBorderShape(.circle)
    .clipShape(Circle())  // ← 加這行修復毛邊
```

### Bug 3：Widget 在 Standard/Dark 模式顯示黑色背景

**狀態**：暫無完整解法
**部分解法**：Tinted 和 Transparent widget 模式使用 `Color.clear` 可正常運作

### Bug 4：Toolbar 導航時動畫錯亂

```swift
// 給 ToolbarItem 固定 ID 避免動畫問題
ToolbarItem(id: "constantID") {
    Button("完成") { }
}
```

---

## 設計原則

**只用在導航層**（toolbar、tabbar、FAB、sheet、popover），不用在內容層（list、table、media、scrollable content）。

**三層視覺架構**：
1. 內容層（下層）— 無 glass
2. 導航層（中層）— Liquid Glass
3. 疊加層（上層）— vibrancy fills

**Tinting 哲學**：傳達語意（主要操作、狀態），不用於裝飾。

**反模式**：glass-on-glass 堆疊、對每個元素用 glass、自訂透明度繞過無障礙。

---

## 向後相容

```swift
extension View {
    @ViewBuilder
    func compatibleGlass(in shape: some Shape = Capsule(), interactive: Bool = false) -> some View {
        if #available(iOS 26.0, *) {
            let g = interactive ? Glass.regular.interactive() : .regular
            self.glassEffect(g, in: shape)
        } else {
            self.background(
                shape.fill(.ultraThinMaterial)
                    .overlay(LinearGradient(
                        colors: [.white.opacity(0.3), .clear],
                        startPoint: .topLeading, endPoint: .bottomTrailing
                    ))
                    .overlay(shape.stroke(.white.opacity(0.2), lineWidth: 1))
            )
        }
    }
}
```

**臨時全局禁用**（iOS 27 前有效）：
```xml
<!-- Info.plist -->
<key>UIDesignRequiresCompatibility</key>
<true/>
```
