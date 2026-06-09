//
//  NotebookCardDataTests.swift
//  Books & Vocab Tests
//
//  鎖封面黃點口徑：actionableCount = dueCount + unlearnedCount，
//  與「今日複習」入口徽章一致（避免 587 vs 597 不一致）。
//

import Foundation
import Testing
@testable import BooksBrowser

private func makeData(due: Int, unlearned: Int, reviewed: Int = 0) -> NotebookCardData {
    NotebookCardData(
        name: "n",
        color: nil,
        coverPattern: nil,
        coverImagePath: nil,
        cardCount: due + unlearned + reviewed,
        dueCount: due,
        unlearnedCount: unlearned,
        reviewedCount: reviewed,
        pendingCount: 0,
        lastActivity: nil,
        isActive: false
    )
}

struct NotebookCardDataTests {

    @Test func actionableCountSumsDueAndUnlearned() {
        // 對應實測：587 到期複習 + 10 未學 = 597（與今日複習徽章同口徑）
        #expect(makeData(due: 587, unlearned: 10).actionableCount == 597)
    }

    @Test func actionableCountExcludesReviewed() {
        // 未到期已複習卡不計入黃點
        #expect(makeData(due: 5, unlearned: 0, reviewed: 39).actionableCount == 5)
    }

    @Test func actionableCountZeroWhenNothingPending() {
        #expect(makeData(due: 0, unlearned: 0, reviewed: 40).actionableCount == 0)
    }
}
