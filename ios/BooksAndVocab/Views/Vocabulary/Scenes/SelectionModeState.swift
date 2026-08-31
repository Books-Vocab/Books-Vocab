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

    private var visibleIDs: Set<UUID> = []

    var isAllSelected: Bool {
        !visibleIDs.isEmpty && selectedIDs == visibleIDs
    }

    func updateVisibleIDs(_ ids: [UUID]) {
        let visibleIDs = Set(ids)
        self.visibleIDs = visibleIDs
        selectedIDs.formIntersection(visibleIDs)
    }

    func exit() {
        isSelecting = false
        selectedIDs.removeAll()
    }

    var selectionCount: Int { selectedIDs.count }
    var hasSelection: Bool { !selectedIDs.isEmpty }
}
