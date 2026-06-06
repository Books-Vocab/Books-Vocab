//
//  ActiveNotebookStoreTests.swift
//  BooksBrowserTests
//

import Foundation
import Testing
@testable import BooksBrowser

@Suite("ActiveNotebookStore")
struct ActiveNotebookStoreTests {

    private func makeDefaults() -> UserDefaults {
        let suite = "ActiveNotebookStoreTests-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: suite)!
        d.removePersistentDomain(forName: suite)
        return d
    }

    @Test("未設定時回 default")
    func defaultsWhenUnset() {
        let store = ActiveNotebookStore(defaults: makeDefaults())
        #expect(store.activeNotebookId == ActiveNotebookStore.defaultNotebookId)
        #expect(store.activeNotebookId == "default")
    }

    @Test("setActive 後讀回同值並落地 UserDefaults")
    func setActivePersists() {
        let d = makeDefaults()
        let store = ActiveNotebookStore(defaults: d)
        store.setActive("nb-42")
        #expect(store.activeNotebookId == "nb-42")
        #expect(d.string(forKey: "activeNotebookId") == "nb-42")
    }

    @Test("新 store 從既有 UserDefaults 讀回值（無 in-memory 快取）")
    func readsExistingDefaults() {
        let d = makeDefaults()
        d.set("nb-7", forKey: "activeNotebookId")
        let store = ActiveNotebookStore(defaults: d)
        #expect(store.activeNotebookId == "nb-7")
    }

    @Test("clearStale 後 fall through 到 default 且 key 移除")
    func clearStaleResets() {
        let d = makeDefaults()
        let store = ActiveNotebookStore(defaults: d)
        store.setActive("nb-9")
        store.clearStale()
        #expect(store.activeNotebookId == "default")
        #expect(d.string(forKey: "activeNotebookId") == nil)
    }

    @Test("clear 後 fall through 到 default 且 key 移除")
    func clearResets() {
        let d = makeDefaults()
        let store = ActiveNotebookStore(defaults: d)
        store.setActive("nb-9")
        store.clear()
        #expect(store.activeNotebookId == "default")
        #expect(d.string(forKey: "activeNotebookId") == nil)
    }
}
