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
#endif
