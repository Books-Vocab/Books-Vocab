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
    static let cardSpacing: CGFloat = 8
    static let cardMetadataSpacing: CGFloat = 3
    static let placeholderTitleHorizontalPadding: CGFloat = 12
    static let coverHeight: CGFloat = 210
    static let coverHeightRegular: CGFloat = 260
    static let coverCornerRadius: CGFloat = 6
    static let coverStrokeWidth: CGFloat = 0.5
    static let coverShadowOpacity: Double = 0.10
    static let coverShadowRadius: CGFloat = 6
    static let coverShadowY: CGFloat = 3
    static let progressBarHeight: CGFloat = 4
    static let progressBarCornerRadius: CGFloat = 2
    static let progressBarAccentOpacity: Double = 0.55
    static let progressBarSpacing: CGFloat = 6
    static let loadingOverlaySpacing: CGFloat = 16
    static let loadingOverlayPadding: CGFloat = 28
    static let loadingOverlayCornerRadius: CGFloat = AppMetrics.cornerRadiusMedium
}

/// 書架主頁 — 簡約留白設計
struct BookshelfView: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.modelContext) private var modelContext
    @Environment(\.bookshelfImportService) private var bookshelfImportService
    @Environment(\.bookFileManager) private var bookFileManager
    @Query(sort: \Book.dateLastRead, order: .reverse) private var books: [Book]
    @State private var coordinator = BookshelfCoordinator()

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
                        .transition(.contentSwap)
                } else {
                    bookGrid
                        .transition(.contentSwap)
                }

                if coordinator.isLoading {
                    loadingOverlay
                }
            }
            .navigationTitle("書庫".localized)
            .navigationBarTitleDisplayMode(.large)
            .animation(AppMotion.phaseChange, value: books.isEmpty)
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
            .alert("匯入錯誤".localized, isPresented: $coordinator.showError) {
                Button("確定".localized, role: .cancel, action: coordinator.dismissError)
            } message: {
                Text((coordinator.errorMessage ?? "未知錯誤").localized)
            }
            .sheet(isPresented: $coordinator.showSettings) {
                SettingsView()
            }
        }
    }

    // MARK: - 空狀態

    @Environment(\.authManager) private var authManager

    private var emptyState: some View {
        ScrollView {
            VStack(spacing: BookshelfMetrics.emptyStateSpacing) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: "尚無書籍".localized,
                    systemImage: "book",
                    description: "匯入 EPUB 電子書開始閱讀".localized,
                    style: .bookshelf(appTheme)
                )

                Button("匯入".localized) {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appAction(.outline))
                .fixedSize(horizontal: false, vertical: true)

                if !authManager.isDemoMode && !authManager.isLoggedIn {
                    Button(action: {
                        authManager.enterDemoMode(modelContainer: modelContext.container)
                    }) {
                        HStack(spacing: 6) {
                            Image(systemName: "play.circle")
                            Text("體驗複習與圖譜".localized)
                        }
                        .font(AppFonts.caption(weight: .medium))
                        .foregroundStyle(appTheme.palette.accent)
                    }
                    .buttonStyle(.plain)
                }

                Spacer(minLength: 120)
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
        }
        .refreshable {
            try? await Task.sleep(for: .seconds(1.5))
        }
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
                    .accessibilityHint("點兩下開始閱讀".localized)
                    .transition(.bookshelfCard)
                    .contextMenu {
                        Button(role: .destructive) {
                            coordinator.deleteBook(
                                book,
                                modelContext: modelContext,
                                fileManager: bookFileManager
                            )
                        } label: {
                            Label("刪除".localized, systemImage: "trash")
                        }
                    }
                }
            }
            .animation(AppMotion.contentFade, value: books.count)
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingSmall)

            epubGuideHint
                .padding(.top, AppMetrics.spacingLarge)
                .padding(.bottom, AppMetrics.spacingExtraLarge)
        }
        .refreshable {
            // CloudKit 自動同步無法直接觸發，短暫等待讓 pending 操作完成
            // @Query 會自動反映 CloudKit 傳入的變更
            try? await Task.sleep(for: .seconds(1.5))
        }
        .navigationDestination(for: Book.self) { book in
            ReaderView(book: book)
        }
    }

    // MARK: - EPUB 取得提示

    private var epubGuideHint: some View {
        Link(destination: URL(string: "https://wordnexus.lol/guide.html")!) {
            Text("了解更多".localized)
                .font(AppFonts.caption2())
                .foregroundStyle(appTheme.palette.quaternaryText)
                .frame(maxWidth: .infinity)
                .padding(.vertical, AppMetrics.spacingSmall)
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
        VStack(alignment: .leading, spacing: BookshelfMetrics.cardSpacing) {
            // 封面
            coverView
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
                .shadow(
                    color: .black.opacity(BookshelfMetrics.coverShadowOpacity),
                    radius: BookshelfMetrics.coverShadowRadius,
                    y: BookshelfMetrics.coverShadowY
                )

            // 進度條（封面外獨立元素）
            if let progress = book.progression, progress > 0 {
                progressBar(progress)
            }

            // 元資料
            VStack(alignment: .leading, spacing: BookshelfMetrics.cardMetadataSpacing) {
                Text(book.title)
                    .font(AppFonts.caption(weight: .medium))
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                    .foregroundStyle(appTheme.palette.primaryText)

                Text(book.author)
                    .font(AppFonts.caption2())
                    .foregroundStyle(appTheme.palette.tertiaryText)
                    .lineLimit(1)

                if let dateLastRead = book.dateLastRead {
                    Text(dateLastRead.relativeShort)
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.quaternaryText)
                }
            }
        }
    }

    @ViewBuilder
    private var coverView: some View {
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
        } else {
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
        }
    }

    private func progressBar(_ progress: Double) -> some View {
        HStack(spacing: BookshelfMetrics.progressBarSpacing) {
            GeometryReader { geo in
                Capsule()
                    .fill(appTheme.palette.mutedFill)
                    .overlay(alignment: .leading) {
                        Capsule()
                            .fill(appTheme.palette.accent.opacity(BookshelfMetrics.progressBarAccentOpacity))
                            .frame(width: geo.size.width * progress)
                    }
            }
            .frame(height: BookshelfMetrics.progressBarHeight)
            .clipShape(Capsule())

            Text("\(Int(progress * 100))%")
                .font(AppFonts.monoNumbers(size: 10))
                .foregroundStyle(appTheme.palette.tertiaryText)
        }
    }
}

private extension Date {
    var relativeShort: String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return formatter.localizedString(for: self, relativeTo: Date())
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
        book.dateLastRead = Calendar.current.date(byAdding: .day, value: -3, to: Date())
        return book
    }()

    static let placeholderBook: Book = {
        let book = Book(
            title: "A Very Long Book Title For Empty Cover Placeholder",
            author: "M. Rivera",
            epubFileName: "placeholder.epub"
        )
        book.progression = 0.18
        book.dateLastRead = Calendar.current.date(byAdding: .hour, value: -5, to: Date())
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
