#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `VocabHighlightColorPresetPicker` (Reader vocab highlight color chooser).
/// The picker is a stateless component bound to a `VocabHighlightColorPreset`; each scenario
/// drives it through a `@State` binding inside a `View` struct so selection chrome renders.
enum VocabHighlightPickerScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Vocab Highlight Picker") {
            Scenario("Paper selected", layout: .fill) {
                PickerScene(initial: .paper)
            }
            Scenario("Blue selected", layout: .fill) {
                PickerScene(initial: .blue)
            }
            Scenario("Sage selected", layout: .fill) {
                PickerScene(initial: .sage)
            }
            Scenario("Rose selected", layout: .fill) {
                PickerScene(initial: .rose)
            }
            Scenario("Dark mode", layout: .fill) {
                PickerScene(initial: .blue)
                    .preferredColorScheme(.dark)
            }
        }
    }
}

// MARK: - Scene harness

private struct PickerScene: View {
    @State private var selection: VocabHighlightColorPreset

    init(initial: VocabHighlightColorPreset) {
        self._selection = State(initialValue: initial)
    }

    var body: some View {
        AppThemeContainer {
            VocabHighlightColorPresetPicker(
                selection: $selection,
                title: "螢光標記顏色"
            )
            .environment(\.appSkin, AppSkin.previewNeutral)
            .padding(AppSpacing.s4)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
