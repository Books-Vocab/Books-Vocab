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
// - Auto-dismiss timing uses the real (short) production durations. To keep the
//   suite fast, timing assertions sample BEFORE the deadline (no full wait) and
//   the post-deadline case uses the success style (2.5s) only.

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

    // MARK: - Auto-dismiss timing
    //
    // These timing tests assume VoiceOver is OFF (the default state of CI
    // simulators). When VoiceOver is ON, `AppToastCoordinator.show()` returns
    // early via `announceIfVoiceOver` and never schedules a `dismissTask`, so
    // the auto-dismiss and timer-reset assertions below would not hold.

    @Test func toastPersistsBeforeDeadline() async throws {
        let coordinator = AppToastCoordinator()
        coordinator.success("done") // 2.5s duration
        // Sample well before the deadline — toast must still be visible.
        try await Task.sleep(for: .milliseconds(300))
        #expect(coordinator.current != nil)
    }

    @Test func toastAutoDismissesAfterDuration() async throws {
        let coordinator = AppToastCoordinator()
        coordinator.success("done") // 2.5s duration
        // Wait past the deadline plus animation slack.
        try await Task.sleep(for: .seconds(3))
        #expect(coordinator.current == nil)
    }

    @Test func newShowResetsAutoDismissTimer() async throws {
        let coordinator = AppToastCoordinator()
        coordinator.success("first") // 2.5s
        try await Task.sleep(for: .seconds(2))
        // Re-show before the first deadline: cancels prior task, restarts timer.
        coordinator.success("second")
        // 1s after the original deadline — the second toast must survive
        // because its 2.5s timer restarted.
        try await Task.sleep(for: .milliseconds(800))
        #expect(coordinator.current?.message == "second")
    }

    @Test func manualDismissCancelsPendingAutoDismiss() async throws {
        let coordinator = AppToastCoordinator()
        coordinator.success("done") // 2.5s
        coordinator.dismiss()
        #expect(coordinator.current == nil)
        // Show a fresh toast, then confirm the cancelled timer cannot clear it.
        coordinator.error("kept") // 4.0s
        try await Task.sleep(for: .seconds(3))
        #expect(coordinator.current?.message == "kept")
    }
}
