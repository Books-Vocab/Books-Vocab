import Testing
@testable import BooksAndVocab

struct AppPrimarySectionTests {
    @Test func sectionOrderMatchesDesktopSidebarInformationArchitecture() {
        #expect(AppPrimarySection.allCases == [.bookshelf, .podcasts, .notebooks, .overview])
    }

    @Test func sectionsExposeLocalizedTitleKeysAndSymbols() {
        #expect(AppPrimarySection.bookshelf.titleKey == "app.section.bookshelf")
        #expect(AppPrimarySection.bookshelf.systemImage == "books.vertical")
        #expect(AppPrimarySection.podcasts.titleKey == "app.section.podcasts")
        #expect(AppPrimarySection.podcasts.systemImage == "waveform")
        #expect(AppPrimarySection.notebooks.titleKey == "app.section.notebooks")
        #expect(AppPrimarySection.notebooks.systemImage == "character.book.closed")
        #expect(AppPrimarySection.overview.titleKey == "app.section.overview")
        #expect(AppPrimarySection.overview.systemImage == "chart.bar")
    }
}
