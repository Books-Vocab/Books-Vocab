import CoreGraphics
import Testing
@testable import BooksAndVocab

/// #2026：卡片區高度過渡的純規則。
/// 不變式：同高恆等、終點 = 新高度、啟動 / 展開中 snap、role 翻面當幀零跳變、
/// 非 active slot 恆 cap（FIX(review-flip-gap)）。
struct TodayReviewDeckHeightTests {

    private typealias H = TodayReviewDeckHeight

    // MARK: plan

    @Test func sameHeightIsIdentity() {
        for h: CGFloat in [1, 120, 240.4, 480] {
            #expect(H.plan(displayed: h, target: h, revealed: false) == .hold)
            #expect(H.plan(displayed: h, target: h + H.epsilon, revealed: false) == .hold)
            #expect(H.plan(displayed: h, target: h - H.epsilon, revealed: true) == .hold)
        }
    }

    @Test func differingHeightAnimatesToTheNewHeight() {
        // 終點恆等於新高度（不產生中間值），起點由 SwiftUI 取螢幕當下值。
        for (from, to): (CGFloat, CGFloat) in [(120, 360), (360, 120), (200, 200.6), (200.6, 200)] {
            #expect(H.plan(displayed: from, target: to, revealed: false) == .animate(to: to))
        }
    }

    @Test func bootstrapAndInvalidTargetSnap() {
        #expect(H.plan(displayed: 0, target: 240, revealed: false) == .snap(to: 240))
        #expect(H.plan(displayed: 240, target: 0, revealed: false) == .snap(to: 0))
        #expect(H.plan(displayed: 240, target: -5, revealed: false) == .snap(to: 0))
    }

    @Test func revealedNeverAnimates() {
        #expect(H.plan(displayed: 120, target: 360, revealed: true) == .snap(to: 360))
    }

    @Test func planIsMonotoneInDirection() {
        // 規劃的終點與 target 同向：target 越大，終點越大；與 displayed 無關。
        let targets: [CGFloat] = [100, 150, 220, 340, 500]
        for displayed: CGFloat in [90, 260, 700] {
            var last: CGFloat = 0
            for target in targets {
                guard case .animate(let end) = H.plan(displayed: displayed, target: target, revealed: false) else {
                    Issue.record("expected animate for \(displayed)->\(target)")
                    continue
                }
                #expect(end == target)
                #expect(end > last)
                last = end
            }
        }
    }

    // MARK: resolvedShell

    @Test func resolvedShellFallsBackToTargetOnlyBeforeBootstrap() {
        #expect(H.resolvedShell(shell: 0, target: 240) == 240)
        #expect(H.resolvedShell(shell: 180, target: 240) == 180)
        #expect(H.resolvedShell(shell: 0, target: -1) == 0)
    }

    // MARK: slotHeight

    @Test func nonActiveSlotsAlwaysCapToTheShell() {
        for inFlight in [false, true] {
            for revealed in [false, true] {
                #expect(H.slotHeight(isActive: false, shell: 200, target: 200, inFlight: inFlight, revealed: revealed) == 200)
                #expect(H.slotHeight(isActive: false, shell: 200, target: 320, inFlight: inFlight, revealed: revealed) == 200)
                #expect(H.slotHeight(isActive: false, shell: 0, target: 320, inFlight: inFlight, revealed: revealed) == 320)
            }
        }
    }

    /// 從較高的舊高度（例如背面展開後的總高）收合：背景卡 cap 在新卡高度，不比 active 高。
    @Test func shrinkingNeverLetsBackgroundCardsExceedTheTarget() {
        #expect(H.slotHeight(isActive: false, shell: 400, target: 200, inFlight: true, revealed: false) == 200)
    }

    /// 窮舉：任何狀態下 cap(非 active) ≤ pin(active) —— ZStack 高度只由 active 決定。
    @Test func capNeverExceedsTheActivePin() {
        let values: [CGFloat] = [0, 120, 200, 200.4, 360, 480]
        for shell in values {
            for target in values {
                for inFlight in [false, true] {
                    for revealed in [false, true] {
                        let cap = H.slotHeight(isActive: false, shell: shell, target: target, inFlight: inFlight, revealed: revealed)
                        guard let pin = H.slotHeight(isActive: true, shell: shell, target: target, inFlight: inFlight, revealed: revealed) else { continue }
                        #expect(cap! <= pin, "shell=\(shell) target=\(target) inFlight=\(inFlight) revealed=\(revealed)")
                    }
                }
            }
        }
    }

    @Test func settledActiveSlotUsesNaturalHeight() {
        #expect(H.slotHeight(isActive: true, shell: 200, target: 200, inFlight: false, revealed: false) == nil)
        #expect(H.slotHeight(isActive: true, shell: 200, target: 200.4, inFlight: false, revealed: false) == nil)
        // 啟動期（shell 尚未建立）也不釘高。
        #expect(H.slotHeight(isActive: true, shell: 0, target: 240, inFlight: false, revealed: false) == nil)
    }

    /// 核心：role 翻面當幀（shell 仍是舊高度、target 已是新卡高度），新 active 取舊高度，
    /// 與翻面前 ZStack 的高度（= shell）相同 → 零跳變。
    @Test func roleFlipFrameKeepsTheOldHeight() {
        for (old, new): (CGFloat, CGFloat) in [(120, 360), (360, 120), (200, 201)] {
            let flipFrame = H.slotHeight(isActive: true, shell: old, target: new, inFlight: false, revealed: false)
            #expect(flipFrame == old)
        }
    }

    @Test func activeStaysPinnedWhileTheAnimationIsInFlight() {
        // 動畫中 model 值已等於 target，但仍在飛 → 不得回 nil（否則 layout 立刻跳到自然高度）。
        #expect(H.slotHeight(isActive: true, shell: 360, target: 360, inFlight: true, revealed: false) == 360)
    }

    @Test func revealedActiveReleasesToNaturalHeightForTheFold() {
        #expect(H.slotHeight(isActive: true, shell: 200, target: 200, inFlight: true, revealed: true) == nil)
        #expect(H.slotHeight(isActive: true, shell: 200, target: 360, inFlight: false, revealed: true) == nil)
    }

    // MARK: slotHeightUpdate

    @Test func slotHeightUpdateComparesAgainstTheSlotNotTheCardCache() {
        // slot 存別張卡的舊值 300；回收回來的卡量到 200 → 必須寫入。
        #expect(H.slotHeightUpdate(stored: 300, measured: 200) == 200)
        #expect(H.slotHeightUpdate(stored: 200, measured: 200.3) == nil)
        #expect(H.slotHeightUpdate(stored: 200, measured: 0) == nil)
        #expect(H.slotHeightUpdate(stored: 0, measured: 120) == 120)
    }
}
