//
//  BookshelfView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import TipKit
import UniformTypeIdentifiers

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
        sizeClass == .regular ? AppBookshelfMetrics.coverHeightRegular : AppBookshelfMetrics.coverHeightCompact
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
                        .transition(.overlayFade)
                }
            }
            .navigationTitle("書庫".localized)
            .navigationBarTitleDisplayMode(.large)
            .animatePhaseChange(books.isEmpty)
            .animateContentFade(coordinator.isLoading)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(action: coordinator.presentSettings) {
                        AppToolbarGlyph(systemImage: "gearshape")
                    }
                    .accessibilityIdentifier("bookshelf.settingsButton")
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: coordinator.presentImporter) {
                        AppToolbarGlyph(systemImage: "plus")
                    }
                    .accessibilityIdentifier("bookshelf.importButton")
                }
            }
            .fileImporter(
                isPresented: $coordinator.isImporting,
                allowedContentTypes: [
                    UTType(filenameExtension: "epub") ?? .data,
                    .plainText,
                    UTType(filenameExtension: "md") ?? .data,
                    .pdf,
                ],
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

    @Environment(\.openURL) private var openURL
    @Environment(\.authManager) private var authManager

    private var emptyState: some View {
        ScrollView {
            VStack(spacing: AppMetrics.sectionInset) {
                Spacer(minLength: 120)

                AppEmptyStateContent(
                    title: "尚無書籍".localized,
                    systemImage: "book",
                    description: "匯入電子書開始閱讀（EPUB・TXT・MD・PDF）".localized,
                    guidanceText: "點擊上方匯入按鈕加入你的第一本書",
                    style: .bookshelf(appTheme)
                )

                TipView(EPUBGuideTip()) { action in
                    if action.id == "查看指南" {
                        openURL(AppURLs.guide)
                    }
                }
                .padding(.horizontal)

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
                    .buttonStyle(.liftable)
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
            .animateContentFade(books.count)
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
            switch book.format {
            case .epub, .txt, .md:
                ReaderView(book: book)
            case .pdf:
                PDFReaderView(book: book)
            }
        }
    }

    // MARK: - EPUB 取得提示

    private var epubGuideHint: some View {
        Link(destination: AppURLs.guide) {
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

            VStack(spacing: AppMetrics.spacingMedium) {
                ProgressView()
                    .scaleEffect(1.0)
                Text(coordinator.loadingMessage)
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(AppBookshelfMetrics.loadingOverlayPadding)
            .compatibleGlass(in: .rect(cornerRadius: AppMetrics.cornerRadiusMedium))
        }
    }

}

// MARK: - 書籍卡片

struct BookCard: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.iCloudDownloadManager) private var downloadManager
    let book: Book
    var coverHeight: CGFloat = AppBookshelfMetrics.coverHeightCompact
    @State private var decodedCoverImage: UIImage?

    var body: some View {
        VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
            // 封面
            coverView
                .overlay(
                    RoundedRectangle(
                        cornerRadius: AppBookshelfMetrics.coverCornerRadius,
                        style: .continuous
                    )
                    .strokeBorder(
                        appTheme.palette.cardBorder,
                        lineWidth: AppMetrics.dividerThin
                    )
                )
                .overlay(alignment: .bottomTrailing) {
                    iCloudDownloadBadge
                }
                .shadow(
                    color: .black.opacity(AppBookshelfMetrics.coverShadowOpacity),
                    radius: AppBookshelfMetrics.coverShadowRadius,
                    y: AppBookshelfMetrics.coverShadowY
                )

            // 進度條（封面外獨立元素）
            if let progress = book.progression, progress > 0 {
                progressBar(progress)
            }

            // 元資料
            VStack(alignment: .leading, spacing: AppMetrics.spacingTiny) {
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
        .task(id: book.coverImageData) {
            await decodeCoverImage()
        }
    }

    @ViewBuilder
    private var coverView: some View {
        if let uiImage = decodedCoverImage {
            Image(uiImage: uiImage)
                .resizable()
                .aspectRatio(2/3, contentMode: .fill)
                .frame(height: coverHeight)
                .clipShape(
                    RoundedRectangle(
                        cornerRadius: AppBookshelfMetrics.coverCornerRadius,
                        style: .continuous
                    )
                )
                .transition(.contentSwap)
        } else {
            RoundedRectangle(
                cornerRadius: AppBookshelfMetrics.coverCornerRadius,
                style: .continuous
            )
            .fill(appTheme.palette.mutedFill)
            .frame(height: coverHeight)
            .overlay {
                VStack(spacing: AppMetrics.spacingSmall) {
                    Image(systemName: "book")
                        .font(AppFonts.h1(weight: .regular))
                        .foregroundStyle(appTheme.palette.tertiaryText)
                    Text(book.title)
                        .font(AppFonts.caption2())
                        .foregroundStyle(appTheme.palette.secondaryText)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, AppBookshelfMetrics.placeholderTitleHorizontalPadding)
                    if book.format != .epub {
                        Text(book.format.rawValue.uppercased())
                            .font(AppFonts.caption2())
                            .foregroundStyle(appTheme.palette.secondaryText)
                            .padding(.horizontal, AppMetrics.spacingExtraSmall)
                            .padding(.vertical, AppMetrics.spacingMicro)
                            .background(appTheme.palette.mutedFill)
                            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusSmall))
                    }
                }
            }
        }
    }

    private func decodeCoverImage() async {
        guard let coverData = book.coverImageData else {
            decodedCoverImage = nil
            return
        }
        let image = await Task.detached {
            UIImage(data: coverData)
        }.value
        guard !Task.isCancelled else { return }
        withAnimation(AppMotion.contentFade) {
            decodedCoverImage = image
        }
    }

    @ViewBuilder
    private var iCloudDownloadBadge: some View {
        if let state = downloadManager.state(for: book.epubFileName) {
            switch state {
            case .downloading(let progress):
                ICloudProgressBadge(progress: progress)
                    .padding(AppBookshelfMetrics.badgePadding)
            case .notDownloaded:
                cloudIconBadge
            case .current:
                EmptyView()
            }
        } else if book.needsICloudDownload {
            cloudIconBadge
        }
    }

    private var cloudIconBadge: some View {
        Image(systemName: "icloud.and.arrow.down")
            .font(AppFonts.caption2(weight: .semibold))
            .foregroundStyle(AppBookshelfMetrics.badgeForeground)
            .padding(AppBookshelfMetrics.badgePadding)
            .background(.ultraThinMaterial, in: Circle())
            .padding(AppBookshelfMetrics.badgePadding)
    }

    private func progressBar(_ progress: Double) -> some View {
        HStack(spacing: AppBookshelfMetrics.progressBarSpacing) {
            GeometryReader { geo in
                Capsule()
                    .fill(appTheme.palette.mutedFill)
                    .overlay(alignment: .leading) {
                        Capsule()
                            .fill(appTheme.palette.accent.opacity(AppBookshelfMetrics.progressBarAccentOpacity))
                            .frame(width: geo.size.width * progress)
                    }
            }
            .frame(height: AppBookshelfMetrics.progressBarHeight)
            .clipShape(Capsule())

            Text("\(Int(progress * 100))%")
                .font(AppFonts.monoNumbers(size: 10))
                .foregroundStyle(appTheme.palette.tertiaryText)
        }
    }
}

// MARK: - iCloud 下載進度徽章

private struct ICloudProgressBadge: View {
    let progress: Double
    private let foreground = AppBookshelfMetrics.badgeForeground

    var body: some View {
        ZStack {
            Circle()
                .stroke(foreground.opacity(0.3), lineWidth: 2.5)
            Circle()
                .trim(from: 0, to: progress)
                .stroke(foreground, style: StrokeStyle(lineWidth: 2.5, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .animation(AppMotion.progressLinear, value: progress)
            Text("\(Int(progress * 100))")
                .font(AppFonts.monoNumbers(size: 8))
                .foregroundStyle(foreground)
        }
        .frame(width: 32, height: 32)
        .background(.ultraThinMaterial, in: Circle())
    }
}

private extension Date {
    private static let shortFormatter: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        return f
    }()

    var relativeShort: String {
        Self.shortFormatter.localizedString(for: self, relativeTo: Date())
    }
}

private enum BookshelfPreviewData {
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
    static var containerWithBooks: ModelContainer = {
        let schema = Schema([Book.self, VocabularyEntry.self])
        let config = ModelConfiguration(isStoredInMemoryOnly: true)
        let container = try! ModelContainer(for: schema, configurations: config)
        let context = ModelContext(container)
        context.insert(activeBook)
        context.insert(placeholderBook)
        try? context.save()
        return container
    }()
}

#Preview("Bookshelf Card / Progress") {
    AppThemeContainer {
        BookCardPreviewScene(book: BookshelfPreviewData.activeBook)
    }
}

#Preview("Bookshelf Card / Placeholder") {
    AppThemeContainer {
        BookCardPreviewScene(book: BookshelfPreviewData.placeholderBook)
    }
}

private struct BookCardPreviewScene: View {
    @Environment(\.appTheme) private var appTheme
    let book: Book

    var body: some View {
        BookCard(book: book)
            .padding()
            .frame(width: 180)
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }
}

// MARK: - 全頁四態 Preview

#Preview("Bookshelf / Empty") {
    AppThemeContainer {
        BookshelfView()
            .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
    }
}

#Preview("Bookshelf / With Books") {
    AppThemeContainer {
        BookshelfView()
            .modelContainer(BookshelfPreviewData.containerWithBooks)
    }
}

#Preview("Bookshelf / Loading") {
    AppThemeContainer {
        BookshelfLoadingPreview()
            .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
    }
}

/// 獨立展示 loadingOverlay 的輔助 view，用於 Loading State preview
private struct BookshelfLoadingPreview: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        ZStack {
            appTheme.palette.pageBackground
                .ignoresSafeArea()
            appTheme.palette.scrim
                .ignoresSafeArea()
            VStack(spacing: AppMetrics.spacingMedium) {
                ProgressView()
                Text("正在匯入書籍...")
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(AppBookshelfMetrics.loadingOverlayPadding)
            .compatibleGlass(in: .rect(cornerRadius: AppMetrics.cornerRadiusMedium))
        }
    }
}
