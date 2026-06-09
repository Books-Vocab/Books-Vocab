#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `NotebookReviewActionBar` — the today-review pill
/// cluster in the notebook list header. Pure presentation; all states driven by
/// the value-type init (dueCount / unlearnedCount / hasReviewItems / etc.).
enum NotebookReviewActionBarScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Review Action Bar") {
            // Both due + unlearned → CTA renders as a multi-mode Menu (total badge).
            Scenario("Both types (menu)", layout: .fill) {
                bar(
                    dueCount: 12,
                    unlearnedCount: 8,
                    hasReviewItems: true,
                    notebookCount: 5,
                    isFiltered: false,
                    canCreate: true
                )
            }

            // Only due items → single-mode due button.
            Scenario("Due only", layout: .fill) {
                bar(
                    dueCount: 7,
                    unlearnedCount: 0,
                    hasReviewItems: true,
                    notebookCount: 3,
                    isFiltered: false,
                    canCreate: true
                )
            }

            // Only unlearned items → single-mode unlearned button.
            Scenario("Unlearned only", layout: .fill) {
                bar(
                    dueCount: 0,
                    unlearnedCount: 4,
                    hasReviewItems: true,
                    notebookCount: 3,
                    isFiltered: false,
                    canCreate: true
                )
            }

            // Filter active (highlighted) with active filter excluding all due/unlearned:
            // title still shows, CTA hidden (hasReviewItems true but both counts 0).
            Scenario("Filtered, no matching items", layout: .fill) {
                bar(
                    dueCount: 0,
                    unlearnedCount: 0,
                    hasReviewItems: true,
                    notebookCount: 6,
                    isFiltered: true,
                    canCreate: true
                )
            }

            // No review items at all + single notebook (no filter pill) + create disabled:
            // bare create pill only.
            Scenario("Empty, create disabled", layout: .fill) {
                bar(
                    dueCount: 0,
                    unlearnedCount: 0,
                    hasReviewItems: false,
                    notebookCount: 1,
                    isFiltered: false,
                    canCreate: false
                )
            }
        }
    }

    private static func bar(
        dueCount: Int,
        unlearnedCount: Int,
        hasReviewItems: Bool,
        notebookCount: Int,
        isFiltered: Bool,
        canCreate: Bool
    ) -> some View {
        AppThemeContainer {
            NotebookReviewActionBar(
                dueCount: dueCount,
                unlearnedCount: unlearnedCount,
                hasReviewItems: hasReviewItems,
                notebookCount: notebookCount,
                isFiltered: isFiltered,
                canCreate: canCreate,
                onReviewAll: {},
                onReviewDue: {},
                onReviewUnlearned: {},
                onFilter: {},
                onCreate: {}
            )
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
