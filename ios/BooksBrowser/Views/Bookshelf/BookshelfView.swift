//
//  BookshelfView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import UniformTypeIdentifiers

private enum BookshelfMetrics {
    static let emptyStateSpacing: CGFloat = 20
    static let cardSpacing: CGFloat = 10
    static let cardMetadataSpacing: CGFloat = 3
    static let placeholderTitleHorizontalPadding: CGFloat = 12
    static let coverHeight: CGFloat = 210
    static let coverHeightRegular: CGFloat = 260
    static let coverCornerRadius: CGFloat = 6
    static let coverStrokeWidth: CGFloat = 0.5
    static let coverShadowOpacity: Double = 0.06
    static let coverShadowRadius: CGFloat = 4
    static let coverShadowY: CGFloat = 2
    static let progressBarHeight: CGFloat = 3
    static let progressBarAccentOpacity: Double = 0.55
    static let loadingOverlaySpacing: CGFloat = 16
    static let loadingOverlayPadding: CGFloat = 28
    static let loadingOverlayCornerRadius: CGFloat = 14
}

/// 書架主頁 — 簡約留白設計
struct BookshelfView: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext
    @Environment(\.bookshelfImportService) private var bookshelfImportService
    @Environment(\.bookFileManager) private var bookFileManager
    @Query(sort: \Book.dateLastRead, order: .reverse) private var books: [Book]
    @StateObject private var coordinator = BookshelfCoordinator()

    private var columns: [GridItem] {
        let item: GridItem = sizeClass == .regular
            ? GridItem(.adaptive(minimum: 180, maximum: 240), spacing: AppShellMetrics.sectionSpacing)
            : GridItem(.adaptive(minimum: 150, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
        return [item]
    }

    private var coverHeight: CGFloat {
        sizeClass == .regular ? BookshelfMetrics.coverHeightRegular : BookshelfMetrics.coverHeight
    }

    var body: some View {
        NavigationStack {
            ZStack {
                appTheme.palette.pageBackground
                    .ignoresSafeArea()

                if books.isEmpty {
                    emptyState
                        .transition(.opacity)
                } else {
                    bookGrid
                        .transition(.opacity)
                }

                if coordinator.isLoading {
                    loadingOverlay
                }
            }
            .navigationTitle("書庫")
            .navigationBarTitleDisplayMode(.large)
            .animation(AppMotion.phaseChange, value: books.isEmpty)
            .toolbarBackground(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(action: coordinator.presentSettings) {
                        AppToolbarGlyph(systemImage: "gearshape")
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: coordinator.presentImporter) {
                        AppToolbarGlyph(systemImage: "plus")
                    }
                }
            }
            .fileImporter(
                isPresented: $coordinator.isImporting,
                allowedContentTypes: [UTType(filenameExtension: "epub") ?? .data],
                allowsMultipleSelection: false
            ) { result in
                coordinator.handleFileImport(
                    result,
                    modelContext: modelContext,
                    importService: bookshelfImportService
                )
            }
            .alert("匯入錯誤", isPresented: $coordinator.showError) {
                Button("確定", role: .cancel, action: coordinator.dismissError)
            } message: {
                Text((coordinator.errorMessage ?? "未知錯誤").localized)
            }
            .sheet(isPresented: $coordinator.showSettings) {
                SettingsView()
            }
        }
    }

    // MARK: - 空狀態

    private var emptyState: some View {
        VStack(spacing: BookshelfMetrics.emptyStateSpacing) {
            Spacer()

            AppEmptyStateContent(
                title: "尚無書籍",
                systemImage: "book",
                description: "匯入 EPUB 電子書開始閱讀",
                style: .bookshelf(appTheme)
            )

            Button("匯入") {
                coordinator.presentImporter()
            }
            .buttonStyle(.appAction(.outline))
            .fixedSize(horizontal: false, vertical: true)

            Spacer()
        }
        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
    }

    // MARK: - 書籍網格

    private var bookGrid: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: AppShellMetrics.sectionSpacing) {
                ForEach(books) { book in
                    NavigationLink(value: book) {
                        BookCard(book: book, coverHeight: coverHeight)
                    }
                    .accessibilityLabel("\(book.title), \(book.author)")
                    .accessibilityHint("點兩下開始閱讀")
                    .transition(.opacity.combined(with: .scale(scale: 0.96)))
                    .contextMenu {
                        Button(role: .destructive) {
                            coordinator.deleteBook(
                                book,
                                modelContext: modelContext,
                                fileManager: bookFileManager
                            )
                        } label: {
                            Label("刪除", systemImage: "trash")
                        }
                    }
                }
            }
            .animation(AppMotion.contentFade, value: books.count)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingSmall)
            .padding(.bottom, AppMetrics.spacingExtraLarge)
        }
        .navigationDestination(for: Book.self) { book in
            ReaderView(book: book)
        }
    }

    // MARK: - 載入覆蓋層

    private var loadingOverlay: some View {
        ZStack {
            appTheme.palette.scrim
                .ignoresSafeArea()

            VStack(spacing: BookshelfMetrics.loadingOverlaySpacing) {
                ProgressView()
                    .scaleEffect(1.0)
                Text(coordinator.loadingMessage)
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(BookshelfMetrics.loadingOverlayPadding)
            .glassEffect(.regular, in: .rect(cornerRadius: BookshelfMetrics.loadingOverlayCornerRadius))
        }
    }

}

// MARK: - 書籍卡片

struct BookCard: View {
    @Environment(\.appTheme) private var appTheme
    let book: Book
    var coverHeight: CGFloat = BookshelfMetrics.coverHeight

    var body: some View {
        VStack(spacing: BookshelfMetrics.cardSpacing) {
            // 封面
            if let coverData = book.coverImageData,
               let uiImage = UIImage(data: coverData) {
                Image(uiImage: uiImage)
                    .resizable()
                    .aspectRatio(2/3, contentMode: .fill)
                    .frame(height: coverHeight)
                    .clipShape(
                        RoundedRectangle(
                            cornerRadius: BookshelfMetrics.coverCornerRadius,
                            style: .continuous
                        )
                    )
                    .shadow(
                        color: .black.opacity(BookshelfMetrics.coverShadowOpacity),
                        radius: BookshelfMetrics.coverShadowRadius,
                        y: BookshelfMetrics.coverShadowY
                    )
                    .overlay(alignment: .bottom) {
                        if let progress = book.progression, progress > 0 {
                            GeometryReader { geo in
                                Rectangle()
                                    .fill(appTheme.palette.pageBackground.opacity(0.82))
                                    .frame(
                                        width: geo.size.width * progress,
                                        height: BookshelfMetrics.progressBarHeight
                                    )
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(height: BookshelfMetrics.progressBarHeight)
                        }
                    }
            } else {
                // 無封面佔位 — 極簡風格
                RoundedRectangle(
                    cornerRadius: BookshelfMetrics.coverCornerRadius,
                    style: .continuous
                )
                    .fill(appTheme.palette.mutedFill)
                    .frame(height: coverHeight)
                    .overlay {
                        VStack(spacing: BookshelfMetrics.cardSpacing) {
                            Image(systemName: "book")
                                .font(AppFonts.h1(weight: .regular))
                                .foregroundStyle(appTheme.palette.tertiaryText)
                            Text(book.title)
                                .font(AppFonts.caption2())
                                .foregroundStyle(appTheme.palette.secondaryText)
                                .multilineTextAlignment(.center)
                                .padding(.horizontal, BookshelfMetrics.placeholderTitleHorizontalPadding)
                        }
                    }
                    .overlay(
                        RoundedRectangle(
                            cornerRadius: BookshelfMetrics.coverCornerRadius,
                            style: .continuous
                        )
                        .strokeBorder(
                            appTheme.palette.cardBorder,
                            lineWidth: BookshelfMetrics.coverStrokeWidth
                        )
                    )
                    .overlay(alignment: .bottom) {
                        if let progress = book.progression, progress > 0 {
                            GeometryReader { geo in
                                Rectangle()
                                    .fill(appTheme.palette.accent.opacity(BookshelfMetrics.progressBarAccentOpacity))
                                    .frame(
                                        width: geo.size.width * progress,
                                        height: BookshelfMetrics.progressBarHeight
                                    )
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(height: BookshelfMetrics.progressBarHeight)
                        }
                    }
            }

            VStack(spacing: BookshelfMetrics.cardMetadataSpacing) {
                Text(book.title)
                    .font(AppFonts.caption())
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(appTheme.palette.primaryText)

                Text(book.author)
                    .font(AppFonts.caption2())
                    .foregroundStyle(appTheme.palette.tertiaryText)
                    .lineLimit(1)
            }
        }
    }
}

private enum BookshelfPreviewData {
    static let activeBook: Book = {
        let book = Book(
            title: "The Architecture of Words",
            author: "Lena Harper",
            epubFileName: "architecture-of-words.epub"
        )
        book.progression = 0.64
        return book
    }()

    static let placeholderBook: Book = {
        let book = Book(
            title: "A Very Long Book Title For Empty Cover Placeholder",
            author: "M. Rivera",
            epubFileName: "placeholder.epub"
        )
        book.progression = 0.18
        return book
    }()
}

#Preview("Bookshelf Card / Progress") {
    AppThemeContainer {
        BookCard(book: BookshelfPreviewData.activeBook)
            .padding()
            .frame(width: 180)
            .background(AppTheme.light.palette.pageBackground.ignoresSafeArea())
    }
}

#Preview("Bookshelf Card / Placeholder") {
    AppThemeContainer {
        BookCard(book: BookshelfPreviewData.placeholderBook)
            .padding()
            .frame(width: 180)
            .background(AppTheme.light.palette.pageBackground.ignoresSafeArea())
    }
}
