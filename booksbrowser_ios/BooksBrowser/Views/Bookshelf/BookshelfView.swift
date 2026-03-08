//
//  BookshelfView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import UniformTypeIdentifiers

/// 書架主頁 — 簡約留白設計
struct BookshelfView: View {
    @Environment(\.appTheme) private var appTheme
    @Environment(\.modelContext) private var modelContext
    @Environment(\.bookshelfImportService) private var bookshelfImportService
    @Environment(\.bookFileManager) private var bookFileManager
    @Query(sort: \Book.dateLastRead, order: .reverse) private var books: [Book]
    @StateObject private var coordinator = BookshelfCoordinator()

    private let columns = [
        GridItem(.adaptive(minimum: 150, maximum: 200), spacing: AppShellMetrics.sectionSpacing)
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                appTheme.palette.pageBackground
                    .ignoresSafeArea()

                if books.isEmpty {
                    emptyState
                } else {
                    bookGrid
                }

                if coordinator.isLoading {
                    loadingOverlay
                }
            }
            .navigationTitle("書庫")
            .navigationBarTitleDisplayMode(.large)
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
        VStack {
            Spacer()

            AppEmptyStateCard(
                title: "尚無書籍",
                systemImage: "book",
                description: "匯入 EPUB 電子書開始閱讀"
            )
            .overlay(alignment: .bottom) {
                Button("匯入") {
                    coordinator.presentImporter()
                }
                .buttonStyle(.appAction(.neutral))
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .offset(y: 34)
            }

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
                        BookCard(book: book)
                    }
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

            VStack(spacing: 16) {
                ProgressView()
                    .scaleEffect(1.0)
                Text(coordinator.loadingMessage)
                    .font(AppFonts.caption())
                    .foregroundStyle(appTheme.palette.secondaryText)
            }
            .padding(28)
            .glassEffect(.regular, in: .rect(cornerRadius: 14))
        }
    }

}

// MARK: - 書籍卡片

struct BookCard: View {
    @Environment(\.appTheme) private var appTheme
    let book: Book

    var body: some View {
        VStack(spacing: 10) {
            // 封面
            if let coverData = book.coverImageData,
               let uiImage = UIImage(data: coverData) {
                Image(uiImage: uiImage)
                    .resizable()
                    .aspectRatio(2/3, contentMode: .fill)
                    .frame(height: 210)
                    .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .shadow(color: .black.opacity(0.06), radius: 4, y: 2)
                    .overlay(alignment: .bottom) {
                        if let progress = book.progression, progress > 0 {
                            GeometryReader { geo in
                                Rectangle()
                                    .fill(appTheme.palette.pageBackground.opacity(0.82))
                                    .frame(width: geo.size.width * progress, height: 3)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(height: 3)
                        }
                    }
            } else {
                // 無封面佔位 — 極簡風格
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(appTheme.palette.mutedFill)
                    .frame(height: 210)
                    .overlay {
                        VStack(spacing: 10) {
                            Image(systemName: "book")
                                .font(AppFonts.h1(weight: .regular))
                                .foregroundStyle(appTheme.palette.tertiaryText)
                            Text(book.title)
                                .font(AppFonts.caption2())
                                .foregroundStyle(appTheme.palette.secondaryText)
                                .multilineTextAlignment(.center)
                                .padding(.horizontal, 12)
                        }
                    }
                    .overlay(
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .strokeBorder(appTheme.palette.cardBorder, lineWidth: 0.5)
                    )
                    .overlay(alignment: .bottom) {
                        if let progress = book.progression, progress > 0 {
                            GeometryReader { geo in
                                Rectangle()
                                    .fill(appTheme.palette.accent.opacity(0.55))
                                    .frame(width: geo.size.width * progress, height: 3)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(height: 3)
                        }
                    }
            }

            VStack(spacing: 3) {
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
