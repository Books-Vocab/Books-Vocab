//
//  SharedDeckPresentation.swift
//  Books & Vocab
//
//  Explore 目錄的純呈現邏輯 —— filter / sort / 數字·評分格式化。抽成非 View 型別使
//  篩選邏輯可離 UI 單測（見 SharedDeckPresentationTests）。
//

import Foundation

enum ExploreSort: String, CaseIterable, Identifiable {
    case recency
    case alphabetical

    var id: String { rawValue }

    /// L10n key（進 5 lproj）。
    var titleKey: String {
        switch self {
        case .recency: return "explore.sort.recency"
        case .alphabetical: return "explore.sort.alphabetical"
        }
    }
}

/// Explore 目錄篩選狀態。全部本機套用在已同步的 SharedDeck 上（Phase 1b-iii：官方
/// 目錄量小、離線友善；server-side q/cursor 分頁列為後續）。
struct ExploreFilter: Equatable {
    var searchText: String = ""
    /// nil = 全部分類。
    var category: String?
    /// nil = 全部語言對。
    var languagePair: String?
    /// Phase 1 目錄全為 official；segment 保留 forward-compat（community 為後續 phase）。
    var officialOnly: Bool = false
    var sort: ExploreSort = .recency

    var isSearching: Bool {
        !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// 是否有任何非預設篩選生效（用於「清除篩選」CTA 與空狀態分辨）。
    var hasActiveFilters: Bool {
        category != nil || languagePair != nil || officialOnly
    }

    /// 純函式篩選 + 排序。輸入應為 live（非 tombstoned）decks 的投影欄位。
    func apply(to decks: [SharedDeckProjection]) -> [SharedDeckProjection] {
        var result = decks
        let q = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !q.isEmpty {
            result = result.filter { deck in
                deck.title.lowercased().contains(q)
                    || (deck.authorLabel?.lowercased().contains(q) ?? false)
                    || deck.tags.contains { $0.lowercased().contains(q) }
            }
        }
        if let category { result = result.filter { $0.category == category } }
        if let languagePair { result = result.filter { $0.languagePair == languagePair } }
        if officialOnly { result = result.filter { $0.isOfficial } }

        switch sort {
        case .recency:
            // server 已依 recency 給 sortOrder；缺 updatedAt 者退回 sortOrder 穩定序。
            result.sort { lhs, rhs in
                switch (lhs.updatedAt, rhs.updatedAt) {
                case let (l?, r?) where l != r: return l > r
                default: return lhs.sortOrder < rhs.sortOrder
                }
            }
        case .alphabetical:
            result.sort { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
        }
        return result
    }
}

/// SharedDeck 的值型投影 —— 使 filter/sort 邏輯可離 SwiftData/UI 單測。
struct SharedDeckProjection: Equatable, Identifiable {
    let remoteId: String
    let title: String
    let authorLabel: String?
    let isOfficial: Bool
    let category: String?
    let languagePair: String?
    let tags: [String]
    let updatedAt: Date?
    let sortOrder: Int

    var id: String { remoteId }
}

extension SharedDeck {
    var projection: SharedDeckProjection {
        SharedDeckProjection(
            remoteId: remoteId, title: title, authorLabel: authorLabel,
            isOfficial: isOfficial, category: category, languagePair: languagePair,
            tags: tags, updatedAt: updatedAt, sortOrder: sortOrder
        )
    }
}

/// Locale-aware 數字 / 評分 / 日期格式化（走 LocaleAwareFormatter；plural 走 stringsdict）。
enum SharedDeckFormat {
    /// 「N 張卡片」——復用既有 `card_count_plural` stringsdict。
    static func cardCount(_ count: Int) -> String {
        L10n.format("card_count_plural", Int64(count))
    }

    /// Locale-aware 整數（千分位）。
    static func compactNumber(_ value: Int) -> String {
        LocaleAwareFormatter.shared.string(from: NSNumber(value: value), style: .decimal)
    }

    /// 評分保留 1 位小數（value-type FormatStyle，locale-aware，非 static formatter）。
    static func rating(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(1)))
    }

    /// 「更新於 …」相對時間；nil → nil（呼叫端略過）。
    static func relativeUpdatedAt(_ date: Date?) -> String? {
        guard let date else { return nil }
        return LocaleAwareFormatter.shared.relativeString(for: date, style: .abbreviated)
    }

    /// 分類 display name：已知 enum → L10n key，未知 → 原樣（render-safety，server 可能加新分類）。
    static func categoryDisplayName(_ category: String) -> String {
        switch category {
        case "language": return L10n.string("explore.category.language")
        case "exam": return L10n.string("explore.category.exam")
        case "phrase": return L10n.string("explore.category.phrase")
        case "custom": return L10n.string("explore.category.custom")
        default: return category   // 未知分類原樣顯示，不漏 key
        }
    }
}
