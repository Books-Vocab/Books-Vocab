#if os(iOS)
//
//  BookshelfPreviews.swift
//  BooksBrowser
//

import SwiftUI
import Inject

enum BookshelfPreviewData {
    @MainActor
    static var progressCard: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: .progressCard)
    }

    @MainActor
    static var placeholderCard: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: .placeholderCard)
    }

    @MainActor
    static var emptyLibrary: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: .emptyLibrary)
    }

    @MainActor
    static var withBooksLibrary: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: .withBooksLibrary)
    }

    @MainActor
    static var loadingOverlay: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: .loadingOverlay)
    }
}

#Preview("Bookshelf Card / Progress") {
    AppThemeContainer {
        BookshelfCardFixtureScene(fixtureID: .progressCard)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Bookshelf Card / Placeholder") {
    AppThemeContainer {
        BookshelfCardFixtureScene(fixtureID: .placeholderCard)
    }
    .environmentObject(AppAppearanceStore.preview)
}

struct BookshelfCardFixtureScene: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let fixtureID: BookshelfFixtureID

    @MainActor
    private var renderModel: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: fixtureID)
    }

    var body: some View {
        BookCard(book: renderModel.books[0])
            .padding()
            .frame(width: 180)
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .environment(\.fixtureReferenceDate, renderModel.referenceDate)
            .enableInjection()
    }
}

// MARK: - 全頁四態 Preview

#Preview("Bookshelf / Empty") {
    AppThemeContainer {
        BookshelfFixtureLibraryScene(fixtureID: .emptyLibrary)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Bookshelf / With Books") {
    AppThemeContainer {
        BookshelfFixtureLibraryScene(fixtureID: .withBooksLibrary)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Bookshelf / Loading") {
    AppThemeContainer {
        BookshelfLoadingPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

/// 獨立展示 loadingOverlay 的輔助 view，用於 Loading State preview
struct BookshelfLoadingPreview: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        ZStack {
            appTheme.palette.pageBackground
                .ignoresSafeArea()
            BookshelfLoadingOverlay(
                message: L10n.string("正在匯入書籍..."),
                progress: nil
            )
        }
        .enableInjection()
    }
}

struct BookshelfFixtureLibraryScene: View {
    let fixtureID: BookshelfFixtureID

    @MainActor
    private var renderModel: BookshelfFixtureRenderModel {
        BookshelfFixtures.renderModel(for: fixtureID)
    }

    var body: some View {
        if let container = renderModel.container {
            BookshelfView()
                .modelContainer(container)
                .environment(\.fixtureReferenceDate, renderModel.referenceDate)
        } else {
            EmptyView()
        }
    }
}
#endif
