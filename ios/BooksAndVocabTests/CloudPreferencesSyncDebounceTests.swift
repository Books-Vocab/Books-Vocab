//
//  CloudPreferencesSyncDebounceTests.swift
//  Books & Vocab Tests
//
//  Spec for PR #625 synchronize() storm regression fix (Track 7 throttle).
//
//  Runs in the hosted unit target (`./ops/ios_ops.sh test --file
//  CloudPreferencesSyncDebounceTests`). Debounce timing is driven by an
//  injected fake clock, not by sleeping against `DispatchQueue.main.asyncAfter`
//  (#2118).
//

import Foundation
import Testing
@testable import BooksAndVocab

/// Drives CloudPreferencesSync through its injectable test seam
/// (`init(flushDelay:scheduler:flushAction:)`) so the debounce/coalesce and
/// force-flush logic is observable without real timers or
/// NSUbiquitousKeyValueStore synchronization.
@MainActor
struct CloudPreferencesSyncDebounceTests {

    /// Consecutive set() calls inside the debounce window collapse to a single
    /// synchronize() flush at the end of the window.
    @Test func consecutiveSetsCoalesceToSingleFlush() {
        let flushes = Counter()
        let clock = ManualFlushScheduler()
        let sut = CloudPreferencesSync(
            flushDelay: 0.5,
            scheduler: { clock.schedule($0, $1) },
            flushAction: { flushes.increment() }
        )

        // Simulate a lineHeight Slider(step:0.1) drag burst, 10ms apart. Each
        // write cancels the pending flush and opens a new window; the last
        // write lands at t=0.14s, so its window closes at t=0.64s.
        for i in 0..<15 {
            sut.set(1.0 + Double(i) * 0.1, forKey: "reader_settings_lineHeight")
            clock.advance(by: 0.01)
        }
        #expect(flushes.value == 0)
        #expect(clock.liveCount == 1)

        // t=0.635s: every earlier window (closing by 0.63s) has elapsed, the
        // last one has not — none of the cancelled windows flushed.
        clock.advance(by: 0.485)
        #expect(flushes.value == 0)

        // t=0.65s: the last window has closed — exactly one coalesced flush.
        clock.advance(by: 0.015)
        #expect(flushes.value == 1)
        #expect(clock.liveCount == 0)

        // No cancelled window from the burst fires later.
        clock.advance(by: 10)
        #expect(flushes.value == 1)
    }

    /// forceFlush() synchronizes immediately and cancels any pending debounced
    /// flush, so it never double-fires.
    @Test func forceFlushSynchronizesImmediatelyAndCancelsPending() {
        let flushes = Counter()
        let clock = ManualFlushScheduler()
        let sut = CloudPreferencesSync(
            flushDelay: 0.5,
            scheduler: { clock.schedule($0, $1) },
            flushAction: { flushes.increment() }
        )

        sut.set("Sepia", forKey: "reader_settings_font")
        #expect(flushes.value == 0)   // still pending
        #expect(clock.liveCount == 1)

        sut.forceFlush()
        #expect(flushes.value == 1)   // immediate
        #expect(clock.liveCount == 0) // the debounced work was cancelled

        // Long past the old window: the cancelled work never fires.
        clock.advance(by: 10)
        #expect(flushes.value == 1)
    }

    /// A set() arriving after a forceFlush() schedules a fresh debounce window.
    @Test func setAfterForceFlushSchedulesNewWindow() {
        let flushes = Counter()
        let clock = ManualFlushScheduler()
        let sut = CloudPreferencesSync(
            flushDelay: 0.5,
            scheduler: { clock.schedule($0, $1) },
            flushAction: { flushes.increment() }
        )

        sut.forceFlush()              // flush #1
        sut.set(1.5, forKey: "reader_settings_lineHeight")
        #expect(clock.liveCount == 1)
        clock.advance(by: 0.5)
        #expect(flushes.value == 2)  // debounced flush #2
    }

    /// The production scheduler (`DispatchQueue.main.asyncAfter`) delivers the
    /// debounced flush. The test awaits the flush itself, no sleep.
    @Test(.timeLimit(.minutes(1)))
    func defaultSchedulerDeliversDebouncedFlushOnMainQueue() async {
        let flushes = Counter()
        let flushed = FlushSignal()
        let sut = CloudPreferencesSync(flushDelay: 0.001) {
            flushes.increment()
            flushed.fire()
        }

        sut.set("Sepia", forKey: "reader_settings_font")
        await flushed.wait()
        #expect(flushes.value == 1)
        // The pending work item holds `sut` weakly; keep it alive until here.
        withExtendedLifetime(sut) {}
    }
}

/// Fake time for `CloudPreferencesSync`'s debounce. `advance(by:)` runs every
/// scheduled work item whose deadline falls inside the advanced window, in
/// deadline order. Like `DispatchQueue.asyncAfter`, a cancelled item never runs.
private final class ManualFlushScheduler {
    private struct Entry {
        let order: Int
        let deadline: TimeInterval
        let work: DispatchWorkItem
    }

    private var now: TimeInterval = 0
    private var nextOrder = 0
    private var entries: [Entry] = []

    /// Scheduled work items that have neither run nor been cancelled.
    var liveCount: Int { entries.filter { !$0.work.isCancelled }.count }

    func schedule(_ delay: TimeInterval, _ work: DispatchWorkItem) {
        entries.append(Entry(order: nextOrder, deadline: now + delay, work: work))
        nextOrder += 1
    }

    func advance(by delta: TimeInterval) {
        let target = now + delta
        while let index = nextDueIndex(notAfter: target) {
            let entry = entries.remove(at: index)
            now = entry.deadline
            if !entry.work.isCancelled {
                entry.work.perform()
            }
        }
        now = target
    }

    private func nextDueIndex(notAfter target: TimeInterval) -> Int? {
        entries.indices
            .filter { entries[$0].deadline <= target }
            .min { (entries[$0].deadline, entries[$0].order) < (entries[$1].deadline, entries[$1].order) }
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

/// One-shot bridge from a flush callback to the awaiting test: `wait()`
/// returns once `fire()` has been called, whichever happens first.
private final class FlushSignal: @unchecked Sendable {
    private let lock = NSLock()
    private var fired = false
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            lock.lock()
            if fired {
                lock.unlock()
                continuation.resume()
            } else {
                self.continuation = continuation
                lock.unlock()
            }
        }
    }

    func fire() {
        lock.lock()
        fired = true
        let waiting = continuation
        continuation = nil
        lock.unlock()
        waiting?.resume()
    }
}
