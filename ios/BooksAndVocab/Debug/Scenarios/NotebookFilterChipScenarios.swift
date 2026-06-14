#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the `NotebookFilterChip` picker sheet.
/// The picker sheet takes a plain `[Notebook]` array, but those notebooks still
/// come from UI World `notebook.*` seeds. Missing seed or SwiftData seed failure
/// fail at catalog construction time through `NotebookFixtures.renderModel`.
enum NotebookFilterChipScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Picker sheet
        playbook.addScenarios(of: "Notebook Filter Chip · Picker") {
            Scenario("With notebooks", layout: .fill) {
                NotebookFilterPickerScene(
                    fixture: .populated,
                    selectedNotebookIndex: 1
                )
            }
            Scenario("Empty list", layout: .fill) {
                NotebookFilterPickerScene(
                    fixture: .empty,
                    selectedNotebookIndex: nil
                )
            }
        }
    }
}

// MARK: - Scene harness

/// Renders the picker sheet directly with notebooks materialized from UI World.
private struct NotebookFilterPickerScene: View {
    @State private var filter: NotebookFilter
    let notebooks: [Notebook]

    init(fixture: NotebookFixtureID, selectedNotebookIndex: Int?) {
        let model = MainActor.assumeIsolated {
            NotebookFixtures.renderModel(for: fixture)
        }
        if let selectedNotebookIndex {
            guard model.notebooks.indices.contains(selectedNotebookIndex) else {
                preconditionFailure("UI World notebook.\(fixture.rawValue) is missing selected notebook index \(selectedNotebookIndex)")
            }
            self._filter = State(initialValue: NotebookFilter(selectedIds: [model.notebooks[selectedNotebookIndex].remoteId]))
        } else {
            self._filter = State(initialValue: NotebookFilter())
        }
        self.notebooks = model.notebooks
    }

    var body: some View {
        AppThemeContainer {
            NotebookFilterPickerSheet(filter: $filter, notebooks: notebooks)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
