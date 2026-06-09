#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `SelectionModeState` — the multi-select state machine shared by the
/// vocab list scenes (enter on long-press, toggle, select-all, exit). Pure
/// in-memory logic with no SwiftUI/`@Query` coupling, so it is exercised
/// directly. Locks the `isAllSelected` visible-count contract and the exit
/// reset that several scenes rely on for toolbar correctness.
@MainActor
struct SelectionModeStateTests {

    private let a = UUID(), b = UUID(), c = UUID()

    @Test func enter_startsSelectingWithSingleSeed() {
        let s = SelectionModeState()
        s.enter(with: a)
        #expect(s.isSelecting)
        #expect(s.selectedIDs == [a])
        #expect(s.selectionCount == 1)
        #expect(s.hasSelection)
    }

    @Test func toggle_addsAndRemoves() {
        let s = SelectionModeState()
        s.enter(with: a)
        s.toggle(b)
        #expect(s.selectedIDs == [a, b])
        s.toggle(a)
        #expect(s.selectedIDs == [b])
        #expect(s.hasSelection)
        s.toggle(b)
        #expect(!s.hasSelection)
    }

    @Test func selectAll_replacesSelection() {
        let s = SelectionModeState()
        s.enter(with: a)
        s.selectAll([a, b, c])
        #expect(s.selectedIDs == [a, b, c])
        s.deselectAll()
        #expect(s.selectedIDs.isEmpty)
    }

    @Test func isAllSelected_requiresVisibleCountMatch() {
        let s = SelectionModeState()
        // visibleCount defaults to 0 → never "all selected", even with picks.
        s.enter(with: a)
        #expect(!s.isAllSelected)

        s.updateVisibleCount(3)
        s.selectAll([a, b, c])
        #expect(s.isAllSelected)

        s.toggle(c)               // 2 of 3 → no longer all
        #expect(!s.isAllSelected)
    }

    @Test func isAllSelected_falseWhenNoVisibleRows() {
        let s = SelectionModeState()
        s.updateVisibleCount(0)
        s.selectAll([])
        // count == visibleCount == 0, but the guard requires visibleCount > 0.
        #expect(!s.isAllSelected)
    }

    @Test func exit_resetsEverything() {
        let s = SelectionModeState()
        s.enter(with: a)
        s.selectAll([a, b, c])
        s.updateVisibleCount(3)
        s.exit()
        #expect(!s.isSelecting)
        #expect(s.selectedIDs.isEmpty)
        #expect(!s.isAllSelected)   // visibleCount also reset to 0
    }
}
#endif
