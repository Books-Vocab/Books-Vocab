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

    var isAllSelected: Bool = false

    func updateAllSelectedState(visibleIDs: [UUID]) {
        isAllSelected = !visibleIDs.isEmpty && selectedIDs.count == visibleIDs.count
    }

    func exit() {
        isSelecting = false
        selectedIDs.removeAll()
        isAllSelected = false
    }

    var selectionCount: Int { selectedIDs.count }
    var hasSelection: Bool { !selectedIDs.isEmpty }
}
