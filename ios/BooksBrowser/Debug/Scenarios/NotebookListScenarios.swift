#if DEBUG
import Playbook
import SwiftUI

/// Notebook 立體堆卡（`NotebookStackedCoverView` × `NotebookCard.grid`）的 catalog。
///
/// 涵蓋：
/// - 5 種 stress case（happy / long-content / large-numbers / narrow-width / a11y3）
/// - 自家 state matrix：0 / 30 / 100 / 500 字 × active/inactive × light/dark
/// - `NotebookAddCard` 與真實卡同 row 對齊
///
/// 與 `NotebooksScenarios` 共存：那份偏既有 hero / grid baseline，本份專攻新堆卡幾何。
enum NotebookListScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebooks · Stack") {

            // MARK: Stress

            Scenario("Stress · happy 2-up", layout: .fill) {
                gridSheet(cards: [Self.mediumActive, Self.fresh])
            }
            Scenario("Stress · long name + large numbers", layout: .fill) {
                gridSheet(cards: [Self.longNameHeavy, Self.heavy])
            }
            Scenario("Stress · narrow width (320pt)", layout: .fixed(length: 320)) {
                gridSheet(cards: [Self.mediumActive, Self.thin], minimum: 140)
            }
            Scenario("Stress · accessibility3", layout: .fill) {
                gridSheet(cards: [Self.mediumActive, Self.fresh])
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
            Scenario("Stress · 3 真實 + add (odd row)", layout: .fill) {
                gridSheet(cards: [Self.fresh, Self.thin, Self.medium], showsAddCard: true)
            }

            // MARK: State matrix — depth layers

            Scenario("Depth · 0 字 (1 層)", layout: .fill) {
                singleSheet(card: Self.fresh)
            }
            Scenario("Depth · 30 字 (2 層)", layout: .fill) {
                singleSheet(card: Self.thin)
            }
            Scenario("Depth · 100 字 (3 層)", layout: .fill) {
                singleSheet(card: Self.medium)
            }
            Scenario("Depth · 500 字 (4 層)", layout: .fill) {
                singleSheet(card: Self.heavy)
            }

            // MARK: State matrix — active × scheme

            Scenario("State · active light", layout: .fill) {
                singleSheet(card: Self.mediumActive)
                    .preferredColorScheme(.light)
            }
            Scenario("State · active dark", layout: .fill) {
                singleSheet(card: Self.mediumActive)
                    .preferredColorScheme(.dark)
            }
            Scenario("State · inactive light", layout: .fill) {
                singleSheet(card: Self.medium)
                    .preferredColorScheme(.light)
            }
            Scenario("State · inactive dark", layout: .fill) {
                singleSheet(card: Self.medium)
                    .preferredColorScheme(.dark)
            }

            // MARK: Reduce Motion

            // 注：`\.accessibilityReduceMotion` 為 read-only env，無法用 `.environment()` 強制；
            // 預覽 reduce motion 走 Xcode preview canvas 的 a11y inspector，不在 catalog 模擬。
            Scenario("A11y · large numbers heavy stack", layout: .fill) {
                singleSheet(card: Self.heavy)
            }

            // MARK: Editorial（cream paper ghosts + rotation + jitter）

            // 同 row 不同 seed → rotation 視覺差異明顯（驗 stableSeed deterministic）
            Scenario("Editorial · different seeds 2-up", layout: .fill) {
                gridSheet(cards: [Self.mediumActive, Self.medium])
            }
            // 「使用中」pill 必須隨 cover 一起轉（不脫離卡片邊界）
            Scenario("Editorial · pill 隨 rotation", layout: .fill) {
                singleSheet(card: Self.mediumActive)
            }
            // 4 本相同字數但不同 name → 確認 seed 純由 name 決定、jitter 各自獨立
            Scenario("Editorial · 4 different names same depth", layout: .fill) {
                gridSheet(cards: [Self.medium, Self.mediumActive, Self.thin, Self.longNameHeavy], minimum: 140)
            }
        }
    }

    // MARK: - Fixtures

    private static let fresh = NotebookCardData(
        name: "Self",
        color: "#5B8C5A", coverPattern: nil, coverImagePath: nil,
        cardCount: 0,
        dueCount: 0, unlearnedCount: 0, reviewedCount: 0, pendingCount: 0,
        lastActivity: nil, isActive: false
    )

    private static let thin = NotebookCardData(
        name: "GRE 字根",
        color: "#7A8C6A", coverPattern: "grid", coverImagePath: nil,
        cardCount: 30,
        dueCount: 5, unlearnedCount: 10, reviewedCount: 15, pendingCount: 0,
        lastActivity: nil, isActive: false
    )

    private static let medium = NotebookCardData(
        name: "TOEIC",
        color: "#4A90D9", coverPattern: "dots", coverImagePath: nil,
        cardCount: 100,
        dueCount: 12, unlearnedCount: 8, reviewedCount: 80, pendingCount: 0,
        lastActivity: nil, isActive: false
    )

    private static let mediumActive = NotebookCardData(
        name: "我的單字本",
        color: "#D4A843", coverPattern: "dots", coverImagePath: nil,
        cardCount: 100,
        dueCount: 12, unlearnedCount: 8, reviewedCount: 80, pendingCount: 0,
        lastActivity: nil, isActive: true
    )

    private static let heavy = NotebookCardData(
        name: "學測必背",
        color: "#A855C7", coverPattern: "stripes", coverImagePath: nil,
        cardCount: 500,
        dueCount: 120, unlearnedCount: 80, reviewedCount: 300, pendingCount: 2,
        lastActivity: nil, isActive: false
    )

    private static let longNameHeavy = NotebookCardData(
        name: "我的學測必背 7000 單字本 (含倒車雷達進階口語延伸)",
        color: "#8B7AA8", coverPattern: "stripes", coverImagePath: nil,
        cardCount: 7000,
        dueCount: 1234, unlearnedCount: 567, reviewedCount: 5199, pendingCount: 0,
        lastActivity: nil, isActive: true
    )

    // MARK: - Sheets

    private static func gridSheet(
        cards: [NotebookCardData],
        showsAddCard: Bool = false,
        minimum: CGFloat = 160
    ) -> some View {
        let skin = AppSkin.previewNeutral
        return ScrollView {
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: minimum), spacing: AppShellMetrics.sectionSpacing)],
                spacing: AppShellMetrics.sectionSpacing
            ) {
                ForEach(Array(cards.enumerated()), id: \.offset) { _, data in
                    NotebookCard(data: data, style: .grid)
                }
                if showsAddCard {
                    NotebookAddCard()
                }
            }
            .padding(.horizontal, skin.metrics.pageHorizontalInset)
            .padding(.top, skin.metrics.pageTopInset)
        }
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    private static func singleSheet(card: NotebookCardData) -> some View {
        let skin = AppSkin.previewNeutral
        return ScrollView {
            VStack(spacing: skin.spacing.sectionGap) {
                NotebookCard(data: card, style: .grid)
                    .frame(maxWidth: 200)
            }
            .padding(.horizontal, skin.metrics.pageHorizontalInset)
            .padding(.top, skin.metrics.pageTopInset)
        }
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }
}
#endif
