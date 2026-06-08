#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the Bookshelf surface.
/// Reuses fixture-driven preview scenes so Preview / Catalog / Snapshot stay aligned.
enum BookshelfScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Bookshelf") {
            Scenario("Card / Progress", layout: .fill) {
                AppThemeContainer {
                    BookshelfCardFixtureScene(fixtureID: .progressCard)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Card / Placeholder", layout: .fill) {
                AppThemeContainer {
                    BookshelfCardFixtureScene(fixtureID: .placeholderCard)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            // NOTE: full-library states (Empty / With Books) live on the
            // "Bookshelf View" featureScreen surface (real `BookshelfView`).
            // This "Bookshelf" surface is building-block scoped: book cards +
            // loading. The former library fixtures here were a byte-identical
            // duplicate of Bookshelf View and were removed; the podcast shelf
            // cards were relocated to the podcast slice (PodcastShelfCardsScenarios).
            Scenario("Loading", layout: .fill) {
                AppThemeContainer {
                    BookshelfLoadingPreview()
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}

#endif
