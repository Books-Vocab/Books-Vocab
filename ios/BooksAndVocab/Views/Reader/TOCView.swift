#if os(iOS)
import SwiftUI
import ReadiumShared

struct TOCView: View {
    enum LoadState {
        case loading
        case loaded
        case empty
        case failed(String)
    }

    @ObserveInjection private var inject

    let publication: Publication
    let onSelect: (ReadiumShared.Link) -> Void
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var appTheme
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var tocLinks: [ReadiumShared.Link] = []
    @State private var loadState: LoadState = .loading
    @State private var loadRequestID = 0

    private var phaseAnimationKey: String {
        switch loadState {
        case .loading: return "loading"
        case .loaded: return "loaded"
        case .empty: return "empty"
        case .failed: return "failed"
        }
    }

    var body: some View {
        let presentation = ReaderTOCPresentation(layoutMode: LayoutMode(horizontalSizeClass: sizeClass))

        return NavigationStack {
            ZStack {
                appTheme.palette.pageBackground.ignoresSafeArea()

                Group {
                    switch loadState {
                    case .loading:
                        tocLoadingState(presentation)
                    case .loaded:
                        tocLoadedList()
                    case .empty:
                        tocEmptyState(presentation)
                    case .failed(let message):
                        tocFailedState(message, presentation)
                    }
                }
                .frame(maxWidth: presentation.contentMaxWidth)
                .padding(.horizontal, presentation.horizontalPadding)
            }
            .animatePhaseChange(phaseAnimationKey)
            .navigationTitle(L10n.string("目錄"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L10n.string("完成")) { dismiss() }
                }
            }
            .task(id: loadRequestID) {
                await loadTableOfContents(requestID: loadRequestID)
            }
        }
        .enableInjection()
    }

    private func loadTableOfContents(requestID: Int) async {
        guard isCurrentLoad(requestID) else { return }
        loadState = .loading
        let result = await publication.tableOfContents()
        guard isCurrentLoad(requestID) else { return }

        switch result {
        case .success(let toc):
            tocLinks = toc
            loadState = toc.isEmpty ? .empty : .loaded
            AppLog.reader.info("TOC loaded: \(toc.count) items")
            for (i, link) in toc.enumerated() {
                AppLog.reader.debug("  [\(i)] \(link.title ?? "nil") → \(String(describing: link.url()))")
            }
            if toc.isEmpty {
                AppLog.reader.warning("TOC is empty — this book may not have a table of contents")
            }
        case .failure(.cancelled):
            // Readium reports cancellation as a ReadError result in some
            // publication implementations, rather than throwing
            // CancellationError. It is never a user-visible failure.
            return
        case .failure(let error):
            AppLog.reader.error("TOC load failed: \(error.localizedDescription)")
            loadState = .failed(error.localizedDescription)
        }
    }

    private func isCurrentLoad(_ requestID: Int) -> Bool {
        !Task.isCancelled && requestID == loadRequestID
    }

    @ViewBuilder
    private func tocLoadingState(_ presentation: ReaderTOCPresentation) -> some View {
        VStack {
            Spacer()
            AppLoadingStateCard(
                title: L10n.string("載入目錄中"),
                systemImage: "text.book.closed",
                description: L10n.string("正在整理這本書的章節結構。"),
                visualStyle: .app
            )
            .frame(maxWidth: presentation.stateCardMaxWidth)
            .padding(.horizontal, presentation == .compact ? AppShellMetrics.pageHorizontalPadding : 0)
            Spacer()
        }
    }

    @ViewBuilder
    private func tocLoadedList() -> some View {
        List {
            ForEach(tocLinks.indices, id: \.self) { index in
                let link = tocLinks[index]
                Button {
                    onSelect(link)
                    dismiss()
                } label: {
                    Text(link.title ?? L10n.string("目錄"))
                        .font(AppFonts.body())
                        .lineLimit(2)
                        .truncationMode(.tail)
                }
                .accessibilityIdentifier("reader.toc.item.\(index)")
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
    }

    @ViewBuilder
    private func tocEmptyState(_ presentation: ReaderTOCPresentation) -> some View {
        VStack {
            Spacer()
            AppEmptyStateCard(
                title: L10n.string("這本書沒有目錄"),
                systemImage: "list.bullet.rectangle",
                description: L10n.string("出版內容沒有提供可導覽的章節列表。")
            )
            .frame(maxWidth: presentation.stateCardMaxWidth)
            .padding(.horizontal, presentation == .compact ? AppShellMetrics.pageHorizontalPadding : 0)
            Spacer()
        }
    }

    @ViewBuilder
    private func tocFailedState(_ message: String, _ presentation: ReaderTOCPresentation) -> some View {
        VStack {
            Spacer()
            AppStateMessageCard(
                title: L10n.string("目錄載入失敗"),
                systemImage: "exclamationmark.triangle.fill",
                description: message
            ) {
                Button(L10n.string("重試")) {
                    loadRequestID += 1
                }
                .buttonStyle(.appCompactAction(.primary))
                .accessibilityIdentifier("reader.toc.retry")
            }
            .frame(maxWidth: presentation.stateCardMaxWidth)
            .padding(.horizontal, presentation == .compact ? AppShellMetrics.pageHorizontalPadding : 0)
            Spacer()
        }
    }
}

struct TOCViewPreviewScene: View {
    @Environment(\.appTheme) private var appTheme
    let loadState: TOCView.LoadState
    let tocTitles: [String]

    var body: some View {
        NavigationStack {
            Group {
                switch loadState {
                case .loading:
                    VStack {
                        Spacer()
                        AppLoadingStateCard(
                            title: L10n.string("載入目錄中"),
                            systemImage: "text.book.closed",
                            description: L10n.string("正在整理這本書的章節結構。"),
                            visualStyle: .app
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                case .loaded:
                    List {
                        ForEach(tocTitles.indices, id: \.self) { index in
                            Text(tocTitles[index])
                                .font(AppFonts.body())
                                .lineLimit(2)
                                .truncationMode(.tail)
                        }
                    }
                    .listStyle(.insetGrouped)
                    .scrollContentBackground(.hidden)
                case .empty:
                    VStack {
                        Spacer()
                        AppEmptyStateCard(
                            title: L10n.string("這本書沒有目錄"),
                            systemImage: "list.bullet.rectangle",
                            description: L10n.string("出版內容沒有提供可導覽的章節列表。")
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                case .failed(let message):
                    VStack {
                        Spacer()
                        AppStateMessageCard(
                            title: L10n.string("目錄載入失敗"),
                            systemImage: "exclamationmark.triangle.fill",
                            description: message
                        )
                        .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                        Spacer()
                    }
                }
            }
            .background(appTheme.palette.pageBackground.ignoresSafeArea())
            .navigationTitle(L10n.string("目錄"))
            .navigationBarTitleDisplayMode(.inline)
        }
    }
}

#Preview("TOC / Loading") {
    AppThemeContainer {
        TOCViewPreviewScene(loadState: .loading, tocTitles: [])
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("TOC / Loaded") {
    AppThemeContainer {
        TOCViewPreviewScene(
            loadState: .loaded,
            tocTitles: [
                "Chapter One",
                "Chapter Two",
                "Chapter Three"
            ]
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("TOC / Empty") {
    AppThemeContainer {
        TOCViewPreviewScene(loadState: .empty, tocTitles: [])
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("TOC / Failed") {
    AppThemeContainer {
        TOCViewPreviewScene(
            loadState: .failed(L10n.string("目錄讀取失敗")),
            tocTitles: []
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
