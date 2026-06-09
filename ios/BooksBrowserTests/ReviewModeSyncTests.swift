//
//  ReviewModeSyncTests.swift
//  Books & Vocab Tests
//
//  Spec for review-mode 後端化 Phase A2: 複習模式 mode + 自訂 SRS 參數從純
//  UserDefaults 升級為三層(UserDefaults + iCloud KVS + 單一 mode_updated_at LWW)。
//  mode 與 5 個 custom 參數為複合原子狀態,共用一個 updated_at 時戳 → 跨裝置整組收斂。
//  共用 ReviewClockSyncTests.swift 的 FakeCloudKVStore(同 test target)。
//

import Foundation
import Testing
@testable import BooksBrowser

/// LWW 決議純函數:取 updatedAt 較新的整組(mode + 5 custom)。
/// 純函數,不碰 KVS,涵蓋四象限 + 雙 nil fallback。
@MainActor
struct ReviewModeLWWTests {

    private func state(_ mode: ReviewSettingsMode, _ updatedAt: Double?) -> ReviewModeState {
        ReviewModeState(
            mode: mode,
            customInitialIntervalHours: 12,
            customRememberedMultiplier: 1.9,
            customForgotMultiplier: 0.45,
            customMinimumIntervalHours: 6,
            customMaximumIntervalHours: 1440,
            updatedAt: updatedAt
        )
    }

    @Test func cloudNewerWins() {
        let resolved = ReviewModeLWW.resolve(local: state(.relaxed, 100), cloud: state(.custom, 200))
        #expect(resolved.mode == .custom)
    }

    @Test func localNewerWins() {
        let resolved = ReviewModeLWW.resolve(local: state(.custom, 300), cloud: state(.relaxed, 200))
        #expect(resolved.mode == .custom)
    }

    @Test func onlyCloudHasTimestamp() {
        let resolved = ReviewModeLWW.resolve(local: state(.relaxed, nil), cloud: state(.intensive, 50))
        #expect(resolved.mode == .intensive)
    }

    @Test func onlyLocalHasTimestamp() {
        let resolved = ReviewModeLWW.resolve(local: state(.intensive, 50), cloud: state(.relaxed, nil))
        #expect(resolved.mode == .intensive)
    }

    @Test func bothNilFallsBackToLocal() {
        let resolved = ReviewModeLWW.resolve(local: state(.relaxed, nil), cloud: state(.custom, nil))
        #expect(resolved.mode == .relaxed)
    }
}

@MainActor
struct ReviewSettingsStoreModeSyncTests {

    private func makeDefaults() -> UserDefaults {
        let suite = "test.reviewmode.\(UUID().uuidString)"
        let d = UserDefaults(suiteName: suite)!
        d.removePersistentDomain(forName: suite)
        return d
    }

    @Test func modeChangeWritesAllThreeLayers() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.mode = .custom
        s.customInitialIntervalHours = 20
        store.update(s)
        // 本地層 + LWW 時戳
        #expect(defaults.string(forKey: "review_settings_mode") == "custom")
        #expect(defaults.object(forKey: "review_settings_mode_updated_at") != nil)
        // iCloud KVS 三鍵都寫入(mode string + customParams JSON + updatedAt)
        #expect(cloud.string(forKey: "review_settings_mode") == "custom")
        #expect(cloud.string(forKey: "review_settings_custom_params") != nil)
        #expect(cloud.double(forKey: "review_settings_mode_updated_at") != nil)
    }

    @Test func pauseChangeDoesNotAdvanceModeClock() {
        // 改 pause 不該動 mode 的 LWW 時戳,否則跨裝置誤判 mode 較新。
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.pauseProgress(at: Date(timeIntervalSince1970: 1000))
        store.update(s)
        #expect(cloud.double(forKey: "review_settings_mode_updated_at") == nil)
        #expect(defaults.object(forKey: "review_settings_mode_updated_at") == nil)
    }

    @Test func initAppliesCloudModeWhenCloudNewer() {
        let defaults = makeDefaults()
        defaults.set("relaxed", forKey: "review_settings_mode")
        defaults.set(100.0, forKey: "review_settings_mode_updated_at")
        let cloud = FakeCloudKVStore()
        cloud.set("intensive", forKey: "review_settings_mode")
        cloud.set(200.0, forKey: "review_settings_mode_updated_at")   // cloud 較新
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        #expect(store.settings.mode == .intensive)
    }

    @Test func initKeepsLocalModeWhenLocalNewer() {
        let defaults = makeDefaults()
        defaults.set("custom", forKey: "review_settings_mode")
        let dict: [String: Double] = [
            "initialIntervalHours": 30, "rememberedMultiplier": 1.9, "forgotMultiplier": 0.45,
            "minimumIntervalHours": 6, "maximumIntervalHours": 1440,
        ]
        defaults.set(try! JSONSerialization.data(withJSONObject: dict), forKey: "review_settings_custom_params")
        defaults.set(500.0, forKey: "review_settings_mode_updated_at")   // local 較新
        let cloud = FakeCloudKVStore()
        cloud.set("relaxed", forKey: "review_settings_mode")
        cloud.set(200.0, forKey: "review_settings_mode_updated_at")
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        #expect(store.settings.mode == .custom)
        #expect(store.settings.customInitialIntervalHours == 30)
    }

    @Test func initAppliesCloudCustomParamsAtomicallyWhenCloudNewer() {
        // cloud 較新時,custom params 整組(JSON)要跟 mode 一起套用,證明整組原子。
        let defaults = makeDefaults()
        defaults.set(100.0, forKey: "review_settings_mode_updated_at")
        let cloud = FakeCloudKVStore()
        cloud.set("custom", forKey: "review_settings_mode")
        let dict: [String: Double] = [
            "initialIntervalHours": 48, "rememberedMultiplier": 3.0, "forgotMultiplier": 0.3,
            "minimumIntervalHours": 12, "maximumIntervalHours": 2000,
        ]
        let json = String(data: try! JSONSerialization.data(withJSONObject: dict), encoding: .utf8)!
        cloud.set(json, forKey: "review_settings_custom_params")
        cloud.set(200.0, forKey: "review_settings_mode_updated_at")   // cloud 較新
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        #expect(store.settings.mode == .custom)
        #expect(store.settings.customInitialIntervalHours == 48)
        #expect(store.settings.customMaximumIntervalHours == 2000)
    }

    @Test func defaultsWhenNeitherLayerHasMode() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        #expect(store.settings.mode == .relaxed)
        #expect(store.settings.customInitialIntervalHours == 12)
    }
}
