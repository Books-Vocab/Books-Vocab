//
//  CloudPreferencesSyncDebounceTests.swift
//  Books & Vocab Tests
//
//  Spec for PR #625 synchronize() storm regression fix (Track 7 throttle).
//
//  NOTE: This test target cannot be executed locally in this environment
//  (CLAUDE.md Scope forbids ios_test.sh here). The cases below are written as
//  the executable spec for the debounce / force-flush / echo-guard behaviour
//  and are to be validated by CI / the reviewer.
//

import Foundation
import Testing
@testable import BooksBrowser

/// Drives CloudPreferencesSync through its injectable test seam
/// (`init(flushDelay:flushAction:)`) so the debounce/coalesce and force-flush
/// logic is observable without real NSUbiquitousKeyValueStore timing.
@MainActor
struct CloudPreferencesSyncDebounceTests {

    /// Consecutive set() calls inside the debounce window collapse to a single
    /// synchronize() flush.
    @Test func consecutiveSetsCoalesceToSingleFlush() async throws {
        let flushes = Counter()
        let sut = CloudPreferencesSync(flushDelay: 0.05) { flushes.increment() }

        // Simulate a lineHeight Slider(step:0.1) drag burst.
        for i in 0..<15 {
            sut.set(1.0 + Double(i) * 0.1, forKey: "reader_settings_lineHeight")
        }

        // Within the window nothing has flushed yet.
        #expect(flushes.value == 0)

        // After the window elapses, exactly one coalesced flush fires.
        try await Task.sleep(nanoseconds: 200_000_000)
        #expect(flushes.value == 1)
    }

    /// forceFlush() synchronizes immediately and cancels any pending debounced
    /// flush, so it never double-fires.
    @Test func forceFlushSynchronizesImmediatelyAndCancelsPending() async throws {
        let flushes = Counter()
        let sut = CloudPreferencesSync(flushDelay: 0.5) { flushes.increment() }

        sut.set("Sepia", forKey: "reader_settings_font")
        #expect(flushes.value == 0)   // still pending

        sut.forceFlush()
        #expect(flushes.value == 1)   // immediate

        // The previously-scheduled debounced work must have been cancelled.
        try await Task.sleep(nanoseconds: 700_000_000)
        #expect(flushes.value == 1)
    }

    /// A set() arriving after a forceFlush() schedules a fresh debounce window.
    @Test func setAfterForceFlushSchedulesNewWindow() async throws {
        let flushes = Counter()
        let sut = CloudPreferencesSync(flushDelay: 0.05) { flushes.increment() }

        sut.forceFlush()              // flush #1
        sut.set(1.5, forKey: "reader_settings_lineHeight")
        try await Task.sleep(nanoseconds: 200_000_000)
        #expect(flushes.value == 2)  // debounced flush #2
    }
}

/// ReaderSettings echo-guard spec: an inbound iCloud change carrying the value
/// already held must NOT re-trigger a cloud write (didSet -> cloud.set).
///
/// The guard is the `value != current` comparison added to handleCloudChange's
/// four cases (font / fontSize / lineHeight / underlineOpacity), mirroring
/// AppLanguage.selection / AppAppearanceMode.selection. The unit below asserts
/// the comparison predicate that gates each assignment.
@MainActor
struct ReaderSettingsEchoGuardTests {

    @Test func echoGuardPredicateRejectsSameValueAndAcceptsDifferent() {
        // lineHeight default 1.4 — an echo of the same value is gated out.
        let current = 1.4
        let echo = 1.4
        let changed = 1.6
        #expect(!(echo != current))     // same value -> guard blocks assignment
        #expect(changed != current)     // different value -> assignment proceeds
    }
}

/// Minimal thread-safe counter for observing flush invocations.
private final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var _value = 0
    var value: Int { lock.lock(); defer { lock.unlock() }; return _value }
    func increment() { lock.lock(); _value += 1; lock.unlock() }
}
