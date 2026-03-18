import Foundation

@Observable @MainActor
final class SelectionModeState {
    var isSelecting = false
    private(set) var selectedIDs: Set<UUID> = []

    func enter(with id: UUID) {
        isSelecting = true
        selectedIDs = [id]
    }

    func toggle(_ id: UUID) {
        if selectedIDs.contains(id) {
            selectedIDs.remove(id)
        } else {
            selectedIDs.insert(id)
        }
    }

    func selectAll(_ ids: [UUID]) {
        selectedIDs = Set(ids)
    }

    func deselectAll() {
        selectedIDs.removeAll()
    }

    private var visibleCount: Int = 0

    var isAllSelected: Bool {
        visibleCount > 0 && selectedIDs.count == visibleCount
    }

    func updateVisibleCount(_ count: Int) {
        visibleCount = count
    }

    func exit() {
        isSelecting = false
        selectedIDs.removeAll()
        visibleCount = 0
    }

    var selectionCount: Int { selectedIDs.count }
    var hasSelection: Bool { !selectedIDs.isEmpty }
}
