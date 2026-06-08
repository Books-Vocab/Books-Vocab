#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the leaf chrome components in
/// `VocabShellComponents.swift` + `VocabShellComponents+Actions.swift`.
/// All components are pure @Environment(\.appSkin) / @Binding views — no
/// @MainActor init traps — but binding-backed components are hosted in
/// @State scene structs so Slider / Menu / Search interactions render live.
enum VocabShellComponentsScenarios {
    static func register(in playbook: Playbook) {
        // MARK: Metric Hero Card
        playbook.addScenarios(of: "Vocab Shell · Metric Hero Card") {
            Scenario("Single", layout: .fill) {
                wrap {
                    VocabMetricHeroCard(
                        title: "待複習",
                        description: "今天到期的卡片數",
                        value: "42"
                    )
                }
            }
            Scenario("Stacked metrics", layout: .fill) {
                wrap {
                    VStack(spacing: 12) {
                        VocabMetricHeroCard(title: "總單字", description: "詞庫累積總量", value: "1,284")
                        VocabMetricHeroCard(title: "已掌握", description: "連續答對 3 次以上", value: "0")
                        VocabMetricHeroCard(title: "連續天數", description: "目前複習連勝", value: "128")
                    }
                }
            }
        }

        // MARK: Sort Pill
        playbook.addScenarios(of: "Vocab Shell · Sort Pill") {
            Scenario("Default (複習優先)", layout: .fill) {
                VocabSortPillScene(initial: .default)
            }
            Scenario("Alphabetical", layout: .fill) {
                VocabSortPillScene(initial: .alphabetical)
            }
            Scenario("Difficulty", layout: .fill) {
                VocabSortPillScene(initial: .difficulty)
            }
        }
    }

    // MARK: - Layout helper (no @MainActor types involved → nonisolated ok)

    @ViewBuilder
    private static func wrap<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            content()
                .padding(24)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}

// MARK: - Binding-backed scene harness

private struct VocabSortPillScene: View {
    @State private var sortOption: KGVocabSortOption

    init(initial: KGVocabSortOption) {
        self._sortOption = State(initialValue: initial)
    }

    var body: some View {
        AppThemeContainer {
            VocabSortPill(sortOption: $sortOption)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
