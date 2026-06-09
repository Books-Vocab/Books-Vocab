#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `SettingsDeleteAccountSheet` — the multi-step
/// destructive account-deletion confirmation sheet.
///
/// The sheet's init is trivial (`onConfirm` + `isDeleting`); both rendered
/// states are reachable without @MainActor-isolated dependencies, so the
/// scenarios construct the view directly inside the Scenario closures.
///
/// NOTE: the sheet's interactive states (acknowledgements toggled, confirm
/// text matched, countdown running) are driven by internal @State that cannot
/// be seeded from outside without a preview seam. We therefore catalog the two
/// externally-controlled states: idle (initial) and deleting (in-progress).
enum DeleteAccountSheetScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Delete Account Sheet") {
            Scenario("Idle", layout: .fill) {
                AppThemeContainer {
                    SettingsDeleteAccountSheet(
                        onConfirm: {},
                        isDeleting: false
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }

            Scenario("Deleting (in progress)", layout: .fill) {
                AppThemeContainer {
                    SettingsDeleteAccountSheet(
                        onConfirm: {},
                        isDeleting: true
                    )
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
