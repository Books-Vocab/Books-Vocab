#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for `BookCard` (Bookshelf cell).
///
/// `Book` is a SwiftData `@Model`; card scenarios therefore materialize UI World
/// `bookshelf.book_card_*` seeds into an in-memory container instead of building
/// standalone local rows.
/// These complement `BookshelfViewScenarios` (which drives the full-screen render model)
/// by stressing the card's own layout invariants: equal-height metadata block,
/// 2-line title clamp, format badge on the placeholder cover, and progress bar
/// occupancy across 0% / mid / 100%.
enum BookCardScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Book Card") {
            Scenario("Placeholder · EPUB", layout: .compressed) {
                BookCardScene(fixture: .placeholderEpub)
            }
            Scenario("Placeholder · PDF badge", layout: .compressed) {
                BookCardScene(fixture: .pdfFormat)
            }
            Scenario("Progress · Mid", layout: .compressed) {
                BookCardScene(fixture: .midProgress)
            }
            Scenario("Progress · Complete", layout: .compressed) {
                BookCardScene(fixture: .complete)
            }
            Scenario("Long title + author", layout: .compressed) {
                BookCardScene(fixture: .longTitle)
            }
            Scenario("A11y3", layout: .compressed) {
                BookCardScene(fixture: .midProgress)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
private enum BookCardFixture {
    case placeholderEpub
    case pdfFormat
    case midProgress
    case complete
    case longTitle

    var bookshelfID: BookshelfFixtureID {
        switch self {
        case .placeholderEpub:
            return .bookCardPlaceholderEpub
        case .pdfFormat:
            return .bookCardPdfFormat
        case .midProgress:
            return .bookCardMidProgress
        case .complete:
            return .bookCardComplete
        case .longTitle:
            return .bookCardLongTitle
        }
    }
}

private struct BookCardScene: View {
    private let container: ModelContainer
    private let book: Book
    private let referenceDate: Date

    init(fixture: BookCardFixture) {
        let renderModel = BookshelfFixtures.renderModel(for: fixture.bookshelfID)
        precondition(
            renderModel.books.count == 1,
            "UI World bookshelf.\(fixture.bookshelfID.rawValue) expected exactly one BookCard book, got \(renderModel.books.count)"
        )
        container = renderModel.container
        book = renderModel.books[0]
        referenceDate = renderModel.referenceDate
    }

    var body: some View {
        AppThemeContainer {
            BookCard(book: book)
                .frame(width: 180)
                .padding()
                .environment(\.fixtureReferenceDate, referenceDate)
                .modelContainer(container)
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif

#endif
