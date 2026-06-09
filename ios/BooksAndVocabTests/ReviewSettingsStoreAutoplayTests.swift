//
//  ReviewSettingsStoreAutoplayTests.swift
//  Books & Vocab Tests
//
//  Pins autoplay speed / sound persistence and the mode-change guard edge case:
//  changing a custom param alone must advance the mode LWW clock.
//  Shares FakeCloudKVStore from ReviewClockSyncTests.
//

import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct ReviewSettingsStoreAutoplayTests {

    private func makeDefaults() -> UserDefaults {
        let suite = "test.autoplay.\(UUID().uuidString)"
        let d = UserDefaults(suiteName: suite)!
        d.removePersistentDomain(forName: suite)
        return d
    }

    // MARK: - autoplay speed / sound always write to UserDefaults

    @Test func autoplaySpeedWritesToDefaults() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.autoplaySpeed = .fast
        store.update(s)
        #expect(defaults.string(forKey: "review_settings_autoplay_speed") == "fast")
    }

    @Test func autoplaySoundDisabledWritesToDefaults() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.autoplaySoundEnabled = false
        store.update(s)
        #expect(defaults.object(forKey: "review_settings_autoplay_sound_enabled") as? Bool == false)
    }

    @Test func autoplayChangeDoesNotTouchModeOrPauseClock() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.autoplaySpeed = .slow
        store.update(s)
        // 不該動 mode 或 pause 的 LWW 時戳
        #expect(defaults.object(forKey: "review_settings_mode_updated_at") == nil)
        #expect(defaults.object(forKey: "review_settings_progress_updated_at") == nil)
        #expect(cloud.double(forKey: "review_settings_mode_updated_at") == nil)
        #expect(cloud.double(forKey: "review_settings_progress_updated_at") == nil)
    }

    // MARK: - custom param alone advances mode clock

    @Test func customParamAloneAdvancesModeClock() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.mode = .custom
        s.customInitialIntervalHours = 20
        store.update(s)

        // 只改 custom param（mode 不變）→ mode clock 仍應推進
        s.customInitialIntervalHours = 25
        store.update(s)

        #expect(cloud.string(forKey: "review_settings_mode") == "custom")
        #expect(cloud.double(forKey: "review_settings_mode_updated_at") != nil)
    }

    @Test func unchangedModeDoesNotAdvanceModeClock() {
        let defaults = makeDefaults()
        let cloud = FakeCloudKVStore()
        let store = ReviewSettingsStore(defaults: defaults, cloud: cloud)
        var s = store.settings
        s.mode = .relaxed
        store.update(s)

        let firstTimestamp = defaults.object(forKey: "review_settings_mode_updated_at") as? Double
        // 完全不改 mode / custom → 再次 update，mode clock 不推進
        store.update(s)

        let secondTimestamp = defaults.object(forKey: "review_settings_mode_updated_at") as? Double
        #expect(secondTimestamp == firstTimestamp)
    }
}
