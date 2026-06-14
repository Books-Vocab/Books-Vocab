#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Notebooks list page (`NotebookListView`) —
/// specifically the `NotebookCard` grid / hero variants introduced in Phase 4a.
///
/// `NotebookCard` consumes view data rather than SwiftData directly, but the
/// card rows still come from UI World `notebook.cardGallery`; missing card
/// state or inconsistent metrics fail at catalog construction time.
enum NotebooksScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Notebooks · Card") {
            Scenario("Hero · single notebook (heavy usage)", layout: .fillH) {
                CardGalleryScene(style: .hero, selection: .heavy)
            }
            Scenario("Hero · fresh notebook (no progress)", layout: .fillH) {
                CardGalleryScene(style: .hero, selection: .fresh)
            }
            Scenario("Grid · two notebooks", layout: .fillH) {
                CardGalleryScene(style: .grid, selection: .gridPair)
            }
            Scenario("Hero · long name truncate", layout: .fillH) {
                CardGalleryScene(style: .hero, selection: .longName)
            }
        }
    }
}

private enum NotebookCardGallerySelection {
    case fresh
    case gridPair
    case heavy
    case longName

    func cards(from cards: [NotebookCardData]) -> [NotebookCardData] {
        switch self {
        case .fresh:
            return require(cards, where: { $0.cardCount == 0 }, label: "fresh")
        case .gridPair:
            return require(cards, where: { $0.cardCount > 0 }, count: 2, label: "gridPair")
        case .heavy:
            return require(cards, where: { $0.cardCount > 500 && $0.dueCount > 0 && $0.isActive }, label: "heavy")
        case .longName:
            return require(cards, where: { $0.name.count > 24 }, label: "longName")
        }
    }

    private func require(
        _ cards: [NotebookCardData],
        where predicate: (NotebookCardData) -> Bool,
        count: Int = 1,
        label: String
    ) -> [NotebookCardData] {
        let matches = cards.filter(predicate)
        guard matches.count >= count else {
            preconditionFailure("UI World notebook.cardGallery is missing \(label) card state")
        }
        return Array(matches.prefix(count))
    }
}

private struct CardGalleryScene: View {
    let style: NotebookCardStyle
    let cards: [NotebookCardData]

    init(style: NotebookCardStyle, selection: NotebookCardGallerySelection) {
        let cards = NotebookFixtures.cardData(for: .cardGallery)
        self.style = style
        self.cards = selection.cards(from: cards)
    }

    var body: some View {
        let skin = AppSkin.previewNeutral
        ScrollView {
            if style == .grid {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 160), spacing: AppShellMetrics.sectionSpacing)],
                          spacing: AppShellMetrics.sectionSpacing) {
                    cardViews
                }
            } else {
                VStack(spacing: skin.spacing.sectionGap) {
                    cardViews
                }
            }
        }
        .padding(.horizontal, skin.metrics.pageHorizontalInset)
        .padding(.top, skin.metrics.pageTopInset)
        .background(skin.palette.pageBackground.ignoresSafeArea())
        .appSkin(skin)
    }

    private var cardViews: some View {
        ForEach(Array(cards.enumerated()), id: \.offset) { _, data in
            NotebookCard(data: data, style: style)
        }
    }
}
#endif
