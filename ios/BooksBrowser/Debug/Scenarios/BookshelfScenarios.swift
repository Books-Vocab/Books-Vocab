#if DEBUG && canImport(Playbook)
import Playbook
import SwiftData
import SwiftUI

/// Catalog scenarios for the Bookshelf surface.
/// Reuses `BookshelfPreviewData` / `BookCardPreviewScene` / `BookshelfLoadingPreview`
/// (defined in `BookshelfPreviews.swift`) so state stays in lock-step with the
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
            // PodcastSeriesCard streaming-meta stress baselines (軸 B Phase 2):
            // the `主持人 · N 集` meta line is single-line tail-truncated, so the
            // long-host / multi-host / a11y3 cases prove card height stays uniform.
            Scenario("Podcast Card / Normal", layout: .fill) {
                PodcastSeriesCardScene(title: "Atomic Habits Unpacked", hosts: ["Ava Chen"], count: 7)
            }
            Scenario("Podcast Card / Long host", layout: .fill) {
                PodcastSeriesCardScene(
                    title: "Finding Flow: The Science of Optimal Experience",
                    hosts: ["Mihaly Csikszentmihalyi", "Alexandra Penultimate-Featherstonehaugh"],
                    count: 24
                )
            }
            Scenario("Podcast Card / Narrow", layout: .fill) {
                PodcastSeriesCardScene(title: "Let Them, Let Me", hosts: ["Leo Park", "Ava Chen"], count: 8, width: 120)
            }
            Scenario("Podcast Card / A11y3", layout: .fill) {
                PodcastSeriesCardScene(title: "Hidden Hand", hosts: ["Leo Park"], count: 12)
                    .environment(\.dynamicTypeSize, .accessibility3)
            }
        }
    }
}

#if os(iOS)
/// PodcastSeriesCard baseline harness. Model construction touches `@MainActor`
/// paths, so it lives in a `View` body (same reason as `BookshelfWithBooksScene`).
private struct PodcastSeriesCardScene: View {
    let title: String
    let hosts: [String]
    let count: Int
    var width: CGFloat = 160

    var body: some View {
        let series = PodcastSeries(remoteId: "s-prev", title: title, hostNames: hosts)
        series.color = "#4A90D9"
        series.coverPattern = NotebookCoverPattern.waves.rawValue
        series.episodeCount = count
        return AppThemeContainer {
            PodcastSeriesCard(series: series)
                .frame(width: width)
                .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif

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
