#if DEBUG
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the Bookshelf surface.
/// Reuses `BookshelfPreviewData` / `BookCardPreviewScene` / `BookshelfLoadingPreview`
/// (defined in `BookshelfView.swift`) so state stays in lock-step with the
/// existing `#Preview` blocks.
enum BookshelfScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Bookshelf") {
            Scenario("Card / Progress", layout: .fill) {
                AppThemeContainer {
                    BookCardPreviewScene(book: BookshelfPreviewData.activeBook)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Card / Placeholder", layout: .fill) {
                AppThemeContainer {
                    BookCardPreviewScene(book: BookshelfPreviewData.placeholderBook)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Empty", layout: .fill) {
                AppThemeContainer {
                    BookshelfView()
                        .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("With Books", layout: .fill) {
                BookshelfWithBooksScene()
            }
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    BookshelfLoadingPreview()
                        .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}

// Why: `BookshelfPreviewData.containerWithBooks` is `@MainActor` (touches ModelContainer
// init paths that require main-thread); the Scenario content closure itself is
// non-isolated, so accessing it directly trips Swift 6 strict concurrency.
// SwiftUI `body` is implicitly `@MainActor`-isolated → wrap the access in a View.
private struct BookshelfWithBooksScene: View {
    var body: some View {
        AppThemeContainer {
            if let container = BookshelfPreviewData.containerWithBooks {
                BookshelfView()
                    .modelContainer(container)
            } else {
                EmptyView()
            }
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
