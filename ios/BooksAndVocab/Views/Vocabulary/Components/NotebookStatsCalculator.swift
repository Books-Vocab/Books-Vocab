//
//  NotebookStatsCalculator.swift
//  Books & Vocab
//
//  Pure 統計與篩選 — NotebookListView 與 NotebookSortOption 共用。
//  搬離 View 後可獨立 unit test，覆蓋 due/unlearned/reviewed/pending/lastActivity 分支。

import Foundation

struct NotebookStats {
    var cardCount: Int = 0
    var dueCount: Int = 0
    var unlearnedCount: Int = 0
    var reviewedCount: Int = 0
    var pendingCount: Int = 0
    var lastActivity: Date?
}

enum NotebookStatsCalculator {
    /// Single-pass O(n) 聚合每個 notebook 的卡片分類與最近活動。
    static func compute(
        _ entries: [VocabularyEntry],
        pendingEntries: [VocabularyEntry],
        now: Date = Date()
    ) -> [String: NotebookStats] {
        var result: [String: NotebookStats] = [:]
        for entry in entries {
            result[entry.notebookId, default: NotebookStats()].cardCount += 1
            if entry.reviewEligible {
                if entry.reviewCount > 0 && entry.nextReviewAt <= now {
                    result[entry.notebookId, default: NotebookStats()].dueCount += 1
                } else if entry.reviewCount == 0 {
                    result[entry.notebookId, default: NotebookStats()].unlearnedCount += 1
                } else {
                    result[entry.notebookId, default: NotebookStats()].reviewedCount += 1
                }
            }
            let activity = entry.lastReviewedAt ?? entry.dateAdded
            if result[entry.notebookId]?.lastActivity == nil || activity > result[entry.notebookId]!.lastActivity! {
                result[entry.notebookId, default: NotebookStats()].lastActivity = activity
            }
        }
        for entry in pendingEntries {
            result[entry.notebookId, default: NotebookStats()].pendingCount += 1
        }
        return result
    }

    /// 依 filter 將 entries 切成 (due, unlearned) — 餵 today review。
    static func filtered(
        _ entries: [VocabularyEntry],
        filter: NotebookFilter,
        now: Date = Date()
    ) -> (due: [VocabularyEntry], unlearned: [VocabularyEntry]) {
        var due: [VocabularyEntry] = []
        var unlearned: [VocabularyEntry] = []
        for entry in entries where filter.matches(entry.notebookId) && entry.reviewEligible {
            if entry.reviewCount > 0 && entry.nextReviewAt <= now {
                due.append(entry)
            } else if entry.reviewCount == 0 {
                unlearned.append(entry)
            }
        }
        return (due, unlearned)
    }
}
