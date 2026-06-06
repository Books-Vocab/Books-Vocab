#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Notebook 立體堆卡（`NotebookStackedCoverView` × `NotebookCard.grid`）的 catalog。
///
/// 涵蓋：
/// - 4 種 stress case（happy / long-content / narrow-width / a11y3）
/// - 自家 state matrix：0 / 30 / 100 / 500 字 × active/inactive × light/dark
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
            // D3 spine — 4pt cover 左側,跟 cover 一起旋轉,不脫離邊界
            Scenario("Editorial · spine 隨 rotation (active)", layout: .fill) {
                singleSheet(card: Self.mediumActive)
            }
            // 4 本相同字數但不同 name → 確認 seed 純由 name 決定、jitter 各自獨立
            Scenario("Editorial · 4 different names same depth", layout: .fill) {
                gridSheet(cards: [Self.medium, Self.mediumActive, Self.thin, Self.longNameHeavy], minimum: 140)
            }

            // MARK: Editorial Cover Composition (D1)

            // D1 三件事:serif name 左上 / hairline rule / N 詞 右下 (+ active spine)
            Scenario("D1 · cover composition basic", layout: .fill) {
                gridSheet(cards: [Self.mediumActive, Self.medium])
            }
            // 大 cardCount(99999 詞)— monoLabel 字寬不抖,rule width 25% 仍合理
            Scenario("D1 · very large cardCount (99999)", layout: .fill) {
                singleSheet(card: Self.massiveCount)
            }
            // 大 dueCount(9999 到期)— bottom chip 不擠破 ProgressCapsule
            Scenario("D1 · very large dueCount (9999)", layout: .fill) {
                gridSheet(cards: [Self.massiveDue, Self.medium])
            }
            // cardCount = 0 → cover 不顯示 N 詞 row
            Scenario("D1 · empty notebook (0 詞 hides count)", layout: .fill) {
                singleSheet(card: Self.fresh)
            }
            // Dark mode AA — primaryText #E6E6E3 對 darken(Morandi, 0.55) 應 ≥ AA 4.5
            Scenario("D1 · dark mode contrast", layout: .fill) {
                gridSheet(cards: [Self.mediumActive, Self.medium, Self.thin], minimum: 140)
                    .preferredColorScheme(.dark)
            }
            // Grid height 穩定 — dueCount=0/>0 兩卡並排同高
            Scenario("D2 · grid height stability (mixed due)", layout: .fill) {
                gridSheet(cards: [Self.medium, Self.fresh])
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

    // D1 stress — 99999 詞 cardCount 邊界,monoLabel 不抖
    private static let massiveCount = NotebookCardData(
        name: "Massive Vocab",
        color: "#AFC2D3", coverPattern: "dots", coverImagePath: nil,
        cardCount: 99999,
        dueCount: 42, unlearnedCount: 10, reviewedCount: 99947, pendingCount: 0,
        lastActivity: nil, isActive: false
    )

    // D2 stress — 9999 到期 chip 不擠破 ProgressCapsule
    private static let massiveDue = NotebookCardData(
        name: "Heavy Due",
        color: "#DCABA4", coverPattern: nil, coverImagePath: nil,
        cardCount: 9999,
        dueCount: 9999, unlearnedCount: 0, reviewedCount: 0, pendingCount: 0,
        lastActivity: nil, isActive: true
    )

    // MARK: - Sheets

    private static func gridSheet(
        cards: [NotebookCardData],
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
