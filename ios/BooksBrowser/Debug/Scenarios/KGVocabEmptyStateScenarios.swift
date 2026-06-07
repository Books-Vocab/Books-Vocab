#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Vocabulary KG empty-state copy resolver
/// (`KGVocabEmptyState`). The resolver is a pure title/description/icon
/// branch selector; these scenarios render each branch through the same
/// `AppEmptyStateContent` view the production list uses, so the visual
/// regression covers icon + title + description per branch.
enum KGVocabEmptyStateScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "KG Empty State") {
            // Branch 1: 整本 notebook 沒卡 — 含「重新整理」CTA。
            Scenario("No entries (with CTA)", layout: .fill) {
                EmptyStateScene(
                    hasNoEntries: true,
                    searchText: "",
                    filters: [],
                    showsAction: true
                )
            }
            // 同 branch 但未登入 → 無 CTA。
            Scenario("No entries (logged out)", layout: .fill) {
                EmptyStateScene(
                    hasNoEntries: true,
                    searchText: "",
                    filters: [],
                    showsAction: false
                )
            }
            // Branch 2: 搜尋無結果。
            Scenario("Search no match", layout: .fill) {
                EmptyStateScene(
                    hasNoEntries: false,
                    searchText: "serendipity",
                    filters: [],
                    showsAction: false
                )
            }
            // Branch 3a: 單一篩選（待複習）→ 專屬圖示。
            Scenario("Single filter (due)", layout: .fill) {
                EmptyStateScene(
                    hasNoEntries: false,
                    searchText: "",
                    filters: [.due],
                    showsAction: false
                )
            }
            // Branch 3b: 多選篩選 → 通用篩選圖示。
            Scenario("Multi filter", layout: .fill) {
                EmptyStateScene(
                    hasNoEntries: false,
                    searchText: "",
                    filters: [.unlearned, .reviewed],
                    showsAction: false
                )
            }
        }
    }
}

// MARK: - Scene harness

private struct EmptyStateScene: View {
    @Environment(\.appTheme) private var appTheme
    let hasNoEntries: Bool
    let searchText: String
    let filters: Set<VocabularyReviewState>
    let showsAction: Bool

    private var action: AppEmptyStateAction? {
        guard showsAction else { return nil }
        return AppEmptyStateAction(
            title: "重新整理",
            systemImage: "arrow.clockwise",
            handler: {}
        )
    }

    var body: some View {
        AppThemeContainer {
            VStack {
                Spacer()
                AppEmptyStateContent(
                    title: KGVocabEmptyState.title(
                        hasNoEntries: hasNoEntries,
                        searchText: searchText,
                        filters: filters
                    ),
                    systemImage: KGVocabEmptyState.systemImage(
                        hasNoEntries: hasNoEntries,
                        searchText: searchText,
                        filters: filters
                    ),
                    description: KGVocabEmptyState.description(
                        hasNoEntries: hasNoEntries,
                        searchText: searchText,
                        filters: filters
                    ),
                    action: action,
                    style: .vocab(AppSkin.previewNeutral)
                )
                .padding(.horizontal, 32)
                Spacer()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
