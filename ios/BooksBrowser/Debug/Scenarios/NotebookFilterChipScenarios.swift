#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for `NotebookFilterChip` and its picker sheet.
/// The chip uses a `@Query` for notebooks, so the chip scenarios install an
/// in-memory `modelContainer` (empty DB — chip renders from the binding only).
/// The picker sheet takes a plain `[Notebook]` array, so it is fed synthetic
/// fixtures directly without a container.
enum NotebookFilterChipScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Chip states
        playbook.addScenarios(of: "Notebook Filter Chip · Chip") {
            Scenario("Unfiltered", layout: .fill) {
                NotebookFilterChipScene(initialFilter: NotebookFilter())
            }
            Scenario("Single selected", layout: .fill) {
                NotebookFilterChipScene(initialFilter: NotebookFilter(selectedIds: ["nb-1"]))
            }
            Scenario("Multiple selected", layout: .fill) {
                NotebookFilterChipScene(initialFilter: NotebookFilter(selectedIds: ["nb-1", "nb-2", "nb-3"]))
            }
        }

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

// MARK: - Scene harnesses

/// Hosts the chip with a live `@State` binding and an empty in-memory container
/// so the `@Query` dependency resolves.
private struct NotebookFilterChipScene: View {
    @State private var filter: NotebookFilter

    init(initialFilter: NotebookFilter) {
        self._filter = State(initialValue: initialFilter)
    }

    var body: some View {
        AppThemeContainer {
            VStack(spacing: AppSpacing.s4) {
                NotebookFilterChip(filter: $filter)
            }
            .padding()
            .modelContainer(for: [Notebook.self], inMemory: true)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

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
