#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `EditorialCoverComposition` — the D1
/// editorial cover overlay (serif name 左上 + hairline rule + N 詞 右下 +
/// (active) spine).
///
/// Pure-value component: it takes `name`/`cardCount`/`coverColor`/`isActive`/
/// `style` and reads `@Environment(\.appSkin)`. No `@MainActor` init, so each
/// Scenario constructs it directly inside the closure. The composition has no
/// intrinsic size (ZStack + GeometryReader + bottom-trailing overlay), so it is
/// placed over a colored cover rectangle with explicit frames matching the two
/// card styles (grid vs hero).
enum NotebookCardEditorialCoverScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebook Cover · Editorial") {
            Scenario("Grid · default", layout: .compressed) {
                EditorialCoverScene(
                    name: "晨間散文",
                    cardCount: 48,
                    coverColor: Color(red: 0.42, green: 0.55, blue: 0.78),
                    isActive: false,
                    style: .grid
                )
            }
            Scenario("Grid · active (spine)", layout: .compressed) {
                EditorialCoverScene(
                    name: "晨間散文",
                    cardCount: 48,
                    coverColor: Color(red: 0.42, green: 0.55, blue: 0.78),
                    isActive: true,
                    style: .grid
                )
            }
            Scenario("Grid · empty (no count)", layout: .compressed) {
                EditorialCoverScene(
                    name: "新筆記本",
                    cardCount: 0,
                    coverColor: Color(red: 0.78, green: 0.62, blue: 0.45),
                    isActive: false,
                    style: .grid
                )
            }
            Scenario("Grid · long name (truncate)", layout: .compressed) {
                EditorialCoverScene(
                    name: "十九世紀英國浪漫主義詩歌精選與註解合集",
                    cardCount: 1280,
                    coverColor: Color(red: 0.55, green: 0.42, blue: 0.62),
                    isActive: true,
                    style: .grid
                )
            }
            Scenario("Hero · default", layout: .compressed) {
                EditorialCoverScene(
                    name: "夜讀筆記",
                    cardCount: 312,
                    coverColor: Color(red: 0.36, green: 0.66, blue: 0.58),
                    isActive: false,
                    style: .hero
                )
            }
            Scenario("Hero · active", layout: .compressed) {
                EditorialCoverScene(
                    name: "夜讀筆記",
                    cardCount: 312,
                    coverColor: Color(red: 0.82, green: 0.45, blue: 0.45),
                    isActive: true,
                    style: .hero
                )
            }
        }
    }
}

// MARK: - Scene harness

private struct EditorialCoverScene: View {
    let name: String
    let cardCount: Int
    let coverColor: Color
    let isActive: Bool
    let style: NotebookCardStyle

    private var size: CGSize {
        switch style {
        case .grid: return CGSize(width: 168, height: 224)
        case .hero: return CGSize(width: 320, height: 200)
        }
    }

    var body: some View {
        AppThemeContainer {
            ZStack {
                AppRoundedRect(roundness: AppRoundness.card)
                    .fill(coverColor.opacity(0.35))
                EditorialCoverComposition(
                    name: name,
                    cardCount: cardCount,
                    coverColor: coverColor,
                    isActive: isActive,
                    style: style
                )
            }
            .frame(width: size.width, height: size.height)
            .clipShape(AppRoundedRect(roundness: AppRoundness.card))
            .padding(AppSpacing.s4)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif