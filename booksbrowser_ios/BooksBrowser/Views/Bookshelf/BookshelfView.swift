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
        GridItem(.adaptive(minimum: 150, maximum: 200), spacing: 20)
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
                        Image(systemName: "gearshape")
                            .font(.system(size: 15, weight: .light))
                            .foregroundStyle(.secondary)
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: coordinator.presentImporter) {
                        Image(systemName: "plus")
                            .font(.system(size: 15, weight: .light))
                            .foregroundStyle(.secondary)
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
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "book")
                .font(.system(size: 48, weight: .ultraLight))
                .foregroundStyle(.quaternary)

            VStack(spacing: 6) {
                Text("尚無書籍")
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundStyle(.secondary)

                Text("匯入 EPUB 電子書開始閱讀")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }

            Button {
                coordinator.presentImporter()
            } label: {
                Text("匯入")
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 10)
                    .background(
                        Capsule()
                            .strokeBorder(.secondary.opacity(0.3), lineWidth: 0.5)
                    )
                    .foregroundStyle(.primary)
            }

            Spacer()
        }
    }

    // MARK: - 書籍網格

    private var bookGrid: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 24) {
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
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 32)
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
                    .font(.caption)
                    .foregroundStyle(.secondary)
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
                                .font(.system(size: 28, weight: .ultraLight))
                                .foregroundStyle(.tertiary)
                            Text(book.title)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
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
                    .font(.caption)
                    .fontWeight(.regular)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.primary)

                Text(book.author)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
            }
        }
    }
}
