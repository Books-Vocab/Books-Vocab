//
//  SharedDeckPresentationTests.swift
//  Books & Vocab Tests
//
//  Explore 目錄篩選 / 排序純邏輯 —— 離 UI/SwiftData 單測。
//

import Foundation
import Testing
@testable import BooksAndVocab

struct SharedDeckPresentationTests {

    private func proj(
        _ id: String, title: String, author: String? = nil, official: Bool = true,
        category: String? = nil, languagePair: String? = nil, tags: [String] = [],
        updatedAt: Date? = nil, sortOrder: Int = 0
    ) -> SharedDeckProjection {
        SharedDeckProjection(
            remoteId: id, title: title, authorLabel: author, isOfficial: official,
            category: category, languagePair: languagePair, tags: tags,
            updatedAt: updatedAt, sortOrder: sortOrder
        )
    }

    private var sample: [SharedDeckProjection] {
        [
            proj("d1", title: "GRE 高頻", author: "KG", category: "exam", languagePair: "en-zh", tags: ["gre", "exam"], sortOrder: 0),
            proj("d2", title: "Everyday Phrases", category: "phrase", languagePair: "en-zh", tags: ["daily"], sortOrder: 1),
            proj("d3", title: "商用英文", category: "exam", languagePair: "en-zh", tags: ["business"], sortOrder: 2),
        ]
    }

    @Test func default_filter_returns_all_in_sortOrder() {
        let out = ExploreFilter().apply(to: sample)
        #expect(out.map(\.remoteId) == ["d1", "d2", "d3"])
    }

    @Test func search_matches_title_author_tags_case_insensitively() {
        var f = ExploreFilter()
        f.searchText = "gre"
        #expect(f.apply(to: sample).map(\.remoteId) == ["d1"])   // title + tag match

        f.searchText = "PHRASE"
        #expect(f.apply(to: sample).map(\.remoteId) == ["d2"])   // category-less; matches d2 title? no → tag/title

        f.searchText = "kg"
        #expect(f.apply(to: sample).map(\.remoteId) == ["d1"])   // author match
    }

    @Test func category_filter_narrows() {
        var f = ExploreFilter()
        f.category = "exam"
        #expect(Set(f.apply(to: sample).map(\.remoteId)) == ["d1", "d3"])
    }

    @Test func languagePair_filter_narrows() {
        var f = ExploreFilter()
        f.languagePair = "en-zh"
        #expect(f.apply(to: sample).count == 3)
    }

    @Test func officialOnly_filter() {
        var decks = sample
        decks.append(proj("d4", title: "Community Deck", official: false, sortOrder: 3))
        var f = ExploreFilter()
        f.officialOnly = true
        #expect(!f.apply(to: decks).contains { $0.remoteId == "d4" })
    }

    @Test func alphabetical_sort_uses_localized_compare() {
        var f = ExploreFilter()
        f.sort = .alphabetical
        let ordered = f.apply(to: sample).map(\.title)
        // CJK-vs-Latin absolute position is locale/ICU-dependent; assert only the
        // deterministic relative order of the two Latin-leading titles (E < G) and
        // that the result is a permutation of the input.
        #expect(Set(ordered) == Set(sample.map(\.title)))
        let iEveryday = ordered.firstIndex(of: "Everyday Phrases")
        let iGRE = ordered.firstIndex(of: "GRE 高頻")
        #expect(iEveryday != nil && iGRE != nil && iEveryday! < iGRE!)
    }

    @Test func recency_sort_prefers_updatedAt_then_sortOrder() {
        let now = Date()
        let decks = [
            proj("old", title: "Old", updatedAt: now.addingTimeInterval(-1000), sortOrder: 0),
            proj("new", title: "New", updatedAt: now, sortOrder: 1),
            proj("nodate", title: "NoDate", updatedAt: nil, sortOrder: 2),
        ]
        var f = ExploreFilter()
        f.sort = .recency
        let ids = f.apply(to: decks).map(\.remoteId)
        #expect(ids.first == "new")               // 最新 updatedAt 置頂
        #expect(ids.contains("nodate"))            // 無日期者仍在，不被丟棄
    }

    @Test func hasActiveFilters_reflects_non_default_state() {
        #expect(ExploreFilter().hasActiveFilters == false)
        var f = ExploreFilter()
        f.searchText = "x"
        #expect(f.hasActiveFilters == false)   // 搜尋不算「篩選」
        #expect(f.isSearching == true)
        f.category = "exam"
        #expect(f.hasActiveFilters == true)
    }

    @Test func unknown_category_renders_raw_no_key_leak() {
        // server 新增未知分類 → 原樣顯示（不漏 L10n key）。
        #expect(SharedDeckFormat.categoryDisplayName("brand_new_category") == "brand_new_category")
    }
}
