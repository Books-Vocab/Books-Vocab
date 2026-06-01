import Testing
@testable import BooksBrowser

struct AppPrimarySectionTests {
    @Test func sectionOrderMatchesDesktopSidebarInformationArchitecture() {
        #expect(AppPrimarySection.allCases == [.bookshelf, .notebooks, .overview])
    }

    @Test func sectionsExposeLocalizedTitleKeysAndSymbols() {
        #expect(AppPrimarySection.bookshelf.titleKey == "app.section.bookshelf")
        #expect(AppPrimarySection.bookshelf.systemImage == "books.vertical")
        #expect(AppPrimarySection.notebooks.titleKey == "app.section.notebooks")
        #expect(AppPrimarySection.notebooks.systemImage == "character.book.closed")
        #expect(AppPrimarySection.overview.titleKey == "app.section.overview")
        #expect(AppPrimarySection.overview.systemImage == "chart.bar")
    }
}
