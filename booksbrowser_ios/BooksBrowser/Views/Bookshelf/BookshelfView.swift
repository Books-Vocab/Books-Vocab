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
    @Environment(\.modelContext) private var modelContext
    @Query(sort: \Book.dateLastRead, order: .reverse) private var books: [Book]

    @State private var isImporting = false
    @State private var isLoading = false
    @State private var loadingMessage = ""
    @State private var errorMessage: String?
    @State private var showError = false
    @State private var showSettings = false

    private let columns = [
        GridItem(.adaptive(minimum: 150, maximum: 200), spacing: 20)
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                if books.isEmpty {
                    emptyState
                } else {
                    bookGrid
                }

                if isLoading {
                    loadingOverlay
                }
            }
            .navigationTitle("書庫")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.hidden, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .font(.system(size: 15, weight: .light))
                            .foregroundStyle(.secondary)
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        isImporting = true
                    } label: {
                        Image(systemName: "plus")
                            .font(.system(size: 15, weight: .light))
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .fileImporter(
                isPresented: $isImporting,
                allowedContentTypes: [UTType(filenameExtension: "epub") ?? .data],
                allowsMultipleSelection: false
            ) { result in
                handleFileImport(result)
            }
            .alert("匯入錯誤", isPresented: $showError) {
                Button("確定", role: .cancel) {}
            } message: {
                Text(errorMessage ?? "未知錯誤")
            }
            .sheet(isPresented: $showSettings) {
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
                isImporting = true
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
                            deleteBook(book)
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
            Color.black.opacity(0.2)
                .ignoresSafeArea()

            VStack(spacing: 16) {
                ProgressView()
                    .scaleEffect(1.0)
                Text(loadingMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(28)
            .glassEffect(.regular, in: .rect(cornerRadius: 14))
        }
    }

    // MARK: - 檔案匯入（Readium 版）

    private func handleFileImport(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            importEPUB(from: url)
        case .failure(let error):
            errorMessage = error.localizedDescription
            showError = true
        }
    }

    private func importEPUB(from url: URL) {
        isLoading = true
        loadingMessage = "正在匯入書籍..."

        Task {
            do {
                print("🚀 BookshelfView: starting import from \(url)")
                let readiumService = ReadiumService.shared
                loadingMessage = "正在解析 EPUB..."

                let (fileName, publication) = try await readiumService.importEPUB(from: url)
                print("🚀 import succeeded: \(fileName)")
                let metadata = readiumService.extractMetadata(from: publication)
                print("🚀 metadata: \(metadata)")
                let coverData = await readiumService.extractCover(from: publication)
                print("🚀 cover: \(coverData?.count ?? 0) bytes")

                await MainActor.run {
                    loadingMessage = "正在儲存..."

                    let book = Book(
                        title: metadata.title,
                        author: metadata.author,
                        coverImageData: coverData,
                        epubFileName: fileName
                    )

                    modelContext.insert(book)
                    try? modelContext.save()
                    print("🚀 book saved: \(book.title)")

                    isLoading = false
                    loadingMessage = ""
                }
            } catch {
                print("❌ BookshelfView import error: \(error)")
                print("❌ error type: \(type(of: error))")
                await MainActor.run {
                    isLoading = false
                    loadingMessage = ""
                    errorMessage = "\(error)"
                    showError = true
                }
            }
        }
    }

    // MARK: - 刪除書籍

    private func deleteBook(_ book: Book) {
        // 刪除 EPUB 檔案
        ReadiumService.shared.deleteEPUB(fileName: book.epubFileName)
        // 從資料庫刪除
        modelContext.delete(book)
    }
}

// MARK: - 書籍卡片

struct BookCard: View {
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
                                    .fill(Color.white.opacity(0.55))
                                    .frame(width: geo.size.width * progress, height: 3)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .frame(height: 3)
                        }
                    }
            } else {
                // 無封面佔位 — 極簡風格
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(Color.primary.opacity(0.04))
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
                            .strokeBorder(.primary.opacity(0.06), lineWidth: 0.5)
                    )
                    .overlay(alignment: .bottom) {
                        if let progress = book.progression, progress > 0 {
                            GeometryReader { geo in
                                Rectangle()
                                    .fill(Color.primary.opacity(0.2))
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
