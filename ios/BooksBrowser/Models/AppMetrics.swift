//
//  AppMetrics.swift
//  BooksBrowser
//
//  統一的間距、圓角與陰影參數 (Design System Tokens)
//

import SwiftUI

enum AppMetrics {
    // ── Divider / Separator ───────────────────────────────────────────────────
    static let dividerThin: CGFloat = 0.5
    static let dividerStandard: CGFloat = 1
    /// 「呼吸式」群組分節 — Mochi-borrowed（北極星二：border 退場、divider 進場）。
    /// 配 `AppAirDivider` 使用，給 list / 群組之間的軟分隔，不靠卡片邊框。
    /// 原值 32pt 對應 Mochi `<hr style="margin:32px 0">` long-form editorial；
    /// 2026-05 user feedback 收緊到 16pt — iPhone 列表頁 32pt 過鬆。
    static let dividerAirMargin: CGFloat = 16

    // ── Glass Stroke (iOS <26 fallback) ─────────────────────────────────────────
    static let glassStrokeOpacity: Double = 0.12

    // ── Control Dimensions ──────────────────────────────────────────────────────
    static let iconButtonSize: CGFloat = 52

    // ── Loading Indicator ─────────────────────────────────────────────────
    static let loadingIndicatorScaleMedium: CGFloat = 0.8
    static let loadingIndicatorScaleSmall: CGFloat = 0.7
}

enum AppMotion {
    static let quickEaseOut = Animation.easeOut(duration: 0.15)
    static let controlEaseOut = Animation.easeOut(duration: 0.14)
    static let progressLinear = Animation.linear(duration: 0.1)
    static let standardSpring = Animation.spring(response: 0.3, dampingFraction: 0.75)
    static let emphasizedSpring = Animation.spring(response: 0.35, dampingFraction: 0.8)
    static let relaxedSpring = Animation.spring(response: 0.4, dampingFraction: 0.8)
    static let systemSpring = Animation.spring()
    static let modalSwapSpring = Animation.spring(response: 0.45, dampingFraction: 0.85)
    static let buttonSpring = Animation.spring(response: 0.35, dampingFraction: 0.7, blendDuration: 0)
    static let breathing = Animation.easeInOut(duration: 2.8).repeatForever(autoreverses: true)
    static let reviewRevealSpring = Animation.spring(response: 0.42, dampingFraction: 0.88)
    static let reviewNavigationSpring = Animation.spring(response: 0.32, dampingFraction: 0.86)

    // Swipe gesture
    static let swipeSnapBackSpring = Animation.spring(response: 0.4, dampingFraction: 0.82)

    // MARK: - Micro-interaction Springs
    /// 卡片甩出畫面（高剛性快速飛離）
    static let swipeFlingSpring = Animation.interpolatingSpring(stiffness: 500, damping: 28)
    /// 回饋按鈕跟隨 swipe 強度（快速貼合手勢）
    static let feedbackButtonSpring = Animation.spring(response: 0.22, dampingFraction: 0.72)
    /// 拖拽中卡片跟手（極低延遲、高阻尼，貼合手指）
    static let swipeTrackingSpring = Animation.interactiveSpring(response: 0.14, dampingFraction: 0.86)

    // --- Visual polish tokens ---
    static let pressFeedback: Animation = .spring(response: 0.25, dampingFraction: 0.65)
    static let contentReveal: Animation = .spring(response: 0.35, dampingFraction: 0.82)
    static let celebrationBounce: Animation = .spring(response: 0.4, dampingFraction: 0.55)
    static let sheetContentAppear: Animation = .spring(response: 0.3, dampingFraction: 0.78)

    // Semantic motion tokens for shared interaction patterns.
    // 每個語意 token 對應唯一一條曲線，不設同值別名。
    static let panelState = standardSpring
    static let headerState = relaxedSpring
    static let phaseChange = emphasizedSpring
    static let feedbackPulse = systemSpring
    static let contentFade = quickEaseOut
    static let chipSelect = Animation.easeOut(duration: 0.18)

    // MARK: - Asymmetric Emphasized Easing
    // Material Design 3 / Apple HIG 非對稱曲線：進場慢出（觀眾還在看）、退場快進（觀眾已轉移注意）。
    // 是「絲滑感」與「Things 3 / Linear 質感」的核心曲線。

    /// 進場曲線 — 緩入快出，配 sheet / panel / overlay reveal
    /// timingCurve(0.05, 0.7, 0.1, 1.0, duration: 0.4) — 標準 Material decelerate
    static let emphasizedDecelerate = Animation.timingCurve(0.05, 0.7, 0.1, 1.0, duration: 0.4)

    /// Continuous follow-scroll glide for the podcast transcript: one animated
    /// `scrollTo(.center)` per sentence boundary. The duration is what makes the
    /// move read as a continuous glide rather than a jump (tuned on device).
    static let podcastFollowScroll = Animation.easeInOut(duration: 0.6)

    /// Step indicator / pagination indicator 寬度切換
    /// 配 onboarding capsule 寬度由 inactive → active 過渡，須線性短促不彈跳
    static let indicatorTransition = Animation.easeOut(duration: 0.25)

    // MARK: - Continuous / Loading Motion

    /// 微脈動 — 用於 empty state、loading 等需要「呼吸感」但不搶焦的元素
    static let subtleBreath = Animation.easeInOut(duration: 2.4).repeatForever(autoreverses: true)

    // MARK: - Tap Feedback Triplet (scale + opacity + haptic)
    // 「按下去」物理感的三件套常量，供 PressableInteraction / ButtonStyle 內部使用

    enum TapFeedback {
        /// 按下時的縮放比例
        static let scaleDown: CGFloat = 0.97
        /// 按下時的透明度（opacity dip）
        static let opacityDip: Double = 0.92
        /// 對應的動畫曲線
        static let animation = Animation.interactiveSpring(response: 0.18, dampingFraction: 0.7)
    }

    /// Notebook deck card release / cancel 回彈
    /// 給 `NotebookDeckButtonStyle` 在 `isPressed` false 時用；
    /// 比 `TapFeedback.animation` 略長、阻尼略高，營造卡片落回紙堆的物理感。
    static let cardDeckRelease = Animation.spring(response: 0.28, dampingFraction: 0.85)
}

extension AnyTransition {
    static let overlayFade = AnyTransition.opacity
    static let readerPanelReveal = AnyTransition.move(edge: .bottom).combined(with: .opacity)
    static let headerSwap = AnyTransition.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity)
    static let feedbackBadge = AnyTransition.scale(scale: 0.8).combined(with: .opacity)
    static let linkedOverlayCard = AnyTransition.scale(scale: 0.96).combined(with: .opacity)
    static let modalSwap = AnyTransition.asymmetric(
        insertion: .scale(scale: 0.97).combined(with: .opacity),
        removal: .opacity
    )
    static let statusRowReveal = AnyTransition.move(edge: .top).combined(with: .opacity)
    /// 內容替換（適用於 list item、card 內容切換）
    static let contentSwap: AnyTransition = .opacity.combined(with: .scale(scale: 0.97))
    /// Banner / toast 從頂部滑入
    static let bannerReveal: AnyTransition = .move(edge: .top).combined(with: .opacity)
    /// 書架卡片進出（微縮放 + 淡出）
    static let bookshelfCard: AnyTransition = .opacity.combined(with: .scale(scale: 0.96))
    /// 列表項目簡潔過渡
    static let listItemFade: AnyTransition = .opacity.animation(AppMotion.contentFade)
    static let listInsert: AnyTransition = .opacity.combined(with: .offset(y: 8))
    /// 列表內容批次替換（insert + remove asymmetric 包裝）
    static let listSwap: AnyTransition = .asymmetric(insertion: .listInsert, removal: .opacity)
    /// 抽屜 / drawer 從右側滑入並淡入
    static let drawerReveal: AnyTransition = .move(edge: .trailing).combined(with: .opacity)
    /// Sync phase 切換（blur replace）
    static let phaseBlurSwap: AnyTransition = .init(.blurReplace)
    /// 選取模式 checkbox 顯現
    static let selectionReveal: AnyTransition = .scale.combined(with: .opacity)
}

// MARK: - 8pt grid spacing / radius scale / elevation language
// 所有元件一律使用此 namespace（AppSpacing / AppRadius / AppElevation）。

/// 8pt grid spacing scale。一律以 4 的倍數為節奏，2/3pt 為例外 hairline 用途。
enum AppSpacing {
    static let zero: CGFloat = 0
    /// hairline — 僅用於 divider / progress / 微縫隙
    static let hairline: CGFloat = 1
    /// 2pt 微縫隙 — 8pt grid 例外，僅限極小貼合間距
    static let microGap: CGFloat = 2
    /// 3pt 微縫隙 — 8pt grid 例外
    static let tinyGap: CGFloat = 3
    static let s1: CGFloat = 4
    static let s2: CGFloat = 8
    static let s3: CGFloat = 12
    static let s4: CGFloat = 16
    static let s5: CGFloat = 20
    static let s6: CGFloat = 24
    static let s7: CGFloat = 32
    static let s8: CGFloat = 40
    static let s9: CGFloat = 48
    static let s10: CGFloat = 64

    /// Card 雙層 padding — 外緣比內項大，形成呼吸層次（Linear / Notion pattern）
    static let cardOuterPadding: CGFloat = s6  // 24
    static let cardInnerGap: CGFloat = s4      // 16
    static let cardSectionGap: CGFloat = s3    // 12
}

/// Radius scale — 收斂到 4 主階 + hairline + pill。新元件不使用 7/9/13/14/18 等鄰近半階值。
// Notion-inspired：俐落小角半徑 — 控制元件 ~4-6、卡片 ~8、modal ~16。
enum AppRadius {
    static let none: CGFloat = 0
    static let xs: CGFloat = 4
    static let sm: CGFloat = 6
    static let md: CGFloat = 8
    static let lg: CGFloat = 12
    static let xl: CGFloat = 16
    /// Capsule / pill — 直接用 `Capsule()` shape 即可，此值為 RoundedRectangle 場合的 fallback
    static let pill: CGFloat = 999
}

/// Elevation language — z0 flush ← → z4 modal，跨元件統一深度層級。
/// 全 app 唯一的 shadow 系統 — 所有投影一律走 `.appElevation(.zN)`。
enum AppElevation {
    case z0  // flush
    case z1  // resting card / list row
    case z2  // raised / hover / pressed up
    case z3  // overlay (sheet, drawer, popover)
    case z4  // modal / fullscreen overlay

    // Notion-inspired：表面靠 border 分層，shadow 僅做極輕的浮起暗示。
    // resting card（z1）幾乎無陰影；明顯陰影保留給 overlay / modal。
    var opacity: Double {
        switch self {
        case .z0: return 0
        case .z1: return 0.03
        case .z2: return 0.06
        case .z3: return 0.10
        case .z4: return 0.16
        }
    }

    var radius: CGFloat {
        switch self {
        case .z0: return 0
        case .z1: return 4
        case .z2: return 10
        case .z3: return 18
        case .z4: return 28
        }
    }

    var y: CGFloat {
        switch self {
        case .z0: return 0
        case .z1: return 1
        case .z2: return 4
        case .z3: return 8
        case .z4: return 14
        }
    }
}

/// Elevation 投影方向 — `.down` 標準下投（卡片浮起），`.up` 向上投影（底部 toolbar / panel）。
enum ElevationDirection {
    case down
    case up
}

/// Theme-aware elevation modifier — 在 dark mode 自動加強陰影 opacity
/// 否則黑底加黑影完全不可見，導致 elevation 語意失效。
private struct AppElevationModifier: ViewModifier {
    let z: AppElevation
    var direction: ElevationDirection = .down
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        // dark mode 上 black shadow 與 dark background 對比不足，
        // 提高 opacity 至 1.8x 補回視覺層次（Material Dark Elevation pattern）
        let darkBoost: Double = colorScheme == .dark ? 1.8 : 1.0
        // `.up` 將投影方向翻轉為向上（底部浮動 bar / panel）
        let offsetY = direction == .up ? -z.y : z.y
        return content.shadow(
            color: .black.opacity(z.opacity * darkBoost),
            radius: z.radius,
            y: offsetY
        )
    }
}

extension View {
    /// Apply elevation shadow token。使用 `.appElevation(.z2)` 取代 raw `.shadow(...)`。
    /// 自動感知 light / dark mode 並調整 shadow 強度，dark mode 上會加強至 1.8x opacity。
    /// `direction: .up` 用於底部 toolbar / panel 的向上投影。
    func appElevation(_ z: AppElevation, direction: ElevationDirection = .down) -> some View {
        modifier(AppElevationModifier(z: z, direction: direction))
    }
}

// MARK: - AppMotion Convenience Modifiers
extension View {
    func animatePhaseChange<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.phaseChange, value: value)
    }
    func animateSpring<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.standardSpring, value: value)
    }
    func animateContentFade<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.contentFade, value: value)
    }
    func animateControl<V: Equatable>(_ value: V) -> some View {
        animation(AppMotion.controlEaseOut, value: value)
    }
}
