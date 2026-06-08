#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `BookCard` (Bookshelf cell).
///
/// `Book` is a SwiftData `@Model`; its initializer is fine to call standalone
/// (no `ModelContext` required), but we still construct fixtures inside a
/// `@MainActor` `View` body to stay clear of the Scenario closure isolation trap.
/// These complement `BookshelfViewScenarios` (which drives the full-screen render model)
/// by stressing the card's own layout invariants: equal-height metadata block,
/// 2-line title clamp, format badge on the placeholder cover, and progress bar
/// occupancy across 0% / mid / 100%.
enum BookCardScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Book Card") {
            Scenario("Placeholder · EPUB", layout: .compressed) {
                BookCardScene(spec: .placeholderEpub)
            }
            Scenario("Placeholder · PDF badge", layout: .compressed) {
                BookCardScene(spec: .pdfFormat)
            }
            Scenario("Progress · Mid", layout: .compressed) {
                BookCardScene(spec: .midProgress)
            }
            Scenario("Progress · Complete", layout: .compressed) {
                BookCardScene(spec: .complete)
            }
            Scenario("Long title + author", layout: .compressed) {
                BookCardScene(spec: .longTitle)
            }
            Scenario("A11y3", layout: .compressed) {
                BookCardScene(spec: .midProgress)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// Synthetic `BookCard` harness. `Book` is a `@MainActor`-friendly `@Model`, so
/// it is built inside this `View` body rather than in the Scenario closure.
private struct BookCardScene: View {
    struct Spec {
        var title: String
        var author: String
        var format: BookFormat
        var progression: Double?
        var dateLastRead: Date?

        static let placeholderEpub = Spec(
            title: "原子習慣",
            author: "James Clear",
            format: .epub,
            progression: nil,
            dateLastRead: nil
        )
        static let pdfFormat = Spec(
            title: "深度工作論文集",
            author: "Cal Newport",
            format: .pdf,
            progression: nil,
            dateLastRead: nil
        )
        static let midProgress = Spec(
            title: "刻意練習",
            author: "Anders Ericsson",
            format: .epub,
            progression: 0.42,
            dateLastRead: Date(timeIntervalSince1970: 1_717_000_000)
        )
        static let complete = Spec(
            title: "心流",
            author: "Mihaly Csikszentmihalyi",
            format: .epub,
            progression: 1.0,
            dateLastRead: Date(timeIntervalSince1970: 1_717_400_000)
        )
        static let longTitle = Spec(
            title: "尋找心流：最優體驗的科學與日常生活中的應用實踐指南",
            author: "Mihaly Csikszentmihalyi & Co-Author With A Rather Long Name",
            format: .txt,
            progression: 0.08,
            dateLastRead: Date(timeIntervalSince1970: 1_716_000_000)
        )
    }

    let spec: Spec

    var body: some View {
        let book = Book(
            title: spec.title,
            author: spec.author,
            fileName: "fixture.\(spec.format.rawValue)",
            format: spec.format
        )
        book.progression = spec.progression
        book.dateLastRead = spec.dateLastRead

        return AppThemeContainer {
            BookCard(book: book)
                .frame(width: 180)
                .padding()
                .environment(\.fixtureReferenceDate, Date(timeIntervalSince1970: 1_717_500_000))
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif

#endif
