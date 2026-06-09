//
//  KGVocabEmptyState.swift
//  Books & Vocab
//
//  KGVocabView 空狀態文案/圖示的純解析。從 View 抽出後：
//   1. title / description / systemImage 三欄共用「整本空 > 搜尋中 > 篩選中 > 預設」
//      的同一分支優先序，不再各自複製條件而漂移；
//   2. 純輸入 → 純輸出，可單元測試（見 KGVocabEmptyStateTests）。
//

import Foundation

enum KGVocabEmptyState {
    /// - Parameters:
    ///   - hasNoEntries: 整本 notebook 完全沒有已收錄單字（`syncedEntries.isEmpty`）。
    ///   - searchText: 目前搜尋字串。
    ///   - filters: 目前選取的複習狀態篩選集合。
    static func title(hasNoEntries: Bool, searchText: String, filters: Set<VocabularyReviewState>) -> String {
        if hasNoEntries { return "尚無已收錄單字".localized }
        if !searchText.isEmpty { return "沒有符合的單字".localized }
        if !filters.isEmpty { return "目前沒有符合篩選條件的單字".localized }
        return "尚無已收錄單字".localized
    }

    static func description(hasNoEntries: Bool, searchText: String, filters: Set<VocabularyReviewState>) -> String {
        if hasNoEntries {
            return "在書架閱讀時長按生字加入單字本，或重新整理以拉取雲端已有資料。".localized
        }
        if !searchText.isEmpty { return "試試其他關鍵字，或取消部分篩選條件。".localized }
        if !filters.isEmpty { return "試試取消部分篩選條件，或切換排序方式。".localized }
        return "同步完成後，這裡會顯示你的雲端單字。".localized
    }

    static func systemImage(hasNoEntries: Bool, searchText: String, filters: Set<VocabularyReviewState>) -> String {
        if hasNoEntries { return "books.vertical" }
        if !searchText.isEmpty { return "magnifyingglass" }
        // 單一篩選時給該狀態的專屬圖示；多選或無選回到通用篩選圖示。
        if filters.count == 1, let state = filters.first {
            switch state {
            case .unlearned: return "sparkles"
            case .due: return "checkmark.seal"
            case .reviewed: return "leaf"
            }
        }
        return "line.3.horizontal.decrease.circle"
    }
}
