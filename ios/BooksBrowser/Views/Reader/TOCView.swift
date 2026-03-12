import SwiftUI
import ReadiumShared
import os

struct TOCView: View {
    private enum LoadState {
        case loading
        case loaded
        case empty
        case failed(String)
    }

    let publication: Publication
    let onSelect: (ReadiumShared.Link) -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var appTheme
    @State private var tocLinks: [ReadiumShared.Link] = []
    @State private var loadState: LoadState = .loading

    var body: some View {
        NavigationStack {
            Group {
                switch loadState {
                case .loading:
                    VStack {
                        Spacer()
                        AppStateMessageCard(
                            title: "載入目錄中".localized,
                            systemImage: "text.book.closed",
                            description: "正在整理這本書的章節結構。".localized
                        ) {
                            ProgressView()
                                .controlSize(.small)
                        }
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                case .loaded:
                    List {
                        ForEach(tocLinks.indices, id: \.self) { index in
                            let link = tocLinks[index]
                            Button {
                                onSelect(link)
                                dismiss()
                            } label: {
                                Text(link.title ?? "Untitled")
                                    .font(AppFonts.body())
                            }
                        }
                    }
                case .empty:
                    VStack {
                        Spacer()
                        AppEmptyStateCard(
                            title: "這本書沒有目錄".localized,
                            systemImage: "list.bullet.rectangle",
                            description: "出版內容沒有提供可導覽的章節列表。".localized
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                case .failed(let message):
                    VStack {
                        Spacer()
                        AppStateMessageCard(
                            title: "目錄載入失敗".localized,
                            systemImage: "exclamationmark.triangle.fill",
                            description: message
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                }
            }
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("目錄".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                }
            }
            .task {
                do {
                    let toc = try await publication.tableOfContents().get()
                    tocLinks = toc
                    loadState = toc.isEmpty ? .empty : .loaded
                    AppLog.reader.info("TOC loaded: \(toc.count) items")
                    for (i, link) in toc.enumerated() {
                        AppLog.reader.debug("  [\(i)] \(link.title ?? "nil") → \(String(describing: link.url()))")
                    }
                    if toc.isEmpty {
                        AppLog.reader.warning("TOC is empty — this book may not have a table of contents")
                    }
                } catch {
                    AppLog.reader.error("TOC load failed: \(error.localizedDescription)")
                    loadState = .failed(error.localizedDescription)
                }
            }
        }
    }
}

private enum TOCPreviewLoadState {
    case loading
    case loaded
    case empty
    case failed(String)
}

private struct TOCViewPreviewScene: View {
    let loadState: TOCPreviewLoadState
    let tocTitles: [String]

    var body: some View {
        NavigationStack {
            Group {
                switch loadState {
                case .loading:
                    VStack {
                        Spacer()
                        AppStateMessageCard(
                            title: "載入目錄中",
                            systemImage: "text.book.closed",
                            description: "正在整理這本書的章節結構。"
                        ) {
                            ProgressView()
                                .controlSize(.small)
                        }
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                case .loaded:
                    List {
                        ForEach(tocTitles.indices, id: \.self) { index in
                            Text(tocTitles[index])
                                .font(AppFonts.body())
                        }
                    }
                case .empty:
                    VStack {
                        Spacer()
                        AppEmptyStateCard(
                            title: "這本書沒有目錄",
                            systemImage: "list.bullet.rectangle",
                            description: "出版內容沒有提供可導覽的章節列表。"
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                case .failed(let message):
                    VStack {
                        Spacer()
                        AppStateMessageCard(
                            title: "目錄載入失敗",
                            systemImage: "exclamationmark.triangle.fill",
                            description: message
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                }
            }
            .background(AppTheme.light.palette.pageBackground.ignoresSafeArea())
            .navigationTitle("目錄")
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

#Preview("TOC / Loading") {
    AppThemeContainer {
        TOCViewPreviewScene(loadState: .loading, tocTitles: [])
    }
}

#Preview("TOC / Loaded") {
    AppThemeContainer {
        TOCViewPreviewScene(
            loadState: .loaded,
            tocTitles: [
                "第一章",
                "第二章",
                "第三章"
            ]
        )
    }
}

#Preview("TOC / Empty") {
    AppThemeContainer {
        TOCViewPreviewScene(loadState: .empty, tocTitles: [])
    }
}

#Preview("TOC / Failed") {
    AppThemeContainer {
        TOCViewPreviewScene(
            loadState: .failed("Publication manifest 解析失敗。"),
            tocTitles: []
        )
    }
}
