#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SelectionToolbar` — the bottom action bar shown during
/// multi-select in the vocabulary list. State is driven purely by `selectionCount`
/// (0 disables/greys the buttons; >0 enables Archive + Delete).
enum SelectionToolbarScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Selection Toolbar") {
            Scenario("No selection (disabled)", layout: .fillH) {
                toolbarScene(count: 0)
            }
            Scenario("Single selected", layout: .fillH) {
                toolbarScene(count: 1)
            }
            Scenario("Multiple selected", layout: .fillH) {
                toolbarScene(count: 12)
            }
        }
    }

    private static func toolbarScene(count: Int) -> some View {
        AppThemeContainer {
            VStack {
                Spacer()
                SelectionToolbar(
                    selectionCount: count,
                    onArchive: {},
                    onDelete: {}
                )
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
