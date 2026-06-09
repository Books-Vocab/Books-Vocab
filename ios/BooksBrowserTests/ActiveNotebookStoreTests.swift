//
//  ActiveNotebookStoreTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksBrowser

@Suite("ActiveNotebookLWW")
@MainActor
struct ActiveNotebookLWWTests {
    @Test func cloudNewerWins() {
        let local = ActiveNotebookState(activeNotebookId: "a", updatedAt: 100)
        let cloud = ActiveNotebookState(activeNotebookId: "b", updatedAt: 200)
        #expect(ActiveNotebookLWW.resolve(local: local, cloud: cloud).activeNotebookId == "b")
    }

    @Test func localNewerWins() {
        let local = ActiveNotebookState(activeNotebookId: "a", updatedAt: 300)
        let cloud = ActiveNotebookState(activeNotebookId: "b", updatedAt: 200)
        #expect(ActiveNotebookLWW.resolve(local: local, cloud: cloud).activeNotebookId == "a")
    }

    @Test func cloudWinsWhenLocalNil() {
        let local = ActiveNotebookState(activeNotebookId: "a", updatedAt: nil)
        let cloud = ActiveNotebookState(activeNotebookId: "b", updatedAt: 1)
        #expect(ActiveNotebookLWW.resolve(local: local, cloud: cloud).activeNotebookId == "b")
    }

    @Test func localWinsWhenCloudNil() {
        let local = ActiveNotebookState(activeNotebookId: "a", updatedAt: 1)
        let cloud = ActiveNotebookState(activeNotebookId: "b", updatedAt: nil)
        #expect(ActiveNotebookLWW.resolve(local: local, cloud: cloud).activeNotebookId == "a")
    }

    @Test func bothNilKeepsLocal() {
        let local = ActiveNotebookState(activeNotebookId: "a", updatedAt: nil)
        let cloud = ActiveNotebookState(activeNotebookId: "b", updatedAt: nil)
        #expect(ActiveNotebookLWW.resolve(local: local, cloud: cloud).activeNotebookId == "a")
    }
}

@Suite("ActiveNotebookStore")
@MainActor
struct ActiveNotebookStoreTests {

    private func makeDefaults() -> UserDefaults {
        let suite = "ActiveNotebookStoreTests-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: suite)!
        d.removePersistentDomain(forName: suite)
        return d
    }

    @Test("未設定時回 default，activeNotebookIdIfSet 為 nil")
    func defaultsWhenUnset() {
        let store = ActiveNotebookStore(defaults: makeDefaults(), cloud: FakeCloudKVStore())
        #expect(store.activeNotebookId == "default")
        #expect(store.activeNotebookIdIfSet == nil)
    }

    @Test("setActive 寫本地 + iCloud + updatedAt 三層")
    func setActiveWritesAllLayers() {
        let d = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ActiveNotebookStore(defaults: d, cloud: cloud)
        store.setActive("nb-42")
        #expect(store.activeNotebookId == "nb-42")
        #expect(d.string(forKey: "activeNotebookId") == "nb-42")
        #expect(d.object(forKey: "active_notebook_updated_at") as? Double != nil)
        #expect(cloud.string(forKey: "activeNotebookId") == "nb-42")
        #expect(cloud.double(forKey: "active_notebook_updated_at") != nil)
    }

    @Test("init：cloud 較新時套 cloud 並寫回本地（直讀者一致）")
    func initAppliesCloudWhenNewer() {
        let d = makeDefaults()
        d.set("local-nb", forKey: "activeNotebookId")
        d.set(100.0, forKey: "active_notebook_updated_at")
        let cloud = FakeCloudKVStore()
        cloud.set("cloud-nb", forKey: "activeNotebookId")
        cloud.set(200.0, forKey: "active_notebook_updated_at")
        let store = ActiveNotebookStore(defaults: d, cloud: cloud)
        #expect(store.activeNotebookId == "cloud-nb")
        #expect(d.string(forKey: "activeNotebookId") == "cloud-nb")  // 寫回本地
    }

    @Test("init：local 較新時保留 local")
    func initKeepsLocalWhenNewer() {
        let d = makeDefaults()
        d.set("local-nb", forKey: "activeNotebookId")
        d.set(300.0, forKey: "active_notebook_updated_at")
        let cloud = FakeCloudKVStore()
        cloud.set("cloud-nb", forKey: "activeNotebookId")
        cloud.set(200.0, forKey: "active_notebook_updated_at")
        let store = ActiveNotebookStore(defaults: d, cloud: cloud)
        #expect(store.activeNotebookId == "local-nb")
    }

    @Test("clearStale 寫回 default 並推進 updatedAt（跨裝置同步重置）")
    func clearStaleResetsWithTimestamp() {
        let d = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ActiveNotebookStore(defaults: d, cloud: cloud)
        store.setActive("nb-9")
        store.clearStale()
        #expect(store.activeNotebookId == "default")
        #expect(cloud.string(forKey: "activeNotebookId") == "default")
        #expect(cloud.double(forKey: "active_notebook_updated_at") != nil)
    }

    @Test("clear 只清本地，不碰 iCloud（Apple-ID scope）")
    func clearOnlyLocal() {
        let d = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ActiveNotebookStore(defaults: d, cloud: cloud)
        store.setActive("nb-9")
        store.clear()
        #expect(store.activeNotebookIdIfSet == nil)
        #expect(d.object(forKey: "active_notebook_updated_at") == nil)
        #expect(cloud.string(forKey: "activeNotebookId") == "nb-9")  // iCloud 不被清
    }

    @Test("applyServerState 只寫本地層，不回寫 iCloud（對齊 applyServerModeState）")
    func applyServerStateWritesLocalOnly() {
        let d = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ActiveNotebookStore(defaults: d, cloud: cloud)
        store.applyServerState(ActiveNotebookState(activeNotebookId: "srv-nb", updatedAt: 500))
        #expect(store.activeNotebookId == "srv-nb")
        #expect(d.object(forKey: "active_notebook_updated_at") as? Double == 500)
        // cold-start 不回寫 iCloud KVS：避免新裝置與他裝置未傳播的 genuine local write 競爭。
        #expect(cloud.string(forKey: "activeNotebookId") == nil)
        #expect(cloud.double(forKey: "active_notebook_updated_at") == nil)
    }

    @Test("snapshot 讀本地層")
    func snapshotReadsLocal() {
        let store = ActiveNotebookStore(defaults: makeDefaults(), cloud: FakeCloudKVStore())
        #expect(store.snapshot.updatedAt == nil)
        store.setActive("nb-1")
        #expect(store.snapshot.updatedAt != nil)
        #expect(store.snapshot.activeNotebookId == "nb-1")
    }
}
