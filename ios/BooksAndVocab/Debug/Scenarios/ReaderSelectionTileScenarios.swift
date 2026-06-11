#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `ReaderSelectionTile` — the reusable selected/unselected
/// chrome tile that backs the reader's vocab highlight color / preset pickers
/// (`VocabHighlightColorPresetPicker`, `ReaderSettingsPresenter+Vocab`).
///
/// State is binary (`isSelected`): selected fills with `mutedFill` + `cardBorder`
/// and promotes content to `primaryText`; unselected uses `pageBackground` + a
/// faint divider border and `secondaryText`. Both states are shown side-by-side
/// so the web port (R3/R4) can diff fill/border/text-tone deltas in one frame.
enum ReaderSelectionTileScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Reader Selection Tile") {
            Scenario("Selected vs Unselected", layout: .fillH) {
                tileScene {
                    ReaderSelectionTile(isSelected: true) {
                        Text("已選").padding(AppSpacing.s3)
                    }
                    ReaderSelectionTile(isSelected: false) {
                        Text("未選").padding(AppSpacing.s3)
                    }
                }
            }
            Scenario("Selected", layout: .fillH) {
                tileScene {
                    ReaderSelectionTile(isSelected: true) {
                        Text("已選").padding(AppSpacing.s3)
                    }
                }
            }
            Scenario("Unselected", layout: .fillH) {
                tileScene {
                    ReaderSelectionTile(isSelected: false) {
                        Text("未選").padding(AppSpacing.s3)
                    }
                }
            }
        }
    }

    private static func tileScene<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            HStack(spacing: AppSpacing.s3) {
                content()
            }
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
