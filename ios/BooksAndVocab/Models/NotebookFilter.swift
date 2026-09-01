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
        save(to: .standard)
    }

    func save(to defaults: UserDefaults) {
        defaults.set(Array(selectedIds), forKey: Self.storageKey)
    }

    /// Removes selections that no longer exist in the live notebook collection.
    ///
    /// Returns whether the filter changed. Persist only when it did so that a
    /// live collection refresh does not create unnecessary UserDefaults writes.
    @discardableResult
    mutating func reconcile(
        with availableNotebookIds: Set<String>,
        defaults: UserDefaults = .standard
    ) -> Bool {
        let reconciledIds = selectedIds.intersection(availableNotebookIds)
        guard reconciledIds != selectedIds else { return false }

        selectedIds = reconciledIds
        save(to: defaults)
        return true
    }

    static func load() -> NotebookFilter {
        load(from: .standard)
    }

    static func load(from defaults: UserDefaults) -> NotebookFilter {
        let ids = defaults.stringArray(forKey: storageKey) ?? []
        return NotebookFilter(selectedIds: Set(ids))
    }
}
