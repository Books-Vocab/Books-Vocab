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
        // MARK: Metric Hero Card (full-width card → .fillH: 滿寬、貼合高)
        playbook.addScenarios(of: "Vocab Shell · Metric Hero Card") {
            Scenario("Single", layout: .fillH) {
                wrapWide {
                    VocabMetricHeroCard(
                        title: "待複習",
                        description: "今天到期的卡片數",
                        value: "42"
                    )
                }
            }
            Scenario("Stacked metrics", layout: .fillH) {
                wrapWide {
                    VStack(spacing: 12) {
                        VocabMetricHeroCard(title: "總單字", description: "詞庫累積總量", value: "1,284")
                        VocabMetricHeroCard(title: "已掌握", description: "連續答對 3 次以上", value: "0")
                        VocabMetricHeroCard(title: "連續天數", description: "目前複習連勝", value: "128")
                    }
                }
            }
        }

        // MARK: Sort Pill (compact pill → .compressed: 貼合 intrinsic)
        playbook.addScenarios(of: "Vocab Shell · Sort Pill") {
            Scenario("Default (複習優先)", layout: .compressed) {
                VocabSortPillScene(initial: .default)
            }
            Scenario("Alphabetical", layout: .compressed) {
                VocabSortPillScene(initial: .alphabetical)
            }
            Scenario("Difficulty", layout: .compressed) {
                VocabSortPillScene(initial: .difficulty)
            }
        }

        // MARK: Review State Tab Selector (full-width filter bar → .fillH)
        // The vocabulary list's review-state filter bar (未學習 / 待複習 / 已複習).
        playbook.addScenarios(of: "Vocab Shell · Tab Selector") {
            Scenario("With counts · due selected", layout: .fillH) {
                VocabTabSelectorScene(initial: .due, counts: [.unlearned: 12, .due: 5, .reviewed: 38])
            }
            Scenario("No counts · unlearned selected", layout: .fillH) {
                VocabTabSelectorScene(initial: .unlearned, counts: [:])
            }
            Scenario("Zero counts · reviewed selected", layout: .fillH) {
                VocabTabSelectorScene(initial: .reviewed, counts: [.unlearned: 0, .due: 0, .reviewed: 0])
            }
        }

        // MARK: Review CTA Pill (compact capsule → .compressed)
        // brandHero 填色 capsule，依到期 / 未學數量切 single-button vs menu。
        playbook.addScenarios(of: "Vocab Shell · Review CTA Pill") {
            Scenario("Both types (menu)", layout: .compressed) {
                wrapCompact {
                    VocabReviewCTAPill(dueCount: 5, unlearnedCount: 12,
                                       onStartDue: {}, onStartUnlearned: {}, onStartMixed: {})
                }
            }
            Scenario("Due only", layout: .compressed) {
                wrapCompact {
                    VocabReviewCTAPill(dueCount: 5, unlearnedCount: 0,
                                       onStartDue: {}, onStartUnlearned: {}, onStartMixed: {})
                }
            }
            Scenario("Unlearned only", layout: .compressed) {
                wrapCompact {
                    VocabReviewCTAPill(dueCount: 0, unlearnedCount: 8,
                                       onStartDue: {}, onStartUnlearned: {}, onStartMixed: {})
                }
            }
        }
    }

    // MARK: - Layout helpers
    // 第一性原理：PNG = contentView.bounds。building block 不是一支手機，
    // 故不用 .fill（會把元件畫在整支裝置畫布裡、佔幾%空白）。
    // .fillH → 滿寬貼合高（bar/row/card）；.compressed → 貼合 intrinsic（pill/chip）。

    /// 全寬元件：撐滿畫布寬、貼合內容高。搭 `layout: .fillH`。
    @ViewBuilder
    private static func wrapWide<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            content()
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(24)
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    /// 緊湊元件：畫布貼合 intrinsic 尺寸。搭 `layout: .compressed`。
    @ViewBuilder
    private static func wrapCompact<Content: View>(@ViewBuilder _ content: @escaping () -> Content) -> some View {
        AppThemeContainer {
            content()
                .padding(24)
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
