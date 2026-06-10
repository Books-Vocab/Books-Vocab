import Foundation
import Testing
@testable import BooksAndVocab

/// Chrome Equatable 切片契約（settle 白工 Phase 2）。
///
/// ReviewTopBar / ReviewToolbarControls 的 `==` 只比較 `model`；契約是
/// 「所有影響渲染的值都收進 model（synthesized == 全欄位）、其餘 stored
/// property 只能是 intent 閉包或 @Environment/@State 動態 wrapper（自帶
/// 失效通道）」。若未來有人加了一個裸值欄位卻沒進 model，Equatable skip
/// 會讓 UI 不更新——本 suite 用 Mirror 把這種欄位擋在編譯後第一道。
@MainActor
struct ReviewChromeSliceTests {
    private static let topBarModel = ReviewTopBarModel(
        progressText: "1 / 8",
        canShuffle: true,
        isAutoPlaying: false,
        isCardInteractive: true
    )

    private static let toolbarModel = ReviewToolbarModel(
        showsAnswer: false,
        isAutoPlaying: false,
        isAutoPlayPaused: false,
        autoplaySoundEnabled: true,
        autoplaySpeedName: "1×",
        autoplayProgress: 0,
        progressText: "1 / 8",
        forgotCount: 0,
        rememberedCount: 0,
        canGoPrevious: false,
        canGoNext: true,
        isCardInteractive: true,
        swipeIntensity: 0
    )

    private static func makeTopBar(model: ReviewTopBarModel = topBarModel,
                                   onShuffle: @escaping () -> Void = {}) -> ReviewTopBar {
        ReviewTopBar(model: model, onShuffle: onShuffle,
                     onToggleAutoPlay: {}, onToggleHelp: {}, onClose: {})
    }

    private static func makeControls(model: ReviewToolbarModel = toolbarModel,
                                     onForgotTap: @escaping () -> Void = {}) -> ReviewToolbarControls {
        ReviewToolbarControls(model: model, onForgotTap: onForgotTap,
                              onRememberedTap: {}, onPrevious: {}, onNext: {},
                              onToggleAutoPlayPause: {}, onToggleAutoPlaySound: {},
                              onChangeAutoPlaySpeed: {})
    }

    /// 非 model 的 stored property 只允許閉包（"(Function)"/含 "->"）或
    /// `_` 前綴的動態 property wrapper（@Environment/@State，自帶失效通道）。
    private func expectOnlyModelClosuresAndWrappers(_ subject: Any) {
        for child in Mirror(reflecting: subject).children {
            guard let label = child.label else { continue }
            if label == "model" || label.hasPrefix("_") { continue }
            let typeDescription = String(describing: type(of: child.value))
            #expect(
                typeDescription.contains("->"),
                "stored property `\(label)`（\(typeDescription)）不是閉包也不在 model——Equatable skip 會吃掉它的更新"
            )
        }
    }

    @Test func topBarStoredStateIsModelClosuresOrWrappers() {
        expectOnlyModelClosuresAndWrappers(Self.makeTopBar())
    }

    @Test func toolbarControlsStoredStateIsModelClosuresOrWrappers() {
        expectOnlyModelClosuresAndWrappers(Self.makeControls())
    }

    @Test func equalityComparesModelAndIgnoresClosures() {
        var changed = Self.topBarModel
        changed.canShuffle = false
        #expect(Self.makeTopBar() == Self.makeTopBar(onShuffle: { _ = 1 }))
        #expect(Self.makeTopBar() != Self.makeTopBar(model: changed))

        var counted = Self.toolbarModel
        counted.forgotCount += 1
        #expect(Self.makeControls() == Self.makeControls(onForgotTap: { _ = 1 }))
        #expect(Self.makeControls() != Self.makeControls(model: counted))
    }
}
