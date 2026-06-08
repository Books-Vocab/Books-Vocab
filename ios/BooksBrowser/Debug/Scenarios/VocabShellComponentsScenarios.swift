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

        // MARK: Review State Tab Selector
        // The vocabulary list's review-state filter bar (未學習 / 待複習 / 已複習).
        playbook.addScenarios(of: "Vocab Shell · Tab Selector") {
            Scenario("With counts · due selected", layout: .fill) {
                VocabTabSelectorScene(initial: .due, counts: [.unlearned: 12, .due: 5, .reviewed: 38])
            }
            Scenario("No counts · unlearned selected", layout: .fill) {
                VocabTabSelectorScene(initial: .unlearned, counts: [:])
            }
            Scenario("Zero counts · reviewed selected", layout: .fill) {
                VocabTabSelectorScene(initial: .reviewed, counts: [.unlearned: 0, .due: 0, .reviewed: 0])
            }
        }

        // MARK: Review CTA Pill
        // brandHero 填色 capsule，依到期 / 未學數量切 single-button vs menu。
        playbook.addScenarios(of: "Vocab Shell · Review CTA Pill") {
            Scenario("Both types (menu)", layout: .fill) {
                wrap {
                    VocabReviewCTAPill(dueCount: 5, unlearnedCount: 12,
                                       onStartDue: {}, onStartUnlearned: {}, onStartMixed: {})
                }
            }
            Scenario("Due only", layout: .fill) {
                wrap {
                    VocabReviewCTAPill(dueCount: 5, unlearnedCount: 0,
                                       onStartDue: {}, onStartUnlearned: {}, onStartMixed: {})
                }
            }
            Scenario("Unlearned only", layout: .fill) {
                wrap {
                    VocabReviewCTAPill(dueCount: 0, unlearnedCount: 8,
                                       onStartDue: {}, onStartUnlearned: {}, onStartMixed: {})
                }
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

// MARK: - Binding-backed scene harnesses

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

/// Hosts `VocabTabSelector` with a live `@State` selection so the segment
/// switch renders the selected pill. `counts` empty → options carry no count badge.
private struct VocabTabSelectorScene: View {
    @State private var selection: VocabularyReviewState
    let counts: [VocabularyReviewState: Int]

    init(initial: VocabularyReviewState, counts: [VocabularyReviewState: Int]) {
        self._selection = State(initialValue: initial)
        self.counts = counts
    }

    var body: some View {
        let options = VocabularyReviewState.allCases.map {
            VocabTabOption(id: $0, title: $0.title, count: counts[$0])
        }
        return AppThemeContainer {
            VocabTabSelector(options: options, selection: $selection)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
