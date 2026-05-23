#if os(iOS)
//
//  BookshelfPreviews.swift
//  BooksBrowser
//

import SwiftUI
import SwiftData
import Inject

enum BookshelfPreviewData {
    static let activeBook: Book = {
        let book = Book(
            title: "The Architecture of Words",
            author: "Lena Harper",
            fileName: "architecture-of-words.epub"
        )
        book.progression = 0.64
        book.dateLastRead = Calendar.current.date(byAdding: .day, value: -3, to: Date())
        return book
    }()

    static let placeholderBook: Book = {
        let book = Book(
            title: "A Very Long Book Title For Empty Cover Placeholder",
            author: "M. Rivera",
            fileName: "placeholder.epub"
        )
        book.progression = 0.18
        book.dateLastRead = Calendar.current.date(byAdding: .hour, value: -5, to: Date())
        return book
    }()

    @MainActor
    static var containerWithBooks: ModelContainer? = {
        let schema = Schema([Book.self, VocabularyEntry.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        do {
            let container = try ModelContainer(for: schema, configurations: config)
            let context = ModelContext(container)
            context.insert(activeBook)
            context.insert(placeholderBook)
            try? context.save()
            return container
        } catch {
            AppLog.app.warning("BookshelfPreviewData container failed: \(error.localizedDescription)")
            return nil
        }
    }()
}

#Preview("Bookshelf Card / Progress") {
    AppThemeContainer {
        BookCardPreviewScene(book: BookshelfPreviewData.activeBook)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Bookshelf Card / Placeholder") {
    AppThemeContainer {
        BookCardPreviewScene(book: BookshelfPreviewData.placeholderBook)
    }
    .environmentObject(AppAppearanceStore.preview)
}

struct BookCardPreviewScene: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let book: Book

    var body: some View {
        BookCard(book: book)
            .padding()
            .frame(width: 180)
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .enableInjection()
    }
}

// MARK: - 全頁四態 Preview

#Preview("Bookshelf / Empty") {
    AppThemeContainer {
        BookshelfView()
            .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Bookshelf / With Books") {
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

#Preview("Bookshelf / Loading") {
    AppThemeContainer {
        BookshelfLoadingPreview()
            .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
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
            appTheme.palette.scrim
                .ignoresSafeArea()
            VStack(spacing: AppSpacing.s4) {
                ProgressView()
                Text(L10n.string("正在匯入書籍..."))
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(AppBookshelfMetrics.loadingOverlayPadding)
            .compatibleGlass(in: .rect(cornerRadius: AppRadius.md))
        }
        .enableInjection()
    }
}
#endif
