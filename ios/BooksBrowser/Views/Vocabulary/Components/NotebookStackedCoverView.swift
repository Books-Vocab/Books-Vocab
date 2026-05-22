//
//  NotebookStackedCoverView.swift
//  BooksBrowser
//
//  Apple Wallet 風的「一疊單字卡」封面 — 由下而上錯位堆疊，
//  下層只露頂緣、不旋轉、不傾斜。下層為純色 ghost，頂層復用
//  既有 `NotebookCoverView`（pattern / image / text 邏輯 100% 不拷貝）。
//
//  本檔只負責「視覺堆疊」；metadata、使用中 pill、context menu 由
//  外層 `NotebookCard` 持有。Press feedback 由 `NotebookDeckButtonStyle`
//  透過 `\.isDeckPressed` environment 注入。
//

import SwiftUI

// MARK: - Press state environment

/// `NotebookDeckButtonStyle` → `NotebookStackedCoverView` 的 press 訊號通道。
/// 用 environment 而非 binding，因為按壓狀態是 SwiftUI 自動驅動的；
/// view tree 內任何後代都可讀，不需自己穿 binding。
private struct IsDeckPressedKey: EnvironmentKey {
    static let defaultValue: Bool = false
}

/// Reduce-motion 旗標：由 `NotebookDeckButtonStyle` 從 a11y env 傳入，
/// 讓 stacked cover 內部統一決定是否關掉 offset/scale 動效。
private struct DeckReduceMotionKey: EnvironmentKey {
    static let defaultValue: Bool = false
}

extension EnvironmentValues {
    var isDeckPressed: Bool {
        get { self[IsDeckPressedKey.self] }
        set { self[IsDeckPressedKey.self] = newValue }
    }
    var deckReduceMotion: Bool {
        get { self[DeckReduceMotionKey.self] }
        set { self[DeckReduceMotionKey.self] = newValue }
    }
}

// MARK: - Stacked cover view

struct NotebookStackedCoverView: View {
    let color: Color
    let pattern: NotebookCoverPattern?
    let coverImagePath: String?
    let name: String
    /// 1 / 2 / 3 / 4 — 由 `NotebookStackMetrics.layerCount(forCardCount:)` 決定
    let layerCount: Int
    let aspectRatio: CGFloat

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.isDeckPressed) private var isPressed
    @Environment(\.deckReduceMotion) private var reduceMotion

    var body: some View {
        // ghost 數 = layerCount - 1（頂層另外處理）
        let ghostDepths = Array((1..<max(layerCount, 1)).reversed())  // e.g. [3,2,1]

        ZStack(alignment: .top) {
            // ── 下層 ghost：由深到淺由下而上 render ──
            ForEach(ghostDepths, id: \.self) { depth in
                ghostLayer(depth: depth)
            }

            // ── 頂層 L0：實體封面 ──
            NotebookCoverView(
                color: color,
                pattern: pattern,
                coverImagePath: coverImagePath,
                name: name
            )
            .aspectRatio(aspectRatio, contentMode: .fill)
            .clipShape(RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous))
            .appElevation(isPressed ? .z2 : .z2)  // 頂層恆 z2
            .offset(y: isPressed && !reduceMotion ? NotebookStackMetrics.pressedTopOffsetY : 0)
            .scaleEffect(isPressed && !reduceMotion ? AppMotion.TapFeedback.scaleDown : 1.0,
                         anchor: .center)
        }
    }

    /// 純色 ghost 一層 — 不 render pattern / image / text，避免下層雜訊。
    @ViewBuilder
    private func ghostLayer(depth: Int) -> some View {
        let dx = NotebookStackMetrics.layerInsetX * CGFloat(depth)
        let dy = NotebookStackMetrics.layerOffsetY * CGFloat(depth)
        let pressBoost = isPressed && !reduceMotion
            ? NotebookStackMetrics.pressedGhostOffsetY * CGFloat(depth)
            : 0

        RoundedRectangle(cornerRadius: AppRadius.md, style: .continuous)
            .fill(NotebookStackMetrics.deckColor(color, depth: depth, scheme: colorScheme))
            .aspectRatio(aspectRatio, contentMode: .fill)
            .padding(.horizontal, dx)
            .offset(y: dy + pressBoost)
            .appElevation(isPressed ? .z2 : .z1)
            .accessibilityHidden(true)
    }
}

// MARK: - Button style

/// 整張 Notebook 卡 press-in 物理感的單一承載點。
/// - 注入 `\.isDeckPressed` 給 label，讓 `NotebookStackedCoverView` 自己決定怎麼動
/// - opacity dip 套在整 label（含 metadata）形成統一壓感
/// - 動畫：press-in `TapFeedback.animation`、release `AppMotion.cardDeckRelease`
/// - Haptic：`.sensoryFeedback(.selection, ...)` 僅 press-in 時觸發一次
/// - Reduce Motion：保留 opacity dip + haptic，offset/scale 由 cover view 內部自關
struct NotebookDeckButtonStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .environment(\.isDeckPressed, configuration.isPressed)
            .environment(\.deckReduceMotion, reduceMotion)
            .opacity(configuration.isPressed ? AppMotion.TapFeedback.opacityDip : 1.0)
            .animation(
                configuration.isPressed ? AppMotion.TapFeedback.animation : AppMotion.cardDeckRelease,
                value: configuration.isPressed
            )
            .sensoryFeedback(.selection, trigger: configuration.isPressed) { _, newValue in
                newValue  // 僅在進入 pressed 時觸發
            }
    }
}
