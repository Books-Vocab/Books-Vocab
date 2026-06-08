#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the `NotebookFilterChip` picker sheet.
/// The picker sheet takes a plain `[Notebook]` array, so it is fed synthetic
/// fixtures directly without a container.
enum NotebookFilterChipScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Picker sheet
        playbook.addScenarios(of: "Notebook Filter Chip · Picker") {
            Scenario("With notebooks", layout: .fill) {
                NotebookFilterPickerScene(
                    initialFilter: NotebookFilter(selectedIds: ["nb-1"]),
                    notebooks: Self.sampleNotebooks()
                )
            }
            Scenario("Empty list", layout: .fill) {
                NotebookFilterPickerScene(
                    initialFilter: NotebookFilter(),
                    notebooks: []
                )
            }
        }
    }

    // MARK: - Fixtures

    private static func sampleNotebooks() -> [Notebook] {
        [
            Notebook(remoteId: "nb-1", name: "雅思核心字", color: "#4F46E5"),
            Notebook(remoteId: "nb-2", name: "商業英文", color: "#16A34A"),
            Notebook(remoteId: "nb-3", name: "科幻小說生字", color: "#DC2626"),
            Notebook(remoteId: "nb-4", name: "未分類"),
        ]
    }
}

// MARK: - Scene harness

/// Renders the picker sheet directly with synthetic notebooks (no `@Query`).
private struct NotebookFilterPickerScene: View {
    @State private var filter: NotebookFilter
    let notebooks: [Notebook]

    init(initialFilter: NotebookFilter, notebooks: [Notebook]) {
        self._filter = State(initialValue: initialFilter)
        self.notebooks = notebooks
    }

    var body: some View {
        AppThemeContainer {
            NotebookFilterPickerSheet(filter: $filter, notebooks: notebooks)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
