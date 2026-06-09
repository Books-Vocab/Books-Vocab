//
//  NotebookFilter.swift
//  Books & Vocab
//
//  共用的單字本篩選模型 — 複習和統計共用

import Foundation

struct NotebookFilter: Equatable {
    var selectedIds: Set<String> = []  // empty = all

    var isFiltered: Bool { !selectedIds.isEmpty }

    func matches(_ notebookId: String) -> Bool {
        selectedIds.isEmpty || selectedIds.contains(notebookId)
    }

    /// UserDefaults persistence key
    static let storageKey = "notebookFilterSelectedIds"

    func save() {
        UserDefaults.standard.set(Array(selectedIds), forKey: Self.storageKey)
    }

    static func load() -> NotebookFilter {
        let ids = UserDefaults.standard.stringArray(forKey: storageKey) ?? []
        return NotebookFilter(selectedIds: Set(ids))
    }
}
