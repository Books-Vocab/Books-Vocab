import Foundation
import Testing
@testable import BooksAndVocab

// Tests for the toast notification system: AppToastItem model + AppToastCoordinator
// queueing / auto-dismiss lifecycle.
//
// Trade-offs:
// - AppToast / ToastOverlayModifier are SwiftUI Views with no extractable pure
//   state seam (tintColor / dragOffset are private @State driven by gestures),
//   so they are not unit-tested here; the testable seam is the @Observable
//   AppToastCoordinator and the AppToastItem value type.
// - AppToastCoordinator has no de-dup: show() unconditionally replaces `current`.
//   Tests below assert this replace-latest behavior rather than de-dup.
// - Auto-dismiss timing runs on an injected `ManualToastScheduler`: tests advance
//   fake time to exactly the deadline instead of sleeping against real timers,
//   so they neither pass late nor fail on a stalled main queue (#2118). The
//   production `AppToastTaskScheduler` is pinned separately on its own
//   contract (runs after the delay, a cancelled action never runs).

@Suite("ToastNotification")
@MainActor
struct ToastNotificationTests {

    // MARK: - AppToastItem model

    @Test func itemDefaultImagePerStyle() {
        #expect(AppToastItem(message: "a", style: .success).systemImage == "checkmark")
        #expect(AppToastItem(message: "a", style: .info).systemImage == "info.circle")
        #expect(AppToastItem(message: "a", style: .warning).systemImage == "exclamationmark.triangle")
        #expect(AppToastItem(message: "a", style: .error).systemImage == "xmark.circle")
    }

    @Test func itemCustomImageOverridesDefault() {
        let item = AppToastItem(message: "a", systemImage: "star", style: .success)
        #expect(item.systemImage == "star")
    }

    @Test func itemDurationPerStyle() {
        #expect(AppToastItem(message: "a", style: .success).duration == 2.5)
        #expect(AppToastItem(message: "a", style: .info).duration == 2.5)
        #expect(AppToastItem(message: "a", style: .warning).duration == 4.0)
        #expect(AppToastItem(message: "a", style: .error).duration == 4.0)
    }

    @Test func itemIdentityIsUnique() {
        let a = AppToastItem(message: "same", style: .info)
        let b = AppToastItem(message: "same", style: .info)
        // Distinct UUID → distinct identity and inequality even with same payload.
        #expect(a.id != b.id)
        #expect(a != b)
    }

    // MARK: - Coordinator enqueue

    @Test func coordinatorStartsEmpty() {
        let coordinator = AppToastCoordinator()
        #expect(coordinator.current == nil)
    }

    @Test func showEnqueuesItem() {
        let coordinator = AppToastCoordinator()
        let item = AppToastItem(message: "hello", style: .info)
        coordinator.show(item)
        #expect(coordinator.current == item)
    }

    @Test func convenienceHelpersSetStyle() {
        let coordinator = AppToastCoordinator()

        coordinator.success("done")
        #expect(coordinator.current?.style == .success)
        #expect(coordinator.current?.message == "done")

        coordinator.info("fyi")
        #expect(coordinator.current?.style == .info)

        coordinator.warning("careful")
        #expect(coordinator.current?.style == .warning)

        coordinator.error("oops")
        #expect(coordinator.current?.style == .error)
        #expect(coordinator.current?.message == "oops")
    }

    // MARK: - Coordinator dequeue / dismiss

    @Test func dismissClearsCurrent() {
        let coordinator = AppToastCoordinator()
        coordinator.success("done")
        #expect(coordinator.current != nil)
        coordinator.dismiss()
        #expect(coordinator.current == nil)
    }

    @Test func dismissOnEmptyIsNoOp() {
        let coordinator = AppToastCoordinator()
        coordinator.dismiss()
        #expect(coordinator.current == nil)
    }

    // MARK: - Multi-toast queueing (replace-latest semantics)

    @Test func secondShowReplacesFirst() {
        let coordinator = AppToastCoordinator()
        let first = AppToastItem(message: "first", style: .info)
        let second = AppToastItem(message: "second", style: .warning)
        coordinator.show(first)
        coordinator.show(second)
        // No real queue: latest wins, only one toast is ever visible.
        #expect(coordinator.current == second)
    }

    @Test func rapidShowsKeepOnlyLatest() {
        let coordinator = AppToastCoordinator()
        for i in 0..<10 {
            coordinator.show(AppToastItem(message: "msg-\(i)", style: .info))
        }
        #expect(coordinator.current?.message == "msg-9")
    }

    @Test func duplicateMessageIsNotDeduped() {
        let coordinator = AppToastCoordinator()
        let first = AppToastItem(message: "dup", style: .info)
        coordinator.show(first)
        let firstID = coordinator.current?.id

        let second = AppToastItem(message: "dup", style: .info)
        coordinator.show(second)
        let secondID = coordinator.current?.id

        // Same message but the coordinator replaces with the new item (distinct id).
        #expect(firstID != secondID)
        #expect(coordinator.current?.message == "dup")
    }

    // MARK: - Auto-dismiss timing (fake time)
    //
    // `show()` schedules the auto-dismiss whether or not VoiceOver is on
    // (the announcement is a side effect only), so these hold on any
    // simulator configuration.

    @Test func toastPersistsUntilJustBeforeDeadline() {
        let clock = ManualToastScheduler()
        let coordinator = AppToastCoordinator(scheduler: clock)
        coordinator.success("done") // 2.5s
        clock.advance(by: .milliseconds(2_499))
        #expect(coordinator.current?.message == "done")
    }

    @Test func toastAutoDismissesAtDeadline() {
        let clock = ManualToastScheduler()
        let coordinator = AppToastCoordinator(scheduler: clock)
        coordinator.success("done") // 2.5s
        clock.advance(by: .milliseconds(2_500))
        #expect(coordinator.current == nil)
        #expect(clock.scheduledCount == 0)
    }

    @Test func autoDismissUsesTheItemStyleDuration() {
        let clock = ManualToastScheduler()
        let coordinator = AppToastCoordinator(scheduler: clock)
        coordinator.error("failed") // 4.0s
        clock.advance(by: .milliseconds(3_999))
        #expect(coordinator.current?.message == "failed")
        clock.advance(by: .milliseconds(1))
        #expect(coordinator.current == nil)
    }

    @Test func newShowResetsAutoDismissTimer() {
        let clock = ManualToastScheduler()
        let coordinator = AppToastCoordinator(scheduler: clock)
        coordinator.success("first") // deadline t=2.5s
        clock.advance(by: .seconds(2))
        // Re-show before the first deadline: the first timer is cancelled and a
        // fresh 2.5s timer replaces it, so only one dismissal is ever pending.
        coordinator.success("second") // deadline t=4.5s
        #expect(clock.scheduledCount == 1)
        // Past the original deadline (t=2.8s) — the second toast survives.
        clock.advance(by: .milliseconds(800))
        #expect(coordinator.current?.message == "second")
        // Its own deadline still dismisses it.
        clock.advance(by: .milliseconds(1_700))
        #expect(coordinator.current == nil)
    }

    @Test func manualDismissCancelsPendingAutoDismiss() {
        let clock = ManualToastScheduler()
        let coordinator = AppToastCoordinator(scheduler: clock)
        coordinator.success("done") // deadline t=2.5s
        coordinator.dismiss()
        #expect(coordinator.current == nil)
        #expect(clock.scheduledCount == 0)
        // A fresh toast must not be cleared at the cancelled timer's deadline.
        coordinator.error("kept") // deadline t=4.0s
        clock.advance(by: .milliseconds(2_500))
        #expect(coordinator.current?.message == "kept")
        clock.advance(by: .milliseconds(1_500))
        #expect(coordinator.current == nil)
    }

    // MARK: - Production scheduler contract
    //
    // The fake-time tests above assume `AppToastTaskScheduler` runs an action
    // after its delay and never runs a cancelled one. These tests pin that
    // contract against real time by awaiting the action itself, with no sleep
    // in the test.

    @Test(.timeLimit(.minutes(1)))
    func taskSchedulerRunsActionAfterDelay() async {
        let scheduler = AppToastTaskScheduler()
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            _ = scheduler.schedule(after: .milliseconds(1)) {
                continuation.resume()
            }
        }
    }

    @Test(.timeLimit(.minutes(1)))
    func taskSchedulerNeverRunsCancelledAction() async {
        let scheduler = AppToastTaskScheduler()
        let fired = FiredActions()
        let cancelled = scheduler.schedule(after: .milliseconds(1)) {
            fired.names.append("cancelled")
        }
        cancelled.cancel()
        // The cancelled action is due first; once the later action has run,
        // an uncancelled one would already have fired too.
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            _ = scheduler.schedule(after: .milliseconds(20)) {
                fired.names.append("later")
                continuation.resume()
            }
        }
        #expect(fired.names == ["later"])
    }
}

/// Fake time for `AppToastCoordinator`. `advance(by:)` runs every scheduled,
/// uncancelled action whose deadline falls inside the advanced window, in
/// deadline order, synchronously on the main actor.
@MainActor
private final class ManualToastScheduler: AppToastScheduler {
    private struct Entry {
        let id: Int
        let deadline: Duration
        let action: @MainActor () -> Void
    }

    private var now: Duration = .zero
    private var nextID = 0
    private var entries: [Entry] = []

    /// Actions scheduled and neither run nor cancelled yet.
    var scheduledCount: Int { entries.count }

    func schedule(
        after delay: Duration,
        _ action: @escaping @MainActor () -> Void
    ) -> AppToastScheduledAction {
        let id = nextID
        nextID += 1
        entries.append(Entry(id: id, deadline: now + delay, action: action))
        return AppToastScheduledAction { [weak self] in
            self?.entries.removeAll { $0.id == id }
        }
    }

    func advance(by delta: Duration) {
        let target = now + delta
        while let index = nextDueIndex(notAfter: target) {
            let entry = entries.remove(at: index)
            now = entry.deadline
            entry.action()
        }
        now = target
    }

    private func nextDueIndex(notAfter target: Duration) -> Int? {
        entries.indices
            .filter { entries[$0].deadline <= target }
            .min { (entries[$0].deadline, entries[$0].id) < (entries[$1].deadline, entries[$1].id) }
    }
}

/// Records which scheduled actions ran, in order.
@MainActor
private final class FiredActions {
    var names: [String] = []
}
