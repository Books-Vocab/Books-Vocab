#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Notebooks list page (`NotebookListView`) —
/// specifically the `NotebookCard` grid / hero variants introduced in Phase 4a.
///
/// 不掛真實 `Notebook` model：直接餵合成的 `NotebookCardData`，
/// 與 SwiftData / @Query 解耦，catalog 渲染不需要 model container。
enum NotebooksScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebooks · Card") {
            Scenario("Hero · single notebook (heavy usage)", layout: .fillH) {
                cardSheet(style: .hero, cards: [Self.heavyCard])
            }
            Scenario("Hero · fresh notebook (no progress)", layout: .fillH) {
                cardSheet(style: .hero, cards: [Self.freshCard])
            }
            Scenario("Grid · two notebooks", layout: .fillH) {
                gridSheet(cards: [Self.heavyCard, Self.lightCard])
            }
            Scenario("Hero · long name truncate", layout: .fillH) {
                cardSheet(style: .hero, cards: [Self.longNameCard])
            }
        }
    }

    // MARK: - Fixtures

    private static let heavyCard = NotebookCardData(
        name: "我的單字本",
        color: "#5077A0",
        coverPattern: "dots",
        coverImagePath: nil,
        cardCount: 626,
        dueCount: 538,
        unlearnedCount: 0,
        reviewedCount: 88,
        pendingCount: 2,
        lastActivity: Date().addingTimeInterval(-3600),
        isActive: true
    )

    private static let lightCard = NotebookCardData(
        name: "GRE 字根",
        color: "#7A8C6A",
        coverPattern: "grid",
        coverImagePath: nil,
        cardCount: 42,
        dueCount: 3,
        unlearnedCount: 15,
        reviewedCount: 24,
        pendingCount: 0,
        lastActivity: Date().addingTimeInterval(-86400),
        isActive: false
    )

    private static let freshCard = NotebookCardData(
        name: "Self",
        color: "#B5826A",
        coverPattern: nil,
        coverImagePath: nil,
        cardCount: 0,
        dueCount: 0,
        unlearnedCount: 0,
        reviewedCount: 0,
        pendingCount: 0,
        lastActivity: nil,
        isActive: false
    )

    private static let longNameCard = NotebookCardData(
        name: "我的學測必背 7000 單字本 (含倒車雷達進階口語延伸)",
        color: "#8B7AA8",
        coverPattern: "stripes",
        coverImagePath: nil,
        cardCount: 7000,
        dueCount: 1234,
        unlearnedCount: 567,
        reviewedCount: 5199,
        pendingCount: 0,
        lastActivity: Date().addingTimeInterval(-1800),
        isActive: true
    )

    // MARK: - Sheets

    private static func cardSheet(style: NotebookCardStyle, cards: [NotebookCardData]) -> some View {
        let skin = AppSkin.previewNeutral
        return ScrollView {
            VStack(spacing: skin.spacing.sectionGap) {
                ForEach(Array(cards.enumerated()), id: \.offset) { _, data in
                    NotebookCard(data: data, style: style)
                }
            }
            .padding(.horizontal, skin.metrics.pageHorizontalInset)
            .padding(.top, skin.metrics.pageTopInset)
        }
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    private static func gridSheet(cards: [NotebookCardData]) -> some View {
        let skin = AppSkin.previewNeutral
        return ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: AppShellMetrics.sectionSpacing)],
                      spacing: AppShellMetrics.sectionSpacing) {
                ForEach(Array(cards.enumerated()), id: \.offset) { _, data in
                    NotebookCard(data: data, style: .grid)
                }
            }
            .padding(.horizontal, skin.metrics.pageHorizontalInset)
            .padding(.top, skin.metrics.pageTopInset)
        }
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }
}
#endif
