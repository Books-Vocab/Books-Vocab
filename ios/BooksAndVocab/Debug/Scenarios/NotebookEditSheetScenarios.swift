#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `NotebookEditSheet` — the create / edit single
/// vocab-notebook sheet.
///
/// `NotebookEditSheet` is driven by transient `Mode` state rather than
/// SwiftData, so its modes come from UI World `notebook.editGallery`.
/// Missing edit states, unknown patterns, or missing cover assets fail at
/// scenario construction time.
///
enum NotebookEditSheetScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Edit") {
            Scenario("Create · blank", layout: .fill) {
                NotebookEditSheetScene(stateID: "create_blank")
            }

            Scenario("Edit · color + pattern", layout: .fill) {
                NotebookEditSheetScene(stateID: "edit_color_pattern")
            }

            Scenario("Edit · color only", layout: .fill) {
                NotebookEditSheetScene(stateID: "edit_color_only")
            }

            Scenario("Edit · long name", layout: .fill) {
                NotebookEditSheetScene(stateID: "edit_long_name")
            }

            Scenario("Edit · custom image", layout: .fill) {
                NotebookEditSheetScene(stateID: "edit_custom_image")
            }

            Scenario("Edit · empty name (save disabled)", layout: .fill) {
                NotebookEditSheetScene(stateID: "edit_empty_name")
            }
        }
    }
}

private struct NotebookEditSheetScene: View {
    let mode: NotebookEditSheet.Mode

    init(stateID: String) {
        self.mode = NotebookFixtures.editSheetMode(id: stateID, for: .editGallery)
    }

    var body: some View {
        AppThemeContainer {
            NotebookEditSheet(mode: mode, onSave: { _ in })
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
